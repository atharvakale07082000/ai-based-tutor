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

from app.agents_v2.assistant_agent import AssistantAgent
from app.agents_v2.curriculum_agent import CurriculumAgent
from app.agents_v2.doubt_agent import DoubtAgent
from app.agents_v2.progress_agent import ProgressAgent
from app.agents_v2.quiz_agent import QuizAgent
from app.agents_v2.router import AgentRouter
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners

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
        start = time.perf_counter()
        had_error = False
        agent_name = "assistant"

        try:
            PROJ = {"_id": 0}
            learner = await col_learners().find_one({"user_id": user_id}, PROJ) or {}
            context = {
                "learner_id": learner.get("id", ""),
                "current_topic": body.context.get("current_topic", ""),
                "proficiency": learner.get("topic_proficiency_map") or {},
                "history": body.history[-6:],
                **body.context,
            }

            agent_name, reason = await _agent_router.route(stripped, context)
            log.info("v2_chat_routed", agent=agent_name, reason=reason, session_id=session_id)
            yield f"data: {json.dumps({'type': 'routing', 'agent': agent_name, 'reason': reason})}\n\n"

            agent = _AGENTS.get(agent_name, _AGENTS["assistant"])
            async for event in agent.run(stripped, context):
                yield f"data: {json.dumps(event)}\n\n"

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
            yield f"data: {json.dumps({'type': 'error', 'message': 'An internal error occurred. Please try again.'})}\n\n"

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
