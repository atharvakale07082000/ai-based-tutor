"""
Pydantic schemas for agent skill inputs and outputs.

Used for:
1. Validating incoming payloads before agent execution
2. Validating outgoing responses before sending to callers
3. CI coverage check: every agent skill must have an input + output model here

Naming convention:
  <AgentName><Skill>Input   — what the skill accepts
  <AgentName><Skill>Output  — what the skill returns
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ── Shared types ──────────────────────────────────────────────────────────────

BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
Mood = Literal["POSITIVE", "NEUTRAL", "NEGATIVE"]


class CurriculumItem(BaseModel):
    domain: str
    subtopic: str
    priority: int
    elo: float = Field(ge=0, le=1000)


class QuizQuestion(BaseModel):
    question: str = Field(min_length=5)
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0, le=5)
    bloom_level: BloomLevel
    explanation: str = ""


# ── Supervisor ────────────────────────────────────────────────────────────────


class SupervisorInput(BaseModel):
    task_type: str
    iteration_count: int = Field(ge=0)
    max_iterations: int = Field(ge=1)
    curriculum_path: list[CurriculumItem] = []
    topic_proficiency: dict[str, float] = {}
    quiz_questions: list[dict] = []
    progress_delta: dict = {}
    learner_mood: Mood = "NEUTRAL"
    mastery_threshold: float = Field(default=700.0, ge=0, le=1000)


class SupervisorOutput(BaseModel):
    supervisor_decision: str
    iteration_count: int
    session_complete: bool
    agent_reports: list[dict] = []


# ── Curriculum agent ──────────────────────────────────────────────────────────


class CurriculumInput(BaseModel):
    learner_id: str = Field(min_length=1)
    learner_profile: dict = {}
    topic_proficiency: dict[str, float] = {}


class CurriculumOutput(BaseModel):
    curriculum_path: list[CurriculumItem]
    error: str | None = None
    agent_reports: list[dict] = []


# ── Quiz agent ────────────────────────────────────────────────────────────────


class QuizInput(BaseModel):
    current_topic: str = Field(min_length=1, max_length=200)
    bloom_level: BloomLevel = "understand"
    elo: float = Field(default=500.0, ge=0, le=1000)
    learner_mood: Mood = "NEUTRAL"


class QuizOutput(BaseModel):
    quiz_questions: list[QuizQuestion]
    bloom_level: BloomLevel
    topic_difficulty: float = Field(ge=0, le=1)
    error: str | None = None
    agent_reports: list[dict] = []

    @model_validator(mode="after")
    def at_least_one_question_or_error(self) -> "QuizOutput":
        if not self.quiz_questions and not self.error:
            raise ValueError("quiz_questions must be non-empty unless error is set")
        return self


# ── Doubt agent ───────────────────────────────────────────────────────────────


class DoubtInput(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    current_topic: str = ""
    bloom_level: BloomLevel = "understand"


class DoubtOutput(BaseModel):
    doubt_response: str = Field(min_length=1)
    learner_mood: Mood = "NEUTRAL"
    learner_mood_score: float = Field(default=0.5, ge=0, le=1)
    error: str | None = None
    agent_reports: list[dict] = []


# ── Progress agent ────────────────────────────────────────────────────────────


class ProgressInput(BaseModel):
    current_topic: str = Field(min_length=1)
    quiz_score: float = Field(ge=0, le=1)
    current_elo: float = Field(default=500.0, ge=0, le=1000)
    reflection: str = ""


class ProgressOutput(BaseModel):
    topic_proficiency: dict[str, float]
    progress_delta: dict
    learner_mood: Mood = "NEUTRAL"
    learner_mood_score: float = Field(default=0.5, ge=0, le=1)
    error: str | None = None
    agent_reports: list[dict] = []


# ── V2 Chat request/response ──────────────────────────────────────────────────


class V2ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default=[], max_length=20)
    context: dict = {}


class AgentError(BaseModel):
    """Structured error returned on validation failure (never a stack trace)."""

    code: str
    message: str
    agent: str = ""
    field: str = ""
