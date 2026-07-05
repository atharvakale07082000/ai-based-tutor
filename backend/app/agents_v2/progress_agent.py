"""
ProgressAgent — updates Elo proficiency scores after quiz attempts and
captures learner mood from reflection text.
"""

from __future__ import annotations

from app.agents_v2.base import BaseAgent


class ProgressAgent(BaseAgent):
    name = "ProgressAgent"
    # role_description is sourced from prompts/react_agent.yaml (roles.ProgressAgent).
    tool_names = [
        "get_proficiency",
        "calculate_elo",
        "analyze_sentiment",
        "save_progress",
    ]
