"""
NIM model factory — the single place Strands model instances are built.

Every agent (orchestrator + specialists) gets its model from ``get_nim_model``.
``NIMModel`` subclasses the Strands ``OpenAIModel`` pointed at NVIDIA's
OpenAI-compatible endpoint and adds the two process-wide throttles this
backend already enforces everywhere else:

- ``HF_SEMAPHORE`` — the global cap on concurrent outbound LLM calls.
- an RPM token bucket sized to the NVIDIA free tier (``NIM_RPM_LIMIT``).

When the bucket is exhausted a call just waits, which the learner experiences as an
unexplained stall. ``throttle_notices`` lets the layer above subscribe to those waits
without this module knowing anything about SSE (see ``agents/handler.py``, which turns
the callback into a ``reasoning`` event). No subscriber = silent, as before.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, AsyncGenerator, Callable, Iterator

import structlog
from strands.models.openai import OpenAIModel

from app.config import settings
from app.hf.client import HF_SEMAPHORE

log = structlog.get_logger()

# Called with the number of seconds this call is about to wait on the RPM bucket.
ThrottleSink = Callable[[float], None]

_throttle_sink: ContextVar[ThrottleSink | None] = ContextVar(
    "nim_throttle_sink", default=None
)


@contextmanager
def throttle_notices(sink: ThrottleSink) -> Iterator[None]:
    """Subscribe ``sink`` to RPM waits for the duration of this context.

    Context-scoped, so concurrent requests never see each other's waits, and tasks
    created inside the block inherit the subscription.
    """
    token = _throttle_sink.set(sink)
    try:
        yield
    finally:
        try:
            _throttle_sink.reset(token)
        except ValueError:  # closed from another context (e.g. a cancelled stream)
            _throttle_sink.set(None)


def notify_throttle(wait_s: float) -> None:
    """Tell the current subscriber, if any, that this call is waiting ``wait_s`` seconds."""
    sink = _throttle_sink.get()
    if sink is None:
        return
    try:
        sink(wait_s)
    except Exception as e:  # noqa: BLE001 - a bad listener must never break an LLM call
        log.warning("nim_throttle_notify_failed", error=str(e)[:200])


class _RpmBucket:
    """Sliding-window rate limiter: at most ``limit`` acquisitions per 60s."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] > 60.0:
                    self._stamps.popleft()
                if len(self._stamps) < self.limit:
                    self._stamps.append(now)
                    return
                wait = 60.0 - (now - self._stamps[0]) + 0.05
            log.warning("nim_rpm_throttled", wait_s=round(wait, 1))
            # Let the streaming layer tell the learner we're waiting, if it subscribed.
            notify_throttle(wait)
            await asyncio.sleep(wait)


_rpm_bucket = _RpmBucket(settings.NIM_RPM_LIMIT)


class NIMModel(OpenAIModel):
    """OpenAIModel against NVIDIA NIM with the shared semaphore + RPM bucket."""

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator:
        await _rpm_bucket.acquire()
        async with HF_SEMAPHORE:
            async for event in super().stream(*args, **kwargs):
                yield event


@lru_cache(maxsize=8)
def get_nim_model(role: str = "specialist") -> NIMModel:
    """Return the cached NIM model for a role (``orchestrator`` | ``specialist``)."""
    model_id = (
        settings.NIM_ORCHESTRATOR_MODEL
        if role == "orchestrator"
        else settings.NIM_SPECIALIST_MODEL
    )
    return NIMModel(
        client_args={
            "api_key": settings.NVIDIA_API_KEY,
            "base_url": settings.NVIDIA_BASE_URL,
        },
        model_id=model_id,
        params={
            "temperature": 0.2,
            # The default specialist model is a reasoning model: it spends tokens deliberating
            # before the visible answer. At the old 1200 cap it hit MaxTokensReached mid-turn
            # and failed the whole request, so the budget covers thinking + answer.
            "max_tokens": 3000,
            # NIM-specific: disable chat-template "thinking" so answers stream directly
            # (mirrors ResilientGenerationClient._nvidia_extra_body).
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    )
