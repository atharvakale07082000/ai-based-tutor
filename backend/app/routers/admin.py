import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.learner import LearnerProfile
from app.models.user import User
from app.models.doubts import DoubtSession
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()

# In-memory agent config (in production this would be in Redis/DB)
_agent_config = {
    "quiz_frequency": 3,
    "difficulty_ceiling": 0.8,
    "escalation_threshold": 3,
}


@router.get("/learners")
async def get_learners(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(20),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(LearnerProfile, User).join(User, User.id == LearnerProfile.user_id)
    if search:
        query = query.where(
            (LearnerProfile.name.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%"))
        )

    result = await db.execute(query.offset((page - 1) * limit).limit(limit))
    rows = result.all()

    items = []
    for learner, user in rows:
        proficiency = learner.topic_proficiency_map or {}
        avg_proficiency = sum(proficiency.values()) / max(len(proficiency), 1) if proficiency else 0

        # Get latest mood
        mood_result = await db.execute(
            select(DoubtSession.sentiment_mood)
            .where(DoubtSession.learner_id == learner.id, DoubtSession.sentiment_mood != None)
            .order_by(DoubtSession.started_at.desc())
            .limit(1)
        )
        mood = mood_result.scalar_one_or_none()

        items.append({
            "id": str(learner.id),
            "name": learner.name,
            "email": user.email,
            "avg_proficiency": avg_proficiency,
            "last_active": learner.updated_at.isoformat() if learner.updated_at else "",
            "mood": mood,
            "topic_proficiency": proficiency,
        })

    return {"items": items, "total": len(items)}


@router.put("/config")
async def update_config(
    config: dict,
    user_id: str = Depends(get_current_user_id),
):
    _agent_config.update({k: v for k, v in config.items() if k in _agent_config})
    log.info("admin_config_updated", config=_agent_config)
    return {"config": _agent_config}


@router.get("/config")
async def get_config(user_id: str = Depends(get_current_user_id)):
    return _agent_config
