"""
Quiz question bank — pre-generated questions cached in MongoDB.

Primary flow:
  1. Check quiz_bank collection for existing questions for (topic, bloom_level).
  2. If found and sufficient count, return them immediately.
  3. Otherwise generate fresh via quiz_generator, persist to bank, and return.

This makes the chatbot's "quiz me on X" instant after first generation,
and allows course creation to pre-populate the bank for all topics.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import structlog

log = structlog.get_logger()

BLOOM_LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]

BLOOM_BY_ELO: list[tuple[tuple[int, int], str]] = [
    ((0, 300), "remember"),
    ((300, 450), "understand"),
    ((450, 600), "apply"),
    ((600, 720), "analyze"),
    ((720, 870), "evaluate"),
    ((870, 1001), "create"),
]


def bloom_for_elo(elo: float) -> str:
    for (lo, hi), level in BLOOM_BY_ELO:
        if lo <= elo < hi:
            return level
    return "understand"


async def get_or_generate_quiz_questions(
    topic: str,
    bloom_level: str,
    count: int = 5,
) -> list[dict]:
    """
    Return `count` questions for (topic, bloom_level).
    Checks DB first; generates and caches if missing or insufficient.
    """
    from app.db.mongo import col_quiz_bank

    entry = await col_quiz_bank().find_one({"topic": topic, "bloom_level": bloom_level}, {"_id": 0, "questions": 1})
    cached = (entry or {}).get("questions", [])
    if len(cached) >= count:
        # Shuffle so repeated requests feel varied
        sample = random.sample(cached, count)
        log.info("quiz_bank_hit", topic=topic, bloom_level=bloom_level, count=count)
        return sample

    # Generate fresh
    from app.hf.quiz_generator import generate_quiz_questions

    log.info("quiz_bank_miss_generating", topic=topic, bloom_level=bloom_level)
    questions = await generate_quiz_questions(topic, bloom_level, count=max(count, 10))

    if questions:
        merged = list({q["id"]: q for q in (cached + questions)}.values())

        await col_quiz_bank().update_one(
            {"topic": topic, "bloom_level": bloom_level},
            {
                "$set": {
                    "questions": merged,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
        return questions[:count]

    return cached[:count]


async def pregenerate_topic_questions(topic: str, elo: float = 500.0) -> None:
    """
    Fire-and-forget: pre-populate the quiz bank for a topic at its appropriate
    Bloom level.  Called after course creation so first quiz is instant.
    """
    bloom = bloom_for_elo(elo)
    try:
        await get_or_generate_quiz_questions(topic, bloom, count=10)
        log.info("quiz_bank_pregenerated", topic=topic, bloom=bloom)
    except Exception as e:
        log.warning("quiz_bank_pregenerate_error", topic=topic, error=str(e))
