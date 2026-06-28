"""POST /api/v2/chat — agentic SSE endpoint."""

from __future__ import annotations

import json
import time
import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from structlog.contextvars import bind_contextvars

from app.agents.routing import AGENT_DISPLAY_NAMES
from app.agents.steps import StepTimeline
from app.agents_v2.assistant_agent import AssistantAgent
from app.agents_v2.curriculum_agent import CurriculumAgent
from app.agents_v2.doubt_agent import DoubtAgent
from app.agents_v2.progress_agent import ProgressAgent
from app.agents_v2.quiz_agent import QuizAgent
from app.agents_v2.router import AgentRouter
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners
from app.guardrails import check_input

router = APIRouter()
log = structlog.get_logger()

_agent_router = AgentRouter()
_AGENTS: dict[str, object] = {
    "curriculum": CurriculumAgent(),
    "quiz": QuizAgent(),
    "progress": ProgressAgent(),
    "doubt": DoubtAgent(),
    "assistant": AssistantAgent(),
}


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


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
    2. Routes the query via AgentRouter (keyword-first, LLM fallback).
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

        try:
            # Input guardrail: block prompt-injection attempts before any LLM call.
            # (v1 and v3 already guard; this closes the gap on the v2 path.)
            guard = check_input(stripped, context="v2_chat")
            if not guard.passed and guard.reason.startswith("blocked_pattern"):
                log.warning("v2_chat_guardrail_blocked", reason=guard.reason, session_id=session_id)
                yield f"data: {json.dumps({'type': 'guardrail', 'message': 'That request looks like an attempt to override my instructions — I can only help with learning.'})}\n\n"
                return

            PROJ = {"_id": 0}
            learner = await col_learners().find_one({"user_id": user_id}, PROJ) or {}
            context = {
                "learner_id": learner.get("id", ""),
                "current_topic": body.context.get("current_topic", ""),
                "proficiency": learner.get("topic_proficiency_map") or {},
                "history": [m.model_dump() for m in body.history[-6:]],
                **body.context,
            }

            agent_name, reason = await _agent_router.route(stripped, context)
            display_name = AGENT_DISPLAY_NAMES.get(agent_name, "AI Tutor")
            log.info("v2_chat_routed", agent=agent_name, reason=reason, session_id=session_id)
            yield f"data: {json.dumps({'type': 'routing', 'agent': agent_name, 'display_name': display_name, 'reason': reason})}\n\n"

            # Live step timeline: routing done → working (+ one step per tool call) → composing answer.
            tl = StepTimeline("chat")
            yield f"data: {json.dumps(tl.done('route'))}\n\n"
            yield f"data: {json.dumps(tl.start('work'))}\n\n"
            answered = False
            answer_text = ""  # accumulated for online eval sampling
            tool_grounding: list[str] = []  # tool results = the retrieval context for faithfulness

            agent = _AGENTS.get(agent_name, _AGENTS["assistant"])
            async for event in agent.run(stripped, context):
                etype = event.get("type")
                if etype == "tool_call":
                    sid = f"tool:{event.get('name', 'tool')}"
                    label = f"Looking up {str(event.get('name', 'information')).replace('_', ' ')}"
                    yield f"data: {json.dumps(tl.start(sid, label))}\n\n"
                elif etype == "tool_result":
                    sid = f"tool:{event.get('name', 'tool')}"
                    tool_grounding.append(str(event.get("result", ""))[:1500])
                    yield f"data: {json.dumps(tl.done(sid))}\n\n"
                elif etype == "token":
                    answer_text += str(event.get("content", ""))
                    if not answered:
                        answered = True
                        yield f"data: {json.dumps(tl.done('work'))}\n\n"
                        yield f"data: {json.dumps(tl.start('answer'))}\n\n"
                elif etype == "done":
                    # Close the final step *before* forwarding 'done' so the terminal
                    # event of the stream stays 'done' (clients rely on this).
                    yield f"data: {json.dumps(tl.done('answer' if answered else 'work'))}\n\n"
                yield f"data: {json.dumps(event)}\n\n"

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
                    retrieval_context=tool_grounding or None,
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
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong on my end — send your question again and I will be right back.'})}\n\n"

        finally:
            latency_ms = round((time.perf_counter() - start) * 1000)
            log.info(
                "v2_chat_done",
                agent=agent_name,
                session_id=session_id,
                latency_ms=latency_ms,
                had_error=had_error,
            )
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "X-Session-Id": session_id,
            "X-Correlation-Id": correlation_id,
        },
    )
