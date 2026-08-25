"""
Langfuse tracing — the single place the Langfuse client is configured.

What produces spans:

- **Strands agents** (chat orchestrator, specialists, the live interview agent) emit
  OpenTelemetry spans on their own. Langfuse attaches a span processor to the global
  tracer provider, so those become `generation`/`tool` observations with model, token
  usage and cost filled in automatically. No per-agent wiring.
- **Non-Strands generation** (``hf/generation_client.py`` — quiz, course plan, doubt,
  interview scoring) goes through the OpenAI SDK, instrumented by ``langfuse.openai``.
- **Root spans** are opened by the request handlers so each trace is one unit of work
  (one chat turn, one pipeline run, one interview turn) with a readable input/output.

Everything here degrades to a no-op when the keys are unset, so call sites never
branch on whether tracing is configured.

Ordering matters: ``init_observability()`` must run before the first agent call, and
after ``app.otel``'s provider (if any) is installed — see ``main.lifespan``.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager, contextmanager, nullcontext
from typing import Any, Iterator, Optional

import structlog

from app.config import settings

log = structlog.get_logger()

_client: Any | None = None
_enabled = False

# Redacted before export. These traverse agent prompts (learner context blobs carry the
# profile) and would otherwise be stored in Langfuse verbatim.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_KEY_RE = re.compile(r"\b(?:nvapi-|hf_|sk-|pk-lf-|sk-lf-)[A-Za-z0-9_-]{12,}")

_REDACTIONS = (
    (_JWT_RE, "[JWT_REDACTED]"),
    (_KEY_RE, "[API_KEY_REDACTED]"),
    (_EMAIL_RE, "[EMAIL_REDACTED]"),
)


def _redact(value: str) -> str:
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


def _mask_otel_spans(*, params):  # type: ignore[no-untyped-def]
    """Strip PII/credentials from raw span attributes at export time.

    This has to run below the call sites: the spans carrying learner prompts are
    created by Strands and the OpenAI SDK, not by this codebase, so there is no call
    site to sanitise. Runs on the exporter thread, so it stays a cheap regex pass.
    """
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        replacements = {}
        for key, value in span.attributes.items():
            if isinstance(value, str) and len(value) < 200_000:
                masked = _redact(value)
                if masked != value:
                    replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    return MaskOtelSpansResult(span_patches=patches)


def init_observability() -> None:
    """Initialise the Langfuse client once. Safe to call repeatedly."""
    global _client, _enabled

    if _client is not None:
        return

    if not settings.langfuse_enabled:
        log.info("langfuse_disabled", reason="LANGFUSE_PUBLIC_KEY/SECRET_KEY unset")
        return

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            base_url=settings.langfuse_host,
            environment=settings.APP_ENV,
            # release is left to the SDK: it reads the deploy platform's git-SHA env
            # vars (Render/Vercel/etc.) and LANGFUSE_RELEASE on its own.
            sample_rate=settings.LANGFUSE_SAMPLE_RATE,
            mask_otel_spans=_mask_otel_spans,
            # No custom should_export_span: Langfuse's default filter already keeps
            # every Strands span (they all carry gen_ai.* attributes) while dropping
            # Mongo/HTTP noise. Verified against a live agent turn.
        )
        _enabled = True
        log.info(
            "langfuse_initialized",
            host=settings.langfuse_host,
            environment=settings.APP_ENV,
            sample_rate=settings.LANGFUSE_SAMPLE_RATE,
        )
    except Exception as e:  # noqa: BLE001 - tracing must never block startup
        _client = None
        _enabled = False
        log.warning("langfuse_init_failed", error=str(e)[:300])


def is_enabled() -> bool:
    return _enabled


def get_langfuse():
    """Return the initialised client, or None when tracing is off."""
    return _client


def flush() -> None:
    """Force-export buffered spans. Call on shutdown and after fire-and-forget work."""
    if _client is None:
        return
    try:
        _client.flush()
    except Exception as e:  # noqa: BLE001
        log.warning("langfuse_flush_failed", error=str(e)[:200])


def shutdown_observability() -> None:
    """Flush and release the exporter threads at process exit."""
    global _client, _enabled
    if _client is None:
        return
    try:
        _client.shutdown()
        log.info("langfuse_shutdown")
    except Exception as e:  # noqa: BLE001
        log.warning("langfuse_shutdown_failed", error=str(e)[:200])
    finally:
        _client = None
        _enabled = False


class _NoOpObservation:
    """Stands in for a Langfuse observation so call sites never branch on config."""

    def update(self, **_kwargs: Any) -> None:
        pass

    def update_trace(self, **_kwargs: Any) -> None:
        pass

    def end(self, **_kwargs: Any) -> None:
        pass


@contextmanager
def observation(
    name: str,
    *,
    as_type: str = "span",
    input: Any = None,
    metadata: dict | None = None,
    **kwargs: Any,
) -> Iterator[Any]:
    """Open an observation, or yield a no-op when tracing is disabled.

    Names are the stable handle dashboards, saved views and LLM-as-a-judge evaluators
    target — keep them verb-first and free of per-run values.
    """
    if _client is None:
        yield _NoOpObservation()
        return

    try:
        with _client.start_as_current_observation(
            as_type=as_type,
            name=name,
            input=input,
            metadata=metadata,
            **kwargs,
        ) as obs:
            yield obs
    except Exception as e:  # noqa: BLE001 - a tracing fault must never break a request
        log.warning("langfuse_observation_failed", name=name, error=str(e)[:200])
        yield _NoOpObservation()


def trace_attributes(
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
    **kwargs: Any,
):
    """Propagate user/session/tags to every observation created inside the block."""
    if _client is None:
        return nullcontext()
    try:
        from langfuse import propagate_attributes

        return propagate_attributes(
            user_id=user_id or None,
            session_id=session_id or None,
            metadata=metadata,
            tags=tags,
            **kwargs,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("langfuse_propagate_failed", error=str(e)[:200])
        return nullcontext()


def score_current_trace(name: str, value: Any, comment: str | None = None) -> None:
    """Attach a score to the active trace (quality signals, learner feedback)."""
    if _client is None:
        return
    try:
        _client.score_current_trace(name=name, value=value, comment=comment)
    except Exception as e:  # noqa: BLE001
        log.warning("langfuse_score_failed", name=name, error=str(e)[:200])


@asynccontextmanager
async def traced_pipeline(
    name: str,
    *,
    input: Any = None,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
):
    """Root observation for one generation-pipeline run.

    An async context manager so it composes with ``steps.step_emitter`` on a single
    ``async with`` line, which is why the pipelines did not need re-indenting::

        async with traced_pipeline("generate-quiz", input=...) as root, \
                step_emitter(emit) as _e:
            ...
            root.update(output=...)
    """
    with (
        observation(name, input=input, metadata=metadata) as root,
        trace_attributes(
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            trace_name=name,
        ),
    ):
        try:
            yield root
        except Exception as exc:
            root.update(level="ERROR", status_message=str(exc)[:500])
            raise
