"""Pydantic schemas for learner profile request/response bodies."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Canonical job role slugs shown in onboarding autocomplete
JOB_ROLES = [
    "Software Engineer",
    "Senior Software Engineer",
    "Frontend Engineer",
    "Backend Engineer",
    "Full Stack Engineer",
    "Data Scientist",
    "ML Engineer",
    "Data Engineer",
    "DevOps / Platform Engineer",
    "Product Manager",
    "QA Engineer",
    "Site Reliability Engineer",
    "Security Engineer",
    "Mobile Engineer",
    "Solutions Architect",
]


class LearnerProfileSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    goal_vector: list[str]
    topic_proficiency_map: dict[str, float]
    learning_style: str
    xp: int
    streak: int
    curriculum_version: int
    # Job-seeker fields (may be absent on old profiles)
    target_role: str | None = None
    current_role: str | None = None
    years_of_experience: int | None = None
    job_search_urgency: str | None = None
    preferred_companies: list[str] = []
    job_readiness_score: float | None = None


class LearnerProfileUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=50)
    goal_vector: list[str] | None = Field(None, max_length=20)
    learning_style: str | None = None
    session_cadence: dict[str, Any] | None = None
    target_role: str | None = Field(None, max_length=100)
    current_role: str | None = Field(None, max_length=100)
    years_of_experience: int | None = Field(None, ge=0, le=50)
    job_search_urgency: Literal["actively_looking", "exploring", "not_yet"] | None = None
    preferred_companies: list[str] | None = Field(None, max_length=5)


class OnboardRequest(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    # Legacy learning fields (kept for backwards compat)
    goals: list[str] = Field(default=[], max_length=10)
    hoursPerWeek: int = Field(default=10, ge=1, le=40)
    difficulty: Literal["gentle", "balanced", "aggressive"] = "balanced"
    # Job-seeker fields
    target_role: str = Field(default="", max_length=100)
    current_role: str = Field(default="", max_length=100)
    years_of_experience: int = Field(default=0, ge=0, le=50)
    job_search_urgency: Literal["actively_looking", "exploring", "not_yet"] = "exploring"
    preferred_companies: list[str] = Field(default=[], max_length=5)


class OnboardResponse(BaseModel):
    name: str
