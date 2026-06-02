"""
OpenTelemetry instrumentation.

Initialises a tracer that exports spans to an OTLP collector when
OTEL_EXPORTER_OTLP_ENDPOINT is set; falls back to a no-op tracer
so the rest of the codebase never needs to handle the absent case.

Usage:
    from app.otel import get_otel_tracer, new_trace_id
    tracer = get_otel_tracer()
    with tracer.start_as_current_span("my-operation") as span:
        span.set_attribute("agent", "quiz_agent")
        span.set_attribute("task_id", task_id)
        ...

The X-Trace-Id response header is injected by TraceIdMiddleware (added
in main.py) so callers can correlate browser/client logs with server spans.

Environment variables:
    OTEL_EXPORTER_OTLP_ENDPOINT   e.g. http://localhost:4318
    OTEL_SERVICE_NAME              defaults to "ai-tutor"
    OTEL_ENABLED                   set to "false" to force no-op mode
"""
from __future__ import annotations

import os
import uuid
import structlog

log = structlog.get_logger()

_tracer = None


def _build_tracer():
    service_name = os.getenv("OTEL_SERVICE_NAME", "ai-tutor")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    enabled = os.getenv("OTEL_ENABLED", "true").lower() != "false"

    if not enabled or not endpoint:
        log.info("otel_disabled", reason="no endpoint or OTEL_ENABLED=false")
        return _NoOpTracer()

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer(service_name)
        log.info("otel_initialized", endpoint=endpoint, service=service_name)
        return tracer

    except ImportError:
        log.warning("otel_import_error", msg="opentelemetry packages not installed — using no-op tracer")
        return _NoOpTracer()
    except Exception as exc:
        log.warning("otel_init_failed", error=str(exc))
        return _NoOpTracer()


class _NoOpSpan:
    def set_attribute(self, key: str, value) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    def start_as_current_span(self, name: str, **kwargs):
        return _NoOpSpan()


def get_otel_tracer():
    global _tracer
    if _tracer is None:
        _tracer = _build_tracer()
    return _tracer


def new_trace_id() -> str:
    """Generate a W3C-compatible trace ID (32 hex chars)."""
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


def current_trace_id() -> str:
    """Return the active OTEL trace ID, or a fresh UUID if no span is active."""
    try:
        from opentelemetry import trace
        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        pass
    return new_trace_id()
