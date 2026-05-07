"""
Async MongoDB client for evals storage using Motor (async PyMongo).

The client is lazily initialized so tests that never call get_evals_collection()
don't need a running MongoDB.
"""
from __future__ import annotations
import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import motor.motor_asyncio as _motor  # type: ignore

log = structlog.get_logger()

_client: "_motor.AsyncIOMotorClient | None" = None
_db: "_motor.AsyncIOMotorDatabase | None" = None


def _get_client():
    global _client, _db
    if _client is not None:
        return _client, _db

    from app.config import settings
    import motor.motor_asyncio as motor  # type: ignore

    _client = motor.AsyncIOMotorClient(settings.MONGO_URL, serverSelectionTimeoutMS=5000)
    _db = _client[settings.MONGO_DATABASE]
    log.info("mongo_client_initialized", db=settings.MONGO_DATABASE)
    return _client, _db


def get_evals_collection():
    """Return the Motor collection for eval records."""
    from app.config import settings
    _, db = _get_client()
    return db[settings.MONGO_COLLECTION_EVALS]


async def close_mongo() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
        log.info("mongo_client_closed")


async def insert_eval(record: dict) -> str:
    """Insert a single eval record. Returns the inserted _id as string."""
    col = get_evals_collection()
    result = await col.insert_one(record)
    return str(result.inserted_id)


async def query_evals(
    *,
    eval_type: str | None = None,
    agent: str | None = None,
    learner_id: str | None = None,
    passed: bool | None = None,
    limit: int = 50,
) -> list[dict]:
    """Query eval records with optional filters."""
    col = get_evals_collection()
    query: dict = {}
    if eval_type:
        query["eval_type"] = eval_type
    if agent:
        query["agent"] = agent
    if learner_id:
        query["learner_id"] = learner_id
    if passed is not None:
        query["passed"] = passed

    cursor = col.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
    return [doc async for doc in cursor]


async def aggregate_summary(eval_type: str | None = None, agent: str | None = None) -> list[dict]:
    """Return pass-rate and average score aggregated by (eval_type, agent)."""
    col = get_evals_collection()
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

    cursor = col.aggregate(pipeline)
    return [doc async for doc in cursor]
