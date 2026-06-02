"""
CurriculumAgent — builds personalized learning paths by analyzing learner
goals and proficiency gaps using the topic graph.
"""

from __future__ import annotations

from app.agents_v2.base import BaseAgent


class CurriculumAgent(BaseAgent):
    name = "CurriculumAgent"
    role_description = "You build personalized learning paths by analyzing the learner's goals and proficiency gaps."
    tool_names = ["classify_topic", "get_topic_graph", "get_proficiency"]

    def build_system_prompt(self) -> str:
        base = super().build_system_prompt()
        return (
            base + "\n\nWhen done, include a side_effect: "
            "{kind: 'plan_created', payload: {title: str, module_count: int, url: '/curriculum'}}"
        )
