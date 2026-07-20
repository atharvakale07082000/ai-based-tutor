"""
interview_agent — the interrupt-driven adaptive module interview (Strands HITL).

One long-lived agent per interview (session = ``interview_id``) conducts a live
mock interview. It asks ONE question at a time via the ``ask_candidate`` tool; an
``InterviewInterruptHook`` turns each such call into a Strands *interrupt*, which
pauses the run and persists its state into the interview's file session. The HTTP
``answer`` turn then:

  1. scores the answer with the tuned ``evaluate_answer`` prompt (unchanged), and
  2. RESUMES the agent with ``{answer + calibrated eval}`` so it adaptively decides
     the next question,

repeating until the agent calls ``conclude`` or hits the hard cap
(``INTERVIEW_MAX_QUESTIONS``) — after which the existing ``interview_review``
pipeline produces the final grade. The agent never assigns the numeric score; it
only chooses good questions. Because Strands serializes interrupt state through
session management, the pause in ``start`` and the resume in a later ``answer``
request are two separate HTTP calls against the *same* agent thread.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, AsyncIterator

import structlog
from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.session.file_session_manager import FileSessionManager

from app.agents.hooks import GuardrailHook
from app.agents.model import get_nim_model
from app.agents.skills import load_all_skills
from app.agents.stream_adapter import TraceState, translate_event
from app.config import settings
from app.db.mongo import col_interviews

log = structlog.get_logger()

_INTERRUPT_NAME = "ask_candidate"


# ─── Tools ────────────────────────────────────────────────────────────────────


@tool
def ask_candidate(
    question: str,
    is_coding: bool = False,
    language: str = "",
    expected_depth: str = "",
) -> str:
    """Ask the candidate ONE interview question and wait for their answer.

    Put the full question text in ``question`` — do not also restate it as prose. You
    will receive the candidate's answer and its calibrated 0-10 evaluation as this
    tool's result; use them to choose the next question.

    Args:
        question: The exact question to ask the candidate.
        is_coding: True if this needs the code editor (a coding question).
        language: For coding questions, the language id (e.g. "python", "sql").
        expected_depth: One of conceptual | applied | analytical.
    """
    # Only runs if the interrupt is inactive — normally the InterviewInterruptHook
    # pauses (first pass) then cancels the call with the answer (resume). Benign ack.
    return "Awaiting the candidate's answer."


@tool
def conclude(reason: str = "") -> str:
    """End the interview once you have enough signal to assess the candidate.

    Args:
        reason: One short line on why you're concluding now.
    """
    return "Interview concluded."


# ─── Interrupt hook ───────────────────────────────────────────────────────────


def _format_answer(response: Any) -> str:
    """Render the resume payload into the tool-result text the model reads next."""
    if not isinstance(response, dict):
        return str(response)
    parts = [f"Candidate's answer:\n{response.get('answer', '')}".strip()]
    ev = response.get("evaluation") or {}
    if ev:
        parts.append(
            f"Calibrated evaluation — score {ev.get('score', '?')}/10: "
            f"{ev.get('feedback', '')}".strip()
        )
    if response.get("note"):
        parts.append(str(response["note"]))
    return "\n\n".join(p for p in parts if p)


class InterviewInterruptHook(HookProvider):
    """Turn each ``ask_candidate`` call into a HITL interrupt; inject the answer on resume."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._pause_for_answer)

    def _pause_for_answer(self, event: BeforeToolCallEvent) -> None:
        if event.tool_use.get("name") != _INTERRUPT_NAME:
            return
        question_payload = event.tool_use.get("input") or {}
        # First pass raises InterruptException (agent pauses, state persisted to session).
        # On resume this returns the payload we passed in the interruptResponse.
        response = event.interrupt(_INTERRUPT_NAME, reason=question_payload)
        # Resume path: surface the candidate's answer as the tool result (cancel_tool injects
        # the content) so the model reads it and picks the next question. It never runs the tool.
        event.cancel_tool = _format_answer(response)


