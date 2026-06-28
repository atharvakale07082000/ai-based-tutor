import asyncio
import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agents.progress_agent import calculate_elo_update
from app.agents.steps import StepTimeline, sse_step_stream
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners, col_progress, col_quizzes
from app.schemas.quiz import (
    EloUpdate,
    QuizGenerateRequest,
    QuizQuestion,
    QuizSessionSchema,
    QuizSubmitRequest,
    QuizSubmitResult,
)

_SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


async def _get_learner_or_404(user_id: str) -> dict:
    """Fetch a learner document by user_id or raise HTTP 404."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")
    return learner


@router.post("/generate", response_model=QuizSessionSchema)
@limiter.limit("20/hour")
async def generate_quiz(
    request: Request,
    body: QuizGenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Generate or retrieve a cached quiz via the ``quiz_gen`` workflow (resolve → generate → persist)."""
    from app.agents.workflow import run_workflow

    learner = await _get_learner_or_404(user_id)
    log.info("quiz_generate_start", topic=body.topic, learner_id=learner["id"])

    elo = (learner.get("topic_proficiency_map") or {}).get(body.topic, 500.0)
    ctx = await run_workflow(
        "quiz_gen",
        {
            "topic": body.topic,
            "bloom_level": body.bloom_level,
            "elo": elo,
            "learner_id": learner["id"],
        },
    )
    persisted = ctx.result("persist")

    # Online eval sampling: do the generated questions correctly test the requested topic?
    from app.evals.deepeval_metrics import maybe_eval_single_turn

    q_text = "\n".join(q.get("question", "") for q in persisted["questions"])
    maybe_eval_single_turn(
        "quiz_agent", f"Generate a quiz that tests understanding of: {body.topic}", q_text, learner_id=learner["id"]
    )

    return QuizSessionSchema(
        quiz_id=persisted["quiz_id"],
        topic=body.topic,
        bloom_level=persisted["bloom_level"],
        questions=[QuizQuestion(**q) for q in persisted["questions"]],
        time_per_question=60,
    )


@router.get("/{quiz_id}", response_model=QuizSessionSchema)
async def get_quiz(quiz_id: str, user_id: str = Depends(get_current_user_id)):
    """Fetch a quiz session by ID (questions, bloom level, topic)."""
    quiz = await col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return QuizSessionSchema(
        quiz_id=quiz["id"],
        topic=quiz["topic"],
        bloom_level=quiz["bloom_level"],
        questions=[QuizQuestion(**q) for q in quiz.get("questions", [])],
        time_per_question=60,
    )


def _validate_quiz_answers(questions: list, answers: list) -> None:
    """Raise HTTP 400 if the answer set is the wrong length or has out-of-range indices."""
    if len(answers) != len(questions):
        raise HTTPException(400, f"Expected {len(questions)} answers, got {len(answers)}")
    for i, (ans, q) in enumerate(zip(answers, questions)):
        n_opts = len(q.get("options", []))
        if n_opts and not (0 <= ans < n_opts):
            raise HTTPException(400, f"Answer for question {i + 1} is out of range (0–{n_opts - 1})")


async def _grade_and_persist(quiz: dict, learner: dict, answers: list, user_id: str) -> QuizSubmitResult:
    """Score answers, update ELO/XP, persist results, and return the structured result.

    Shared by the plain and streaming submit endpoints so scoring lives in one place.
    """
    questions = quiz.get("questions") or []
    correct_count = 0
    weak_topics: list[str] = []
    for i, q in enumerate(questions):
        if answers[i] == q.get("correct_index", 0):
            correct_count += 1
        else:
            weak_topics.append(quiz["topic"])

    score = correct_count / max(len(questions), 1)

    proficiency = dict(learner.get("topic_proficiency_map") or {})
    old_elo = proficiency.get(quiz["topic"], 500.0)
    new_elo = calculate_elo_update(old_elo, score)
    proficiency[quiz["topic"]] = new_elo

    now = datetime.now(timezone.utc).isoformat()
    # XP: 50 base + up to 50 for score + 200 bonus if topic newly mastered
    xp_delta = 50 + int(score * 50)
    previously_mastered = old_elo >= 700
    if new_elo >= 700 and not previously_mastered:
        xp_delta += 200  # mastery bonus

    await col_learners().update_one(
        {"user_id": user_id},
        {"$set": {"topic_proficiency_map": proficiency, "updated_at": now}, "$inc": {"xp": xp_delta}},
    )
    await col_progress().insert_one(
        {
            "id": str(uuid.uuid4()),
            "learner_id": learner["id"],
            "topic": quiz["topic"],
            "elo_score": new_elo,
            "recorded_at": now,
        }
    )
    await col_quizzes().update_one(
        {"id": quiz["id"]},
        {"$set": {"answers": answers, "score": score, "weak_topics": list(set(weak_topics)), "completed_at": now}},
    )

    log.info("quiz_submitted", quiz_id=quiz["id"], score=score, xp_delta=xp_delta)
    return QuizSubmitResult(
        score=score,
        correct_count=correct_count,
        weak_topics=list(set(weak_topics))[:5],
        elo_update=EloUpdate(topic=quiz["topic"], old_elo=old_elo, new_elo=new_elo),
    )


