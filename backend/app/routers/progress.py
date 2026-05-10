import uuid
import structlog
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.mongo import col_learners, col_progress, col_quizzes, col_doubts, col_study_sessions
from app.auth.jwt import get_current_user_id
from app.hf.spaced_repetition import compute_due_topics

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


class StudySessionRequest(BaseModel):
    minutes: int
    topic: str = "general"
    activity: str = "study"   # "pomodoro" | "quiz" | "reading" | "study"


@router.get("")
async def get_progress(user_id: str = Depends(get_current_user_id)):
    learner = col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return {"topic_proficiency": {}, "history": []}

    records = list(
        col_progress().find({"learner_id": learner["id"]}, PROJ)
        .sort("recorded_at", 1).limit(100)
    )
    quizzes = list(
        col_quizzes().find(
            {"learner_id": learner["id"], "completed_at": {"$ne": None}},
            PROJ,
        )
    )
    doubt_sessions = list(col_doubts().find({"learner_id": learner["id"]}, PROJ))

    quiz_accuracy = 0.0
    if quizzes:
        quiz_accuracy = sum(q.get("score") or 0 for q in quizzes) / len(quizzes)

    mood_timeline = [
        {"session_id": d["id"], "mood": d["sentiment_mood"], "date": d.get("started_at")}
        for d in doubt_sessions
        if d.get("sentiment_mood")
    ]

    study_sessions = list(col_study_sessions().find({"learner_id": learner["id"]}, PROJ))
    total_study_minutes = sum(s.get("minutes", 0) for s in study_sessions) + len(quizzes) * 15

    return {
        "learner_id": learner["id"],
        "topic_proficiency": learner.get("topic_proficiency_map") or {},
        "history": [
            {"topic": r["topic"], "elo_score": r["elo_score"], "recorded_at": r.get("recorded_at")}
            for r in records
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
    Spaced repetition scheduler: returns topics ordered by urgency.
    Uses SM-2-inspired algorithm with HuggingFace difficulty scoring support.
    """
    learner = col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return {"due_topics": []}

    proficiency = learner.get("topic_proficiency_map") or {}
    quizzes = list(
        col_quizzes().find(
            {"learner_id": learner["id"], "completed_at": {"$ne": None}},
            {"_id": 0, "topic": 1, "completed_at": 1},
        ).sort("completed_at", -1)
    )

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
    """Record a completed study session (pomodoro, quiz, reading, etc.)."""
    learner = col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return {"ok": False}

    now = datetime.now(timezone.utc).isoformat()

    col_study_sessions().insert_one({
        "id": str(uuid.uuid4()),
        "learner_id": learner["id"],
        "topic": body.topic,
        "minutes": max(1, body.minutes),
        "activity": body.activity,
        "recorded_at": now,
    })

    # Award XP: 5 XP per minute, capped at 50 per session
    xp_earned = min(50, max(1, body.minutes) * 5)
    _update_xp_and_streak(user_id, xp_earned, now)

    log.info("study_session_recorded", topic=body.topic, minutes=body.minutes, xp=xp_earned)
    return {"ok": True, "xp_earned": xp_earned}


def _update_xp_and_streak(user_id: str, xp_delta: int, now_iso: str) -> None:
    """Atomically add XP and update streak based on last_active date."""
    learner = col_learners().find_one({"user_id": user_id}, PROJ)
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
                pass                   # same day, no streak change
            elif delta_days == 1:
                streak += 1            # consecutive day
            else:
                streak = 1             # streak broken
        except ValueError:
            streak = 1
    else:
        streak = 1

    col_learners().update_one(
        {"user_id": user_id},
        {"$inc": {"xp": xp_delta}, "$set": {"streak": streak, "last_active_date": now_iso[:10], "updated_at": now_iso}},
    )


@router.get("/report")
async def download_report(user_id: str = Depends(get_current_user_id)):
    progress = await get_progress(user_id=user_id)
    return JSONResponse(
        content=progress,
        headers={"Content-Disposition": "attachment; filename=progress-report.json"},
    )
