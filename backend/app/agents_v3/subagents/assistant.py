"""
AssistantSubAgent — fallback agent with access to ALL 13 tools.
Used when the orchestrator cannot confidently route to a domain agent.
Mirrors v2 AssistantAgent capability parity.
"""

from __future__ import annotations

from app.agents_v3.middleware.base import MiddlewareChain
from app.agents_v3.subagents.base import BaseSubAgent


class AssistantSubAgent(BaseSubAgent):
    name = "assistant"
    role_description = (
        "a versatile learning companion who shows up for every kind of request — "
        "from answering a quick concept question to designing a full curriculum. "
        "You're warm, adaptable, and genuinely invested in the learner's growth. "
        "No question is too simple. No goal is too ambitious. You meet the learner "
        "wherever they are and help them take the next best step forward."
    )
    tool_names = [
        "check_guardrail",
        "classify_topic",
        "analyze_sentiment",
        "score_difficulty",
        "generate_quiz",
        "get_embeddings",
        "generate_explanation",
        "get_proficiency",
        "get_topic_graph",
        "save_quiz",
        "save_progress",
        "get_due_topics",
        "calculate_elo",
    ]

    def __init__(self, middleware: MiddlewareChain) -> None:
        super().__init__(middleware)
        self.max_steps = 8  # more steps for general tasks
