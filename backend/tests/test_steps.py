"""Tests for the live agent step timeline backbone (app.agents.steps)."""

import asyncio

import pytest
from app.agents.steps import (
    STEP_PLANS,
    THROTTLE_STEP_ID,
    StepTimeline,
    sse_step_stream,
    step_emitter,
    step_event,
)


def test_step_event_shape():
    assert step_event("research", "Researching", "active") == {
        "type": "step",
        "id": "research",
        "label": "Researching",
        "status": "active",
    }


def test_timeline_uses_plan_labels():
    """A known step id is labelled from its plan — assert the wiring, not the prose.

    Labels are learner-facing copy (first-person reasoning narration) and get
    rewritten; hardcoding the string here just makes the test rot.
    """
    plan_labels = {s.id: s.label for s in STEP_PLANS["course_plan"]}
    assert plan_labels["research"].strip(), "plan labels must be non-empty"

    tl = StepTimeline("course_plan")
    assert tl.start("research") == {
        "type": "step",
        "id": "research",
        "label": plan_labels["research"],
        "status": "active",
    }
    done = tl.done("research")
    assert done["status"] == "done"
    assert done["label"] == plan_labels["research"]


def test_timeline_adhoc_step_remembers_label():
    tl = StepTimeline("chat")
    started = tl.start("tool:get_proficiency", "Looking up proficiency")
    assert started["label"] == "Looking up proficiency"
    # done() without a label reuses the one supplied at start()
    assert tl.done("tool:get_proficiency")["label"] == "Looking up proficiency"


def test_timeline_unknown_id_falls_back_to_id():
    tl = StepTimeline()
    assert tl.start("mystery")["label"] == "mystery"


def test_all_plans_have_unique_ids():
    for key, plan in STEP_PLANS.items():
        ids = [s.id for s in plan]
        assert len(ids) == len(set(ids)), f"duplicate step id in plan {key!r}"


@pytest.mark.asyncio
async def test_sse_step_stream_yields_in_order():
    async def run(emit):
        tl = StepTimeline("quiz_review")
        await emit(tl.start("analyze"))
        await emit(tl.done("analyze"))
        await emit({"type": "action", "kind": "quiz_scored", "payload": {"score": 1.0}})

    events = [ev async for ev in sse_step_stream(run)]
    assert [e["type"] for e in events] == ["step", "step", "action"]
    assert events[0]["status"] == "active"
    assert events[1]["status"] == "done"


@pytest.mark.asyncio
async def test_sse_step_stream_converts_worker_error_to_event():
    async def boom(emit):
        await emit({"type": "step", "id": "x", "label": "X", "status": "active"})
        raise RuntimeError("kaboom")

    events = [ev async for ev in sse_step_stream(boom)]
    # The raw exception never escapes — it becomes a terminal error event.
    assert events[0]["type"] == "step"
    assert events[-1]["type"] == "error"
    assert "kaboom" not in events[-1]["message"]


# ── capacity waits (NIM RPM throttling) ─────────────────────────────────────────
# ``notify_throttle`` is driven directly: waiting on a real rate limit would make
# these tests slow and flaky. ``jd_analyze`` stands in for all four pipelines —
# they share one ``step_emitter`` — and is the only one with no I/O of its own.

_PROFICIENCY = {"python": 800.0}
_PARSED = {
    "company": "Acme",
    "role": "Engineer",
    "seniority": "senior",
    "required_skills": ["python"],
}


@pytest.mark.asyncio
async def test_pipeline_surfaces_one_capacity_notice_during_the_stall(monkeypatch):
    """A throttled pipeline emits exactly one notice, while it is still stalled."""
    from app.agents.handler import THROTTLE_NOTICE
    from app.agents.model import notify_throttle
    from app.agents.pipelines import run_jd_analyze

    events: list[dict] = []
    notice_delivered = asyncio.Event()

    async def emit(ev: dict) -> None:
        events.append(ev)
        if ev["id"] == THROTTLE_STEP_ID:
            notice_delivered.set()

    async def stalling_parse_jd(jd_text: str) -> dict:
        # Stand in for NIMModel.stream: the bucket announces a wait (twice — a
        # pipeline can hit the cap on several calls) and then sleeps mid-step.
        notify_throttle(7.5)
        notify_throttle(7.5)
        # Rendezvous instead of sleeping: deterministic, and a bridge that only
        # delivered at the next step boundary would time out here rather than pass.
        await asyncio.wait_for(notice_delivered.wait(), timeout=5)
        return dict(_PARSED)

    monkeypatch.setattr("app.agents.skill_gap.parse_jd", stalling_parse_jd)

    result = await run_jd_analyze(
        {"jd_text": "We need a senior Python engineer.", "proficiency": _PROFICIENCY},
        emit=emit,
    )

    notices = [e for e in events if e["id"] == THROTTLE_STEP_ID]
    assert len(notices) == 1, "one capacity note per run, however often we throttle"
    # Same wording as the chat path, and a settled `done` step — an `active` one would
    # leave the frontend's reasoning panel spinning forever (nothing resolves it).
    assert notices[0] == {
        "type": "step",
        "id": THROTTLE_STEP_ID,
        "label": THROTTLE_NOTICE,
        "status": "done",
    }
    # Emitted *during* the stall: it lands before the step it interrupted completes.
    order = [(e["id"], e["status"]) for e in events]
    assert order.index((THROTTLE_STEP_ID, "done")) < order.index(("parse", "done"))
    # The pipeline's own result is untouched.
    assert result["parsed"]["role"] == "Engineer"


@pytest.mark.asyncio
async def test_pipeline_event_sequence_unchanged_without_throttling():
    """No throttle = no extra events: the happy path is byte-identical."""
    from app.agents.pipelines import run_jd_analyze

    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    result = await run_jd_analyze(
        {"required_skills": ["python"], "proficiency": _PROFICIENCY}, emit=emit
    )

    assert [(e["type"], e["id"], e["status"]) for e in events] == [
        ("step", "parse", "active"),
        ("step", "parse", "done"),
        ("step", "match", "active"),
        ("step", "match", "done"),
        ("step", "recommend", "active"),
        ("step", "recommend", "done"),
    ]
    assert result["parsed"]["required_skills"] == ["python"]
    assert result["gap"]["readiness_score"] == 100.0


@pytest.mark.asyncio
async def test_headless_pipeline_leaves_an_outer_subscriber_alone(monkeypatch):
    """A pipeline with no emit must not shadow the chat handler's subscription."""
    from app.agents.model import notify_throttle, throttle_notices
    from app.agents.pipelines import run_jd_analyze

    async def stalling_parse_jd(jd_text: str) -> dict:
        notify_throttle(4.0)
        return dict(_PARSED)

    monkeypatch.setattr("app.agents.skill_gap.parse_jd", stalling_parse_jd)

    seen: list[float] = []
    with throttle_notices(seen.append):  # stands in for handler.run_chat's sink
        await run_jd_analyze({"jd_text": "Senior Python engineer."}, emit=None)

    assert seen == [4.0], "headless runs stay out of the way of the caller's sink"


@pytest.mark.asyncio
async def test_step_emitter_headless_drops_events():
    async with step_emitter(None) as emit:
        await emit(step_event("x", "X", "active"))  # no emit channel: swallowed
