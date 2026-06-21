from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners
from app.schemas.learner import JOB_ROLES, LearnerProfileSchema, LearnerProfileUpdate, OnboardRequest, OnboardResponse

limiter = Limiter(key_func=get_remote_address)

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


def _to_schema(learner: dict) -> LearnerProfileSchema:
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
        target_role=learner.get("target_role"),
        current_role=learner.get("current_role"),
        years_of_experience=learner.get("years_of_experience"),
        job_search_urgency=learner.get("job_search_urgency"),
        preferred_companies=learner.get("preferred_companies") or [],
        job_readiness_score=learner.get("job_readiness_score"),
    )


async def _get_learner_or_404(user_id: str) -> dict:
    """Fetch a learner document by user_id or raise HTTP 404."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner profile not found")
    return learner


@router.get("/roles")
async def list_job_roles():
    """Return the canonical list of supported target job roles for onboarding autocomplete."""
    return {"roles": JOB_ROLES}


@router.get("/profile", response_model=LearnerProfileSchema)
async def get_profile(user_id: str = Depends(get_current_user_id)):
    """Return the learner's full profile including goals, XP, streak and proficiency map."""
    learner = await _get_learner_or_404(user_id)
    return _to_schema(learner)


@router.put("/profile", response_model=LearnerProfileSchema)
async def update_profile(
    body: LearnerProfileUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Partial-update the learner's profile fields (name, goals, learning style, cadence)."""
    learner = await _get_learner_or_404(user_id)

    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    for field in (
        "name",
        "goal_vector",
        "learning_style",
        "session_cadence",
        "target_role",
        "current_role",
        "years_of_experience",
        "job_search_urgency",
        "preferred_companies",
    ):
        val = getattr(body, field, None)
        if val is not None:
            updates[field] = val

    await col_learners().update_one({"user_id": user_id}, {"$set": updates})
    learner = await _get_learner_or_404(user_id)
    log.info("learner_profile_updated", learner_id=learner["id"])
    return _to_schema(learner)


@router.post("/onboard", response_model=OnboardResponse)
@limiter.limit("5/day")
async def onboard(
    request: Request,
    body: OnboardRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Save onboarding preferences: name, target role, urgency, experience."""
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
        # Job-seeker fields
        "target_role": body.target_role.strip() if body.target_role else "",
        "current_role": body.current_role.strip() if body.current_role else "",
        "years_of_experience": body.years_of_experience,
        "job_search_urgency": body.job_search_urgency,
        "preferred_companies": body.preferred_companies,
        "onboarded_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await col_learners().update_one({"user_id": user_id}, {"$set": updates}, upsert=True)
    log.info("learner_onboarded", user_id=user_id, name=body.name, target_role=body.target_role)
    return OnboardResponse(name=body.name.strip())
