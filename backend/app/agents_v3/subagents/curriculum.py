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
    # web_search enables dynamic curricula for any topic outside the static graph
    tool_names = ["web_search", "classify_topic", "get_topic_graph", "get_proficiency", "get_due_topics"]

    def __init__(self, middleware: MiddlewareChain) -> None:
        super().__init__(middleware)

    def _build_system_prompt(self) -> str:
        base = super()._build_system_prompt()
        return (
            base + "\n\n## Curriculum strategy\n"
            "1. First check if the learner's query matches a topic already in the topic graph "
            "(use get_topic_graph). If it does, build from there.\n"
            "2. If the topic is custom or specialised (e.g. 'LangChain agents', 'Rust async', "
            "'Kubernetes networking'), use web_search to research it first, then design a "
            "structured module-by-module roadmap from those findings.\n"
            "3. Always personalise using get_proficiency — skip what the learner already knows.\n"
            "4. Structure the curriculum as numbered modules with clear learning outcomes.\n"
            "5. When the plan is ready, emit a side_effect:\n"
            '{"kind":"plan_created","payload":{"title":"<title>","module_count":<n>,"url":"/curriculum/<id>"}}'
        )
