"""Integration tests for the interview-loop endpoints.

Mongo is faked at the router-module level (per the repo's mock-patching rule) so the
round lifecycle — gating, starting, grading, unlocking, retrying — is exercised through
the real HTTP surface without a database or a live model.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.routers.interview_loops as loops_router
from app.agents.loops import ROUND_AVAILABLE, ROUND_LOCKED, build_loop, normalize_rounds

LEARNER_ID = "learner-1"
USER_ID = "user-1"
SKILLS = ["Python", "SQL"]


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def as_learner():
    """Authenticate as a learner whose profile the loop router can resolve."""
    from app.auth.jwt import get_current_learner
    from app.main import app

    learner = {"id": LEARNER_ID, "user_id": USER_ID, "name": "Test"}
    app.dependency_overrides[get_current_learner] = lambda: learner
    yield learner
    app.dependency_overrides.pop(get_current_learner, None)


def _loop_doc(**over) -> dict:
    rounds = normalize_rounds(
        [
            {"kind": "screen", "focus_skills": ["Python"]},
            {"kind": "coding", "focus_skills": ["Python", "SQL"]},
        ],
        SKILLS,
        "senior",
    )
    loop = build_loop(
        learner_id=LEARNER_ID,
        job={
            "id": "job-1",
            "company": "Acme",
            "role": "Backend Engineer",
            "seniority": "senior",
            "required_skills": SKILLS,
        },
        rounds=rounds,
        company_signals={"process_summary": "Three rounds.", "sources": []},
    )
    loop.update(over)
    return loop


def _mock_loops(monkeypatch, loop: dict) -> MagicMock:
    """Patch the loops collection to serve `loop` and capture writes."""
    col = MagicMock()
    col.find_one = AsyncMock(return_value=loop)
    col.update_one = AsyncMock()
    col.insert_one = AsyncMock()
    monkeypatch.setattr(loops_router, "col_interview_loops", lambda: col)
    return col


def _mock_interviews(monkeypatch, doc: dict | None = None) -> MagicMock:
    col = MagicMock()
    col.find_one = AsyncMock(return_value=doc)
    col.update_one = AsyncMock()
    monkeypatch.setattr(loops_router, "col_interviews", lambda: col)
    return col


def _url(round_key: str, suffix: str = "") -> str:
    return f"/api/v1/loops/loop-1/rounds/{round_key}{suffix}"


# ─── Reading ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_loop_returns_the_ladder(client, as_learner, monkeypatch):
    loop = _loop_doc(loop_id="loop-1")
    _mock_loops(monkeypatch, loop)

    r = await client.get("/api/v1/loops/loop-1")

    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "Acme"
    assert [rnd["status"] for rnd in body["rounds"]] == [ROUND_AVAILABLE, ROUND_LOCKED]
    assert body["rounds"][0]["bar"] > 0


@pytest.mark.asyncio
async def test_a_foreign_loop_is_a_404(client, as_learner, monkeypatch):
    """Missing and not-yours must be indistinguishable."""
    col = MagicMock()
    col.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(loops_router, "col_interview_loops", lambda: col)

    r = await client.get("/api/v1/loops/someone-elses-loop")

    assert r.status_code == 404
    # The query is scoped by learner, not just by id.
    assert col.find_one.await_args.args[0]["learner_id"] == LEARNER_ID


# ─── Round gating ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_locked_round_cannot_be_started(client, as_learner, monkeypatch):
    loop = _loop_doc(loop_id="loop-1")
    _mock_loops(monkeypatch, loop)
    locked_key = loop["rounds"][1]["key"]

    r = await client.post(_url(locked_key, "/start"))

    assert r.status_code == 409
    assert "available" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_an_unknown_round_is_a_404(client, as_learner, monkeypatch):
    _mock_loops(monkeypatch, _loop_doc(loop_id="loop-1"))

    r = await client.post(_url("99-telepathy", "/start"))

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_starting_a_round_hands_the_loop_context_to_the_interview(
    client, as_learner, monkeypatch
):
    """The round's bar, budget and company must reach the interview doc."""
    loop = _loop_doc(loop_id="loop-1")
    col = _mock_loops(monkeypatch, loop)
    captured: dict = {}

    async def _fake_start(**kwargs):
        captured.update(kwargs)
        return {
            "interview_id": "iv-1",
            "max_questions": kwargs["max_questions"],
            "bar": kwargs["bar"],
        }

    async def _fake_stream(_interview):
        yield {"type": "question", "id": 1, "text": "Tell me about your work."}

    monkeypatch.setattr(loops_router, "start_interview", _fake_start)
    monkeypatch.setattr(loops_router, "stream_start", _fake_stream)

    screen = loop["rounds"][0]
    r = await client.post(_url(screen["key"], "/start"))

    assert r.status_code == 200
    ctx = captured["context"]
    assert ctx["kind"] == "loop"
    assert ctx["round_kind"] == "screen"
    assert ctx["company"] == "Acme"
    assert ctx["attempt"] == 1
    assert captured["bar"] == screen["bar"]
    assert captured["max_questions"] == screen["max_questions"]
    # A loop round belongs to no course plan.
    assert captured["plan_id"] == "" and captured["module_id"] == ""

    # The round is now in progress and bound to its interview.
    saved = col.update_one.await_args.args[1]["$set"]["rounds"]
    assert saved[0]["interview_id"] == "iv-1"
    assert saved[0]["attempt"] == 1


