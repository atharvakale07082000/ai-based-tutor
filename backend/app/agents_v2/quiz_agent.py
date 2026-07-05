"""
QuizAgent — generates adaptive Bloom-calibrated quizzes tailored to the
learner's current proficiency (Elo score).
"""

from __future__ import annotations

from app.agents_v2.base import BaseAgent


class QuizAgent(BaseAgent):
    name = "QuizAgent"
    # role_description is sourced from prompts/react_agent.yaml (roles.QuizAgent).
    tool_names = ["get_proficiency", "score_difficulty", "generate_quiz", "save_quiz"]
