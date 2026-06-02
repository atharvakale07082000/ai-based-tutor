"""
Tool schemas for the Master Tool Registry.

Tool        — descriptor: name, description, parameters, handler, category, timeout
ToolResult  — execution result envelope: result or error + timing
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str  # shown verbatim to the LLM in system prompts
    parameters: dict  # JSON Schema object describing args
    handler: Callable  # async callable
    category: str  # "hf" | "db" | "logic"
    timeout_s: float = 30.0


@dataclass
class ToolResult:
    name: str
    args: dict
    result: dict | None
    error: str | None
    latency_ms: int
