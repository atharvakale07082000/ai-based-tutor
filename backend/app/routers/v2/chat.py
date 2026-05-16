"""POST /api/v2/chat — agentic SSE endpoint."""
from __future__ import annotations

import json
import time

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners
from app.agents_v2.router import AgentRouter
from app.agents_v2.curriculum_agent import CurriculumAgent
from app.agents_v2.quiz_agent import QuizAgent
from app.agents_v2.progress_agent import ProgressAgent
from app.agents_v2.doubt_agent import DoubtAgent
from app.agents_v2.assistant_agent import AssistantAgent

router = APIRouter()
log = structlog.get_logger()

_agent_router = AgentRouter()
_AGENTS: dict[str, object] = {
    "curriculum": CurriculumAgent(),
    "quiz":       QuizAgent(),
    "progress":   ProgressAgent(),
    "doubt":      DoubtAgent(),
    "assistant":  AssistantAgent(),
}


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    context: dict = {}


@router.post("/chat")
async def v2_chat(body: ChatRequest, user_id: str = Depends(get_current_user_id)):
    """
    Agentic SSE endpoint.

    1. Loads learner context from MongoDB.
    2. Routes the query via AgentRouter (keyword-first, LLM fallback).
    3. Streams structured agent events as Server-Sent Events.
    """

    async def event_stream():
        try:
            # Load learner profile
            PROJ = {"_id": 0}
            learner = col_learners().find_one({"user_id": user_id}, PROJ) or {}
            context = {
                "learner_id": learner.get("id", ""),
                "current_topic": body.context.get("current_topic", ""),
                "proficiency": learner.get("topic_proficiency_map") or {},
                "history": body.history[-6:],  # last 6 turns only
                **body.context,
            }

            # Route the query
            agent_name, reason = await _agent_router.route(body.message, context)
            yield f"data: {json.dumps({'type': 'routing', 'agent': agent_name, 'reason': reason})}\n\n"

            # Run the selected agent
            agent = _AGENTS.get(agent_name, _AGENTS["assistant"])
            async for event in agent.run(body.message, context):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            log.error("v2_chat_error", error=str(e), user_id=user_id)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
