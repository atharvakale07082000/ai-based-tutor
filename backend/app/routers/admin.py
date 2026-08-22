"""
Admin API — learner management and agent configuration.

**Superuser-only.** Every route depends on `require_superuser`, not `get_current_user_id`:
these endpoints expose the whole user base (names, emails, proficiency, inferred mood) and
mutate global agent config, so authentication alone is not enough. Same gate as /evals.

Endpoints:
  GET  /admin/learners     — paginated learner list with proficiency + mood
  GET  /admin/skill-gaps   — org-wide skill gap per topic, aggregated from real proficiency
  PUT  /admin/config       — update runtime agent config (quiz frequency, difficulty cap)
  GET  /admin/config       — read current agent config
  POST /admin/send-digest  — manually trigger the weekly progress digest for a user
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from app.agents.progress import MASTERY_ELO
from app.auth.jwt import require_superuser
from app.db.mongo import PROJ, col_doubts, col_learners

router = APIRouter()
log = structlog.get_logger()


_agent_config = {
    "quiz_frequency": 3,
    "difficulty_ceiling": 0.8,
    "escalation_threshold": 3,
}


@router.get("/learners")
async def get_learners(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(require_superuser),
):
    """Return a paginated list of learners with their proficiency averages and latest mood."""
    query: dict = {}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]

    learners = (
        await col_learners()
        .find(query, PROJ)
        .skip((page - 1) * limit)
        .limit(limit)
        .to_list(length=None)
    )

    items = []
    for learner in learners:
        proficiency = learner.get("topic_proficiency_map") or {}
        avg_proficiency = (
            sum(proficiency.values()) / max(len(proficiency), 1) if proficiency else 0
        )

        mood_doc = await col_doubts().find_one(
            {"learner_id": learner["id"], "sentiment_mood": {"$ne": None}},
            {"sentiment_mood": 1, "_id": 0},
            sort=[("started_at", -1)],
        )
        mood = mood_doc["sentiment_mood"] if mood_doc else None

        items.append(
            {
                "id": learner["id"],
                "name": learner.get("name", ""),
                "email": learner.get("email", ""),
                "avg_proficiency": avg_proficiency,
                "last_active": learner.get("updated_at", ""),
                "mood": mood,
                "topic_proficiency": proficiency,
            }
        )

    return {"items": items, "total": len(items)}


@router.get("/skill-gaps")
async def get_skill_gaps(
    limit: int = Query(10, ge=1, le=40),
    user_id: str = Depends(require_superuser),
):
    """Org-wide skill gap per topic, aggregated across every learner's proficiency map.

    "Gap" is the share of learners tracking a topic who have not yet mastered it
    (Elo < ``MASTERY_ELO``) — so a high percentage means most people studying that topic
    are still below the bar, which is what an operator wants to act on.

    Aggregated in MongoDB rather than in Python: ``topic_proficiency_map`` is a
    per-learner object, so ``$objectToArray`` unrolls it into one row per (learner, topic)
    without pulling every learner document into memory.
    """
    pipeline = [
        {"$match": {"topic_proficiency_map": {"$exists": True, "$ne": {}}}},
        {"$project": {"kv": {"$objectToArray": "$topic_proficiency_map"}}},
        {"$unwind": "$kv"},
        {
            "$group": {
                "_id": "$kv.k",
                "learners": {"$sum": 1},
                "below": {"$sum": {"$cond": [{"$lt": ["$kv.v", MASTERY_ELO]}, 1, 0]}},
                "avg_elo": {"$avg": "$kv.v"},
            }
        },
        # A topic one person has touched is noise, not an org signal.
        {"$match": {"learners": {"$gte": 2}}},
        {"$sort": {"below": -1, "_id": 1}},
        {"$limit": limit},
    ]

    # pymongo's async aggregate() returns a coroutine yielding the cursor — it must be
    # awaited before the cursor can be drained.
    cursor = await col_learners().aggregate(pipeline)
    rows = await cursor.to_list(length=None)
    items = [
        {
            "name": r["_id"],
            "pct": round(r["below"] / r["learners"], 4),
            "learners": r["learners"],
            "below_mastery": r["below"],
            "avg_elo": round(r["avg_elo"], 1),
        }
        for r in rows
    ]
    return {"items": items, "mastery_elo": MASTERY_ELO}


@router.put("/config")
async def update_config(config: dict, user_id: str = Depends(require_superuser)):
    """Update one or more runtime agent configuration values."""
    _agent_config.update({k: v for k, v in config.items() if k in _agent_config})
    return {"config": _agent_config}


@router.get("/config")
async def get_config(user_id: str = Depends(require_superuser)):
    """Return the current runtime agent configuration."""
    return _agent_config


@router.post("/send-digest")
async def trigger_digest(
    email: str = Query(..., description="Send digest to this email address"),
    user_id: str = Depends(require_superuser),
):
    """Manually trigger the weekly digest for a specific email address."""
    from app.db.mongo import col_users

    user_doc = await col_users().find_one({"email": email}, {"_id": 0, "id": 1})
    if not user_doc:
        raise HTTPException(status_code=404, detail=f"No user found with email {email}")

    learner = await col_learners().find_one(
        {"user_id": user_doc["id"]}, {"_id": 0, "id": 1}
    )
    if not learner:
        raise HTTPException(
            status_code=404, detail="Learner profile not found for that user"
        )

    from app.tasks.task_definitions import send_progress_digest

    send_progress_digest.delay(learner_id=learner["id"])
    log.info("digest_triggered_manually", email=email, learner_id=learner["id"])
    return {"ok": True, "message": f"Digest queued for {email}"}
