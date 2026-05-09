import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.mongo import col_learners, col_progress, col_quizzes, col_doubts
from app.auth.jwt import get_current_user_id

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


@router.get("/report")
async def download_report(user_id: str = Depends(get_current_user_id)):
    progress = await get_progress(user_id=user_id)
    return JSONResponse(
        content=progress,
        headers={"Content-Disposition": "attachment; filename=progress-report.json"},
    )
