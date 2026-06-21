"""
Structured logging via structlog.

In development (JSON_LOGS=false): coloured, human-readable terminal output.
In production  (JSON_LOGS=true):  compact JSON lines (one per event).

Call configure_logging() once at app startup.
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.contextvars import merge_contextvars


def configure_logging(log_level: str = "INFO", json_logs: bool = False) -> None:
    """Wire up structlog. Safe to call multiple times — subsequent calls are no-ops."""

    shared_processors: list = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%H:%M:%S" if not json_logs else "iso", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        renderer = structlog.processors.JSONRenderer()
        final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ]
    else:
        # Pretty console: show filename+line so you can click straight to source
        shared_processors.insert(
            0,
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
        )
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
            pad_event=40,
        )
        final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=final_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    if root.handlers:
        return  # already configured
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Silence noisy third-party loggers that flood the terminal
    for noisy in ("pymongo", "uvicorn.access", "httpx", "httpcore", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
