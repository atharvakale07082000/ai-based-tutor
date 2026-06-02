"""Agentic RAG Assistant — streaming SSE endpoint."""

import json
import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from structlog.contextvars import bind_contextvars

from app.agents.chat_orchestrator import run_assistant
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default=[], max_length=20)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    session_id = request.headers.get("X-Session-Id") or uuid.uuid4().hex
    correlation_id = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
    bind_contextvars(session_id=session_id, user_id=user_id, agent="assistant")

    async def event_stream():
        try:
            async for event in run_assistant(body.message, body.history, user_id, session_id=session_id):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            log.error("assistant_chat_error", error=str(e)[:500], session_id=session_id)
            yield f"data: {json.dumps({'type': 'error', 'message': 'An internal error occurred. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'agent': 'error'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Session-Id": session_id,
            "X-Correlation-Id": correlation_id,
        },
    )
