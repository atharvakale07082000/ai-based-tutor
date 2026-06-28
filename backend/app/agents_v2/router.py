"""
AgentRouter — thin wrapper around the shared two-phase router in
``app.agents.routing`` (keyword match first, LLM fallback).

The routing logic itself lives in one place now; this class only preserves the
v2 call site's ``AgentRouter().route(query, context)`` interface.
"""

from __future__ import annotations

from app.agents import routing


class AgentRouter:
    async def route(self, query: str, context: dict | None = None) -> tuple[str, str]:
        """Return ``(agent_name, reason)`` for the query. ``context`` is currently unused."""
        return await routing.route(query)
