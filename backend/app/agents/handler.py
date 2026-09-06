"""
AgentHandler — the single entry point every chat initiation flows through.

``handler`` is a module-level singleton. ``run_chat`` performs the always-on LLM
routing decision, then streams the chosen specialist(s), translating Strands
events into the frontend SSE wire contract.

Design note on state: the shared NIM *model* is cached (connection pool, one
asyncio loop under FastAPI), but specialist/router *Agent* instances are built
per request — Strands Agents accumulate conversation history on the instance, so
reusing one across requests would leak one learner's turns into another's.

Design note on the queue: the model layer can stall on the NIM RPM bucket *while*
we're awaiting the next agent event, so there'd be no point at which to tell the
learner. Both the agent stream and the throttle callback therefore feed one queue
that ``run_chat`` consumes, which lets a wait surface as a ``reasoning`` note in
real time instead of as a silent multi-second gap.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from typing import Any, AsyncIterator, Awaitable, Callable

import structlog

from app.agents import orchestrator
from app.agents.learner_context import LearnerContext
from app.agents.model import throttle_notices
from app.agents.prompt_utils import history_messages
from app.agents.routing_meta import display_name
from app.agents.specialists import build_specialist
from app.agents.stream_adapter import TraceState, finish_events, translate_event

log = structlog.get_logger()


# Learner-facing note for an upstream capacity wait. First person, calm, and free of
# infrastructure jargon — it rides the existing thinking channel, not a new event type.
THROTTLE_NOTICE = "Give me a moment — I'm waiting on capacity."

# Queue item kinds: ("event", strands_event) | ("result", value) | ("error", exc)
# | ("throttled", wait_s) | ("end", None)
_QueueItem = tuple[str, Any]


def _throttle_sink_for(queue: asyncio.Queue) -> Callable[[float], None]:
    """Build the model-layer throttle callback that feeds this turn's queue."""

    def _sink(wait_s: float) -> None:
        queue.put_nowait(("throttled", wait_s))

    return _sink


async def _pump_stream(stream: AsyncIterator, queue: asyncio.Queue) -> None:
    """Drain an agent stream into ``queue`` (so throttle notices can interleave)."""
    try:
        async for event in stream:
            await queue.put(("event", event))
    except Exception as e:  # noqa: BLE001 - re-raised on the consumer side
        await queue.put(("error", e))
    finally:
        await queue.put(("end", None))


async def _pump_call(awaitable: Awaitable, queue: asyncio.Queue) -> None:
    """Run a one-shot agent call, putting its result (or failure) on ``queue``."""
    try:
        await queue.put(("result", await awaitable))
    except Exception as e:  # noqa: BLE001 - re-raised on the consumer side
        await queue.put(("error", e))
    finally:
        await queue.put(("end", None))


async def _consume(
    queue: asyncio.Queue, pump: Awaitable[None]
) -> AsyncIterator[_QueueItem]:
    """Yield queued items until the pump signals it's done; always clean the task up."""
    task = asyncio.create_task(pump)
    try:
        while True:
            kind, item = await queue.get()
            if kind == "end":
                return
            yield kind, item
    finally:
        if not task.done():
            task.cancel()


def _build_prompt(query: str, context: dict, *, include_history: bool = True) -> str:
    """Compose recent history + the learner's message into one user turn.

    When the thread has persistent memory (a Strands session), ``include_history`` is
    False — the session already carries prior turns, so re-injecting them here would
    duplicate context.

    This used to lead with ``Learner context: {json blob}``. That blob carried the whole
    proficiency map (up to ~108 topics) on every single turn, defeated prefix KV-caching,
    and existed partly so the model could read ``learner_id`` back out of it for tool
    calls. Identity is now bound server-side (``tools.learner_scoped_tools``) and the
    learner briefing lives in the system prompt (``LearnerContext.render``), so the user
    turn is just what the learner actually said.
    """
    parts = []
    if include_history:
        turns = history_messages(context.get("history"))
        if turns:
            convo = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
            parts.append(f"Recent conversation:\n{convo}")
    parts.append(query)
    return "\n\n".join(parts)


class AgentHandler:
    """Singleton coordinator for the chat orchestrator + specialists."""

    async def run_chat(
        self,
        query: str,
        context: dict,
        *,
        trace: TraceState | None = None,
        learner: LearnerContext | None = None,
    ) -> AsyncIterator[dict]:
        """Yield wire-contract events: routing -> specialist trace/tokens -> done.

        ``trace`` lets the caller keep the per-stream ``TraceState`` after the stream
        ends — the chat router uses its ``grounding`` (tool results, never emitted) as
        the retrieval context for the online faithfulness eval.

        ``learner`` is the briefing appended to each specialist's system prompt so the
        answer is pitched at this person. Omitted -> the prompt is what it always was.
        """
        query = (query or "").strip()
        if not query:
            yield {
                "type": "error",
                "message": "Your message was empty — type a question and send it",
            }
            return

        state = trace if trace is not None else TraceState()
        queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
        told_about_wait = False  # one capacity note per turn is enough

        with throttle_notices(_throttle_sink_for(queue)):
            # ── routing decision (one LLM call) ──────────────────────────────────
            router = orchestrator.build_router()
            agents, reason = ["assistant"], "heuristic fallback"
            async with aclosing(
                _consume(queue, _pump_call(orchestrator.route(query, router), queue))
            ) as routing:
                async for kind, item in routing:
                    if kind == "throttled" and not told_about_wait:
                        told_about_wait = True
                        yield {"type": "reasoning", "content": THROTTLE_NOTICE}
                    elif kind == "result":
                        agents, reason = item
                    elif kind == "error":  # route() swallows its own failures
                        log.warning("agent_handler_route_error", error=str(item)[:200])

            primary = agents[0]
            yield {
                "type": "routing",
                "agent": primary,
                "display_name": display_name(primary),
                "reason": reason,
            }

            thread_id = (context.get("thread_id") or "").strip() or None
            prompt = _build_prompt(query, context, include_history=not thread_id)
            transcript = ""

            # ── specialist stream(s) ────────────────────────────────────────────
            try:
                learner_id = (context.get("learner_id") or "").strip() or None
                for idx, key in enumerate(agents):
                    specialist = build_specialist(
                        key,
                        session_id=thread_id,
                        learner_id=learner_id,
                        learner=learner,
                    )
                    step_prompt = prompt
                    if transcript:
                        step_prompt = (
                            f"{prompt}\n\nEarlier specialists produced:\n{transcript}"
                        )
                    answer_chunks: list[str] = []
                    async with aclosing(
                        _consume(
                            queue,
                            _pump_stream(specialist.stream_async(step_prompt), queue),
                        )
                    ) as stream:
                        async for kind, item in stream:
                            if kind == "throttled":
                                if not told_about_wait:
                                    told_about_wait = True
                                    yield {
                                        "type": "reasoning",
                                        "content": THROTTLE_NOTICE,
                                    }
                                continue
                            if kind == "error":
                                raise item
                            for wire in translate_event(
                                item, state, forward_tokens=True
                            ):
                                if wire["type"] == "token":
                                    answer_chunks.append(wire["content"])
                                yield wire
                    if idx < len(agents) - 1:
                        transcript += f"[{key}] {''.join(answer_chunks)}\n"
            except Exception as e:  # noqa: BLE001 - surface a generic error, log details
                log.error("agent_handler_run_error", error=str(e)[:300], agents=agents)
                yield {
                    "type": "error",
                    "message": "Something went wrong on my end — send your question again",
                }
                return

        for wire in finish_events(state):
            yield wire


# The one handler every initiation uses.
handler = AgentHandler()
