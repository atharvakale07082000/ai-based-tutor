"""QuizSubAgent — generates Bloom-calibrated quizzes adapted to learner Elo."""

from __future__ import annotations

from app.agents_v3.middleware.base import MiddlewareChain
from app.agents_v3.subagents.base import BaseSubAgent


class QuizSubAgent(BaseSubAgent):
    name = "quiz"
    role_description = (
        "an encouraging challenge-setter who turns learning into an exciting game. "
        "You create questions that stretch the learner just enough — not too easy, "
        "not overwhelming. You always check where they are before you design questions, "
        "so every quiz feels personally crafted for them. You celebrate the act of testing "
        "oneself as the fastest path to mastery."
    )
    tool_names = ["get_proficiency", "score_difficulty", "generate_quiz", "save_quiz"]

    def __init__(self, middleware: MiddlewareChain) -> None:
        super().__init__(middleware)

    def _build_system_prompt(self) -> str:
        base = super()._build_system_prompt()
        return (
            base + "\n\nWhen the quiz is saved, emit a side_effect:\n"
            '{"kind":"quiz_created","payload":{"quiz_id":"<id>",'
            '"topic":"<topic>","question_count":<n>,"bloom_level":"<level>",'
            '"url":"/quiz/<id>"}}'
        )
