"""
Chat orchestrator — the "pure orchestrator" router.

Every chat turn goes through ``route``: a Strands agent (no domain tools) makes
one LLM call and returns an ordered list of specialist keys to run. This is the
single always-on LLM routing decision; the handler then streams the chosen
specialist(s) directly, so the learner hears one voice and specialist traces +
action events surface without a second synthesis pass.

A deterministic keyword heuristic is kept ONLY as a fallback when the routing
LLM call errors or returns nothing valid — never as the primary path.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field
from strands import Agent

from app.agents.model import get_nim_model
from app.agents.specialists import SPECIALISTS
from app.prompts.loader import get_section

log = structlog.get_logger()

_VALID = set(SPECIALISTS)  # doubt/quiz/curriculum/progress/assistant


class RoutePlan(BaseModel):
    agents: list[str] = Field(
        description="Ordered specialist keys to run: doubt/quiz/curriculum/progress/assistant.",
        min_length=1,
    )
    reason: str = Field(description="One short line on why.", default="")


_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("quiz", ("quiz", "test me", "assess", "examine")),
    ("curriculum", ("learn", "roadmap", "curriculum", "study plan", "path")),
    ("progress", ("my progress", "elo", "how am i doing", "update my", "score")),
    ("doubt", ("explain", "what is", "how does", "why", "confused", "difference")),
]


def _heuristic(query: str) -> list[str]:
    q = query.lower()
    for key, words in _KEYWORDS:
        if any(w in q for w in words):
            return [key]
    return ["assistant"]


def build_router() -> Agent:
    return Agent(
        name="Orchestrator",
        model=get_nim_model("orchestrator"),
        system_prompt=get_section("orchestrator", "system"),
        callback_handler=None,
    )


async def route(query: str, router: Agent) -> tuple[list[str], str]:
    """Return (ordered specialist keys, reason). LLM-first, heuristic fallback."""
    try:
        result = await router.invoke_async(query, structured_output_model=RoutePlan)
        plan = result.structured_output
        agents = [a for a in (plan.agents or []) if a in _VALID]
        if agents:
            return agents, plan.reason or "llm route"
        log.warning("orchestrator_empty_plan", raw=str(plan.agents)[:120])
    except Exception as e:  # noqa: BLE001 - routing must never hard-fail the request
        log.warning("orchestrator_route_error", error=str(e)[:200])
    return _heuristic(query), "heuristic fallback"
