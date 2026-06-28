"""Pydantic schemas for the Job Tracker (job applications + AI skill-gap analysis)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Application pipeline stages (Kanban columns, in order).
JOB_STAGES = ["saved", "applied", "interview", "offer", "rejected"]
JobStage = Literal["saved", "applied", "interview", "offer", "rejected"]

# Per-skill gap status against the learner's proficiency map.
SkillStatus = Literal["have", "partial", "missing"]


class SkillGap(BaseModel):
    skill: str
    have_elo: float | None = None  # learner's ELO for the matched topic, if any
    status: SkillStatus


class Recommendation(BaseModel):
    type: Literal["quiz", "course"]
    skill: str
    label: str
    url: str


class JDParseRequest(BaseModel):
    """Paste-a-job request: the raw job-description text to analyze."""

    jd_text: str = Field(min_length=20, max_length=20_000)


class JobCreate(BaseModel):
    """Save a job application (typically from an analyzed JD, but all fields are editable)."""

    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    seniority: str = Field(default="", max_length=80)
    required_skills: list[str] = Field(default=[], max_length=40)
    stage: JobStage = "saved"
    source_jd: str = Field(default="", max_length=20_000)
    readiness_score: float = Field(default=0.0, ge=0, le=100)
    skill_gaps: list[SkillGap] = []
    recommendations: list[Recommendation] = []
    notes: str = Field(default="", max_length=4_000)


class JobUpdate(BaseModel):
    """Partial update — move stage, edit notes, or correct fields."""

    company: str | None = Field(None, max_length=200)
    role: str | None = Field(None, max_length=200)
    seniority: str | None = Field(None, max_length=80)
    stage: JobStage | None = None
    notes: str | None = Field(None, max_length=4_000)


class JobApplication(JobCreate):
    """A stored job application, as returned to the client."""

    id: str
    learner_id: str
    created_at: str
    updated_at: str
