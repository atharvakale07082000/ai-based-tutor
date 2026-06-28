"""Tests for the live agent step timeline backbone (app.agents.steps)."""

import pytest
from app.agents.steps import STEP_PLANS, StepTimeline, sse_step_stream, step_event


def test_step_event_shape():
    assert step_event("research", "Researching", "active") == {
        "type": "step",
        "id": "research",
        "label": "Researching",
        "status": "active",
    }


def test_timeline_uses_plan_labels():
    tl = StepTimeline("course_plan")
    assert tl.start("research") == {
        "type": "step",
        "id": "research",
        "label": "Researching the topic",
        "status": "active",
    }
    assert tl.done("research")["status"] == "done"


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
