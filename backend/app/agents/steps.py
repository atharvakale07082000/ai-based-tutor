"""
Live agent step timeline.

A long-running flow (course generation, quiz review, interview review, agentic
chat, …) declares an ordered list of named steps and emits ``step`` SSE events as
it progresses. The frontend folds these into a timeline: an ``active`` step shows
as pending/pulsing, a ``done`` step turns green, and the next step streams in
dynamically until the final answer/result arrives.

Event shape (additive — clients that don't know ``step`` ignore it):
    {"type": "step", "id": "research", "label": "Researching the topic", "status": "active"}
    {"type": "step", "id": "research", "label": "Researching the topic", "status": "done"}

``status`` ∈ {"active", "done", "error"}.

``step_emitter`` wraps a pipeline body so upstream capacity waits (the NIM RPM
bucket, see ``agents/model.py``) surface as one more step instead of a frozen
timeline — the pipeline-side counterpart of what ``agents/handler.py`` does for chat.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Optional

import structlog

from app.agents.model import throttle_notices

log = structlog.get_logger()

StepStatus = str  # "active" | "done" | "error"

# Optional step-emit callback a pipeline forwards its timeline events to. It receives
# a step/event dict and pushes it onto the SSE queue (see ``sse_step_stream``).
# ``None`` = run headless with no live timeline.
StepEmit = Optional[Callable[[dict], Awaitable[None]]]


@dataclass(frozen=True)
class Step:
    id: str
    label: str


# Ordered, human-facing step plans per flow. A flow may also emit ad-hoc steps not
# listed here (e.g. one timeline entry per tool the chat agent calls).
# Labels are written as first-person reasoning narration — the flow is shown to the
# learner as "how I'm thinking through this", not as a mechanical workflow checklist.
STEP_PLANS: dict[str, list[Step]] = {
    "course_plan": [
        Step("research", "Looking into what this goal really takes to reach"),
        Step("design", "Mapping a path from the basics up to mastery"),
        Step("finalize", "Putting your plan together"),
    ],
    "quiz_review": [
        Step("analyze", "Reading through how you answered"),
        Step("score", "Working out your new mastery level"),
        Step("feedback", "Pulling together your feedback"),
    ],
    "interview_review": [
        Step("evaluate", "Going through each of your answers"),
        Step("score", "Weighing them against what a strong answer covers"),
        Step("feedback", "Writing up your feedback"),
    ],
    "chat": [
        Step("route", "Working out what you're really asking"),
        Step("work", "Thinking it through"),
        Step("answer", "Putting the answer together"),
    ],
    "jd_analyze": [
        Step("parse", "Reading through the role"),
        Step("match", "Comparing it against your skills"),
        Step("recommend", "Finding the fastest ways to close the gaps"),
    ],
    "loop_setup": [
        Step("research", "Looking into how this company actually interviews"),
        Step("design", "Laying out the rounds you'll face"),
        Step("calibrate", "Setting the bar each round is graded against"),
    ],
    "loop_debrief": [
        Step("gather", "Pulling together how each round went"),
        Step("assess", "Weighing your rounds against the bar for this role"),
        Step("advise", "Working out what to fix first"),
    ],
}


def step_event(step_id: str, label: str, status: StepStatus) -> dict:
    """Build a ``step`` SSE event dict."""
    return {"type": "step", "id": step_id, "label": label, "status": status}


class StepTimeline:
    """Tracks a flow's steps and produces ``step`` event dicts to yield into a stream.

    Labels for known step ids come from the flow's plan; ad-hoc steps can pass an
    explicit label. Callers yield the returned dicts (the router frames them as SSE).
    """

    def __init__(self, plan_key: str | None = None) -> None:
        plan = STEP_PLANS.get(plan_key, []) if plan_key else []
        self._labels: dict[str, str] = {s.id: s.label for s in plan}

    def _label(self, step_id: str, label: str | None) -> str:
        if label:
            self._labels[step_id] = label
        return self._labels.get(step_id, step_id)

    def start(self, step_id: str, label: str | None = None) -> dict:
        """Mark a step active (adds it to the timeline as pending/pulsing)."""
        return step_event(step_id, self._label(step_id, label), "active")

    def done(self, step_id: str, label: str | None = None) -> dict:
        """Mark a step complete (turns green)."""
        return step_event(step_id, self._label(step_id, label), "done")

    def error(self, step_id: str, label: str | None = None) -> dict:
        """Mark a step failed."""
        return step_event(step_id, self._label(step_id, label), "error")


# ── capacity waits ──────────────────────────────────────────────────────────────
# Id of the ad-hoc step a capacity wait adds to the timeline. Distinct from every
# plan's ids so it appends instead of overwriting the step that's mid-flight.
THROTTLE_STEP_ID = "capacity"


async def _drop_event(_ev: dict) -> None:
    """Swallow an event — the headless (``emit is None``) emitter."""


def _throttle_notice_event() -> dict:
    """Build the ``step`` event announcing an upstream capacity wait.

    The wording is imported from the chat path rather than restated, so the learner
    hears one voice wherever the wait happens.

    Status is ``done``, not ``active``, on purpose: nothing ever resolves this entry,
    and the frontend reads *any* active step as "still thinking" (``ReasoningStream``
    derives its live state from the segments), so an active notice would leave the
    panel spinning after the run finished. ``error`` would be wrong too — waiting on
    capacity is not a failure. ``done`` renders as an inert, already-settled line.
    """
    from app.agents.handler import THROTTLE_NOTICE  # local: steps is the lower layer

    return step_event(THROTTLE_STEP_ID, THROTTLE_NOTICE, "done")


@asynccontextmanager
async def step_emitter(
    emit: StepEmit,
) -> AsyncIterator[Callable[[dict], Awaitable[None]]]:
    """Wrap a pipeline body: yields a safe ``emit`` and narrates capacity waits.

    Usage — one line per pipeline, replacing the hand-rolled ``_e`` closure::

        async with step_emitter(emit) as _e:
            await _e(tl.start("research"))
            ...

    The model layer announces an RPM wait through a *synchronous* callback while
    ``emit`` is a coroutine, and the stall happens inside an ``await`` *between* step
    transitions — there is no emit point to hang the notice on, and deferring it to
    the next step boundary would only tell the learner once the wait was already over.
    So the sink parks the wait on a queue and a relay task, running concurrently with
    the pipeline body, emits it while the body is still blocked.

    A headless run (``emit is None``) is a complete no-op: no subscription, no relay
    task, and the yielded emitter drops events exactly like the closures it replaces.
    Staying unsubscribed there is load-bearing — a pipeline called inside a chat turn
    would otherwise shadow the handler's own subscription and swallow its notice.
    """
    if emit is None:
        yield _drop_event
        return

    loop = asyncio.get_running_loop()
    waits: asyncio.Queue[float] = asyncio.Queue()
    notified = False

    def _sink(wait_s: float) -> None:
        nonlocal notified
        if notified:
            return  # one capacity note per run is enough
        notified = True
        # Sync, and reachable from an ``asyncio.to_thread`` worker (context vars
        # propagate into those), so hop back onto the loop before touching the queue.
        loop.call_soon_threadsafe(waits.put_nowait, wait_s)

    async def _relay() -> None:
        wait_s = await waits.get()
        log.info("pipeline_throttle_notice", wait_s=round(wait_s, 1))
        try:
            await emit(_throttle_notice_event())
        except Exception as e:  # noqa: BLE001 — a notice must never break a run
            log.warning("pipeline_throttle_notice_failed", error=str(e)[:200])

    task = asyncio.create_task(_relay())
    try:
        with throttle_notices(_sink):
            yield emit
    finally:
        if not task.done():
            task.cancel()


async def sse_step_stream(
    run: Callable[[Callable[[dict], Awaitable[None]]], Awaitable[None]],
) -> AsyncIterator[dict]:
    """Drive a worker that emits event dicts, yielding them for SSE framing.

    ``run`` is an async function receiving an ``emit(event_dict)`` coroutine. It is
    executed as a background task so its events stream to the client as they happen,
    even while the worker is mid-await. Any unhandled error becomes a generic
    ``error`` event so raw exceptions never reach the caller.

    Usage in a router::

        async def event_stream():
            async def run(emit):
                tl = StepTimeline("course_plan")
                await emit(tl.start("research"))
                ...
                await emit(tl.done("research"))
                await emit({"type": "action", "kind": "plan_created", "payload": {...}})
            async for ev in sse_step_stream(run):
                yield f"data: {json.dumps(ev)}\\n\\n"
            yield "data: [DONE]\\n\\n"
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(ev: dict) -> None:
        await queue.put(ev)

    async def _runner() -> None:
        try:
            await run(emit)
        except Exception as e:  # noqa: BLE001 — convert any failure to a safe event
            log.error("sse_step_stream_error", error=str(e)[:300])
            await queue.put(
                {
                    "type": "error",
                    "message": "Something went wrong on my end — try again",
                }
            )
        finally:
            await queue.put(None)  # sentinel: worker finished

    task = asyncio.create_task(_runner())
    try:
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield ev
    finally:
        if not task.done():
            task.cancel()
