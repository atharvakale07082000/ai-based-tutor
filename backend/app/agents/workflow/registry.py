"""
Task-agent registry.

A *task agent* is one unit of work — a thin async wrapper around an existing function/agent/tool
with a single responsibility. Workflows reference task agents by key; the Executor looks them up
here. Keeping the registry free of imports from ``base`` avoids an import cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.agents.workflow.base import TaskAgent

# agent_key -> async task agent
TASK_AGENTS: dict[str, "TaskAgent"] = {}


def register(key: str) -> "Callable[[TaskAgent], TaskAgent]":
    """Decorator: register an async task agent under ``key``.

    Usage::

        @register("course.research")
        async def research(ctx, task):
            ...
    """

    def deco(fn: "TaskAgent") -> "TaskAgent":
        if key in TASK_AGENTS:
            raise ValueError(f"Task agent '{key}' is already registered")
        TASK_AGENTS[key] = fn
        return fn

    return deco
