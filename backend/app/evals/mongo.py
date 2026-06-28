"""Eval storage using pymongo (replaces motor)."""

from __future__ import annotations

import structlog

from app.db.mongo import col_evals

log = structlog.get_logger()


# ─── Write ────────────────────────────────────────────────────────────────────


async def insert_eval(record: dict) -> str:
    result = await col_evals().insert_one({**record})
    return str(result.inserted_id)


# ─── Read ─────────────────────────────────────────────────────────────────────


async def query_evals(
    *,
    eval_type: str | None = None,
    agent: str | None = None,
    learner_id: str | None = None,
    passed: bool | None = None,
    limit: int = 50,
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
    return await col_evals().find(query, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(length=None)


async def aggregate_summary(
    eval_type: str | None = None,
    agent: str | None = None,
) -> list[dict]:
    match: dict = {}
    if eval_type:
        match["eval_type"] = eval_type
    if agent:
        match["agent"] = agent

    pipeline = [
        *([{"$match": match}] if match else []),
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
                "pass_rate": {"$round": [{"$divide": ["$passed", {"$max": ["$total", 1]}]}, 3]},
            }
        },
        {"$sort": {"eval_type": 1, "agent": 1}},
    ]
    return await (await col_evals().aggregate(pipeline)).to_list(length=None)


def _group_stats(field: str) -> list[dict]:
    """Aggregation stage list grouping by ``field`` into count / pass_rate / avg_score."""
    return [
        {
            "$group": {
                "_id": f"${field}",
                "total": {"$sum": 1},
                "passed": {"$sum": {"$cond": ["$passed", 1, 0]}},
                "avg_score": {"$avg": "$score"},
            }
        },
        {
            "$project": {
                "_id": 0,
                field: "$_id",
                "total": 1,
                "avg_score": {"$round": [{"$ifNull": ["$avg_score", 0]}, 3]},
                "pass_rate": {"$round": [{"$divide": ["$passed", {"$max": ["$total", 1]}]}, 3]},
            }
        },
        {"$sort": {"total": -1}},
    ]


async def dashboard_stats(*, recent_limit: int = 25, trend_days: int = 14) -> dict:
    """One-shot aggregation powering the evals dashboard: overall, by-metric, by-agent, recent, trend."""
    from datetime import datetime, timedelta, timezone

    col = col_evals()

    totals = await (
        await col.aggregate(
            [
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": 1},
                        "passed": {"$sum": {"$cond": ["$passed", 1, 0]}},
                        "avg_score": {"$avg": "$score"},
                    }
                }
            ]
        )
    ).to_list(length=1)
    t = totals[0] if totals else {}
    total = t.get("total", 0)
    overall = {
        "total": total,
        "pass_rate": round((t.get("passed", 0) / max(total, 1)), 3),
        "avg_score": round(t.get("avg_score") or 0.0, 3),
    }

    by_metric = await (await col.aggregate(_group_stats("eval_type"))).to_list(length=None)
    by_agent = await (await col.aggregate(_group_stats("agent"))).to_list(length=None)

    recent = await col.find({}, {"_id": 0}).sort("timestamp", -1).limit(recent_limit).to_list(length=None)

    since = datetime.now(timezone.utc) - timedelta(days=trend_days)
    trend = await (
        await col.aggregate(
            [
                {"$match": {"timestamp": {"$gte": since}}},
                {
                    "$group": {
                        "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                        "avg_score": {"$avg": "$score"},
                        "count": {"$sum": 1},
                    }
                },
                {"$project": {"_id": 0, "day": "$_id", "avg_score": {"$round": ["$avg_score", 3]}, "count": 1}},
                {"$sort": {"day": 1}},
            ]
        )
    ).to_list(length=None)

    return {"overall": overall, "by_metric": by_metric, "by_agent": by_agent, "recent": recent, "trend": trend}


async def close_mongo() -> None:
    """No-op — pymongo client manages its own connection pool."""
