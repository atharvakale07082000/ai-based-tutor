import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.learner import LearnerProfile
from app.models.user import User
from app.schemas.learner import LearnerProfileSchema, LearnerProfileUpdate
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()


async def _get_learner(user_id: str, db: AsyncSession) -> LearnerProfile:
    result = await db.execute(
        select(LearnerProfile)
        .join(User, User.id == LearnerProfile.user_id)
        .where(User.id == user_id)
    )
    learner = result.scalar_one_or_none()
    if not learner:
        raise HTTPException(status_code=404, detail="Learner profile not found")
    return learner


@router.get("/profile", response_model=LearnerProfileSchema)
async def get_profile(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner = await _get_learner(user_id, db)
    return LearnerProfileSchema(
        id=str(learner.id),
        user_id=str(learner.user_id),
        name=learner.name,
        goal_vector=learner.goal_vector or [],
        topic_proficiency_map=learner.topic_proficiency_map or {},
        learning_style=learner.learning_style,
        xp=learner.xp,
        streak=learner.streak,
        curriculum_version=learner.curriculum_version,
    )


@router.put("/profile", response_model=LearnerProfileSchema)
async def update_profile(
    body: LearnerProfileUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner = await _get_learner(user_id, db)

    if body.name is not None:
        learner.name = body.name
    if body.goal_vector is not None:
        learner.goal_vector = body.goal_vector
    if body.learning_style is not None:
        learner.learning_style = body.learning_style
    if body.session_cadence is not None:
        learner.session_cadence = body.session_cadence

    await db.commit()
    await db.refresh(learner)
    log.info("learner_profile_updated", learner_id=str(learner.id))

    return LearnerProfileSchema(
        id=str(learner.id),
        user_id=str(learner.user_id),
        name=learner.name,
        goal_vector=learner.goal_vector or [],
        topic_proficiency_map=learner.topic_proficiency_map or {},
        learning_style=learner.learning_style,
        xp=learner.xp,
        streak=learner.streak,
        curriculum_version=learner.curriculum_version,
    )
