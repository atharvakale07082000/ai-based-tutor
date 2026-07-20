"""
Tests for the interrupt-driven module interview agent (``app/agents/interview_agent.py``).

We patch ``build_interview_agent`` at the agent-module level (per the repo's mock-patching
rule) so the tests never hit NVIDIA NIM. A ``_FakeAgent`` scripts the ``stream_async`` events
and the terminal ``AgentResult`` (with or without interrupts), which lets us verify the turn
drivers end-to-end: reasoning/question emission, DB persistence of the paused interrupt, the
tuned-scorer hand-off, and the hard cap — all without a live model or Mongo.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import app.agents.interview_agent as ia
from app.config import settings


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeInterrupt:
    def __init__(self, id: str, reason: dict) -> None:
        self.id = id
        self.reason = reason


class _FakeResult:
    def __init__(self, interrupts=None, stop_reason="interrupt") -> None:
        self.interrupts = interrupts
        self.stop_reason = stop_reason


class _FakeAgent:
    """Stands in for a Strands Agent: yields scripted stream events + a terminal result."""

    def __init__(self, events: list) -> None:
        self._events = events

    async def stream_async(self, prompt=None):
        for ev in self._events:
            yield ev


def _mock_col(monkeypatch) -> MagicMock:
    """Patch interview_agent.col_interviews() → a collection with an async update_one."""
    col = MagicMock()
    col.update_one = AsyncMock()
    monkeypatch.setattr(ia, "col_interviews", lambda: col)
    return col


def _interview(**over) -> dict:
    base = {
        "interview_id": "iv-1",
        "module_title": "SQL Joins",
        "module_topics": ["joins", "indexes"],
        "candidate_proficiency": {"joins": 540},
        "turn_count": 0,
        "current_interrupt_id": None,
    }
    base.update(over)
    return base


# ── stream_start ──────────────────────────────────────────────────────────────


async def test_stream_start_asks_first_question(monkeypatch):
    """Start streams reasoning, emits a `question`, and persists the paused interrupt."""
    col = _mock_col(monkeypatch)
    reason = {
        "question": "Explain an INNER JOIN vs a LEFT JOIN.",
        "is_coding": True,
        "language": "sql",
        "expected_depth": "applied",
    }
    events = [
        {"data": "<reasoning>Opening with a foundational join question.</reasoning>"},
        {"result": _FakeResult(interrupts=[_FakeInterrupt("int-1", reason)])},
    ]
    monkeypatch.setattr(
        ia, "build_interview_agent", lambda interview: _FakeAgent(events)
    )

    out = [ev async for ev in ia.stream_start(_interview())]
    kinds = [e["type"] for e in out]

    assert (
        "reasoning" in kinds
    )  # the <reasoning> note is surfaced, not the tool workflow
    question = next(e for e in out if e["type"] == "question")
    assert question["id"] == 1
    assert question["text"].startswith("Explain an INNER JOIN")
    assert question["is_coding_question"] is True
    assert question["language"] == "sql"
    assert question["expected_depth"] == "applied"

    # the interrupt is persisted so a later `answer` request can resume this agent
    col.update_one.assert_awaited_once()
    _, kwargs = col.update_one.call_args
    update = col.update_one.call_args[0][1]
    assert update["$set"]["current_interrupt_id"] == "int-1"
    assert update["$set"]["turn_count"] == 1
    assert update["$push"]["questions"]["is_coding_question"] is True


async def test_stream_start_concludes_when_no_interrupt(monkeypatch):
    """If the agent returns no interrupt, the turn finishes instead of emitting a question."""
    col = _mock_col(monkeypatch)
    events = [{"result": _FakeResult(interrupts=None, stop_reason="end_turn")}]
    monkeypatch.setattr(
        ia, "build_interview_agent", lambda interview: _FakeAgent(events)
    )

    out = [ev async for ev in ia.stream_start(_interview())]
    assert [e["type"] for e in out][-1] == "finished"
    assert col.update_one.call_args[0][1]["$set"]["status"] == "awaiting_final"


# ── stream_answer ─────────────────────────────────────────────────────────────


async def test_stream_answer_scores_then_next_question(monkeypatch):
    """Answer emits the tuned score, then resumes the agent to the next adaptive question."""
    _mock_col(monkeypatch)
    evaluation = {
        "score": 7,
        "feedback": "Solid, mention NULL handling.",
        "key_points_covered": ["inner"],
    }
    eval_mock = AsyncMock(return_value=evaluation)
    monkeypatch.setattr("app.agents.course_planner.evaluate_answer", eval_mock)

    next_reason = {
        "question": "When would a LEFT JOIN return NULLs?",
        "expected_depth": "analytical",
    }
    events = [
        {"result": _FakeResult(interrupts=[_FakeInterrupt("int-2", next_reason)])}
    ]
    monkeypatch.setattr(
        ia, "build_interview_agent", lambda interview: _FakeAgent(events)
    )

    interview = _interview(turn_count=1, current_interrupt_id="int-1")
    out = [
        ev
        async for ev in ia.stream_answer(
            interview, question_id=1, answer_text="An inner join..."
        )
    ]

    ev = next(e for e in out if e["type"] == "evaluation")
    assert ev["score"] == 7 and ev["question_id"] == 1
    q = next(e for e in out if e["type"] == "question")
    assert q["id"] == 2 and q["text"].startswith("When would a LEFT JOIN")
    eval_mock.assert_awaited_once_with("iv-1", 1, "An inner join...")


async def test_hard_cap_forces_finish(monkeypatch):
    """At the cap, the turn finishes even if the model tries to ask another question."""
    col = _mock_col(monkeypatch)
    monkeypatch.setattr(
        "app.agents.course_planner.evaluate_answer",
        AsyncMock(
            return_value={"score": 6, "feedback": "ok", "key_points_covered": []}
        ),
    )
    # The agent still tries to ask another question — the cap must override it.
    events = [
        {
            "result": _FakeResult(
                interrupts=[_FakeInterrupt("int-x", {"question": "one more?"})]
            )
        }
    ]
    monkeypatch.setattr(
        ia, "build_interview_agent", lambda interview: _FakeAgent(events)
    )

    interview = _interview(
        turn_count=settings.INTERVIEW_MAX_QUESTIONS, current_interrupt_id="int-9"
    )
    out = [
        ev async for ev in ia.stream_answer(interview, question_id=8, answer_text="...")
    ]
    kinds = [e["type"] for e in out]

    assert "finished" in kinds and "question" not in kinds
    assert col.update_one.call_args[0][1]["$set"]["status"] == "awaiting_final"


async def test_stream_answer_without_pending_interrupt_errors(monkeypatch):
    """A resume with no stored interrupt id surfaces an error rather than calling the model."""
    _mock_col(monkeypatch)
    monkeypatch.setattr(
        "app.agents.course_planner.evaluate_answer",
        AsyncMock(return_value={"score": 5, "feedback": "", "key_points_covered": []}),
    )
    interview = _interview(turn_count=1, current_interrupt_id=None)
    out = [
        ev async for ev in ia.stream_answer(interview, question_id=1, answer_text="x")
    ]
    assert out[-1]["type"] == "error"


# ── pure helpers ──────────────────────────────────────────────────────────────


def test_system_prompt_injects_context_rubric_and_caps():
    prompt = ia._system_prompt(_interview())
    assert "SQL Joins" in prompt  # module title
    assert "joins" in prompt  # topics
    assert str(settings.INTERVIEW_MIN_QUESTIONS) in prompt
    assert str(settings.INTERVIEW_MAX_QUESTIONS) in prompt
    assert "ask_candidate" in prompt and "conclude" in prompt
    # the interview-coaching SKILL rubric is embedded as question-design guidance
    assert "Interview coaching" in prompt or "Calibrate" in prompt


def test_format_answer_surfaces_answer_and_score():
    text = ia._format_answer(
        {
            "answer": "A join combines rows",
            "evaluation": {"score": 8, "feedback": "good"},
            "note": "ask 1 more",
        }
    )
    assert "A join combines rows" in text
    assert "8/10" in text
    assert "ask 1 more" in text
