from typing import Any
from pydantic import BaseModel, ConfigDict


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
    name: str | None = None
    goal_vector: list[str] | None = None
    learning_style: str | None = None
    session_cadence: dict[str, Any] | None = None