# ─── Agent builder ────────────────────────────────────────────────────────────


def _system_prompt(interview: dict) -> str:
    rubric = load_all_skills().get("interview-coaching")
    rubric_text = rubric.instructions if rubric else ""
    topics = (
        ", ".join((interview.get("module_topics") or [])[:8]) or "the module topics"
    )
    proficiency = interview.get("candidate_proficiency") or {}
    max_q = settings.INTERVIEW_MAX_QUESTIONS
    min_q = settings.INTERVIEW_MIN_QUESTIONS
    return f"""## Role
You are conducting a live, adaptive technical mock interview on Atelier for the module \
"{interview.get("module_title", "")}".
Module topics: {topics}.
Candidate proficiency (per-topic Elo, 0-1000; ~500 is average): {json.dumps(proficiency, default=str)}.

## How to run the interview
- The candidate's proficiency is already given above — do NOT call any tool to look it up. Your only
  tools are `ask_candidate` and `conclude`; do not call anything else.
- Ask EXACTLY ONE question at a time by calling the `ask_candidate` tool. Put the full question text in
  the `question` argument only — do NOT also write the question as prose. Set `is_coding` and `language`
  for coding questions, and set `expected_depth` (conceptual | applied | analytical).
- After each question you receive the candidate's answer and its calibrated 0-10 evaluation as the tool
  result. Read it, then adapt: probe deeper after a strong answer, scaffold after a weak one, and move
  across the module's topics so the set is well-rounded.
- Ask at least {min_q} and at most {max_q} questions. When you have enough signal (or are told it was the
  last question), call the `conclude` tool instead of asking again. Never call `ask_candidate` and
  `conclude` in the same turn.
- You do NOT assign scores — the platform scores each answer with a separate rubric. Your only job is to
  choose and phrase good, discriminating questions and adapt to the candidate.

Before each tool call you MAY include one short first-person `<reasoning>…</reasoning>` note (one sentence)
on what you're probing for. Never reveal the answer.

## Question-design rubric (context for choosing and calibrating questions)
{rubric_text}""".strip()


def build_interview_agent(interview: dict) -> Agent:
    """Construct the interrupt-driven interview agent bound to this interview's session.

    The ``FileSessionManager`` (keyed by interview_id) persists both the conversation and
    the interrupt state, so a later ``answer`` request can resume the paused agent.
    """
    storage_dir = settings.AGENT_SESSIONS_DIR or os.path.join(
        tempfile.gettempdir(), "atelier_agent_sessions"
    )
    interview_id = interview["interview_id"]
    return Agent(
        name="InterviewAgent",
        model=get_nim_model("specialist"),
        system_prompt=_system_prompt(interview),
        tools=[ask_candidate, conclude],
        hooks=[InterviewInterruptHook(), GuardrailHook()],
        callback_handler=None,  # we drive streaming via stream_async
        agent_id="interview",
        session_manager=FileSessionManager(
            session_id=f"interview-{interview_id}", storage_dir=storage_dir
        ),
    )


# ─── Streaming turn drivers ───────────────────────────────────────────────────


