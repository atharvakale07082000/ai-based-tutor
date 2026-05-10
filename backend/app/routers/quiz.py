import uuid
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.mongo import col_learners, col_quizzes, col_progress
from app.schemas.quiz import QuizGenerateRequest, QuizSessionSchema, QuizQuestion, QuizSubmitRequest, QuizSubmitResult, EloUpdate
from app.agents.progress_agent import calculate_elo_update
from app.auth.jwt import get_current_user_id
from app.hf.quiz_questions import get_or_generate_quiz_questions, bloom_for_elo

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


def _get_learner_or_404(user_id: str) -> dict:
    learner = col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")
    return learner


@router.post("/generate", response_model=QuizSessionSchema)
async def generate_quiz(
    body: QuizGenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
    learner = _get_learner_or_404(user_id)
    log.info("quiz_generate_start", topic=body.topic, learner_id=learner["id"])

    proficiency = learner.get("topic_proficiency_map") or {}
    elo = proficiency.get(body.topic, 500.0)
    bloom_level = body.bloom_level or bloom_for_elo(elo)

    questions = await get_or_generate_quiz_questions(body.topic, bloom_level, count=5)

    quiz_id = str(uuid.uuid4())
    col_quizzes().insert_one({
        "id": quiz_id,
        "learner_id": learner["id"],
        "topic": body.topic,
        "bloom_level": bloom_level,
        "questions": questions,
        "answers": [],
        "score": None,
        "weak_topics": [],
        "sentiment_mood": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    })

    return QuizSessionSchema(
        quiz_id=quiz_id,
        topic=body.topic,
        bloom_level=bloom_level,
        questions=[QuizQuestion(**q) for q in questions],
        time_per_question=60,
    )


@router.get("/{quiz_id}", response_model=QuizSessionSchema)
async def get_quiz(quiz_id: str, user_id: str = Depends(get_current_user_id)):
    quiz = col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return QuizSessionSchema(
        quiz_id=quiz["id"],
        topic=quiz["topic"],
        bloom_level=quiz["bloom_level"],
        questions=[QuizQuestion(**q) for q in quiz.get("questions", [])],
        time_per_question=60,
    )


@router.post("/{quiz_id}/submit", response_model=QuizSubmitResult)
async def submit_quiz(
    quiz_id: str,
    body: QuizSubmitRequest,
    user_id: str = Depends(get_current_user_id),
):
    quiz = col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    learner = _get_learner_or_404(user_id)

    questions = quiz.get("questions") or []
    answers = body.answers or []
    correct_count = 0
    weak_topics: list[str] = []

    for i, q in enumerate(questions):
        user_answer = answers[i] if i < len(answers) else -1
        if user_answer == q.get("correct_index", 0):
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

    col_learners().update_one(
        {"user_id": user_id},
        {"$set": {
            "topic_proficiency_map": proficiency,
            "updated_at": now,
        }, "$inc": {"xp": xp_delta}},
    )

    col_progress().insert_one({
        "id": str(uuid.uuid4()),
        "learner_id": learner["id"],
        "topic": quiz["topic"],
        "elo_score": new_elo,
        "recorded_at": now,
    })

    col_quizzes().update_one(
        {"id": quiz_id},
        {"$set": {
            "answers": answers,
            "score": score,
            "weak_topics": list(set(weak_topics)),
            "completed_at": now,
        }},
    )

    log.info("quiz_submitted", quiz_id=quiz_id, score=score, xp_delta=xp_delta)
    return QuizSubmitResult(
        score=score,
        correct_count=correct_count,
        weak_topics=list(set(weak_topics))[:5],
        elo_update=EloUpdate(topic=quiz["topic"], old_elo=old_elo, new_elo=new_elo),
    )


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
