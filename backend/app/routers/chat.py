"""POST /api/v1/chat — agentic SSE chat endpoint (the single chat implementation)."""

from __future__ import annotations

import time
import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from structlog.contextvars import bind_contextvars

from app.agents.handler import handler
from app.agents.learner_context import LearnerContext
from app.agents.steps import StepTimeline
from app.agents.stream_adapter import TraceState
from app.auth.jwt import get_current_user_id
from app.db.mongo import PROJ, col_learners
from app.guardrails import check_input
from app.observability import observation, trace_attributes
from app.sse import SSE_DONE, sse_frame, sse_stream_response

router = APIRouter()
log = structlog.get_logger()


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    # No length cap: prior turns include the assistant's own (often long) answers, and capping
    # them here is what broke multi-turn chat with a 422. Only the last few turns are kept anyway.
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default=[], max_length=20)
    context: dict = {}


@router.post("/chat")
async def v2_chat(
    body: ChatRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """
    Agentic SSE endpoint.

    1. Loads learner context from MongoDB.
    2. Hands off to the Strands agent handler, which LLM-routes the query to one
       or more specialists (agents-as-orchestrator) and streams their trace.
    3. Streams structured agent events as Server-Sent Events.

    Error events sent to the client use generic messages; full details
    are in server-side structured logs (never exposed to the caller).
    """
    stripped = body.message.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="Message cannot be blank.")

    session_id = request.headers.get("X-Session-Id") or uuid.uuid4().hex
    correlation_id = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex

    bind_contextvars(session_id=session_id, user_id=user_id, agent="v2_chat")

    async def event_stream():
        """Yield SSE frames: routing → agent events → [DONE]; log latency on exit."""
        start = time.perf_counter()
        had_error = False
        agent_name = "assistant"
        answer_text = ""

        # One trace per chat turn, tied into a conversation by session_id — the per-turn
        # scope Langfuse recommends, because a conversation has no known end. The root
        # input is the learner's message alone: the handler's context blob (profile,
        # proficiency map, history) would bury it in the trace list, and it is already
        # captured on the child agent spans.
        with (
            observation(
                "chat-turn",
                input=stripped,
                metadata={"correlation_id": correlation_id},
            ) as root,
            trace_attributes(
                user_id=user_id,
                session_id=session_id,
                tags=["chat"],
                trace_name="chat-turn",
            ),
        ):
            try:
                # Input guardrail: block prompt-injection attempts before any LLM call.
                # (v1 and v3 already guard; this closes the gap on the v2 path.)
                guard = check_input(stripped, context="v2_chat")
                if not guard.passed and guard.reason.startswith("blocked_pattern"):
                    log.warning(
                        "v2_chat_guardrail_blocked",
                        reason=guard.reason,
                        session_id=session_id,
                    )
                    yield sse_frame(
                        {
                            "type": "guardrail",
                            "message": "That request looks like an attempt to override my instructions — I can only help with learning.",
                        }
                    )
                    return

                learner_doc = (
                    await col_learners().find_one({"user_id": user_id}, PROJ) or {}
                )
                # The learner's profile now reaches the agent as a briefing in the
                # SYSTEM prompt (bounded, and phrased as instructions), instead of a raw
                # JSON dump of the whole proficiency map in the user turn.
                learner = LearnerContext.from_doc(
                    learner_doc,
                    current_topic=str(body.context.get("current_topic") or ""),
                )
                context = {
                    "learner_id": learner_doc.get("id", ""),
                    "current_topic": body.context.get("current_topic", ""),
                    "history": [m.model_dump() for m in body.history[-6:]],
                    **body.context,
                    # Stable chat-thread id (client sends its thread id as X-Session-Id) enables
                    # persistent per-thread memory; absent → stateless turn. Header wins over body.
                    "thread_id": request.headers.get("X-Session-Id", ""),
                }

                # Live step timeline: routing done → working → composing answer.
                tl = StepTimeline("chat")
                answered = False
                # The handler's TraceState collects tool results as `grounding` while it
                # translates the stream. Those never reach the wire (the mechanical tool
                # workflow stays hidden); they're the retrieval context the faithfulness
                # metric grades the answer against below.
                trace = TraceState()

                # The handler performs the always-on LLM routing decision itself and
                # emits it as the first `routing` event; we frame the StepTimeline around
                # the events it yields (routing → reasoning/token/action → done).
                async for event in handler.run_chat(
                    stripped, context, trace=trace, learner=learner
                ):
                    etype = event.get("type")
                    if etype == "routing":
                        agent_name = event.get("agent", "assistant")
                        log.info(
                            "chat_routed",
                            agent=agent_name,
                            reason=event.get("reason"),
                            session_id=session_id,
                        )
                        # Which specialist handled the turn is the main dimension you
                        # filter a chat dashboard by, and it is only known after routing
                        # — so metadata, not a tag (tags are fixed at creation time).
                        root.update(
                            metadata={
                                "routed_agent": agent_name,
                                "routing_reason": event.get("reason"),
                            }
                        )
                        yield sse_frame(event)
                        yield sse_frame(tl.done("route"))
                        yield sse_frame(tl.start("work"))
                        continue
                    if etype == "token":
                        answer_text += str(event.get("content", ""))
                        if not answered:
                            answered = True
                            yield sse_frame(tl.done("work"))
                            yield sse_frame(tl.start("answer"))
                    elif etype == "done":
                        # Close the final step *before* forwarding 'done' so the terminal
                        # event of the stream stays 'done' (clients rely on this).
                        yield sse_frame(tl.done("answer" if answered else "work"))
                    yield sse_frame(event)

                # The assistant reply is the trace output — what a reviewer reads first
                # in the trace list and what trace-level evaluators grade.
                #
                # `grounding` (the tool payloads the answer was built from) rides along in
                # metadata because Langfuse observation-level evaluators see ONLY the
                # observation they match — they do not load child spans. Without it here,
                # a faithfulness judge on `chat-turn` would have nothing to check the
                # answer against. It still never reaches the wire.
                root.update(
                    output=answer_text,
                    metadata={"grounding": trace.grounding or None},
                )

                # Online eval sampling (random gate, fire-and-forget — never blocks the response).
                try:
                    from app.evals.deepeval_metrics import maybe_eval_chat

                    turns = [
                        {"role": m.get("role"), "content": m.get("content")}
                        for m in context.get("history", [])
                        if isinstance(m, dict)
                    ]
                    turns.append({"role": "user", "content": stripped})
                    turns.append({"role": "assistant", "content": answer_text})
                    maybe_eval_chat(
                        agent_name,
                        stripped,
                        answer_text,
                        turns,
                        retrieval_context=trace.grounding or None,
                        learner_id=context.get("learner_id", ""),
                        session_id=session_id,
                    )
                except Exception as e:  # noqa: BLE001 - sampling must never affect the response
                    log.warning("v2_eval_sample_failed", error=str(e)[:200])

            except Exception as e:
                had_error = True
                # Log full details server-side; send a generic message to the client.
                log.error(
                    "v2_chat_error",
                    error=str(e)[:500],
                    agent=agent_name,
                    session_id=session_id,
                    user_id=user_id,
                )
                root.update(
                    level="ERROR",
                    status_message=str(e)[:500],
                    output=answer_text or None,
                )
                yield sse_frame(
                    {
                        "type": "error",
                        "message": "Something went wrong on my end — send your question again",
                    }
                )

            finally:
                latency_ms = round((time.perf_counter() - start) * 1000)
                log.info(
                    "v2_chat_done",
                    agent=agent_name,
                    session_id=session_id,
                    latency_ms=latency_ms,
                    had_error=had_error,
                )
                yield SSE_DONE

    return sse_stream_response(
        event_stream(),
        headers={"X-Session-Id": session_id, "X-Correlation-Id": correlation_id},
    )
