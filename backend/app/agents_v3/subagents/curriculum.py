"""CurriculumSubAgent — builds personalised learning paths from the topic graph."""

from __future__ import annotations

from app.agents_v3.middleware.base import MiddlewareChain
from app.agents_v3.subagents.base import BaseSubAgent


class CurriculumSubAgent(BaseSubAgent):
    name = "curriculum"
    role_description = (
        "a thoughtful guide who designs personalised journeys, not generic syllabi. "
        "You respect the learner's existing knowledge, their goals, and their pace. "
        "You build paths that feel like a well-curated adventure — each topic unlocking "
        "the next, with no wasted steps. You prioritise spaced repetition and also "
        "surface topics the learner should revisit before they fall behind."
    )
    # get_due_topics added vs v2 — surfaces spaced-repetition overdue topics
    tool_names = ["classify_topic", "get_topic_graph", "get_proficiency", "get_due_topics"]

    def __init__(self, middleware: MiddlewareChain) -> None:
        super().__init__(middleware)

    def _build_system_prompt(self) -> str:
        base = super()._build_system_prompt()
        return (
            base + "\n\nWhen a curriculum plan is ready, emit a side_effect:\n"
            '{"kind":"plan_created","payload":{"title":"<title>",'
            '"module_count":<n>,"url":"/curriculum/<id>"}}'
        )
