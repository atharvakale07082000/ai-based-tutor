"""Query/aggregation helpers for the Profile > Activity Logs page."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.mongo import col_activity_logs

PROJ = {"_id": 0}

STATS_WINDOW_DAYS = 30


async def get_user_logs(
    user_id: str,
    limit: int = 20,
    skip: int = 0,
    action_filter: str | None = None,
) -> tuple[list[dict], int]:
    query: dict = {"user_id": user_id}
    if action_filter:
        query["action"] = action_filter

    col = col_activity_logs()
    total = await col.count_documents(query)
    logs = await col.find(query, PROJ).sort("timestamp", -1).skip(skip).limit(limit).to_list(length=None)
    return logs, total


async def get_log_stats(user_id: str) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=STATS_WINDOW_DAYS)
    col = col_activity_logs()

    action_counts_pipeline = [
        {"$match": {"user_id": user_id, "timestamp": {"$gte": since}}},
        {"$group": {"_id": "$action", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    action_rows = await (await col.aggregate(action_counts_pipeline)).to_list(length=None)
    action_counts = {row["_id"]: row["count"] for row in action_rows}

    daily_pipeline = [
        {"$match": {"user_id": user_id, "timestamp": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1},
    ]
    daily_rows = await (await col.aggregate(daily_pipeline)).to_list(length=None)
    most_active_day = daily_rows[0]["_id"] if daily_rows else None

    total_actions = sum(action_counts.values())

    return {
        "action_counts": action_counts,
        "most_active_day": most_active_day,
        "total_actions": total_actions,
        "window_days": STATS_WINDOW_DAYS,
    }


async def delete_user_logs(user_id: str) -> int:
    result = await col_activity_logs().delete_many({"user_id": user_id})
    return result.deleted_count
