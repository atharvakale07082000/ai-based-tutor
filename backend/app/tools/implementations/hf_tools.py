"""
HuggingFace tool implementations.

All handlers are async and delegate to existing app.hf.* modules — no inference
logic is re-implemented here.  The `generate_explanation` tool is the one
exception: it calls chat_completion directly because no single-shot (non-streaming)
explanation wrapper exists yet.
"""
from __future__ import annotations

import asyncio
import structlog

from app.tools.schemas import Tool

log = structlog.get_logger()


# ── Handlers ──────────────────────────────────────────────────────────────────

async def _classify_topic(text: str, labels: list[str] | None = None) -> dict:
    from app.hf.topic_classifier import classify_topic
    return await classify_topic(text, candidate_labels=labels)


async def _analyze_sentiment(text: str) -> dict:
    from app.hf.sentiment import analyze_sentiment
    return await analyze_sentiment(text)


async def _score_difficulty(text: str) -> dict:
    from app.hf.difficulty_scorer import score_difficulty
    score = await score_difficulty(text)
    return {"score": score}


async def _generate_quiz(topic: str, bloom_level: str, count: int = 5) -> dict:
    from app.hf.quiz_generator import generate_quiz_questions
    questions = await generate_quiz_questions(topic, bloom_level, count)
    return {"questions": questions}


async def _get_embeddings(text: str) -> dict:
    from app.hf.embeddings import get_embeddings
    vector = await get_embeddings(text)
    return {"embedding": vector}


async def _generate_explanation(
    topic: str,
    question: str,
    bloom_level: str = "understand",
) -> dict:
    """Non-streaming single-shot explanation via DOUBT_SOLVER model."""
    from app.hf.client import get_hf_client
    from app.hf.models import HF_MODELS

    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]

    system_prompt = "You are a tutor. Explain clearly and concisely."
    user_message = f"Topic: {topic}\n\nQuestion: {question}"

    result = await asyncio.to_thread(
        client.chat_completion,
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=512,
        temperature=0.7,
        stream=False,
    )

    explanation = result.choices[0].message.content or ""
    log.info("generate_explanation_done", topic=topic, chars=len(explanation))
    return {"explanation": explanation}


# ── Tool descriptors ──────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="classify_topic",
        description="Classify learner text into learning domains using zero-shot classification",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "text to classify",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "optional candidate labels",
                    "default": None,
                },
            },
            "required": ["text"],
        },
        handler=_classify_topic,
        category="hf",
        timeout_s=15.0,
    ),
    Tool(
        name="analyze_sentiment",
        description="Analyze emotional tone of learner reflection text (POSITIVE/NEGATIVE/NEUTRAL)",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "reflection or feedback text",
                },
            },
            "required": ["text"],
        },
        handler=_analyze_sentiment,
        category="hf",
        timeout_s=10.0,
    ),
    Tool(
        name="score_difficulty",
        description="Score the difficulty of a topic or content piece from 0.0 (easy) to 1.0 (hard)",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "topic name or content to score",
                },
            },
            "required": ["text"],
        },
        handler=_score_difficulty,
        category="hf",
        timeout_s=15.0,
    ),
    Tool(
        name="generate_quiz",
        description="Generate Bloom-calibrated quiz questions for a topic",
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "bloom_level": {
                    "type": "string",
                    "enum": ["remember", "understand", "apply", "analyze", "evaluate", "create"],
                },
                "count": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["topic", "bloom_level"],
        },
        handler=_generate_quiz,
        category="hf",
        timeout_s=60.0,
    ),
    Tool(
        name="get_embeddings",
        description="Get semantic embedding vector for text (useful for similarity search)",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        },
        handler=_get_embeddings,
        category="hf",
        timeout_s=15.0,
    ),
    Tool(
        name="generate_explanation",
        description="Generate a single-shot explanation for a concept or question (not streaming)",
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "question": {"type": "string"},
                "bloom_level": {
                    "type": "string",
                    "default": "understand",
                },
            },
            "required": ["topic", "question"],
        },
        handler=_generate_explanation,
        category="hf",
        timeout_s=30.0,
    ),
]
