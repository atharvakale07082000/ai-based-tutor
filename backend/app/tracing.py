"""
Langfuse tracing integration.

Usage:
    from app.tracing import get_tracer

    tracer = get_tracer()
    with tracer.trace("my_agent", input={"key": "val"}) as span:
        result = do_work()
        span.update(output=result)

If LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set the tracer is a no-op
so the rest of the codebase never needs to handle the missing-credentials case.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

import structlog

log = structlog.get_logger()


# ── No-op span / tracer used when Langfuse is not configured ─────────────────


@dataclass
class _NoOpSpan:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def update(self, **_kwargs) -> None:
        pass

    def end(self, **_kwargs) -> None:
        pass


class _NoOpTracer:
    @contextmanager
    def trace(self, name: str, **_kwargs) -> Generator[_NoOpSpan, None, None]:
        yield _NoOpSpan()

    def flush(self) -> None:
        pass


# ── Real Langfuse tracer ──────────────────────────────────────────────────────


class _LangfuseTracer:
    def __init__(self, lf):
        self._lf = lf

    @contextmanager
    def trace(
        self,
        name: str,
        input: dict | None = None,
        metadata: dict | None = None,
        **_kwargs,
    ) -> Generator[Any, None, None]:
        trace = self._lf.trace(name=name, input=input or {}, metadata=metadata or {})
        span = trace.span(name=name, input=input or {})
        start = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.update(level="ERROR", status_message=str(exc))
            raise
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000)
            span.end(metadata={"latency_ms": latency_ms})

    def flush(self) -> None:
        try:
            self._lf.flush()
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracer: _NoOpTracer | _LangfuseTracer | None = None


def get_tracer() -> _NoOpTracer | _LangfuseTracer:
    global _tracer
    if _tracer is not None:
        return _tracer

    from app.config import settings

    if settings.langfuse_enabled:
        try:
            from langfuse import Langfuse  # type: ignore

            lf = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
            _tracer = _LangfuseTracer(lf)
            log.info("langfuse_tracer_initialized", host=settings.LANGFUSE_HOST)
        except Exception as e:
            log.warning("langfuse_init_failed", error=str(e))
            _tracer = _NoOpTracer()
    else:
        log.info("langfuse_disabled_using_noop_tracer")
        _tracer = _NoOpTracer()

    return _tracer
