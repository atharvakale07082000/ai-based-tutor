"""
Specialist agent builders.

Each specialist is a Strands ``Agent`` composed of:
- a role system-prompt (from ``prompts/react_agent.yaml`` ``roles:``) plus its
  skills catalog block (progressive disclosure via ``load_skill``),
- the ``load_skill`` tool + its domain tools,
- the shared NIM specialist model and the GuardrailHook.

Specialists are invoked by the orchestrator (agents-as-tools). Construction is
cached in ``handler.py`` — nothing here builds an Agent at import time.
"""

from __future__ import annotations

from dataclasses import dataclass

from strands import Agent

from app.agents import tools
from app.agents.hooks import GuardrailHook
from app.agents.learner_context import LearnerContext
from app.agents.model import get_nim_model
from app.agents.skills import load_skill, skills_prompt_block
from app.config import settings
from app.prompts.loader import get_section


@dataclass(frozen=True)
class SpecialistSpec:
    key: str  # routing key (doubt/quiz/curriculum/progress/assistant)
    role_name: str  # key in react_agent.yaml roles:
    tool_desc: str  # description the orchestrator sees for this agent-as-tool
    skills: tuple[str, ...]
    domain_tools: tuple  # stateless tools, shared across requests
    # Names of learner-bound tools (see tools.learner_scoped_tools). Resolved per
    # request against the authenticated learner — never handed to the model as an
    # argument, so it cannot pass someone else's id or garble its own.
    learner_tools: tuple[str, ...] = ()


SPECIALISTS: dict[str, SpecialistSpec] = {
    "doubt": SpecialistSpec(
        key="doubt",
        role_name="DoubtAgent",
        tool_desc=(
            "Answer a learner's conceptual question or doubt with a clear, "
            "Bloom-appropriate explanation. Use for 'what is', 'why', 'how does', "
            "'explain', 'I'm confused about' style questions."
        ),
        skills=("explanation", "web-research"),
        domain_tools=tuple(tools.DOUBT_TOOLS),
        learner_tools=("get_proficiency",),
    ),
    "quiz": SpecialistSpec(
        key="quiz",
        role_name="QuizAgent",
        tool_desc=(
            "Create an adaptive, Bloom-calibrated quiz on a topic and save it. "
            "Use when the learner wants to be quizzed, tested, or assessed."
        ),
        skills=("quiz-authoring",),
        domain_tools=tuple(tools.QUIZ_TOOLS),
        learner_tools=("get_proficiency", "save_quiz"),
    ),
    "curriculum": SpecialistSpec(
        key="curriculum",
        role_name="CurriculumAgent",
        tool_desc=(
            "Design a personalized, ordered learning path from the learner's goal "
            "and proficiency gaps. Use for 'learn X', 'roadmap', 'study plan', "
            "'where do I start'."
        ),
        skills=("curriculum-design", "web-research"),
        domain_tools=tuple(tools.CURRICULUM_TOOLS),
        learner_tools=("get_proficiency",),
    ),
    "progress": SpecialistSpec(
        key="progress",
        role_name="ProgressAgent",
        tool_desc=(
            "Update the learner's proficiency (Elo) after a quiz and capture mood, "
            "or report how they're doing. Use for 'my progress', 'update my score', "
            "'how am I doing'."
        ),
        skills=("progress-tracking",),
        domain_tools=tuple(tools.PROGRESS_TOOLS),
        learner_tools=("get_proficiency", "save_progress"),
    ),
    "assistant": SpecialistSpec(
        key="assistant",
        role_name="AssistantAgent",
        tool_desc=(
            "General-purpose tutor for anything that doesn't fit a more specific "
            "specialist. Handles open-ended help by combining available tools, "
            "and runs chat mock interviews via the interview-coaching skill."
        ),
        skills=("explanation", "web-research", "interview-coaching"),
        domain_tools=tuple(tools.ASSISTANT_TOOLS),
        learner_tools=(
            "get_proficiency",
            "save_quiz",
            "save_progress",
            "get_due_topics",
        ),
    ),
}


def _system_prompt(spec: SpecialistSpec, learner: LearnerContext | None = None) -> str:
    """Role + skills + reasoning protocol, then the learner briefing.

    ORDER IS LOAD-BEARING — do not append anything stable after the learner block:

    * everything above the briefing is identical for every learner, so the provider can
      KV-cache that prefix across all of them (the same property ``orchestrator.yaml``
      is deliberately written for). Learner data used to travel in the *user* turn,
      which defeated caching entirely and read as data-to-parse rather than
      instructions-to-follow;
    * putting the briefing last also puts it closest to the question, which is where
      instructions get followed best.
    """
    roles = get_section("react_agent", "roles")
    role_text = roles.get(spec.role_name, "You are a helpful AI tutor.")
    skills_block = skills_prompt_block(list(spec.skills))
    reasoning_block = get_section("react_agent", "reasoning_protocol")
    parts = [role_text, skills_block, reasoning_block]
    if learner is not None:
        # Empty for a learner we know nothing about — see LearnerContext.render.
        parts.append(learner.render())
    return "\n\n".join(p for p in parts if p).strip()


def _session_kwargs(session_id: str) -> dict:
    """Strands session + conversation managers giving a chat thread durable memory.

    All specialists in a thread share one ``agent_id`` ("chat") within the thread's
    session, so memory carries ACROSS specialists (e.g. "quiz me on that" after a
    doubt turn). A SlidingWindow bounds how much history stays in the model context.
    """
    import os
    import tempfile

    from strands.agent.conversation_manager import SlidingWindowConversationManager
    from strands.session.file_session_manager import FileSessionManager

    storage_dir = settings.AGENT_SESSIONS_DIR or os.path.join(
        tempfile.gettempdir(), "atelier_agent_sessions"
    )
    return {
        "agent_id": "chat",
        "session_manager": FileSessionManager(
            session_id=f"chat-{session_id}", storage_dir=storage_dir
        ),
        "conversation_manager": SlidingWindowConversationManager(
            window_size=settings.CHAT_MEMORY_WINDOW
        ),
    }


def build_specialist(
    key: str,
    session_id: str | None = None,
    learner_id: str | None = None,
    learner: LearnerContext | None = None,
) -> Agent:
    """Construct (uncached) the specialist Agent for a routing key.

    When ``session_id`` (a chat thread id) is given, the agent is wired to that
    thread's persisted conversation (Strands ``FileSessionManager``) so Ask Atelier
    remembers earlier turns across the whole thread. Without it the agent is stateless
    (the generation pipelines that reuse this builder stay memoryless).

    ``learner_id`` binds this agent's learner-scoped tools to one learner. Without it
    those tools are **omitted entirely** rather than bound to an empty id — a tool that
    silently reads nobody's records is worse than a tool the agent doesn't have, because
    the empty result reads as "this learner has no progress".

    ``learner`` is the briefing appended to the system prompt so the agent pitches its
    answer at this person. Omit it (pipelines do) and the prompt is exactly what it was
    before personalisation existed.
    """
    spec = SPECIALISTS[key]
    scoped = tools.learner_scoped_tools(learner_id) if learner_id else {}
    return Agent(
        name=spec.role_name,
        model=get_nim_model("specialist"),
        system_prompt=_system_prompt(spec, learner),
        tools=[
            load_skill,
            *spec.domain_tools,
            *(scoped[n] for n in spec.learner_tools if n in scoped),
        ],
        hooks=[GuardrailHook()],
        callback_handler=None,  # we drive streaming via stream_async ourselves
        **(_session_kwargs(session_id) if session_id else {}),
    )
