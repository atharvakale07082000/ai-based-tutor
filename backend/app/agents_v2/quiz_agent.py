"""
QuizAgent — generates adaptive Bloom-calibrated quizzes tailored to the
learner's current proficiency (Elo score).
"""
from __future__ import annotations

from app.agents_v2.base import BaseAgent


class QuizAgent(BaseAgent):
    name = "QuizAgent"
    role_description = (
        "You generate adaptive Bloom-calibrated quizzes tailored to the learner's current proficiency."
    )
    tool_names = ["get_proficiency", "score_difficulty", "generate_quiz", "save_quiz"]

    def build_system_prompt(self) -> str:
        base = super().build_system_prompt()
        return (
            base
            + "\n\nWhen done, include a side_effect: "
            "{kind: 'quiz_created', payload: {quiz_id: str, topic: str, question_count: int, bloom_level: str, url: '/quiz/{quiz_id}'}}"
        )