async def _drive(
    agent: Agent,
    prompt: Any,
    interview: dict,
    *,
    force_finish: bool = False,
) -> AsyncIterator[dict]:
    """Stream one agent turn to its next interrupt (a new question) or conclusion.

    Yields ``reasoning``/``token`` wire events live, then persists + emits either a
    ``question`` event (agent paused on ``ask_candidate``) or a ``finished`` event.
    """
    interview_id = interview["interview_id"]
    state = TraceState()
    result = None
    try:
        async for event in agent.stream_async(prompt):
            if isinstance(event, dict) and "result" in event:
                result = event["result"]
                continue
            for wire in translate_event(event, state, forward_tokens=True):
                yield wire
    except Exception as e:  # noqa: BLE001 - surface a generic error, log details
        log.error(
            "interview_agent_stream_error",
            interview_id=interview_id,
            error=str(e)[:300],
        )
        yield {
            "type": "error",
            "message": "The interview hit a problem — please try again.",
        }
        return

    interrupts = list(getattr(result, "interrupts", None) or []) if result else []

    if interrupts and not force_finish:
        payload = interrupts[0].reason or {}
        next_id = int(interview.get("turn_count", 0)) + 1
        question = {
            "id": next_id,
            "text": str(payload.get("question", "")).strip(),
            "is_coding_question": bool(payload.get("is_coding")),
            "language": (payload.get("language") or None),
            "expected_depth": payload.get("expected_depth") or "conceptual",
        }
        await col_interviews().update_one(
            {"interview_id": interview_id},
            {
                "$push": {"questions": question},
                "$set": {
                    "current_interrupt_id": interrupts[0].id,
                    "turn_count": next_id,
                    "status": "in_progress",
                },
            },
        )
        # keep the in-memory copy consistent for callers that reuse it
        interview["turn_count"] = next_id
        interview["current_interrupt_id"] = interrupts[0].id
        log.info(
            "interview_question_asked",
            interview_id=interview_id,
            q_id=next_id,
            is_coding=question["is_coding_question"],
        )
        yield {"type": "question", **question}
    else:
        await col_interviews().update_one(
            {"interview_id": interview_id},
            {"$set": {"current_interrupt_id": None, "status": "awaiting_final"}},
        )
        log.info(
            "interview_agent_concluded",
            interview_id=interview_id,
            turns=interview.get("turn_count"),
            forced=force_finish,
        )
        yield {"type": "finished"}


async def stream_start(interview: dict) -> AsyncIterator[dict]:
    """Open an interview: stream the agent to its first question."""
    agent = build_interview_agent(interview)
    prompt = (
        "Begin the interview. Ask your first question now by calling ask_candidate."
    )
    async for wire in _drive(agent, prompt, interview):
        yield wire


async def stream_answer(
    interview: dict, question_id: int, answer_text: str
) -> AsyncIterator[dict]:
    """Score the submitted answer (tuned rubric), then resume the agent for the next question."""
    from app.agents.course_planner import evaluate_answer

    interview_id = interview["interview_id"]

    # 1) Calibrated per-answer score (unchanged pipeline; persists into answers[]).
    try:
        evaluation = await evaluate_answer(interview_id, question_id, answer_text)
    except Exception as e:  # noqa: BLE001
        log.error(
            "interview_evaluate_failed", interview_id=interview_id, error=str(e)[:200]
        )
        yield {"type": "error", "message": "Could not score that answer — try again."}
        return
    yield {
        "type": "evaluation",
        "question_id": question_id,
        "score": evaluation.get("score"),
        "feedback": evaluation.get("feedback", ""),
        "key_points_covered": evaluation.get("key_points_covered", []),
    }

    # 2) Resume the paused agent with the answer + eval so it picks the next question.
    cur_id = interview.get("current_interrupt_id")
    if not cur_id:
        yield {"type": "error", "message": "This interview is not awaiting an answer."}
        return

    turn_count = int(interview.get("turn_count", 1))
    must_conclude = turn_count >= settings.INTERVIEW_MAX_QUESTIONS
    if must_conclude:
        note = (
            f"You have asked {turn_count} of {settings.INTERVIEW_MAX_QUESTIONS} questions — "
            "that was the final question. Call conclude now; do not ask another."
        )
    elif turn_count < settings.INTERVIEW_MIN_QUESTIONS:
        note = (
            f"You have asked {turn_count} question(s); ask at least "
            f"{settings.INTERVIEW_MIN_QUESTIONS} before you conclude."
        )
    else:
        note = None

    response = {
        "answer": answer_text,
        "evaluation": {
            "score": evaluation.get("score"),
            "feedback": evaluation.get("feedback", ""),
        },
        "note": note,
    }
    resume_prompt = [
        {"interruptResponse": {"interruptId": cur_id, "response": response}}
    ]
    agent = build_interview_agent(interview)
    async for wire in _drive(
        agent, resume_prompt, interview, force_finish=must_conclude
    ):
        yield wire
