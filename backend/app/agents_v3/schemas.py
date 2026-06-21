"""
Pydantic models for the agents_v3 DeepAgent layer.

All inter-agent communication uses these typed models. AGENT_DISPLAY_NAMES is the
single source of truth for mapping internal route keys → user-facing product names.
"""

from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# SaaS display-name map — never expose internal keys to end users
# ---------------------------------------------------------------------------
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "doubt": "Learning Assistant",
    "quiz": "Quiz Creator",
    "curriculum": "Learning Path Builder",
    "progress": "Progress Tracker",
}

AgentKey = Literal["doubt", "quiz", "curriculum", "progress"]


# ---------------------------------------------------------------------------
# Structured output models
# ---------------------------------------------------------------------------


class CoTStep(BaseModel):
    step: int
    reasoning: str
    decision: str


class ToolCallRecord(BaseModel):
    name: str
    args: dict
    result: dict | None = None
    latency_ms: int = 0


class SideEffect(BaseModel):
    kind: str
    payload: dict


class AgentReport(BaseModel):
    agent_name: str
    display_name: str
    task: str
    cot_chain: list[CoTStep] = []
    tool_calls: list[ToolCallRecord] = []
    result: str
    side_effects: list[SideEffect] = []
    confidence: float = 1.0
    latency_ms: int = 0
    blocked: bool = False


class RoutingDecision(BaseModel):
    agent: AgentKey
    display_name: str
    reason: str
    confidence: float = 1.0

    @classmethod
    def from_agent_key(cls, agent: str, reason: str, confidence: float = 1.0) -> "RoutingDecision":
        key = agent if agent in AGENT_DISPLAY_NAMES else "doubt"
        return cls(
            agent=key,  # type: ignore[arg-type]
            display_name=AGENT_DISPLAY_NAMES[key],
            reason=reason,
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------


def _append_reports(existing: list, new: list) -> list:
    return existing + new


class DeepAgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    learner_id: str
    query: str
    context: dict
    routing_decision: RoutingDecision | None
    agent_reports: Annotated[list[AgentReport], _append_reports]
    final_response: str
    iteration: int


# ---------------------------------------------------------------------------
# Agent context passed through the middleware chain
# ---------------------------------------------------------------------------


class AgentContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    learner_id: str
    query: str
    context: dict
    system_prompt: str = ""
    blocked: bool = False
    block_reason: str = ""
