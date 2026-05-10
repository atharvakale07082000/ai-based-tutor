from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


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
    supervisor_decision: str   # last routing decision made by LLM supervisor
    iteration_count: int       # incremented by supervisor on each loop
    max_iterations: int        # hard cap (default 8)
    session_complete: bool
    mastery_threshold: float   # Elo threshold for mastery (default 700)

    # Legacy compat fields (kept so existing routers don't break)
    next_action: str
    resume_action: str
