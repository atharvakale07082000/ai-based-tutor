"""
Shared production utilities for all HF / LLM agent calls.

  - llm_timeout()     : wraps asyncio.to_thread with a hard deadline
  - truncate_history  : caps conversation history before it blows token budget
  - BoundedCache      : thread-safe LRU dict to cache embeddings / results
"""

from __future__ import annotations

import asyncio
import collections
import threading
from typing import Any, Callable

import structlog

log = structlog.get_logger()

# Hard deadline for any single LLM / HF inference call (seconds)
LLM_CALL_TIMEOUT: float = 45.0
# Max chars per history message before truncation (≈ 300 tokens)
HISTORY_MSG_MAX_CHARS: int = 1200
# Max messages kept in history sent to LLM
HISTORY_MAX_TURNS: int = 8


async def llm_timeout(
    fn: Callable,
    *args: Any,
    timeout: float = LLM_CALL_TIMEOUT,
    **kwargs: Any,
) -> Any:
    """
    Run a blocking LLM call in a thread with a hard timeout.
    Raises asyncio.TimeoutError on breach (caller should catch and degrade).
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        log.error("llm_call_timeout", fn=getattr(fn, "__name__", str(fn)), timeout=timeout)
        raise


def truncate_history(
    history: list[dict],
    max_turns: int = HISTORY_MAX_TURNS,
    max_chars_per_msg: int = HISTORY_MSG_MAX_CHARS,
) -> list[dict]:
    """
    Trim conversation history to stay within token budget.
    - Keeps only the last `max_turns` messages
    - Truncates individual messages to `max_chars_per_msg` chars
    """
    recent = history[-max_turns:]
    result = []
    for msg in recent:
        content = str(msg.get("content", ""))
        if len(content) > max_chars_per_msg:
            content = content[:max_chars_per_msg] + "…"
            log.debug("history_message_truncated", original_len=len(msg.get("content", "")))
        result.append({**msg, "content": content})
    return result


class BoundedCache:
    """
    Thread-safe LRU dict. Evicts the oldest entry when max_size is reached.
    Drop-in replacement for a plain dict used as a cache.
    """

    def __init__(self, max_size: int = 1024) -> None:
        self._max = max_size
        self._data: collections.OrderedDict[str, Any] = collections.OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            if len(self._data) > self._max:
                self._data.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __getitem__(self, key: str) -> Any:
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)
