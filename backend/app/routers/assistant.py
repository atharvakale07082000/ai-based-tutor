"""Agentic RAG Assistant — streaming SSE endpoint."""
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.jwt import get_current_user_id
from app.agents.chat_orchestrator import run_assistant

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/chat")
async def chat(
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    async def event_stream():
        try:
            async for event in run_assistant(body.message, body.history, user_id):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'agent': 'error'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
