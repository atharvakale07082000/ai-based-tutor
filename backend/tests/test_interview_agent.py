"""
Tests for the interrupt-driven module interview agent (``app/agents/interview_agent.py``).

We patch ``build_interview_agent`` at the agent-module level (per the repo's mock-patching
rule) so the tests never hit NVIDIA NIM. A ``_FakeAgent`` scripts the ``stream_async`` events
and the terminal ``AgentResult`` (with or without interrupts), which lets us verify the turn
drivers end-to-end: reasoning/question emission, DB persistence of the paused interrupt, the
tuned-scorer hand-off, and the hard cap — all without a live model or Mongo.

The resume endpoint (``GET .../interview/{interview_id}``) is covered here too: it is the
read side of the same live interview, and its payload comes from
``course_planner.interview_state``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.agents.interview_agent as ia
import app.routers.courses as courses_router
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


USER_ID = "u-owner"


def _stored_interview(**over) -> dict:
    """A mid-interview Mongo document: two questions asked, the first one answered."""
    base = {
        "interview_id": "iv-1",
        "plan_id": "plan-1",
        "module_id": "mod-1",
        "user_id": USER_ID,
        "module_title": "SQL Joins",
        "module_topics": ["joins", "indexes"],
        "candidate_proficiency": {"joins": 540},
        "questions": [
            {
                "id": 1,
                "text": "Explain an INNER JOIN vs a LEFT JOIN.",
                "is_coding_question": False,
                "language": None,
                "expected_depth": "conceptual",
            },
            {
                "id": 2,
                "text": "Write a query joining orders and customers.",
                "is_coding_question": True,
                "language": "sql",
                "expected_depth": "applied",
            },
        ],
        "answers": [
            {
                "question_id": 1,
                "answer_text": "An inner join keeps matching rows...",
                "score": 7,
                "feedback": "Solid — mention NULL handling.",
                "key_points_covered": ["inner"],
            }
        ],
        "turn_count": 2,
        "current_interrupt_id": "int-2",
        "status": "in_progress",
        "final_score": None,
        "passed": None,
        "scoring_matrix": [],
        "summary": None,
        "created_at": "2026-07-25T09:00:00+00:00",
        "completed_at": None,
    }
    base.update(over)
    return base


@pytest.fixture
def as_learner():
    """Authenticate the ASGI client as the interview's owner."""
    from app.auth.jwt import get_current_user_id
    from app.main import app

    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    yield USER_ID
    app.dependency_overrides.pop(get_current_user_id, None)


def _url(interview_id: str = "iv-1") -> str:
    return f"/api/v1/courses/plan-1/modules/mod-1/interview/{interview_id}"


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


async def test_stream_start_reports_error_when_agent_never_asks(monkeypatch):
    """No interrupt at start = nothing was asked, so the turn errors rather than "finishing".

    A start turn has zero answers by construction, so marking it ``awaiting_final`` here
    would offer a grade that ``run_interview_review`` can only reject ("No answers
    submitted"). The client is told to retry instead.
    """
    col = _mock_col(monkeypatch)
    events = [{"result": _FakeResult(interrupts=None, stop_reason="end_turn")}]
    monkeypatch.setattr(
        ia, "build_interview_agent", lambda interview: _FakeAgent(events)
    )

    out = [ev async for ev in ia.stream_start(_interview())]
    assert [e["type"] for e in out][-1] == "error"
    assert col.update_one.await_count == 0


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
    # answered/total discriminator so the client can render "2 of 8" without extra state
    assert ev["answered_count"] == 1
    assert ev["max_questions"] == settings.INTERVIEW_MAX_QUESTIONS
    q = next(e for e in out if e["type"] == "question")
    assert q["id"] == 2 and q["text"].startswith("When would a LEFT JOIN")
    assert q["max_questions"] == settings.INTERVIEW_MAX_QUESTIONS
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


def test_interview_state_status_ladder():
    """`status` distinguishes awaiting-answer / concluded / graded / interrupted-start."""
    from app.agents.course_planner import interview_state

    # concluded by the agent, not yet scored
    concluded = interview_state(
        {
            **_stored_interview(),
            "current_interrupt_id": None,
            "status": "awaiting_final",
        }
    )
    assert concluded["status"] == "awaiting_final"
    assert concluded["current_question"] is None

    # scored — the review pipeline stamped final_score/completed_at
    graded = interview_state(
        {
            **_stored_interview(),
            "current_interrupt_id": None,
            "status": "awaiting_final",
            "final_score": 72.0,
            "passed": True,
            "completed_at": "2026-07-25T10:00:00+00:00",
        }
    )
    assert graded["status"] == "complete"
    assert graded["final_score"] == 72.0 and graded["passed"] is True

    # nothing asked yet (start stream died before the first question)
    fresh = interview_state(
        {**_stored_interview(), "questions": [], "answers": [], "turn_count": 0}
    )
    assert fresh["status"] == "in_progress"
    assert fresh["current_question"] is None and fresh["answered_count"] == 0


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


# ── GET .../interview/{interview_id} (resume a dropped interview) ──────────────