@router.post("/{quiz_id}/submit", response_model=QuizSubmitResult)
async def submit_quiz(
    quiz_id: str,
    body: QuizSubmitRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Score quiz answers, update ELO proficiency, award XP, and persist results."""
    quiz = await col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    learner = await _get_learner_or_404(user_id)
    answers = body.answers or []
    _validate_quiz_answers(quiz.get("questions") or [], answers)
    return await _grade_and_persist(quiz, learner, answers, user_id)


@router.post("/{quiz_id}/submit/stream")
async def submit_quiz_stream(
    quiz_id: str,
    body: QuizSubmitRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Score a quiz while streaming a live step timeline as SSE.

    Emits `step` events (analyze → score → feedback), then a `quiz_scored` action
    carrying the full result, then `[DONE]`. Validation still happens up-front so a
    bad request returns a normal 400 instead of an in-stream error.
    """
    quiz = await col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    learner = await _get_learner_or_404(user_id)
    answers = body.answers or []
    _validate_quiz_answers(quiz.get("questions") or [], answers)

    async def event_stream():
        """Emit timeline steps around grading, then the result as an action."""

        async def run(emit):
            tl = StepTimeline("quiz_review")
            await emit(tl.start("analyze"))
            await asyncio.sleep(0.4)  # brief pacing so the review reads as progress
            await emit(tl.done("analyze"))

            await emit(tl.start("score"))
            result = await _grade_and_persist(quiz, learner, answers, user_id)
            await emit(tl.done("score"))

            await emit(tl.start("feedback"))
            await asyncio.sleep(0.3)
            await emit(tl.done("feedback"))

            await emit({"type": "action", "kind": "quiz_scored", "payload": result.model_dump()})

        async for ev in sse_step_stream(run):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


class ExplainRequest(BaseModel):
    question_index: int = Field(ge=0, le=100)


@router.post("/{quiz_id}/explain")
async def explain_quiz_answer(
    quiz_id: str,
    body: ExplainRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Explain why a question's correct answer is right — server-side via the resilient LLM.

    Replaces the old browser→HuggingFace call so the feature works without a client HF token.
    """
    from app.hf.client import hf_chat_completion_with_resilience
    from app.hf.models import HF_MODELS

    quiz = await col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(404, "Quiz not found")
    questions = quiz.get("questions") or []
    if body.question_index >= len(questions):
        raise HTTPException(400, "question_index out of range")

    q = questions[body.question_index]
    options = q.get("options") or []
    correct_idx = q.get("correct_index", 0)
    correct = options[correct_idx] if 0 <= correct_idx < len(options) else ""
    prompt = (
        f'Question: "{q.get("question", "")}"\n'
        f'The correct answer is: "{correct}".\n'
        "In 2–3 sentences, explain clearly why that answer is correct. Be concrete and tutoring-friendly."
    )
    cfg = HF_MODELS["DOUBT_SOLVER"]
    try:
        text = await hf_chat_completion_with_resilience(
            provider=cfg["provider"],
            model_id=cfg["model_id"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
            timeout_s=30.0,
        )
    except Exception as e:
        log.warning("quiz_explain_failed", quiz_id=quiz_id, error=str(e)[:200])
        raise HTTPException(503, "Explanation is unavailable right now — please try again.")
    return {"explanation": text}


@router.post("/flashcards")
async def generate_flashcards(
    topic: str = Query(..., min_length=2),
    count: int = Query(10, ge=5, le=20),
    user_id: str = Depends(get_current_user_id),
):
    """Generate AI-powered recall flashcards for a topic."""
    from app.hf.flashcard_generator import generate_flashcards as _gen

    log.info("flashcards_generate", topic=topic, count=count)
    cards = await _gen(topic, count)
    return {"topic": topic, "cards": cards, "count": len(cards)}
