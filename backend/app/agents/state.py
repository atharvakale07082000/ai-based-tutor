from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

# Single source of truth — imported by all agents instead of repeating 700.0 literals.
MASTERY_THRESHOLD_DEFAULT: float = 700.0

# Single source of truth — imported by all agents instead of repeating 700.0 literals.
MASTERY_THRESHOLD_DEFAULT: float = 700.0


def _append_reports(existing: list, new: list) -> list:
    """Reducer: append new agent reports without overwriting prior ones."""
    return list(existing or []) + list(new or [])


class AgentState(TypedDict):
    learner_id: str
    task_type: str  # "curriculum" | "quiz" | "progress" | "doubt" | "start"
    messages: Annotated[list[BaseMessage], add_messages]
    learner_profile: dict
    topic_proficiency: dict  # topic -> Elo score 0-1000
    current_topic: str
    quiz_questions: list[dict]
    curriculum_path: list[dict]
    doubt_response: str
    progress_delta: dict
    bloom_level: str
    error: str | None

    # ── Supervisor (multi-agent) fields ───────────────────────────────────────
    # Each agent appends a structured brief here; supervisor reads them to decide.
    agent_reports: Annotated[list[dict], _append_reports]
    supervisor_decision: str  # last routing decision made by LLM supervisor
    iteration_count: int  # incremented by supervisor on each loop
    max_iterations: int  # hard cap (default 8)
    session_complete: bool
    mastery_threshold: float  # Elo threshold for mastery (default 700)

    # ── Cross-agent signals ────────────────────────────────────────────────────
    # Written by progress_agent and doubt_agent; read by quiz_agent and supervisor.
    learner_mood: str  # "POSITIVE" | "NEUTRAL" | "NEGATIVE"
    learner_mood_score: float  # 0.0–1.0 confidence from analyze_sentiment

    # Written by quiz_agent (via score_difficulty); read by supervisor summary.
    topic_difficulty: float  # 0.0–1.0 difficulty of current_topic

    # ── Cross-agent signals ────────────────────────────────────────────────────
    # Written by progress_agent and doubt_agent; read by quiz_agent and supervisor.
    learner_mood: str  # "POSITIVE" | "NEUTRAL" | "NEGATIVE"
    learner_mood_score: float  # 0.0–1.0 confidence from analyze_sentiment

    # Written by quiz_agent (via score_difficulty); read by supervisor summary.
    topic_difficulty: float  # 0.0–1.0 difficulty of current_topic

    # Legacy compat fields (kept so existing routers don't break)
    next_action: str
    resume_action: str
