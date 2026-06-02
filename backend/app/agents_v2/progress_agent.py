"""
ProgressAgent — updates Elo proficiency scores after quiz attempts and
captures learner mood from reflection text.
"""

from __future__ import annotations

from app.agents_v2.base import BaseAgent


class ProgressAgent(BaseAgent):
    name = "ProgressAgent"
    role_description = (
        "You update Elo proficiency scores after quiz attempts and capture learner mood from reflections."
    )
    tool_names = ["get_proficiency", "calculate_elo", "analyze_sentiment", "save_progress"]

    def build_system_prompt(self) -> str:
        base = super().build_system_prompt()
        return (
            base + "\n\nWhen done, include a side_effect: "
            "{kind: 'progress_updated', payload: {topic: str, old_elo: float, new_elo: float, mood: str}}"
        )