@pytest.mark.asyncio
async def test_starting_a_round_twice_is_rejected(client, as_learner, monkeypatch):
    loop = _loop_doc(loop_id="loop-1")
    loop["rounds"][0]["interview_id"] = "iv-1"
    _mock_loops(monkeypatch, loop)

    r = await client.post(_url(loop["rounds"][0]["key"], "/start"))

    assert r.status_code == 409
    assert "already in progress" in r.json()["detail"]


# ─── Grading and unlocking ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completing_a_round_records_it_and_unlocks_the_next(
    client, as_learner, monkeypatch
):
    loop = _loop_doc(loop_id="loop-1")
    screen = loop["rounds"][0]
    screen["interview_id"] = "iv-1"
    screen["status"] = "in_progress"
    col = _mock_loops(monkeypatch, loop)
    _mock_interviews(monkeypatch, {"interview_id": "iv-1", "user_id": USER_ID})

    async def _fake_review(interview_id, plan_id, module_id, emit=None):
        return {
            "interview_id": interview_id,
            "final_score": screen["bar"] + 1,
            "passed": True,
            "bar": screen["bar"],
            "scoring_matrix": [],
            "summary": "Strong.",
            "total_questions": 3,
            "completed_at": "2026-08-15T10:00:00+00:00",
        }

    monkeypatch.setattr(
        "app.agents.pipelines.run_interview_review", _fake_review, raising=False
    )

    r = await client.post(_url(screen["key"], "/complete/stream"))
    assert r.status_code == 200
    body = "".join([chunk.decode() async for chunk in r.aiter_bytes()])

    payload = _action_payload(body, "round_scored")
    rounds = payload["loop"]["rounds"]
    assert rounds[0]["status"] == "passed"
    assert rounds[1]["status"] == ROUND_AVAILABLE  # the next round opened up
    assert col.update_one.await_count >= 1


@pytest.mark.asyncio
async def test_completing_a_round_that_never_started_is_rejected(
    client, as_learner, monkeypatch
):
    _mock_loops(monkeypatch, _loop_doc(loop_id="loop-1"))
    loop = _loop_doc(loop_id="loop-1")

    r = await client.post(_url(loop["rounds"][0]["key"], "/complete/stream"))

    assert r.status_code == 409


# ─── Retry ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_carries_the_previous_questions_forward(
    client, as_learner, monkeypatch
):
    """A retry that re-asks the same questions measures recall, not skill."""
    loop = _loop_doc(loop_id="loop-1")
    screen = loop["rounds"][0]
    screen.update(
        {"interview_id": "iv-1", "status": "failed", "score": 2.0, "attempt": 1}
    )
    col = _mock_loops(monkeypatch, loop)
    _mock_interviews(
        monkeypatch,
        {
            "interview_id": "iv-1",
            "user_id": USER_ID,
            "questions": [
                {"text": "Walk me through your last project."},
                {"text": "Why this role?"},
            ],
        },
    )

    r = await client.post(_url(screen["key"], "/retry"))

    assert r.status_code == 200
    saved = col.update_one.await_args.args[1]["$set"]["rounds"][0]
    assert saved["prior_questions"] == [
        "Walk me through your last project.",
        "Why this role?",
    ]
    assert saved["status"] == ROUND_AVAILABLE
    assert saved["interview_id"] is None
    assert saved["score"] is None
    # The attempt counter is not reset — it increments on the next start.
    assert saved["attempt"] == 1


@pytest.mark.asyncio
async def test_retry_is_rejected_while_a_round_is_in_progress(
    client, as_learner, monkeypatch
):
    loop = _loop_doc(loop_id="loop-1")
    loop["rounds"][0].update({"interview_id": "iv-1", "status": "in_progress"})
    _mock_loops(monkeypatch, loop)

    r = await client.post(_url(loop["rounds"][0]["key"], "/retry"))

    assert r.status_code == 409


@pytest.mark.asyncio
async def test_a_second_attempt_increments_and_passes_prior_questions(
    client, as_learner, monkeypatch
):
    loop = _loop_doc(loop_id="loop-1")
    screen = loop["rounds"][0]
    screen.update({"attempt": 1, "prior_questions": ["Why this role?"]})
    _mock_loops(monkeypatch, loop)
    captured: dict = {}

    async def _fake_start(**kwargs):
        captured.update(kwargs)
        return {"interview_id": "iv-2", "max_questions": 4, "bar": screen["bar"]}

    async def _fake_stream(_interview):
        yield {"type": "question", "id": 1, "text": "Something different."}

    monkeypatch.setattr(loops_router, "start_interview", _fake_start)
    monkeypatch.setattr(loops_router, "stream_start", _fake_stream)

    r = await client.post(_url(screen["key"], "/start"))

    assert r.status_code == 200
    assert captured["prior_questions"] == ["Why this role?"]
    assert captured["context"]["attempt"] == 2


# ─── Debrief ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_debrief_is_rejected_until_every_round_is_graded(
    client, as_learner, monkeypatch
):
    _mock_loops(monkeypatch, _loop_doc(loop_id="loop-1"))

    r = await client.post("/api/v1/loops/loop-1/debrief/stream")

    assert r.status_code == 409
    assert "every round" in r.json()["detail"].lower()


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _action_payload(body: str, kind: str) -> dict:
    """Pull one action event's payload out of a raw SSE body."""
    for line in body.splitlines():
        if not line.startswith("data: ") or line.endswith("[DONE]"):
            continue
        ev = json.loads(line[len("data: ") :])
        if ev.get("type") == "action" and ev.get("kind") == kind:
            return ev["payload"]
    raise AssertionError(f"no {kind} action in stream:\n{body}")
