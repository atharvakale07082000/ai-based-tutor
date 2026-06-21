"""Pydantic schemas for learner profile request/response bodies."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class LearnerProfileUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=50)
    goal_vector: list[str] | None = Field(None, max_length=20)
    learning_style: str | None = None
    session_cadence: dict[str, Any] | None = None


class OnboardRequest(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    goals: list[str] = Field(min_length=1, max_length=10)
    hoursPerWeek: int = Field(ge=1, le=40)
    difficulty: Literal["gentle", "balanced", "aggressive"]


class OnboardResponse(BaseModel):
    name: str
