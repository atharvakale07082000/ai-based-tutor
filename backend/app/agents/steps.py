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
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable

import structlog

log = structlog.get_logger()

StepStatus = str  # "active" | "done" | "error"


@dataclass(frozen=True)
class Step:
    id: str
    label: str


# Ordered, human-facing step plans per flow. A flow may also emit ad-hoc steps not
# listed here (e.g. one timeline entry per tool the chat agent calls).
STEP_PLANS: dict[str, list[Step]] = {
    "course_plan": [
        Step("research", "Researching the topic"),
        Step("design", "Designing your curriculum"),
        Step("finalize", "Saving your plan"),
    ],
    "quiz_review": [
        Step("analyze", "Analyzing your answers"),
        Step("score", "Scoring & updating mastery"),
        Step("feedback", "Preparing your feedback"),
    ],
    "interview_review": [
        Step("evaluate", "Evaluating your responses"),
        Step("score", "Scoring across the rubric"),
        Step("feedback", "Writing your feedback"),
    ],
    "chat": [
        Step("route", "Understanding your question"),
        Step("work", "Working through it"),
        Step("answer", "Composing the answer"),
    ],
    "jd_analyze": [
        Step("parse", "Reading the job description"),
        Step("match", "Matching against your skills"),
        Step("recommend", "Finding ways to close the gaps"),
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
            await queue.put({"type": "error", "message": "Something went wrong on my end — please try again."})
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
