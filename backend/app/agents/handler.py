"""
AgentHandler — the single entry point every chat initiation flows through.

``handler`` is a module-level singleton. ``run_chat`` performs the always-on LLM
routing decision, then streams the chosen specialist(s), translating Strands
events into the frontend SSE wire contract.

Design note on state: the shared NIM *model* is cached (connection pool, one
asyncio loop under FastAPI), but specialist/router *Agent* instances are built
per request — Strands Agents accumulate conversation history on the instance, so
reusing one across requests would leak one learner's turns into another's.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import structlog

from app.agents import orchestrator
from app.agents.prompt_utils import history_messages
from app.agents.routing_meta import display_name
from app.agents.specialists import build_specialist
from app.agents.stream_adapter import TraceState, finish_events, translate_event

log = structlog.get_logger()


_INTERNAL_CTX_KEYS = {"history", "thread_id"}


def _build_prompt(query: str, context: dict, *, include_history: bool = True) -> str:
    """Compose the learner-context blob + recent history + query into one prompt.

    When the thread has persistent memory (a Strands session), ``include_history`` is
    False — the session already carries prior turns, so re-injecting them here would
    duplicate context.
    """
    ctx = {k: v for k, v in context.items() if k not in _INTERNAL_CTX_KEYS}
    parts = [f"Learner context: {json.dumps(ctx, default=str)}"]
    if include_history:
        turns = history_messages(context.get("history"))
        if turns:
            convo = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
            parts.append(f"Recent conversation:\n{convo}")
    parts.append(f"Current message: {query}")
    return "\n\n".join(parts)


class AgentHandler:
    """Singleton coordinator for the chat orchestrator + specialists."""

    async def run_chat(self, query: str, context: dict) -> AsyncIterator[dict]:
        """Yield wire-contract events: routing -> specialist trace/tokens -> done."""
        query = (query or "").strip()
        if not query:
            yield {"type": "error", "message": "Query cannot be empty."}
            return

        router = orchestrator.build_router()
        agents, reason = await orchestrator.route(query, router)
        primary = agents[0]
        yield {
            "type": "routing",
            "agent": primary,
            "display_name": display_name(primary),
            "reason": reason,
        }

        state = TraceState()
        thread_id = (context.get("thread_id") or "").strip() or None
        prompt = _build_prompt(query, context, include_history=not thread_id)
        transcript = ""

        try:
            for idx, key in enumerate(agents):
                specialist = build_specialist(key, session_id=thread_id)
                step_prompt = prompt
                if transcript:
                    step_prompt = (
                        f"{prompt}\n\nEarlier specialists produced:\n{transcript}"
                    )
                answer_chunks: list[str] = []
                async for event in specialist.stream_async(step_prompt):
                    for wire in translate_event(event, state, forward_tokens=True):
                        if wire["type"] == "token":
                            answer_chunks.append(wire["content"])
                        yield wire
                if idx < len(agents) - 1:
                    transcript += f"[{key}] {''.join(answer_chunks)}\n"
        except Exception as e:  # noqa: BLE001 - surface a generic error, log details
            log.error("agent_handler_run_error", error=str(e)[:300], agents=agents)
            yield {
                "type": "error",
                "message": "Something went wrong on my end — send your question again.",
            }
            return

        for wire in finish_events(state):
            yield wire


# The one handler every initiation uses.
handler = AgentHandler()
