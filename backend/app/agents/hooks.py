"""
Strands lifecycle hooks shared by every agent built in ``handler.py``.

``GuardrailHook`` mirrors the old belt-and-suspenders posture: the chat router
still runs ``check_input`` on the raw query before any LLM call (the primary
gate); this hook additionally screens every tool call's string arguments so a
prompt-injection payload smuggled into tool args is cancelled mid-loop.
"""

from __future__ import annotations

import structlog
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from app.guardrails import check_input

log = structlog.get_logger()

_BLOCK_MESSAGE = (
    "Blocked by safety guardrail: the arguments looked like an attempt to "
    "override instructions. Rephrase the request as a learning question."
)


class GuardrailHook(HookProvider):
    """Cancel tool calls whose string arguments trip the input guardrail."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._screen_tool_args)

    def _screen_tool_args(self, event: BeforeToolCallEvent) -> None:
        tool_input = event.tool_use.get("input") or {}
        for value in tool_input.values():
            if not isinstance(value, str) or len(value) < 8:
                continue
            guard = check_input(value, context="tool_args")
            if not guard.passed and guard.reason.startswith("blocked_pattern"):
                log.warning(
                    "guardrail_tool_cancelled",
                    tool=event.tool_use.get("name"),
                    reason=guard.reason,
                )
                event.cancel_tool = _BLOCK_MESSAGE
                return
