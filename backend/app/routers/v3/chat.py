"""POST /api/v3/chat — DeepAgent SSE endpoint with CoT, middleware, and structured outputs."""

from __future__ import annotations

import json
import time
import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from structlog.contextvars import bind_contextvars

from app.agents_v3.deep_agent import create_deep_agent
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners

router = APIRouter()
log = structlog.get_logger()
limiter = Limiter(key_func=get_remote_address)


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default=[], max_length=20)
    context: dict = {}


@router.post("/chat")
@limiter.limit("60/minute")
async def v3_chat(
    request: Request,
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    DeepAgent SSE endpoint.

    1. Loads learner context from MongoDB.
    2. Runs the LangGraph DeepAgent (orchestrator → middleware → subagent → synthesizer).
    3. Streams typed events: routing / cot_step / tool_call / tool_result / token / action / done.

    v3 events superset v2: existing clients that ignore unknown event types are unaffected.
    """
    stripped = body.message.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="Message cannot be blank.")

    session_id = request.headers.get("X-Session-Id") or uuid.uuid4().hex
    correlation_id = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex

    bind_contextvars(session_id=session_id, user_id=user_id, agent="v3_chat")

    async def event_stream():
        """Yield typed SSE frames from the DeepAgent: routing/cot_step/token/done; log latency."""
        start = time.perf_counter()
        had_error = False

        try:
            PROJ = {"_id": 0}
            learner = await col_learners().find_one({"user_id": user_id}, PROJ) or {}
            context = {
                "learner_id": learner.get("id", user_id),
                "current_topic": body.context.get("current_topic", ""),
                "proficiency": learner.get("topic_proficiency_map") or {},
                "history": [m.model_dump() for m in body.history[-6:]],
                **body.context,
            }

            agent = create_deep_agent()

            async for event in agent.astream(stripped, context):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            had_error = True
            log.error(
                "v3_chat_error",
                error=str(e)[:500],
                session_id=session_id,
                user_id=user_id,
            )
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong on my end — send your question again and I will be right back.'})}\n\n"

        finally:
            latency_ms = round((time.perf_counter() - start) * 1000)
            log.info(
                "v3_chat_done",
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
