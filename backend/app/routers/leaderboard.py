"""
Anonymous Leaderboard — top learners by XP with current user's rank.

GET /leaderboard — top 10 + caller's rank
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from app.auth.jwt import get_current_user_id
from app.db.mongo import col_learners

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0, "id": 1, "user_id": 1, "name": 1, "xp": 1, "streak": 1, "topic_proficiency_map": 1}


def _topics_mastered(proficiency: dict) -> int:
    return sum(1 for elo in proficiency.values() if elo >= 700)


def _anonymize(learner: dict, is_self: bool) -> dict:
    name = (learner.get("name") or "Learner").strip()
    first = name.split()[0] if name else "Learner"
    initial = first[0].upper() if first else "L"
    proficiency = learner.get("topic_proficiency_map") or {}
    return {
        "display_name": first if is_self else f"{first[0]}{'·' * (len(first) - 1)}",
        "initial": initial,
        "xp": learner.get("xp", 0),
        "streak": learner.get("streak", 0),
        "topics_mastered": _topics_mastered(proficiency),
        "is_self": is_self,
    }


@router.get("")
async def get_leaderboard(user_id: str = Depends(get_current_user_id)):
    """Return top 10 learners by XP + the caller's rank (even if outside top 10)."""
    all_learners = list(
        col_learners().find({}, PROJ).sort("xp", -1)
    )

    top_10 = all_learners[:10]
    caller_rank = next(
        (i + 1 for i, l in enumerate(all_learners) if l.get("user_id") == user_id),
        None,
    )
    caller = next((l for l in all_learners if l.get("user_id") == user_id), None)

    board = [_anonymize(l, l.get("user_id") == user_id) for l in top_10]
    for i, entry in enumerate(board):
        entry["rank"] = i + 1

    result = {
        "board": board,
        "total_learners": len(all_learners),
        "your_rank": caller_rank,
    }

    if caller and (caller_rank is None or caller_rank > 10):
        result["you"] = {**_anonymize(caller, True), "rank": caller_rank}

    return result
