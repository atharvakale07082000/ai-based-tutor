"""
Pydantic schemas for eval records stored in MongoDB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

EvalType = Literal[
    # ── Structural / rule-based ──────────────────────────────────────────────
    "quiz_format",
    "doubt_relevance",
    "curriculum_ordering",
    "planner_decision",
    "guardrail_triggered",
    "progress_elo",
    "supervisor_routing",
    # ── LLM-as-judge ─────────────────────────────────────────────────────────
    "doubt_accuracy",
    "quiz_bloom_alignment",
    "curriculum_coherence",
    # ── Chat orchestrator ─────────────────────────────────────────────────────
    "chat_session",  # full assistant turn: routing + response + delegation
    "chat_guardrail",  # turn blocked by input guardrail before any agent ran
]


class EvalRecord(BaseModel):
    """Represents a single evaluation result for one agent invocation."""

    eval_type: EvalType
    agent: str
    learner_id: str = ""
    trace_id: str = ""
    session_id: str = ""

    # What went in / what came out
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)

    # Score in [0.0, 1.0] — 1.0 = perfect, 0.0 = complete failure
    score: float
    passed: bool
    details: dict = Field(default_factory=dict)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    langfuse_trace_url: str | None = None

    def to_mongo(self) -> dict:
        d = self.model_dump()
        d["timestamp"] = self.timestamp  # Motor handles datetime natively
        return d


class EvalQuery(BaseModel):
    eval_type: EvalType | None = None
    agent: str | None = None
    learner_id: str | None = None
    passed: bool | None = None
    limit: int = 50


class EvalSummary(BaseModel):
    eval_type: EvalType
    agent: str
    total: int
    passed: int
    avg_score: float
    pass_rate: float
