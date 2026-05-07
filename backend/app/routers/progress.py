import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.learner import LearnerProfile
from app.models.user import User
from app.models.quiz import ProgressRecord, QuizSession
from app.models.doubts import DoubtSession
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()


@router.get("")
async def get_progress(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner_result = await db.execute(
        select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
    )
    learner = learner_result.scalar_one_or_none()
    if not learner:
        return {"topic_proficiency": {}, "history": []}

    records_result = await db.execute(
        select(ProgressRecord)
        .where(ProgressRecord.learner_id == learner.id)
        .order_by(ProgressRecord.recorded_at.asc())
        .limit(100)
    )
    records = records_result.scalars().all()

    quizzes_result = await db.execute(
        select(QuizSession)
        .where(QuizSession.learner_id == learner.id, QuizSession.completed_at != None)
    )
    quizzes = quizzes_result.scalars().all()

    doubts_result = await db.execute(
        select(DoubtSession).where(DoubtSession.learner_id == learner.id)
    )
    doubt_sessions = doubts_result.scalars().all()

    quiz_accuracy = 0.0
    if quizzes:
        quiz_accuracy = sum(q.score or 0 for q in quizzes) / len(quizzes)

    mood_timeline = [
        {"session_id": str(d.id), "mood": d.sentiment_mood or "NEUTRAL", "date": d.started_at.isoformat()}
        for d in doubt_sessions
        if d.sentiment_mood
    ]

    return {
        "learner_id": str(learner.id),
        "topic_proficiency": learner.topic_proficiency_map or {},
        "history": [
            {"topic": r.topic, "elo_score": r.elo_score, "recorded_at": r.recorded_at.isoformat()}
            for r in records
        ],
        "total_study_minutes": len(quizzes) * 15,
        "quiz_accuracy": quiz_accuracy,
        "doubts_resolved": len(doubt_sessions),
        "streak": learner.streak,
        "mood_timeline": mood_timeline,
    }


@router.get("/report")
async def download_report(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    progress = await get_progress(user_id=user_id, db=db)
    # Return JSON as a downloadable file (PDF generation would require reportlab/weasyprint)
    return JSONResponse(
        content=progress,
        headers={"Content-Disposition": "attachment; filename=progress-report.json"},
    )
