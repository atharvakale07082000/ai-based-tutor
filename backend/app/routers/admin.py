import structlog
from fastapi import APIRouter, Depends, Query

from app.db.mongo import col_learners, col_doubts
from app.auth.jwt import get_current_user_id

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

    learners = list(
        col_learners().find(query, PROJ)
        .skip((page - 1) * limit).limit(limit)
    )

    items = []
    for learner in learners:
        proficiency = learner.get("topic_proficiency_map") or {}
        avg_proficiency = sum(proficiency.values()) / max(len(proficiency), 1) if proficiency else 0

        mood_doc = col_doubts().find_one(
            {"learner_id": learner["id"], "sentiment_mood": {"$ne": None}},
            {"sentiment_mood": 1, "_id": 0},
            sort=[("started_at", -1)],
        )
        mood = mood_doc["sentiment_mood"] if mood_doc else None

        items.append({
            "id": learner["id"],
            "name": learner.get("name", ""),
            "email": learner.get("email", ""),
            "avg_proficiency": avg_proficiency,
            "last_active": learner.get("updated_at", ""),
            "mood": mood,
            "topic_proficiency": proficiency,
        })

    return {"items": items, "total": len(items)}


@router.put("/config")
async def update_config(config: dict, user_id: str = Depends(get_current_user_id)):
    _agent_config.update({k: v for k, v in config.items() if k in _agent_config})
    return {"config": _agent_config}


@router.get("/config")
async def get_config(user_id: str = Depends(get_current_user_id)):
    return _agent_config
