"""
Master Tool Registry — public entry point.

Import this module to get the fully-populated `tool_registry` singleton:

    from app.tools import tool_registry
    result = await tool_registry.call("classify_topic", {"text": "learn python"})
    descriptions = tool_registry.describe_tools(["classify_topic", "calculate_elo"])

All 13 tools are registered here in deterministic order:
  6 HF tools → 5 DB tools → 2 logic tools
"""
from __future__ import annotations

from app.tools.registry import ToolRegistry
from app.tools.schemas import Tool, ToolResult  # re-export for convenience

# ── 1. Create singleton ───────────────────────────────────────────────────────
tool_registry = ToolRegistry()

# ── 2. Register HF tools ─────────────────────────────────────────────────────
from app.tools.implementations.hf_tools import TOOLS as _HF_TOOLS
for _tool in _HF_TOOLS:
    tool_registry.register(_tool)

# ── 3. Register DB tools ─────────────────────────────────────────────────────
from app.tools.implementations.db_tools import TOOLS as _DB_TOOLS
for _tool in _DB_TOOLS:
    tool_registry.register(_tool)

# ── 4. Register logic tools ───────────────────────────────────────────────────
from app.tools.implementations.logic_tools import TOOLS as _LOGIC_TOOLS
for _tool in _LOGIC_TOOLS:
    tool_registry.register(_tool)

__all__ = ["tool_registry", "Tool", "ToolResult"]
