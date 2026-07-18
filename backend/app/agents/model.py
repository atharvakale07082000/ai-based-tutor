"""
NIM model factory — the single place Strands model instances are built.

Every agent (orchestrator + specialists) gets its model from ``get_nim_model``.
``NIMModel`` subclasses the Strands ``OpenAIModel`` pointed at NVIDIA's
OpenAI-compatible endpoint and adds the two process-wide throttles this
backend already enforces everywhere else:

- ``HF_SEMAPHORE`` — the global cap on concurrent outbound LLM calls.
- an RPM token bucket sized to the NVIDIA free tier (``NIM_RPM_LIMIT``).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from functools import lru_cache
from typing import Any, AsyncGenerator

import structlog
from strands.models.openai import OpenAIModel

from app.config import settings
from app.hf.client import HF_SEMAPHORE

log = structlog.get_logger()


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
            "max_tokens": 1200,
            # NIM-specific: disable chat-template "thinking" so answers stream directly
            # (mirrors ResilientGenerationClient._nvidia_extra_body).
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    )
