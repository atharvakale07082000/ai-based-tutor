from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    learner_id: str
    task_type: str  # "curriculum" | "quiz" | "progress" | "doubt" | "start"
    messages: Annotated[list[BaseMessage], add_messages]
    learner_profile: dict
    topic_proficiency: dict  # topic -> Elo score 0-1000
    current_topic: str
    quiz_questions: list[dict]
    curriculum_path: list[dict]
    doubt_response: str
    progress_delta: dict
    bloom_level: str
    error: str | None
    # Autonomous session fields
    next_action: str        # "curriculum" | "quiz" | "end" — set by planner
    resume_action: str      # where to return after a doubt is resolved
    iteration_count: int    # incremented by planner each cycle
    max_iterations: int     # hard cap to prevent infinite loops (default 10)
    session_complete: bool  # true when all topics mastered or max_iterations hit
    mastery_threshold: float  # Elo score at which a topic is considered mastered
