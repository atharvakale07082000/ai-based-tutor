import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

from app.db.mongo import col_learners
from app.schemas.learner import LearnerProfileSchema, LearnerProfileUpdate
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


def _get_learner_or_404(user_id: str) -> dict:
    learner = col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner profile not found")
    return learner


@router.get("/profile", response_model=LearnerProfileSchema)
async def get_profile(user_id: str = Depends(get_current_user_id)):
    learner = _get_learner_or_404(user_id)
    return LearnerProfileSchema(
        id=learner["id"],
        user_id=learner["user_id"],
        name=learner.get("name", ""),
        goal_vector=learner.get("goal_vector") or [],
        topic_proficiency_map=learner.get("topic_proficiency_map") or {},
        learning_style=learner.get("learning_style", "visual"),
        xp=learner.get("xp", 0),
        streak=learner.get("streak", 0),
        curriculum_version=learner.get("curriculum_version", 1),
    )


@router.put("/profile", response_model=LearnerProfileSchema)
async def update_profile(
    body: LearnerProfileUpdate,
    user_id: str = Depends(get_current_user_id),
):
    learner = _get_learner_or_404(user_id)

    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.name is not None:
        updates["name"] = body.name
    if body.goal_vector is not None:
        updates["goal_vector"] = body.goal_vector
    if body.learning_style is not None:
        updates["learning_style"] = body.learning_style
    if body.session_cadence is not None:
        updates["session_cadence"] = body.session_cadence

    col_learners().update_one({"user_id": user_id}, {"$set": updates})
    learner = _get_learner_or_404(user_id)
    log.info("learner_profile_updated", learner_id=learner["id"])

    return LearnerProfileSchema(
        id=learner["id"],
        user_id=learner["user_id"],
        name=learner.get("name", ""),
        goal_vector=learner.get("goal_vector") or [],
        topic_proficiency_map=learner.get("topic_proficiency_map") or {},
        learning_style=learner.get("learning_style", "visual"),
        xp=learner.get("xp", 0),
        streak=learner.get("streak", 0),
        curriculum_version=learner.get("curriculum_version", 1),
    )
