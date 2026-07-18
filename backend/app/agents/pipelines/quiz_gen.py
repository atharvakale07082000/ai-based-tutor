"""quiz_gen pipeline: resolve (bloom + mood-ease) -> generate -> persist.

Non-streaming (the /quiz/generate endpoint runs it headless). Behavior and the
returned quiz shape are unchanged from the old ``quiz_gen`` workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

_BLOOM_ORDER = ["remember", "understand", "apply", "analyze", "evaluate", "create"]


async def _resolve_bloom(request: dict) -> str:
    from app.db.mongo import col_quizzes
    from app.hf.quiz_questions import bloom_for_elo

    bloom = request.get("bloom_level") or bloom_for_elo(request.get("elo", 500.0))
    if not request.get("bloom_level"):
        recent = (
            await col_quizzes()
            .find({"learner_id": request["learner_id"]}, {"sentiment_mood": 1})
            .sort("started_at", -1)
            .to_list(length=3)
        )
        negative = sum(1 for q in recent if q.get("sentiment_mood") == "negative")
        if negative >= 2:
            idx = _BLOOM_ORDER.index(bloom) if bloom in _BLOOM_ORDER else 2
            if idx > 0:
                bloom = _BLOOM_ORDER[idx - 1]
    return bloom


async def run_quiz_gen(request: dict) -> dict:
    """Resolve difficulty, generate/cache questions, persist a quiz session."""
    from app.db.mongo import col_quizzes
    from app.hf.quiz_questions import get_or_generate_quiz_questions

    bloom = await _resolve_bloom(request)
    questions = await get_or_generate_quiz_questions(request["topic"], bloom, count=5)

    quiz_id = str(uuid.uuid4())
    await col_quizzes().insert_one(
        {
            "id": quiz_id,
            "learner_id": request["learner_id"],
            "topic": request["topic"],
            "bloom_level": bloom,
            "questions": questions,
            "answers": [],
            "score": None,
            "weak_topics": [],
            "sentiment_mood": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        }
    )
    return {"quiz_id": quiz_id, "bloom_level": bloom, "questions": questions}
