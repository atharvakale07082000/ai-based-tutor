"""Package: agents_v3/subagents."""

from app.agents_v3.subagents.assistant import AssistantSubAgent
from app.agents_v3.subagents.curriculum import CurriculumSubAgent
from app.agents_v3.subagents.doubt import DoubtSubAgent
from app.agents_v3.subagents.progress import ProgressSubAgent
from app.agents_v3.subagents.quiz import QuizSubAgent

__all__ = [
    "DoubtSubAgent",
    "QuizSubAgent",
    "CurriculumSubAgent",
    "ProgressSubAgent",
    "AssistantSubAgent",
]
