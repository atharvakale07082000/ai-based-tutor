"""ProgressSubAgent — updates learner Elo, detects mood, saves progress."""

from __future__ import annotations

from app.agents_v3.middleware.base import MiddlewareChain
from app.agents_v3.subagents.base import BaseSubAgent


class ProgressSubAgent(BaseSubAgent):
    name = "progress"
    role_description = (
        "a supportive growth coach who turns raw data into meaningful milestones. "
        "You track how the learner is growing, notice when they need encouragement, "
        "and celebrate every step forward — whether it's a 5-point Elo gain or "
        "consistency over a tough week. You update their record with care and "
        "always frame growth in a positive, motivating way."
    )
    tool_names = ["get_proficiency", "calculate_elo", "analyze_sentiment", "save_progress"]

    def __init__(self, middleware: MiddlewareChain) -> None:
        super().__init__(middleware)

    def _build_system_prompt(self) -> str:
        base = super()._build_system_prompt()
        return (
            base + "\n\nWhen progress is saved, emit a side_effect:\n"
            '{"kind":"progress_updated","payload":{"topic":"<topic>",'
            '"old_elo":<float>,"new_elo":<float>,"mood":"<positive|neutral|negative>"}}'
        )
