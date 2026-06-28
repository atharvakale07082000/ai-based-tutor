"""
quiz_gen workflow: resolve (difficulty) → generate → persist.

Non-streaming workflow (runs with ``emit=None``) — demonstrates the framework isn't limited to
timeline flows. Wraps the logic previously inlined in the ``/quiz/generate`` endpoint; behaviour and
the returned quiz are unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.agents.workflow.base import Task
from app.agents.workflow.planner import register_workflow
from app.agents.workflow.registry import register

_BLOOM_ORDER = ["remember", "understand", "apply", "analyze", "evaluate", "create"]


@register("quiz.resolve")
async def _resolve(ctx, task):
    """Pick the Bloom level from the learner's ELO, easing it after recent discouragement."""
    from app.db.mongo import col_quizzes
    from app.hf.quiz_questions import bloom_for_elo

    req = ctx.request
    bloom = req.get("bloom_level") or bloom_for_elo(req.get("elo", 500.0))
    if not req.get("bloom_level"):
        recent = (
            await col_quizzes()
            .find({"learner_id": req["learner_id"]}, {"sentiment_mood": 1})
            .sort("started_at", -1)
            .to_list(length=3)
        )
        negative = sum(1 for q in recent if q.get("sentiment_mood") == "negative")
        if negative >= 2:
            idx = _BLOOM_ORDER.index(bloom) if bloom in _BLOOM_ORDER else 2
            if idx > 0:
                bloom = _BLOOM_ORDER[idx - 1]
    return {"bloom_level": bloom}


@register("quiz.generate")
async def _generate(ctx, task):
    """Generate (or retrieve cached) questions for the topic at the resolved Bloom level."""
    from app.hf.quiz_questions import get_or_generate_quiz_questions

    bloom = ctx.result("resolve")["bloom_level"]
    return await get_or_generate_quiz_questions(ctx.request["topic"], bloom, count=5)


@register("quiz.persist")
async def _persist(ctx, task):
    """Insert the quiz session document and return its id + level + questions."""
    from app.db.mongo import col_quizzes

    req = ctx.request
    bloom = ctx.result("resolve")["bloom_level"]
    questions = ctx.result("generate")
    quiz_id = str(uuid.uuid4())
    await col_quizzes().insert_one(
        {
            "id": quiz_id,
            "learner_id": req["learner_id"],
            "topic": req["topic"],
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


register_workflow(
    "quiz_gen",
    [
        Task("resolve", "Setting the difficulty", "quiz.resolve"),
        Task("generate", "Generating questions", "quiz.generate"),
        Task("persist", "Saving your quiz", "quiz.persist"),
    ],
)
