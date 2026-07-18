"""
Translate Strands ``stream_async`` events into the SSE wire contract the
frontend already speaks (see AtelierV2Page's ``V2Event`` union):

    {"type": "thought",     "step": n, "content": str}
    {"type": "tool_call",   "step": n, "name": str, "args": dict}
    {"type": "tool_result", "step": n, "name": str, "result": Any, "latency_ms": int}
    {"type": "token",       "content": str}
    {"type": "action",      "kind": str, "payload": dict}
    {"type": "done",        "steps": n, "total_ms": int}
    {"type": "error",       "message": str}

One ``TraceState`` instance tracks step numbering and in-flight tool calls for a
single agent stream. ``translate_event`` is used for both the orchestrator's own
events and (with ``forward_tokens=False``) a specialist's events replayed through
``tool_stream`` — specialists surface their trace live but only the orchestrator
streams answer tokens, so the learner hears a single voice.
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


@dataclass
class _ToolCall:
    name: str
    input_buffer: str = ""
    started: float = field(default_factory=time.monotonic)
    call_emitted: bool = False


@dataclass
class TraceState:
    """Mutable per-stream trace bookkeeping."""

    step: int = 0
    started: float = field(default_factory=time.monotonic)
    thought_buffer: str = ""
    tools: dict[str, _ToolCall] = field(default_factory=dict)

    def next_step(self) -> int:
        self.step += 1
        return self.step


def _parse_args(raw: str) -> dict | None:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        return None


def _tool_result_payload(tool_result: dict) -> Any:
    """Unwrap a Strands ToolResult content list into the old payload shape."""
    content = tool_result.get("content") or []
    parts: list[Any] = []
    for block in content:
        if "json" in block:
            parts.append(block["json"])
        elif "text" in block:
            text = block["text"]
            # Tool adapters return dicts, which strands stringifies; recover them
            # so the frontend's ToolCallCard renders structured results.
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


def _flush_thought(state: TraceState, events: list[dict]) -> None:
    if state.thought_buffer.strip():
        events.append(
            {
                "type": "thought",
                "step": state.next_step(),
                "content": state.thought_buffer.strip(),
            }
        )
    state.thought_buffer = ""


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

    # Reasoning text (only some models emit it) → buffered thought
    if event.get("reasoning") and event.get("reasoningText"):
        state.thought_buffer += str(event["reasoningText"])
        return events

    # Streaming tool-use input: emit tool_call as soon as args parse cleanly
    if event.get("type") == "tool_use_stream":
        current = event.get("current_tool_use") or {}
        tool_id = current.get("toolUseId", "")
        name = current.get("name", "")
        if not tool_id or not name:
            return events
        call = state.tools.get(tool_id)
        if call is None:
            _flush_thought(state, events)
            call = _ToolCall(name=name)
            state.tools[tool_id] = call
        raw_input = current.get("input", "")
        call.input_buffer = (
            raw_input if isinstance(raw_input, str) else json.dumps(raw_input)
        )
        if not call.call_emitted:
            args = _parse_args(call.input_buffer)
            if args is not None:
                call.call_emitted = True
                events.append(
                    {
                        "type": "tool_call",
                        "step": state.next_step(),
                        "name": call.name,
                        "args": args,
                    }
                )
        return events

    # Completed tool execution → tool_result (+ action for side-effect tools)
    if event.get("type") == "tool_result":
        tool_result = event.get("tool_result") or {}
        tool_id = tool_result.get("toolUseId", "")
        call = state.tools.get(tool_id)
        name = call.name if call else "tool"
        if call and not call.call_emitted:
            call.call_emitted = True
            events.append(
                {
                    "type": "tool_call",
                    "step": state.next_step(),
                    "name": name,
                    "args": _parse_args(call.input_buffer) or {},
                }
            )
        payload = _tool_result_payload(tool_result)
        latency_ms = int((time.monotonic() - call.started) * 1000) if call else 0
        events.append(
            {
                "type": "tool_result",
                "step": state.step,
                "name": name,
                "result": payload,
                "latency_ms": latency_ms,
            }
        )
        action = action_for_tool(name, payload)
        if action:
            events.append(action)
        return events

    # Model text chunk → token (orchestrator only)
    if "data" in event and event.get("data"):
        if forward_tokens:
            events.append({"type": "token", "content": str(event["data"])})
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
    """Terminal events for a completed stream (flush thoughts, emit done)."""
    events: list[dict] = []
    _flush_thought(state, events)
    events.append(
        {
            "type": "done",
            "steps": max(state.step, 1),
            "total_ms": int((time.monotonic() - state.started) * 1000),
        }
    )
    return events
