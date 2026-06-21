"""
Learning session API.

A session is a single study round: the orchestrator picks the next topic,
generates quiz questions, and the learner submits answers to advance.

Endpoints:
  POST /session/start   — start a new session (AI picks topic + quiz)
  POST /session/advance — submit quiz answers and progress to the next topic
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agents.orchestrator import orchestrator
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_curricula, col_learners, col_progress, col_quizzes

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}

_DEFAULT_STATE_EXTRAS = {
    "next_action": "",
    "resume_action": "",
    "iteration_count": 0,
    "max_iterations": 10,
    "session_complete": False,
    "mastery_threshold": 700.0,
}


class SessionStartResponse(BaseModel):
    session_id: str
    curriculum_path: list[dict]
    current_topic: str
    bloom_level: str
    quiz_questions: list[dict]
    session_complete: bool
    iteration_count: int


class SessionAdvanceRequest(BaseModel):
    quiz_id: str
    answers: list[int]
    reflection: str = ""


class SessionAdvanceResponse(BaseModel):
    topic_proficiency: dict
    progress_delta: dict
    current_topic: str
    bloom_level: str
    quiz_questions: list[dict]
    session_complete: bool
    iteration_count: int


async def _get_learner_or_404(user_id: str) -> dict:
    """Fetch a learner document by user_id or raise HTTP 404."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")
    return learner


async def _load_active_curriculum(learner_id: str) -> tuple[list, dict | None]:
    """Return (topics_list, curriculum_doc) for the learner's most recent active curriculum."""
    record = await col_curricula().find_one(
        {"learner_id": learner_id, "is_active": True},
        PROJ,
        sort=[("generated_at", -1)],
    )
    return (record["topics"] if record else []), record


@router.post("/start", response_model=SessionStartResponse)
async def start_session(user_id: str = Depends(get_current_user_id)):
    """Start a new study session: orchestrator picks the next topic and generates quiz questions."""
    learner = await _get_learner_or_404(user_id)
    existing_path, _ = await _load_active_curriculum(learner["id"])

    state = {
        "learner_id": learner["id"],
        "task_type": "start",
        "messages": [],
        "learner_profile": {
            "goal_vector": learner.get("goal_vector") or [],
            "learning_style": learner.get("learning_style", "visual"),
        },
        "topic_proficiency": learner.get("topic_proficiency_map") or {},
        "current_topic": "",
        "quiz_questions": [],
        "curriculum_path": existing_path,
        "doubt_response": "",
        "progress_delta": {},
        "bloom_level": "",
        "error": None,
        **_DEFAULT_STATE_EXTRAS,
    }

    log.info("session_start", learner_id=learner["id"])
    final = await orchestrator.ainvoke(state)

    new_path = final.get("curriculum_path", existing_path)
    now = datetime.now(timezone.utc).isoformat()

    if new_path and new_path != existing_path:
        await col_curricula().update_many(
            {"learner_id": learner["id"], "is_active": True},
            {"$set": {"is_active": False}},
        )
        await col_curricula().insert_one(
            {
                "id": str(uuid.uuid4()),
                "learner_id": learner["id"],
                "version": learner.get("curriculum_version", 1) + 1,
                "topics": new_path,
                "generated_at": now,
                "is_active": True,
            }
        )
        await col_learners().update_one(
            {"user_id": user_id},
            {"$set": {"curriculum_version": learner.get("curriculum_version", 1) + 1, "updated_at": now}},
        )

    questions = final.get("quiz_questions", [])
    session_id = str(uuid.uuid4())
    # Always persist the quiz document so /session/advance can look it up by
    # session_id regardless of whether the orchestrator produced questions.
    # An empty questions list is valid — advance will score it as 100% (0/0).
    await col_quizzes().insert_one(
        {
            "id": session_id,
            "learner_id": learner["id"],
            "topic": final.get("current_topic", ""),
            "bloom_level": final.get("bloom_level", "understand"),
            "questions": questions,
            "answers": [],
            "score": None,
            "weak_topics": [],
            "sentiment_mood": None,
            "started_at": now,
            "completed_at": None,
        }
    )

    log.info("session_start_done", session_id=session_id, topic=final.get("current_topic"))
    return SessionStartResponse(
        session_id=session_id,
        curriculum_path=new_path,
        current_topic=final.get("current_topic", ""),
        bloom_level=final.get("bloom_level", "understand"),
        quiz_questions=questions,
        session_complete=final.get("session_complete", False),
        iteration_count=final.get("iteration_count", 1),
    )


@router.post("/advance", response_model=SessionAdvanceResponse)
async def advance_session(
    body: SessionAdvanceRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Score quiz answers, update ELO + XP, and have the orchestrator pick the next topic."""
    quiz = await col_quizzes().find_one({"id": body.quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    learner = await _get_learner_or_404(user_id)
    curriculum_path, _ = await _load_active_curriculum(learner["id"])

    questions = quiz.get("questions") or []
    answers = body.answers or []
    correct_count = sum(
        1 for i, q in enumerate(questions) if i < len(answers) and answers[i] == q.get("correct_index", 0)
    )
    score = correct_count / max(len(questions), 1)

    state = {
        "learner_id": learner["id"],
        "task_type": "progress",
        "messages": [],
        "learner_profile": {},
        "topic_proficiency": learner.get("topic_proficiency_map") or {},
        "current_topic": quiz["topic"],
        "quiz_questions": [],
        "curriculum_path": curriculum_path,
        "doubt_response": "",
        "progress_delta": {"score": score, "reflection": body.reflection},
        "bloom_level": "",
        "error": None,
        **_DEFAULT_STATE_EXTRAS,
    }

    log.info("session_advance", learner_id=learner["id"], topic=quiz["topic"], score=score)
    final = await orchestrator.ainvoke(state)

    proficiency = final.get("topic_proficiency", {})
    delta = final.get("progress_delta", {})
    now = datetime.now(timezone.utc).isoformat()

    await col_learners().update_one(
        {"user_id": user_id},
        {
            "$set": {
                "topic_proficiency_map": proficiency,
                "xp": learner.get("xp", 0) + int(score * 100),
                "updated_at": now,
            }
        },
    )

    await col_progress().insert_one(
        {
            "id": str(uuid.uuid4()),
            "learner_id": learner["id"],
            "topic": quiz["topic"],
            "elo_score": delta.get("new_elo", proficiency.get(quiz["topic"], 500.0)),
            "recorded_at": now,
        }
    )

    await col_quizzes().update_one(
        {"id": body.quiz_id},
        {"$set": {"answers": answers, "score": score, "completed_at": now}},
    )

    next_questions = final.get("quiz_questions", [])
    next_session_id = str(uuid.uuid4())
    if next_questions:
        await col_quizzes().insert_one(
            {
                "id": next_session_id,
                "learner_id": learner["id"],
                "topic": final.get("current_topic", ""),
                "bloom_level": final.get("bloom_level", "understand"),
                "questions": next_questions,
                "answers": [],
                "score": None,
                "weak_topics": [],
                "sentiment_mood": None,
                "started_at": now,
                "completed_at": None,
            }
        )

    log.info("session_advance_done", next_topic=final.get("current_topic"), complete=final.get("session_complete"))
    return SessionAdvanceResponse(
        topic_proficiency=proficiency,
        progress_delta=delta,
        current_topic=final.get("current_topic", ""),
        bloom_level=final.get("bloom_level", "understand"),
        quiz_questions=next_questions,
        session_complete=final.get("session_complete", False),
        iteration_count=final.get("iteration_count", 1),
    )
