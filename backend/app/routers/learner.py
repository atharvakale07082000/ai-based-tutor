from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners
from app.schemas.learner import LearnerProfileSchema, LearnerProfileUpdate, OnboardRequest, OnboardResponse

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


async def _get_learner_or_404(user_id: str) -> dict:
    """Fetch a learner document by user_id or raise HTTP 404."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner profile not found")
    return learner


@router.get("/profile", response_model=LearnerProfileSchema)
async def get_profile(user_id: str = Depends(get_current_user_id)):
    """Return the learner's full profile including goals, XP, streak and proficiency map."""
    learner = await _get_learner_or_404(user_id)
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
    """Partial-update the learner's profile fields (name, goals, learning style, cadence)."""
    learner = await _get_learner_or_404(user_id)

    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.name is not None:
        updates["name"] = body.name
    if body.goal_vector is not None:
        updates["goal_vector"] = body.goal_vector
    if body.learning_style is not None:
        updates["learning_style"] = body.learning_style
    if body.session_cadence is not None:
        updates["session_cadence"] = body.session_cadence

    await col_learners().update_one({"user_id": user_id}, {"$set": updates})
    learner = await _get_learner_or_404(user_id)
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


@router.post("/onboard", response_model=OnboardResponse)
async def onboard(
    body: OnboardRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Save onboarding preferences: name, goals, hours/week, difficulty pacing."""
    difficulty_to_cadence = {
        "gentle": {"sessions_per_week": max(1, body.hoursPerWeek // 2), "pace": "gentle"},
        "balanced": {"sessions_per_week": max(2, body.hoursPerWeek // 2), "pace": "balanced"},
        "aggressive": {"sessions_per_week": max(3, body.hoursPerWeek), "pace": "aggressive"},
    }
    updates = {
        "name": body.name.strip(),
        "goal_vector": body.goals,
        "session_cadence": difficulty_to_cadence.get(body.difficulty, {"pace": "balanced"}),
        "hours_per_week": body.hoursPerWeek,
        "onboarded_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await col_learners().update_one({"user_id": user_id}, {"$set": updates}, upsert=True)
    log.info("learner_onboarded", user_id=user_id, name=body.name)
    return OnboardResponse(name=body.name.strip())
