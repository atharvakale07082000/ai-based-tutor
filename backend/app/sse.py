"""
SSE wire framing — the one place that knows how an event dict becomes bytes.

``agents/steps.py`` owns the *event* half of the streaming contract (step plans,
timelines, capacity notices) and deliberately knows nothing about HTTP. This
module owns the other half: the ``data: …`` framing, the ``[DONE]`` sentinel and
the response headers that keep proxies from buffering a live stream.

Two entry points, matching the two shapes a streaming endpoint takes:

* ``sse_response(run)`` — the common case: a pipeline that emits step/action
  events through ``sse_step_stream``. The whole endpoint body becomes one line.
* ``sse_frame(ev)`` + ``SSE_HEADERS`` — for the handful of endpoints that build
  their own generator (chat, doubts, the interview turn loop) because they
  interleave events from a source other than a pipeline runner.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Awaitable, Callable

from fastapi.responses import StreamingResponse

from app.agents.steps import sse_step_stream

# ``X-Accel-Buffering: no`` stops nginx (and Render's proxy) from buffering the
# stream into chunks; ``Cache-Control: no-cache`` stops any intermediary caching it.
SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}

SSE_DONE = "data: [DONE]\n\n"


def sse_frame(ev: dict) -> str:
    """Encode one event dict as an SSE ``data:`` frame."""
    return f"data: {json.dumps(ev)}\n\n"


def sse_stream_response(
    gen: AsyncIterator[str], headers: dict[str, str] | None = None
) -> StreamingResponse:
    """Wrap an already-framed generator in a correctly-headed streaming response.

    ``headers`` adds to (never replaces) ``SSE_HEADERS`` — the chat endpoint echoes
    its session/correlation ids this way instead of restating the buffering headers.
    """
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **(headers or {})},
    )


def sse_response(
    run: Callable[[Callable[[dict], Awaitable[None]]], Awaitable[None]],
) -> StreamingResponse:
    """Stream a pipeline's events to the client as SSE.

    ``run`` is the same worker ``sse_step_stream`` takes — an async function that
    receives an ``emit(event_dict)`` coroutine. Errors inside it are already
    converted to a generic ``error`` event by ``sse_step_stream``, so nothing raw
    escapes here.
    """

    async def event_stream() -> AsyncIterator[str]:
        async for ev in sse_step_stream(run):
            yield sse_frame(ev)
        yield SSE_DONE

    return sse_stream_response(event_stream())
