import structlog
from fastapi import APIRouter, Depends, Query

from app.auth.jwt import get_current_user_id
from app.db.mongo import col_doubts, col_learners

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}

_agent_config = {
    "quiz_frequency": 3,
    "difficulty_ceiling": 0.8,
    "escalation_threshold": 3,
}


@router.get("/learners")
async def get_learners(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(20),
    user_id: str = Depends(get_current_user_id),
):
    query: dict = {}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]

    learners = await col_learners().find(query, PROJ).skip((page - 1) * limit).limit(limit).to_list(length=None)

    items = []
    for learner in learners:
        proficiency = learner.get("topic_proficiency_map") or {}
        avg_proficiency = sum(proficiency.values()) / max(len(proficiency), 1) if proficiency else 0

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


@router.put("/config")
async def update_config(config: dict, user_id: str = Depends(get_current_user_id)):
    _agent_config.update({k: v for k, v in config.items() if k in _agent_config})
    return {"config": _agent_config}


@router.get("/config")
async def get_config(user_id: str = Depends(get_current_user_id)):
    return _agent_config


@router.post("/send-digest")
async def trigger_digest(
    email: str = Query(..., description="Send digest to this email address"),
    user_id: str = Depends(get_current_user_id),
):
    """Manually trigger the weekly digest for a specific email address."""
    from app.db.mongo import col_users

    user_doc = await col_users().find_one({"email": email}, {"_id": 0, "id": 1})
    if not user_doc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"No user found with email {email}")

    learner = await col_learners().find_one({"user_id": user_doc["id"]}, {"_id": 0, "id": 1})
    if not learner:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Learner profile not found for that user")

    from app.tasks.task_definitions import send_progress_digest

    send_progress_digest.delay(learner_id=learner["id"])
    log.info("digest_triggered_manually", email=email, learner_id=learner["id"])
    return {"ok": True, "message": f"Digest queued for {email}"}