async def test_get_interview_returns_resumable_state(client, as_learner, monkeypatch):
    """Mid-interview read returns the outstanding question + the graded answers so far."""
    monkeypatch.setattr(
        courses_router, "get_interview", AsyncMock(return_value=_stored_interview())
    )

    r = await client.get(_url())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["interview_id"] == "iv-1"
    assert body["module_title"] == "SQL Joins"
    assert body["status"] == "awaiting_answer"
    assert body["answered_count"] == 1
    assert body["questions_asked"] == 2
    assert body["max_questions"] == settings.INTERVIEW_MAX_QUESTIONS
    assert body["final_score"] is None and body["passed"] is None

    # the question the agent is paused on — same shape as the SSE `question` event
    q = body["current_question"]
    assert q["id"] == 2
    assert q["text"].startswith("Write a query")
    assert q["is_coding_question"] is True and q["language"] == "sql"
    assert q["expected_depth"] == "applied"

    # the already-answered turn, with the feedback the learner has seen
    (answered,) = body["answers"]
    assert answered["question_id"] == 1
    assert answered["question_text"].startswith("Explain an INNER JOIN")
    assert answered["score"] == 7
    assert answered["feedback"].startswith("Solid")
    assert answered["key_points_covered"] == ["inner"]

    # internal state stays server-side
    assert "candidate_proficiency" not in body
    assert "current_interrupt_id" not in body
    assert "scoring_matrix" not in body and "summary" not in body


async def test_get_interview_404_for_other_users_interview(
    client, as_learner, monkeypatch
):
    """Ownership is enforced exactly like submit_answer: someone else's interview is a 404."""
    monkeypatch.setattr(
        courses_router,
        "get_interview",
        AsyncMock(return_value=_stored_interview(user_id="someone-else")),
    )

    r = await client.get(_url())
    assert r.status_code == 404
    assert r.json()["detail"] == "Interview not found"


async def test_get_interview_404_for_unknown_id(client, as_learner, monkeypatch):
    """An interview id that doesn't exist is a 404, not a 500."""
    monkeypatch.setattr(courses_router, "get_interview", AsyncMock(return_value=None))

    r = await client.get(_url("nope"))
    assert r.status_code == 404
    assert r.json()["detail"] == "Interview not found"


# ── Edge cases: a misbehaving model must not strand the interview ─────────────
#
# The agent is an LLM, so `ask_candidate` can arrive malformed and `conclude` can fire
# before a single question. Neither may leave a doc the UI offers to grade — the review
# pipeline raises "No answers submitted", so an armed-but-empty interview is a dead end.


@pytest.mark.parametrize(
    "reason,label",
    [
        ({"question": "   ", "is_coding": False}, "whitespace-only question"),
        ({"is_coding": True, "language": "python"}, "no question key at all"),
        (None, "tool called with no input"),
    ],
)
async def test_blank_question_is_rejected_not_streamed(monkeypatch, reason, label):
    """A blank `ask_candidate` must not be persisted or shown as a question."""
    col = _mock_col(monkeypatch)
    interview = _interview()
    agent = _FakeAgent([{"result": _FakeResult([_FakeInterrupt("int-1", reason)])}])

    out = [w async for w in ia._drive(agent, "go", interview)]
    kinds = [w["type"] for w in out]

    assert "question" not in kinds, (
        f"{label}: streamed an empty question to the learner"
    )
    assert "error" in kinds, f"{label}: failed silently instead of reporting"
    assert col.update_one.await_count == 0, f"{label}: persisted a blank question"
    # Nothing was asked, so nothing may claim to be awaiting an answer.
    assert interview.get("current_interrupt_id") is None
    assert interview.get("turn_count") == 0


async def test_conclude_with_no_answers_does_not_arm_final_grading(monkeypatch):
    """Concluding before any answer must leave the interview restartable, not gradeable."""
    col = _mock_col(monkeypatch)
    interview = _interview(answers=[])
    agent = _FakeAgent([{"result": _FakeResult(None)}])

    out = [w async for w in ia._drive(agent, "go", interview)]

    assert "finished" not in [w["type"] for w in out], (
        "told the client the interview finished when nothing was ever asked"
    )
    assert "error" in [w["type"] for w in out]
    sets = [c.args[1].get("$set", {}) for c in col.update_one.await_args_list]
    assert not any(s.get("status") == "awaiting_final" for s in sets), (
        "armed final grading on an empty interview — run_interview_review raises there"
    )


async def test_conclude_with_answers_still_arms_final_grading(monkeypatch):
    """Regression guard: the normal conclusion path is unchanged."""
    col = _mock_col(monkeypatch)
    interview = _interview(turn_count=3, answers=[{"question_id": 1, "score": 7}])
    agent = _FakeAgent([{"result": _FakeResult(None)}])

    out = [w async for w in ia._drive(agent, "go", interview)]

    assert "finished" in [w["type"] for w in out]
    sets = [c.args[1].get("$set", {}) for c in col.update_one.await_args_list]
    assert any(s.get("status") == "awaiting_final" for s in sets)


@pytest.mark.parametrize(
    "over,expect_min,expect_max",
    [
        ({"min_questions": 5, "max_questions": 2}, 2, 2),  # misconfigured round
        ({"max_questions": -3}, 1, 1),  # negative budget
        ({"max_questions": 1, "min_questions": 1}, 1, 1),  # single-question round
    ],
)
def test_question_budget_is_coerced_to_a_sane_range(over, expect_min, expect_max):
    """A round's budget must never ask for more questions than it allows."""
    interview = _interview(**over)
    max_q = ia._max_questions(interview)
    min_q = ia._min_questions(interview)

    assert max_q >= 1, "a budget of zero or fewer questions can never ask anything"
    assert min_q <= max_q, f"asked for at least {min_q} but capped at {max_q}"
    assert (min_q, max_q) == (expect_min, expect_max)


def test_system_prompt_never_states_a_contradictory_budget():
    """The prompt must not tell the model 'at least 5 and at most 2'."""
    prompt = ia._system_prompt(_interview(min_questions=5, max_questions=2))
    import re

    m = re.search(r"at least (\d+) and at most (\d+)", prompt)
    assert m, "budget sentence not found — update this test if the wording moved"
    assert int(m.group(1)) <= int(m.group(2)), f"contradictory budget: {m.group(0)}"
