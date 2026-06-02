"""
Structured JSON logging via structlog.

Call configure_logging() once at app startup (in lifespan).
After that, every `structlog.get_logger()` call returns a logger
that emits a single JSON line per event with a consistent schema:

  {
    "timestamp": "2026-06-02T12:00:00.123456Z",
    "level": "info",
    "agent": "...",
    "task_id": "...",
    "session_id": "...",
    "correlation_id": "...",
    "event": "...",
    ...
  }

Context variables (task_id, session_id, correlation_id, agent) are
injected via structlog.contextvars and survive across async awaits
within the same request thanks to Python's contextvars module.
"""
from __future__ import annotations

import logging
import sys

import structlog
from structlog.contextvars import merge_contextvars


def configure_logging(log_level: str = "INFO", json_logs: bool = True) -> None:
    """
    Wire up structlog with JSON rendering and stdlib bridge.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    shared_processors: list = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    if root.handlers:
        return  # already configured
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Quiet noisy third-party loggers
    for noisy in ("pymongo", "uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
