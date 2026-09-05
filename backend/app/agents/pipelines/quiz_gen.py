"""quiz_gen pipeline: resolve (bloom + mood-ease) -> generate -> persist.

Non-streaming (the /quiz/generate endpoint runs it headless). Behavior and the
returned quiz shape are unchanged from the old ``quiz_gen`` workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.agents.progress import BLOOM_LEVELS, bloom_for_elo
from app.agents.steps import StepEmit, step_emitter
from app.observability import traced_pipeline


async def _effective_settings(learner_id: str):
    """Org agent settings overlaid with this learner's own. Never fails a quiz."""
    from app.agents.agent_settings import DEFAULTS, resolve
    from app.db.mongo import PROJ, col_app_settings, col_learners

    try:
        org = await col_app_settings().find_one({"_id": "agent_settings"}) or {}
        learner = await col_learners().find_one({"id": learner_id}, PROJ) or {}
        return resolve({k: v for k, v in org.items() if k != "_id"}, learner)
    except Exception:  # noqa: BLE001 - settings are a preference, not a dependency
        return DEFAULTS


async def _resolve_bloom(request: dict) -> str:
    """Proficiency picks the level, recent mood can ease it, the ceiling caps it."""
    from app.db.mongo import col_quizzes

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
            idx = BLOOM_LEVELS.index(bloom) if bloom in BLOOM_LEVELS else 2
            if idx > 0:
                bloom = BLOOM_LEVELS[idx - 1]

    # The difficulty ceiling is the one admin/learner setting with a real consumer:
    # it caps how demanding questions may get, on top of everything above.
    settings = await _effective_settings(request.get("learner_id", ""))
    return settings.cap_bloom(bloom)


async def run_quiz_gen(request: dict, emit: StepEmit = None) -> dict:
    """Resolve difficulty, generate/cache questions, persist a quiz session.

    ``emit`` is accepted for parity with the other pipelines: every caller today runs
    this headless, in which case ``step_emitter`` is a no-op, but a streaming caller
    gets the same capacity-wait narration for free.
    """
    from app.db.mongo import col_quizzes
    from app.hf.quiz_questions import get_or_generate_quiz_questions

    async with (
        traced_pipeline(
            "generate-quiz",
            input={
                "topic": request.get("topic"),
                "bloom_level": request.get("bloom_level"),
                "elo": request.get("elo"),
            },
            user_id=request.get("learner_id"),
            tags=["quiz-gen"],
        ) as root,
        step_emitter(emit),
    ):
        bloom = await _resolve_bloom(request)
        questions = await get_or_generate_quiz_questions(
            request["topic"], bloom, count=5
        )

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
        result = {"quiz_id": quiz_id, "bloom_level": bloom, "questions": questions}
        root.update(
            output={
                "quiz_id": quiz_id,
                "bloom_level": bloom,
                "question_count": len(questions),
                "questions": [q.get("question") for q in questions],
            }
        )
        return result
