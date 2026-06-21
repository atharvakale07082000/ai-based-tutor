"""
Progress tracking API.

Endpoints:
  GET  /progress              — full proficiency snapshot + history
  GET  /progress/due-topics   — spaced-repetition scheduler
  GET  /progress/report       — downloadable JSON progress report
  POST /progress/study-session — record a completed study session and award XP
"""

import asyncio
import uuid
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.jwt import get_current_user_id
from app.db.mongo import col_doubts, col_learners, col_progress, col_quizzes, col_study_sessions
from app.hf.spaced_repetition import compute_due_topics

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


class StudySessionRequest(BaseModel):
    """Payload for recording a completed study session."""

    minutes: int
    topic: str = "general"
    activity: str = "study"  # "pomodoro" | "quiz" | "reading" | "study"


@router.get("")
async def get_progress(user_id: str = Depends(get_current_user_id)):
    """Return the learner's full progress snapshot: proficiency, quiz history, mood, XP, streak."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return {"topic_proficiency": {}, "history": []}

    learner_id = learner["id"]

    # Parallelise all four independent collection reads now that we have learner_id.
    records, quizzes, doubt_sessions, study_sessions = await asyncio.gather(
        col_progress().find({"learner_id": learner_id}, PROJ).sort("recorded_at", 1).limit(100).to_list(length=None),
        col_quizzes().find({"learner_id": learner_id, "completed_at": {"$ne": None}}, PROJ).to_list(length=None),
        col_doubts().find({"learner_id": learner_id}, PROJ).to_list(length=None),
        col_study_sessions().find({"learner_id": learner_id}, PROJ).to_list(length=None),
    )

    quiz_accuracy = sum(q.get("score") or 0 for q in quizzes) / len(quizzes) if quizzes else 0.0

    mood_timeline = [
        {"session_id": d["id"], "mood": d["sentiment_mood"], "date": d.get("started_at")}
        for d in doubt_sessions
        if d.get("sentiment_mood")
    ]

    total_study_minutes = sum(s.get("minutes", 0) for s in study_sessions) + len(quizzes) * 15

    return {
        "learner_id": learner_id,
        "topic_proficiency": learner.get("topic_proficiency_map") or {},
        "history": [
            {"topic": r["topic"], "elo_score": r["elo_score"], "recorded_at": r.get("recorded_at")} for r in records
        ],
        "total_study_minutes": total_study_minutes,
        "quiz_accuracy": quiz_accuracy,
        "doubts_resolved": len(doubt_sessions),
        "streak": learner.get("streak", 0),
        "xp": learner.get("xp", 0),
        "mood_timeline": mood_timeline,
    }


@router.get("/due-topics")
async def get_due_topics(user_id: str = Depends(get_current_user_id)):
    """
    Spaced-repetition scheduler: return topics ordered by urgency.

    Uses an SM-2-inspired algorithm. Topics the learner has not reviewed recently
    or scored poorly on float to the top of the list.
    """
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return {"due_topics": []}

    proficiency = learner.get("topic_proficiency_map") or {}

    # Fetch only the fields needed for scheduling — minimal projection.
    quizzes = await (
        col_quizzes()
        .find(
            {"learner_id": learner["id"], "completed_at": {"$ne": None}},
            {"_id": 0, "topic": 1, "completed_at": 1},
        )
        .sort("completed_at", -1)
        .to_list(length=None)
    )

    # Keep only the most-recent completion date per topic.
    last_quiz_dates: dict[str, str] = {}
    for q in quizzes:
        topic = q.get("topic", "")
        if topic and topic not in last_quiz_dates:
            last_quiz_dates[topic] = q["completed_at"]

    due_topics = compute_due_topics(proficiency, last_quiz_dates)
    log.info("spaced_repetition_computed", user_id=user_id, due_count=sum(1 for t in due_topics if t["is_due"]))

    return {"due_topics": due_topics}


@router.post("/study-session")
async def record_study_session(
    body: StudySessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Record a completed study session (pomodoro, quiz, reading, etc.) and award XP."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return {"ok": False}

    now = datetime.now(timezone.utc).isoformat()

    # XP: 5 per minute, capped at 50 per session.
    xp_earned = min(50, max(1, body.minutes) * 5)

    # Write session record and update XP/streak in parallel.
    await asyncio.gather(
        col_study_sessions().insert_one(
            {
                "id": str(uuid.uuid4()),
                "learner_id": learner["id"],
                "topic": body.topic,
                "minutes": max(1, body.minutes),
                "activity": body.activity,
                "recorded_at": now,
            }
        ),
        _update_xp_and_streak(user_id, xp_earned, now),
    )

    log.info("study_session_recorded", topic=body.topic, minutes=body.minutes, xp=xp_earned)
    return {"ok": True, "xp_earned": xp_earned}


async def _update_xp_and_streak(user_id: str, xp_delta: int, now_iso: str) -> None:
    """Atomically add XP and update the login streak based on last-active date."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return

    today = date.fromisoformat(now_iso[:10])
    last_active_str = learner.get("last_active_date")
    streak = learner.get("streak", 0)

    if last_active_str:
        try:
            last_active = date.fromisoformat(last_active_str)
            delta_days = (today - last_active).days
            if delta_days == 0:
                pass  # same day — streak unchanged
            elif delta_days == 1:
                streak += 1  # consecutive day
            else:
                streak = 1  # gap breaks the streak
        except ValueError:
            streak = 1
    else:
        streak = 1

    await col_learners().update_one(
        {"user_id": user_id},
        {
            "$inc": {"xp": xp_delta},
            "$set": {
                "streak": streak,
                "last_active_date": now_iso[:10],
                "updated_at": now_iso,
            },
        },
    )


@router.get("/report")
async def download_report(user_id: str = Depends(get_current_user_id)):
    """Download the full progress snapshot as a JSON file attachment."""
    progress = await get_progress(user_id=user_id)
    return JSONResponse(
        content=progress,
        headers={"Content-Disposition": "attachment; filename=progress-report.json"},
    )
