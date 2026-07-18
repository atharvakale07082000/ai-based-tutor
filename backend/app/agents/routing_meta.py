"""Display-name metadata for chat routing.

The orchestrator delegates to specialists by tool name; the chat router maps the
first delegated specialist to a human-facing name for the ``routing`` SSE event.
Kept as its own tiny module so nothing depends on the retired LangGraph router.
"""

from __future__ import annotations

# Specialist key (as used in tool/agent names) -> product display name.
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "doubt": "Learning Assistant",
    "quiz": "Quiz Creator",
    "curriculum": "Learning Path Builder",
    "progress": "Progress Tracker",
    "assistant": "AI Tutor",
}


def display_name(agent_key: str) -> str:
    return AGENT_DISPLAY_NAMES.get(agent_key, "AI Tutor")
