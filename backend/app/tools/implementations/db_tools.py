"""
Database tool implementations.

All handlers are async.  MongoDB collection accessors are imported lazily
inside each handler to avoid connection setup at module import time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

from app.tools.schemas import Tool

log = structlog.get_logger()


# ── Handlers ──────────────────────────────────────────────────────────────────


async def _get_proficiency(learner_id: str) -> dict:
    from app.db.mongo import col_learners

    doc = col_learners().find_one({"id": learner_id}, {"_id": 0})
    if not doc:
        log.warning("get_proficiency_not_found", learner_id=learner_id)
        return {"proficiency": {}, "xp": 0, "streak": 0}
    return {
        "proficiency": doc.get("topic_proficiency", {}),
        "xp": doc.get("xp", 0),
        "streak": doc.get("streak", 0),
    }


async def _get_topic_graph() -> dict:
    from app.prompts.loader import get_curriculum_config

    cfg = get_curriculum_config()
    return {
        "topic_graph": cfg.get("topic_graph", {}),
        "domains": cfg.get("domains", []),
    }


async def _save_quiz(
    learner_id: str,
    topic: str,
    bloom_level: str,
    questions: list,
) -> dict:
    from app.db.mongo import col_quizzes

    quiz_id = str(uuid.uuid4())
    doc = {
        "id": quiz_id,
        "learner_id": learner_id,
        "topic": topic,
        "bloom_level": bloom_level,
        "questions": questions,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    col_quizzes().insert_one(doc)
    log.info("save_quiz_done", quiz_id=quiz_id, topic=topic, learner_id=learner_id)
    return {"quiz_id": quiz_id, "url": f"/quiz/{quiz_id}"}


async def _save_progress(
    learner_id: str,
    topic: str,
    old_elo: float,
    new_elo: float,
    score: float,
    mood: str = "NEUTRAL",
) -> dict:
    from app.db.mongo import col_learners, col_progress

    xp_delta = min(50, int(score * 50))
    now = datetime.now(timezone.utc).isoformat()

    # Update the proficiency map and xp on the learner profile
    col_learners().update_one(
        {"id": learner_id},
        {
            "$set": {f"topic_proficiency.{topic}": new_elo},
            "$inc": {"xp": xp_delta},
        },
        upsert=False,
    )

    # Insert a progress record
    col_progress().insert_one(
        {
            "learner_id": learner_id,
            "topic": topic,
            "old_elo": old_elo,
            "new_elo": new_elo,
            "score": score,
            "mood": mood,
            "xp_delta": xp_delta,
            "recorded_at": now,
        }
    )

    log.info(
        "save_progress_done",
        learner_id=learner_id,
        topic=topic,
        old_elo=old_elo,
        new_elo=new_elo,
        xp_delta=xp_delta,
    )
    return {"ok": True, "xp_delta": xp_delta}


async def _get_due_topics(learner_id: str) -> dict:
    from app.db.mongo import col_learners, col_quizzes
    from app.hf.spaced_repetition import compute_due_topics

    learner = col_learners().find_one({"id": learner_id}, {"_id": 0}) or {}
    topic_proficiency: dict[str, float] = learner.get("topic_proficiency", {})

    # Build last_quiz_dates from quiz session records
    quiz_cursor = col_quizzes().find(
        {"learner_id": learner_id},
        {"topic": 1, "created_at": 1, "_id": 0},
    )
    last_quiz_dates: dict[str, str] = {}
    for doc in quiz_cursor:
        topic = doc.get("topic", "")
        created_at = doc.get("created_at", "")
        if topic and created_at:
            # Keep only the most recent date per topic
            if topic not in last_quiz_dates or created_at > last_quiz_dates[topic]:
                last_quiz_dates[topic] = created_at

    due = compute_due_topics(topic_proficiency, last_quiz_dates)
    log.info("get_due_topics_done", learner_id=learner_id, due_count=len(due))
    return {"due_topics": due}


# ── Tool descriptors ──────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="get_proficiency",
        description="Fetch a learner's current Elo proficiency map for all topics",
        parameters={
            "type": "object",
            "properties": {
                "learner_id": {
                    "type": "string",
                    "description": "internal learner UUID (not user_id)",
                },
            },
            "required": ["learner_id"],
        },
        handler=_get_proficiency,
        category="db",
        timeout_s=5.0,
    ),
    Tool(
        name="get_topic_graph",
        description="Get the full topic dependency graph and available domains for curriculum building",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=_get_topic_graph,
        category="db",
        timeout_s=2.0,
    ),
    Tool(
        name="save_quiz",
        description="Persist a generated quiz to the database and return its ID",
        parameters={
            "type": "object",
            "properties": {
                "learner_id": {"type": "string"},
                "topic": {"type": "string"},
                "bloom_level": {"type": "string"},
                "questions": {"type": "array"},
            },
            "required": ["learner_id", "topic", "bloom_level", "questions"],
        },
        handler=_save_quiz,
        category="db",
        timeout_s=5.0,
    ),
    Tool(
        name="save_progress",
        description="Persist an Elo update for a topic and update the learner's proficiency map",
        parameters={
            "type": "object",
            "properties": {
                "learner_id": {"type": "string"},
                "topic": {"type": "string"},
                "old_elo": {"type": "number"},
                "new_elo": {"type": "number"},
                "score": {"type": "number"},
                "mood": {
                    "type": "string",
                    "default": "NEUTRAL",
                },
            },
            "required": ["learner_id", "topic", "old_elo", "new_elo", "score"],
        },
        handler=_save_progress,
        category="db",
        timeout_s=5.0,
    ),
    Tool(
        name="get_due_topics",
        description="Get topics due for spaced-repetition review, ordered by urgency",
        parameters={
            "type": "object",
            "properties": {
                "learner_id": {"type": "string"},
            },
            "required": ["learner_id"],
        },
        handler=_get_due_topics,
        category="db",
        timeout_s=10.0,
    ),
]
