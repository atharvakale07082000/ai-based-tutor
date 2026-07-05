"""
CurriculumAgent — builds personalized learning paths by analyzing learner
goals and proficiency gaps using the topic graph.
"""

from __future__ import annotations

from app.agents_v2.base import BaseAgent


class CurriculumAgent(BaseAgent):
    name = "CurriculumAgent"
    # role_description is sourced from prompts/react_agent.yaml (roles.CurriculumAgent).
    tool_names = ["classify_topic", "get_topic_graph", "get_proficiency"]
