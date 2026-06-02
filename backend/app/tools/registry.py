"""
Master Tool Registry.

ToolRegistry manages registration, lookup, timed execution, and LLM-readable
description of all tools in the system.  A module-level singleton is created
in __init__.py after all implementations are imported.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from app.tools.schemas import Tool, ToolResult

log = structlog.get_logger()


class ToolRegistry:
    """Central registry for all async tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, tool: Tool) -> None:
        """Add a tool to the registry.  Overwrites silently on name collision."""
        self._tools[tool.name] = tool
        log.debug("tool_registered", name=tool.name, category=tool.category)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Tool:
        """Return the Tool for *name*.  Raises KeyError for unknown tools."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name!r}. Available: {list(self._tools)}")
        return self._tools[name]

    def subset(self, names: list[str]) -> list[Tool]:
        """Return tools in the order given by *names*.  Raises KeyError for any unknown."""
        return [self.get(n) for n in names]

    # ── Execution ─────────────────────────────────────────────────────────────

    async def call(self, name: str, args: dict) -> ToolResult:
        """
        Execute a registered tool by name with *args*.

        - Times out after tool.timeout_s seconds.
        - Catches ALL exceptions and stores them in ToolResult.error.
        - Measures wall-clock latency in milliseconds.
        - Logs start / done / error with structlog.
        """
        tool = self.get(name)  # propagates KeyError for unknown tools
        start = time.monotonic()

        log.info("tool_call_start", tool=name, category=tool.category, args=list(args))

        try:
            result = await asyncio.wait_for(
                tool.handler(**args),
                timeout=tool.timeout_s,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            log.info("tool_call_done", tool=name, latency_ms=latency_ms)
            return ToolResult(
                name=name,
                args=args,
                result=result,
                error=None,
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            err = f"Tool '{name}' timed out after {tool.timeout_s}s"
            log.error("tool_call_timeout", tool=name, timeout_s=tool.timeout_s, latency_ms=latency_ms)
            return ToolResult(name=name, args=args, result=None, error=err, latency_ms=latency_ms)

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            err = str(exc)
            log.error("tool_call_error", tool=name, error=err, latency_ms=latency_ms)
            return ToolResult(name=name, args=args, result=None, error=err, latency_ms=latency_ms)

    # ── LLM description ───────────────────────────────────────────────────────

    def describe_tools(self, names: list[str]) -> str:
        """
        Return a plain-text description block for injecting into LLM system prompts.

        Format (one block per tool separated by ---):
            Tool: classify_topic
            Description: Classify learner text into learning domains
            Parameters: {"text": "string - the text to classify", "labels": "list[str] - optional label set"}
            ---
        """
        tools = self.subset(names)
        blocks: list[str] = []
        for tool in tools:
            # Build a simplified human-readable parameter map
            param_summary: dict[str, str] = {}
            props = tool.parameters.get("properties", {})
            for param_name, schema in props.items():
                ptype = schema.get("type", "any")
                # Represent arrays with their item type if available
                if ptype == "array":
                    item_type = schema.get("items", {}).get("type", "any")
                    ptype = f"list[{item_type}]"
                desc = schema.get("description", "")
                default = schema.get("default")
                parts = [ptype]
                if desc:
                    parts.append(desc)
                if default is not None:
                    parts.append(f"default={default!r}")
                param_summary[param_name] = " - ".join(parts)

            block = f"Tool: {tool.name}\nDescription: {tool.description}\nParameters: {param_summary}"
            blocks.append(block)

        return "\n---\n".join(blocks)


# The populated singleton lives in app.tools (app/tools/__init__.py).
# Import it from there, not from this module directly:
#   from app.tools import tool_registry
