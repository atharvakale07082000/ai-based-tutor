"""
Agent Tool Registry.

Each entry is an async callable that a LangGraph agent node can invoke to delegate
specialized work to another agent.  Agents are purposefully thin wrappers — they
call a specific HF capability, add tracing, and return a typed dict so callers
can use the result without knowing which model/provider was used.

Usage inside an agent node:
    from app.agents.tools import call_tool
    result = await call_tool("classify_topic", text="learn python")
    domain = result["labels"][0]
"""

from __future__ import annotations

from typing import Any

import structlog

from app.tracing import get_tracer

log = structlog.get_logger()


# ── Individual tool implementations ──────────────────────────────────────────


async def _tool_classify_topic(text: str, labels: list[str] | None = None) -> dict:
    """Delegate to topic-classifier HF agent."""
    from app.hf.topic_classifier import classify_topic

    return await classify_topic(text, labels)


async def _tool_analyze_sentiment(text: str) -> dict:
    """Delegate to sentiment-analysis HF agent."""
    from app.hf.sentiment import analyze_sentiment

    return await analyze_sentiment(text)


async def _tool_score_difficulty(text: str) -> dict:
    """Delegate to difficulty-scorer HF agent. Returns {'score': float}."""
    from app.hf.difficulty_scorer import score_difficulty

    score = await score_difficulty(text)
    return {"score": score}


async def _tool_generate_quiz(topic: str, bloom_level: str, count: int = 5) -> dict:
    """Delegate to quiz-generator HF agent."""
    from app.hf.quiz_generator import generate_quiz_questions

    questions = await generate_quiz_questions(topic, bloom_level, count)
    return {"questions": questions}


async def _tool_get_embeddings(text: str) -> dict:
    """Delegate to embedding HF agent for semantic similarity tasks."""
    from app.hf.embeddings import get_embeddings

    vector = await get_embeddings(text)
    return {"embedding": vector}


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, Any] = {
    "classify_topic": _tool_classify_topic,
    "analyze_sentiment": _tool_analyze_sentiment,
    "score_difficulty": _tool_score_difficulty,
    "generate_quiz": _tool_generate_quiz,
    "get_embeddings": _tool_get_embeddings,
}


async def call_tool(name: str, **kwargs) -> dict:
    """
    Call a registered agent tool by name with keyword arguments.
    Automatically traces the call via Langfuse.
    Raises ValueError for unknown tools; propagates tool errors.
    """
    if name not in _REGISTRY:
        raise ValueError(f"Unknown tool: {name!r}. Available: {list(_REGISTRY)}")

    tracer = get_tracer()
    with tracer.trace(f"tool:{name}", input={"tool": name, **kwargs}) as span:
        log.info("agent_tool_call", tool=name, kwargs=list(kwargs))
        try:
            result = await _REGISTRY[name](**kwargs)
            span.update(output=result)
            log.info("agent_tool_done", tool=name)
            return result
        except Exception as exc:
            log.error("agent_tool_error", tool=name, error=str(exc))
            raise


def available_tools() -> list[str]:
    return list(_REGISTRY.keys())
