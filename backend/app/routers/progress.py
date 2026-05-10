import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.mongo import col_learners, col_progress, col_quizzes, col_doubts
from app.auth.jwt import get_current_user_id
from app.hf.spaced_repetition import compute_due_topics

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


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

    return {
        "learner_id": learner["id"],
        "topic_proficiency": learner.get("topic_proficiency_map") or {},
        "history": [
            {"topic": r["topic"], "elo_score": r["elo_score"], "recorded_at": r.get("recorded_at")}
            for r in records
        ],
        "total_study_minutes": len(quizzes) * 15,
        "quiz_accuracy": quiz_accuracy,
        "doubts_resolved": len(doubt_sessions),
        "streak": learner.get("streak", 0),
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


@router.get("/report")
async def download_report(user_id: str = Depends(get_current_user_id)):
    progress = await get_progress(user_id=user_id)
    return JSONResponse(
        content=progress,
        headers={"Content-Disposition": "attachment; filename=progress-report.json"},
    )
