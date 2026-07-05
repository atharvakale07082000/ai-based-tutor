"""
AssistantAgent — general-purpose AI tutor assistant with access to all 13
registered tools. Used as the fallback when the router is not confident.
"""

from __future__ import annotations

from app.agents_v2.base import BaseAgent


class AssistantAgent(BaseAgent):
    name = "AssistantAgent"
    # role_description is sourced from prompts/react_agent.yaml (roles.AssistantAgent).
    tool_names = [
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
        "check_guardrail",
    ]
