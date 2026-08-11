"""
Translate Strands ``stream_async`` events into the SSE wire contract the
frontend speaks (see AtelierV2Page's ``V2Event`` union):

    {"type": "reasoning", "content": str}   # the agent thinking out loud
    {"type": "token",     "content": str}   # the answer, streamed
    {"type": "action",    "kind": str, "payload": dict}
    {"type": "done",      "steps": n, "total_ms": int}
    {"type": "error",     "message": str}

We deliberately do NOT surface the mechanical tool workflow (tool names, args,
results, latencies) to the learner. Instead each specialist is instructed (see
``react_agent.yaml`` ``reasoning_protocol``) to open its reply with a short,
first-person ``<reasoning>…</reasoning>`` note describing how it's approaching the
task; ``translate_event`` splits that out of the token stream into ``reasoning``
events, and everything after it is the answer. Side-effect tools still produce
``action`` cards (a generated quiz, updated progress) — those are outcomes, not
workflow.

Hidden from the wire ≠ thrown away: tool results are still accumulated on the
``TraceState`` as ``grounding`` so the online faithfulness eval can check the
answer against the facts the agent actually retrieved (see ``routers/chat.py``).
That list never becomes an event.

One ``TraceState`` instance tracks a single agent stream.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()

# Tool results that surface as `action` cards in the chat UI.
# kind values match what the frontend's action-card renderer understands.
_ACTION_TOOLS: dict[str, str] = {
    "save_quiz": "quiz_generated",
    "save_progress": "progress_updated",
}

# Delimiters the model wraps its thinking in (see reasoning_protocol prompt).
_R_OPEN = "<reasoning>"
_R_CLOSE = "</reasoning>"

# Bounds on the retrieval context kept for the online faithfulness eval, so a long
# tool chain can't balloon memory. Per-entry cap matches what the chat router used
# to apply before the reasoning-stream refactor dropped the tool events.
_GROUNDING_MAX_ENTRIES = 8
_GROUNDING_MAX_CHARS = 1500


@dataclass
class TraceState:
    """Mutable per-stream bookkeeping for reasoning/answer splitting."""

    started: float = field(default_factory=time.monotonic)
    # toolUseId → tool name. Only the name is needed, to map a completed tool to
    # its `action` card; the mechanical call detail is deliberately not tracked.
    tools: dict[str, str] = field(default_factory=dict)
    in_reasoning: bool = False
    carry: str = ""  # held-back tail that might be a partial <reasoning> tag
    # Tool results seen on this stream, server-side only (never emitted): the
    # retrieval context the faithfulness metric grades the answer against.
    grounding: list[str] = field(default_factory=list)

    def add_grounding(self, payload: Any) -> None:
        """Record one tool result as retrieval context (bounded in count and length)."""
        if len(self.grounding) >= _GROUNDING_MAX_ENTRIES:
            return
        text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
        text = text.strip()
        if text:
            self.grounding.append(text[:_GROUNDING_MAX_CHARS])


def _tool_result_payload(tool_result: dict) -> Any:
    """Unwrap a Strands ToolResult content list into the action-card payload shape."""
    content = tool_result.get("content") or []
    parts: list[Any] = []
    for block in content:
        if "json" in block:
            parts.append(block["json"])
        elif "text" in block:
            text = block["text"]
            # Tool adapters return dicts, which strands stringifies; recover them.
            parsed = None
            if text.startswith("Result: "):
                try:
                    parsed = json.loads(text[len("Result: ") :].replace("'", '"'))
                except json.JSONDecodeError:
                    parsed = None
            parts.append(parsed if parsed is not None else text)
    if not parts:
        return tool_result.get("status", "")
    return parts[0] if len(parts) == 1 else parts


def action_for_tool(name: str, payload: Any) -> dict | None:
    """Map a completed side-effect tool to an `action` event, if any."""
    kind = _ACTION_TOOLS.get(name)
    if kind is None or not isinstance(payload, dict) or payload.get("error"):
        return None
    action_payload = dict(payload)
    if name == "save_progress" and "xp_delta" in action_payload:
        action_payload.setdefault("xp_earned", action_payload["xp_delta"])
        action_payload.setdefault("label", "Progress updated")
    return {"type": "action", "kind": kind, "payload": action_payload}


def _split_safe(buf: str, tag: str) -> tuple[str, str]:
    """Split ``buf`` into (emit_now, hold_back).

    ``hold_back`` is the longest suffix of ``buf`` that is a proper prefix of
    ``tag`` — so a delimiter split across two chunks is never emitted mid-tag.
    """
    for k in range(min(len(buf), len(tag) - 1), 0, -1):
        if buf[-k:] == tag[:k]:
            return buf[:-k], buf[-k:]
    return buf, ""


def _route_text(state: TraceState, text: str, forward_tokens: bool) -> list[dict]:
    """Split model text into `reasoning` (inside tags) vs `token` (the answer)."""
    events: list[dict] = []
    buf = state.carry + text
    state.carry = ""
    while buf:
        if state.in_reasoning:
            i = buf.find(_R_CLOSE)
            if i == -1:
                safe, state.carry = _split_safe(buf, _R_CLOSE)
                if safe:
                    events.append({"type": "reasoning", "content": safe})
                return events
            if buf[:i]:
                events.append({"type": "reasoning", "content": buf[:i]})
            buf = buf[i + len(_R_CLOSE) :]
            state.in_reasoning = False
        else:
            i = buf.find(_R_OPEN)
            if i == -1:
                safe, state.carry = _split_safe(buf, _R_OPEN)
                if safe and forward_tokens:
                    events.append({"type": "token", "content": safe})
                return events
            if buf[:i] and forward_tokens:
                events.append({"type": "token", "content": buf[:i]})
            buf = buf[i + len(_R_OPEN) :]
            state.in_reasoning = True
    return events


def translate_event(
    event: Any,
    state: TraceState,
    *,
    forward_tokens: bool = True,
) -> list[dict]:
    """Translate one Strands stream event into zero or more wire events."""
    if not isinstance(event, dict):
        return []
    events: list[dict] = []

    # Native reasoning tokens (only some models emit these) → reasoning stream.
    if event.get("reasoning") and event.get("reasoningText"):
        events.append({"type": "reasoning", "content": str(event["reasoningText"])})
        return events

    # Tool-use input streaming: register the tool (for action mapping) but emit
    # nothing — the mechanical workflow is intentionally hidden from the learner.
    if event.get("type") == "tool_use_stream":
        current = event.get("current_tool_use") or {}
        tool_id = current.get("toolUseId", "")
        name = current.get("name", "")
        if tool_id and name:
            state.tools.setdefault(tool_id, name)
        return events

    # Completed tool execution → keep the payload as grounding (server-side only)
    # and surface an `action` card for side-effect tools; nothing else reaches the wire.
    if event.get("type") == "tool_result":
        tool_result = event.get("tool_result") or {}
        tool_id = tool_result.get("toolUseId", "")
        name = state.tools.get(tool_id, "tool")
        payload = _tool_result_payload(tool_result)
        state.add_grounding(payload)
        action = action_for_tool(name, payload)
        if action:
            events.append(action)
        return events

    # Model text chunk → split into reasoning vs answer tokens.
    if "data" in event and event.get("data"):
        events.extend(_route_text(state, str(event["data"]), forward_tokens))
        return events

    # Forced stop → error
    if event.get("force_stop"):
        events.append(
            {
                "type": "error",
                "message": "The agent had to stop early — please try again.",
            }
        )
        return events

    return events


def finish_events(state: TraceState) -> list[dict]:
    """Terminal events for a completed stream (flush any held text, emit done)."""
    events: list[dict] = []
    if state.carry:
        kind = "reasoning" if state.in_reasoning else "token"
        events.append({"type": kind, "content": state.carry})
        state.carry = ""
    events.append(
        {
            "type": "done",
            # The chat stream is a single agent turn, so the wire's `steps` count
            # is always 1; the field stays for the frontend's V2Event contract.
            "steps": 1,
            "total_ms": int((time.monotonic() - state.started) * 1000),
        }
    )
    return events
