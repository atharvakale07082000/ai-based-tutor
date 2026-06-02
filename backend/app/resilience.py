"""
Resilience primitives for all outbound HF / external calls.

Provides:
  with_retry(fn, *args, **kwargs)         — async retry with exponential backoff + jitter
  CircuitBreaker                          — per-provider open/half-open/closed state machine
  resilient_call(name, fn, *args, **kwargs) — retry + circuit breaker combined

Configuration (via env vars):
  RETRY_MAX_ATTEMPTS      default 3
  RETRY_BASE_DELAY_S      default 1.0
  RETRY_MAX_DELAY_S       default 16.0
  CB_FAILURE_THRESHOLD    default 5   (opens circuit after N failures in window)
  CB_WINDOW_S             default 60  (rolling window for failure counting)
  CB_RECOVERY_S           default 30  (half-open probe delay after open)
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections import deque
from typing import Any, Callable, TypeVar

import structlog

log = structlog.get_logger()

T = TypeVar("T")

# ── Configuration ──────────────────────────────────────────────────────────────

_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY_S", "1.0"))
_MAX_DELAY = float(os.getenv("RETRY_MAX_DELAY_S", "16.0"))
_CB_THRESHOLD = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
_CB_WINDOW = float(os.getenv("CB_WINDOW_S", "60"))
_CB_RECOVERY = float(os.getenv("CB_RECOVERY_S", "30"))

# Status codes that should trigger a retry (transient errors)
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient errors worth retrying."""
    msg = str(exc)
    # Auth errors are permanent — no retry
    if "401" in msg or "403" in msg:
        return False
    # 400-level non-auth are client errors — no retry
    for code in ("400", "404", "405", "422"):
        if code in msg:
            return False
    return True


async def with_retry(
    fn: Callable[..., Any],
    *args,
    max_attempts: int = _MAX_ATTEMPTS,
    base_delay: float = _BASE_DELAY,
    max_delay: float = _MAX_DELAY,
    label: str = "",
    **kwargs,
) -> Any:
    """
    Retry *fn* with exponential backoff + full jitter.
    Only retries on transient errors; re-raises immediately on permanent ones.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == max_attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            jitter = random.uniform(0, delay * 0.25)
            wait = delay + jitter
            log.warning(
                "retry_attempt",
                label=label,
                attempt=attempt,
                max_attempts=max_attempts,
                wait_s=round(wait, 2),
                error=str(exc)[:120],
            )
            await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ── Circuit Breaker ────────────────────────────────────────────────────────────


class CircuitBreaker:
    """
    Per-name sliding-window circuit breaker.

    States:
      CLOSED     — normal operation, failures are counted
      OPEN       — fast-fail immediately; transitions to HALF_OPEN after recovery_s
      HALF_OPEN  — one probe allowed; success → CLOSED, failure → OPEN
    """

    _CLOSED = "CLOSED"
    _OPEN = "OPEN"
    _HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str,
        threshold: int = _CB_THRESHOLD,
        window_s: float = _CB_WINDOW,
        recovery_s: float = _CB_RECOVERY,
    ) -> None:
        self.name = name
        self._threshold = threshold
        self._window_s = window_s
        self._recovery_s = recovery_s
        self._state = self._CLOSED
        self._failure_times: deque[float] = deque()
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        return self._state

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._window_s
        while self._failure_times and self._failure_times[0] < cutoff:
            self._failure_times.popleft()

    def allow_request(self) -> bool:
        now = time.monotonic()
        if self._state == self._CLOSED:
            return True
        if self._state == self._OPEN:
            if now - self._opened_at >= self._recovery_s:
                self._state = self._HALF_OPEN
                log.info("circuit_half_open", name=self.name)
                return True
            return False
        # HALF_OPEN: allow exactly one probe
        return True

    def record_success(self) -> None:
        if self._state in (self._HALF_OPEN, self._OPEN):
            log.info("circuit_closed", name=self.name)
            self._state = self._CLOSED
            self._failure_times.clear()

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failure_times.append(now)
        self._prune()
        if self._state == self._HALF_OPEN:
            self._state = self._OPEN
            self._opened_at = now
            log.error("circuit_reopened", name=self.name)
            return
        if len(self._failure_times) >= self._threshold:
            self._state = self._OPEN
            self._opened_at = now
            log.error(
                "circuit_opened",
                name=self.name,
                failures=len(self._failure_times),
                window_s=self._window_s,
            )


# Module-level registry so each named dependency gets one breaker instance.
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]


class CircuitOpenError(RuntimeError):
    pass


async def resilient_call(
    name: str,
    fn: Callable[..., Any],
    *args,
    timeout_s: float = 30.0,
    **kwargs,
) -> Any:
    """
    Execute *fn* with retry + circuit breaker + timeout.
    *name* identifies the downstream dependency (used for the circuit breaker key).
    """
    breaker = get_breaker(name)

    if not breaker.allow_request():
        raise CircuitOpenError(f"Circuit breaker open for '{name}' — dependency unavailable")

    async def _timed(*a, **kw):
        return await asyncio.wait_for(fn(*a, **kw), timeout=timeout_s)

    try:
        result = await with_retry(_timed, *args, label=name, **kwargs)
        breaker.record_success()
        return result
    except CircuitOpenError:
        raise
    except Exception as exc:
        if _is_retryable(exc):
            breaker.record_failure()
        raise
