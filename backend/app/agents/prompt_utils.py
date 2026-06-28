"""
Shared helpers for building agent prompts: conversation history and tool-output
truncation. Used by every agent generation so the behaviour stays consistent.
"""

from __future__ import annotations

import json

# Cap on a single serialized tool observation appended to the message list, so a
# large tool result can't blow the model's context window mid-loop.
MAX_OBSERVATION_CHARS = 2000


def truncate_observation(payload: object) -> str:
    """Serialize a tool result to JSON, capped at ``MAX_OBSERVATION_CHARS``."""
    text = json.dumps(payload, default=str)
    if len(text) > MAX_OBSERVATION_CHARS:
        return text[:MAX_OBSERVATION_CHARS] + f"… [truncated, {len(text)} chars total]"
    return text


def history_messages(history: object, max_turns: int = 6, max_chars: int = 600) -> list[dict]:
    """Normalize recent conversation turns into chat-format ``{role, content}`` messages.

    Accepts a list of dicts or pydantic-like objects exposing ``role``/``content``.
    Malformed or non user/assistant entries are skipped. Returns at most the last
    ``max_turns`` messages, each content-truncated to ``max_chars``.
    """
    if not isinstance(history, list):
        return []

    out: list[dict] = []
    for item in history[-max_turns:]:
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
        else:
            role = getattr(item, "role", None)
            content = getattr(item, "content", None)
        if role not in ("user", "assistant") or not content:
            continue
        out.append({"role": role, "content": str(content)[:max_chars]})
    return out
