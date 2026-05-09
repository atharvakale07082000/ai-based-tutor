"""Eval storage using pymongo (replaces motor)."""
from __future__ import annotations
import asyncio
import structlog
from app.db.mongo import col_evals

log = structlog.get_logger()


# ─── Write ────────────────────────────────────────────────────────────────────

def _insert_eval_sync(record: dict) -> str:
    result = col_evals().insert_one({**record})
    return str(result.inserted_id)


async def insert_eval(record: dict) -> str:
    return await asyncio.to_thread(_insert_eval_sync, record)


# ─── Read ─────────────────────────────────────────────────────────────────────

def _query_evals_sync(
    *,
    eval_type: str | None,
    agent: str | None,
    learner_id: str | None,
    passed: bool | None,
    limit: int,
) -> list[dict]:
    query: dict = {}
    if eval_type:
        query["eval_type"] = eval_type
    if agent:
        query["agent"] = agent
    if learner_id:
        query["learner_id"] = learner_id
    if passed is not None:
        query["passed"] = passed
    return list(col_evals().find(query, {"_id": 0}).sort("timestamp", -1).limit(limit))


async def query_evals(
    *,
    eval_type: str | None = None,
    agent: str | None = None,
    learner_id: str | None = None,
    passed: bool | None = None,
    limit: int = 50,
) -> list[dict]:
    return await asyncio.to_thread(
        _query_evals_sync,
        eval_type=eval_type, agent=agent,
        learner_id=learner_id, passed=passed, limit=limit,
    )


def _aggregate_sync(eval_type: str | None, agent: str | None) -> list[dict]:
    match: dict = {}
    if eval_type:
        match["eval_type"] = eval_type
    if agent:
        match["agent"] = agent

    pipeline = [
        *([ {"$match": match} ] if match else []),
        {
            "$group": {
                "_id": {"eval_type": "$eval_type", "agent": "$agent"},
                "total": {"$sum": 1},
                "passed": {"$sum": {"$cond": ["$passed", 1, 0]}},
                "avg_score": {"$avg": "$score"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "eval_type": "$_id.eval_type",
                "agent": "$_id.agent",
                "total": 1,
                "passed": 1,
                "avg_score": {"$round": ["$avg_score", 3]},
                "pass_rate": {
                    "$round": [{"$divide": ["$passed", {"$max": ["$total", 1]}]}, 3]
                },
            }
        },
        {"$sort": {"eval_type": 1, "agent": 1}},
    ]
    return list(col_evals().aggregate(pipeline))


async def aggregate_summary(
    eval_type: str | None = None,
    agent: str | None = None,
) -> list[dict]:
    return await asyncio.to_thread(_aggregate_sync, eval_type, agent)


async def close_mongo() -> None:
    """No-op — pymongo client manages its own connection pool."""
