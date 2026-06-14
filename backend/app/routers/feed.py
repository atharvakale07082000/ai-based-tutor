"""
Today's Feed API — AI-curated trending content with snooze/schedule support.

GET  /feed           → paginated feed items (filtered by learner goals, excluding snoozed)
GET  /feed/trending  → latest 24 trending topics from the discovery agent
POST /feed/run-discovery → manually trigger trend discovery (admin / dev)
POST /feed/{item_id}/snooze   → snooze item for N hours
POST /feed/{item_id}/schedule → schedule item for a specific datetime
DELETE /feed/{item_id}/interaction → clear snooze/schedule for an item
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.auth.jwt import get_current_user_id
from app.db.mongo import (
    col_feed_interactions,
    col_feed_items,
    col_learners,
    col_trending_topics,
)

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


# ── Pydantic models ────────────────────────────────────────────────────────────


class SnoozeRequest(BaseModel):
    hours: int = 24

    @field_validator("hours")
    @classmethod
    def _clamp(cls, v: int) -> int:
        return max(1, min(168, v))  # 1h–1 week


class ScheduleRequest(BaseModel):
    scheduled_for: str  # ISO 8601 datetime


# ── Helpers ────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_interaction(user_id: str, item_id: str) -> dict | None:
    return await col_feed_interactions().find_one({"user_id": user_id, "item_id": item_id}, PROJ)


def _is_snoozed(interaction: dict | None) -> bool:
    if not interaction or not interaction.get("snoozed_until"):
        return False
    try:
        until = datetime.fromisoformat(interaction["snoozed_until"])
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except ValueError:
        return False


# ── GET /feed ──────────────────────────────────────────────────────────────────


@router.get("")
async def list_feed(
    domain: str | None = Query(None),
    content_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
    include_snoozed: bool = Query(False),
    user_id: str = Depends(get_current_user_id),
):
    """Return today's AI-curated feed items, excluding snoozed items."""
    now = datetime.now(timezone.utc)

    # Build query: only non-expired items
    query: dict = {"expires_at": {"$gt": now.isoformat()}}
    if domain:
        query["domain"] = {"$regex": domain, "$options": "i"}
    if content_type:
        query["content_type"] = content_type

    # Fetch active interactions for this user
    if not include_snoozed:
        snoozed_docs = (
            await col_feed_interactions()
            .find(
                {"user_id": user_id, "snoozed_until": {"$gt": now.isoformat()}},
                {"item_id": 1, "_id": 0},
            )
            .to_list(length=None)
        )
        snoozed_items = [i["item_id"] for i in snoozed_docs]
        if snoozed_items:
            query["id"] = {"$nin": snoozed_items}

    skip = (page - 1) * limit
    raw = (
        await col_feed_items()
        .find(query, PROJ)
        .sort("discovered_at", -1)
        .skip(skip)
        .limit(limit + 1)
        .to_list(length=None)
    )
    has_more = len(raw) > limit
    items = raw[:limit]

    # Annotate each item with user interaction state
    item_ids = [i["id"] for i in items]
    interaction_docs = (
        await col_feed_interactions()
        .find({"user_id": user_id, "item_id": {"$in": item_ids}}, PROJ)
        .to_list(length=None)
    )
    interactions = {i["item_id"]: i for i in interaction_docs}

    for item in items:
        ix = interactions.get(item["id"])
        item["_snoozed"] = _is_snoozed(ix)
        item["_snoozed_until"] = ix.get("snoozed_until") if ix else None
        item["_scheduled_for"] = ix.get("scheduled_for") if ix else None

    # If feed is empty, serve fallback seed items
    if not items and page == 1:
        items = _seed_feed()

    return {"items": items, "total": len(items), "has_more": has_more, "page": page}


# ── GET /feed/trending ─────────────────────────────────────────────────────────


@router.get("/trending")
async def list_trending(
    limit: int = Query(24, ge=1, le=48),
    user_id: str = Depends(get_current_user_id),
):
    """Return the latest batch of 24 trending topics discovered by the agent."""
    # Get the most recent discovery batch
    latest = await col_trending_topics().find_one({}, PROJ, sort=[("discovered_at", -1)])
    if not latest:
        return {"topics": _fallback_trending(), "discovered_at": _now_iso(), "fresh": False}

    batch_time = latest["discovered_at"]
    topics = await col_trending_topics().find({"discovered_at": batch_time}, PROJ).limit(limit).to_list(length=None)

    # Annotate with learner proficiency if available
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    proficiency = learner.get("topic_proficiency_map", {}) if learner else {}
    for t in topics:
        elo = proficiency.get(t["subtopic"], None)
        t["_elo"] = elo
        t["_started"] = elo is not None

    return {"topics": topics, "discovered_at": batch_time, "fresh": True}


# ── POST /feed/run-discovery ───────────────────────────────────────────────────


@router.post("/run-discovery")
async def run_discovery(user_id: str = Depends(get_current_user_id)):
    """Manually trigger trend discovery (stores results to DB)."""
    try:
        from app.hf.trend_discovery import discover_trends

        result = await discover_trends()

        # Persist topics
        if result["topics"]:
            await col_trending_topics().insert_many(result["topics"])

        # Persist feed items (deduplicate by URL)
        for item in result["feed_items"]:
            await col_feed_items().update_one(
                {"url": item["url"]},
                {"$setOnInsert": item},
                upsert=True,
            )

        log.info("feed_discovery_manual", topics=len(result["topics"]), items=len(result["feed_items"]))
        return {
            "status": "ok",
            "topics_discovered": len(result["topics"]),
            "feed_items_discovered": len(result["feed_items"]),
            "discovered_at": result["discovered_at"],
        }
    except Exception as e:
        log.error("feed_discovery_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ── POST /feed/{item_id}/snooze ────────────────────────────────────────────────


@router.post("/{item_id}/snooze")
async def snooze_item(
    item_id: str,
    body: SnoozeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Snooze a feed item for the specified number of hours."""
    snoozed_until = (datetime.now(timezone.utc) + timedelta(hours=body.hours)).isoformat()

    await col_feed_interactions().update_one(
        {"user_id": user_id, "item_id": item_id},
        {
            "$set": {
                "user_id": user_id,
                "item_id": item_id,
                "action": "snooze",
                "snoozed_until": snoozed_until,
                "scheduled_for": None,
                "updated_at": _now_iso(),
            },
            "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _now_iso()},
        },
        upsert=True,
    )

    log.info("feed_item_snoozed", item_id=item_id, hours=body.hours, user_id=user_id)
    return {"status": "snoozed", "item_id": item_id, "snoozed_until": snoozed_until}


# ── POST /feed/{item_id}/schedule ─────────────────────────────────────────────


@router.post("/{item_id}/schedule")
async def schedule_item(
    item_id: str,
    body: ScheduleRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Schedule a feed item for study at a specific datetime."""
    try:
        dt = datetime.fromisoformat(body.scheduled_for)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        scheduled_iso = dt.isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid datetime format. Use ISO 8601.")

    await col_feed_interactions().update_one(
        {"user_id": user_id, "item_id": item_id},
        {
            "$set": {
                "user_id": user_id,
                "item_id": item_id,
                "action": "schedule",
                "scheduled_for": scheduled_iso,
                "snoozed_until": None,
                "updated_at": _now_iso(),
            },
            "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _now_iso()},
        },
        upsert=True,
    )

    log.info("feed_item_scheduled", item_id=item_id, scheduled_for=scheduled_iso, user_id=user_id)
    return {"status": "scheduled", "item_id": item_id, "scheduled_for": scheduled_iso}


# ── DELETE /feed/{item_id}/interaction ────────────────────────────────────────


@router.delete("/{item_id}/interaction")
async def clear_interaction(
    item_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Remove snooze or schedule for an item."""
    await col_feed_interactions().delete_one({"user_id": user_id, "item_id": item_id})
    return {"status": "cleared", "item_id": item_id}


# ── GET /feed/scheduled ───────────────────────────────────────────────────────


@router.get("/scheduled")
async def list_scheduled(user_id: str = Depends(get_current_user_id)):
    """Return all items the learner has scheduled for future study."""
    now_iso = _now_iso()
    interactions = await (
        col_feed_interactions()
        .find(
            {"user_id": user_id, "action": "schedule", "scheduled_for": {"$gt": now_iso}},
            PROJ,
        )
        .sort("scheduled_for", 1)
        .to_list(length=None)
    )

    # Join with feed items
    item_ids = [i["item_id"] for i in interactions]
    feed_item_docs = await col_feed_items().find({"id": {"$in": item_ids}}, PROJ).to_list(length=None)
    items_by_id = {i["id"]: i for i in feed_item_docs}

    result = []
    for ix in interactions:
        item = items_by_id.get(ix["item_id"], {})
        result.append({**item, "_scheduled_for": ix["scheduled_for"]})

    return {"items": result, "total": len(result)}


# ── Fallback seed data ─────────────────────────────────────────────────────────


def _seed_feed() -> list[dict]:
    now_iso = _now_iso()
    expires_iso = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    return [
        {
            "id": str(uuid.uuid4()),
            "title": "Apache Kafka for Real-Time Data Pipelines",
            "summary": "Learn how Kafka enables fault-tolerant, scalable streaming data pipelines used in production at Netflix, Uber, and LinkedIn.",
            "url": "https://kafka.apache.org/documentation/",
            "source": "kafka.apache.org",
            "domain": "Data Engineering",
            "subtopic": "Apache Kafka Streams",
            "content_type": "article",
            "is_trending": True,
            "is_ai_recommended": True,
            "estimated_minutes": 15,
            "difficulty": 0.55,
            "discovered_at": now_iso,
            "expires_at": expires_iso,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "GitOps with ArgoCD — From Zero to Production",
            "summary": "Declarative continuous delivery for Kubernetes using ArgoCD and Git as the single source of truth.",
            "url": "https://argo-cd.readthedocs.io/en/stable/",
            "source": "readthedocs.io",
            "domain": "DevOps",
            "subtopic": "GitOps with ArgoCD",
            "content_type": "article",
            "is_trending": True,
            "is_ai_recommended": True,
            "estimated_minutes": 20,
            "difficulty": 0.6,
            "discovered_at": now_iso,
            "expires_at": expires_iso,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "RAG with LangChain and Pinecone",
            "summary": "Build a production-grade Retrieval Augmented Generation pipeline with LangChain, OpenAI embeddings, and Pinecone vector DB.",
            "url": "https://python.langchain.com/docs/tutorials/rag/",
            "source": "langchain.com",
            "domain": "AI Engineering",
            "subtopic": "RAG with Vector Databases",
            "content_type": "article",
            "is_trending": True,
            "is_ai_recommended": True,
            "estimated_minutes": 25,
            "difficulty": 0.65,
            "discovered_at": now_iso,
            "expires_at": expires_iso,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "dbt Fundamentals — Analytics Engineering",
            "summary": "Transform raw data in your warehouse using dbt. Learn models, tests, and documentation for modern analytics engineering.",
            "url": "https://courses.getdbt.com/courses/fundamentals",
            "source": "getdbt.com",
            "domain": "Data Engineering",
            "subtopic": "dbt (Data Build Tool)",
            "content_type": "course",
            "is_trending": True,
            "is_ai_recommended": True,
            "estimated_minutes": 40,
            "difficulty": 0.4,
            "discovered_at": now_iso,
            "expires_at": expires_iso,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Zero Trust Security Architecture",
            "summary": "Why perimeter security is dead and how Zero Trust — verify explicitly, use least privilege, assume breach — changes everything.",
            "url": "https://www.nist.gov/publications/zero-trust-architecture",
            "source": "nist.gov",
            "domain": "Cybersecurity",
            "subtopic": "Zero Trust Architecture",
            "content_type": "article",
            "is_trending": True,
            "is_ai_recommended": False,
            "estimated_minutes": 18,
            "difficulty": 0.5,
            "discovered_at": now_iso,
            "expires_at": expires_iso,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Polars vs Pandas: 10x Faster DataFrames",
            "summary": "Polars is a blazingly fast dataframes library written in Rust. This benchmark shows when to use it over pandas.",
            "url": "https://pola.rs/",
            "source": "pola.rs",
            "domain": "Data Science",
            "subtopic": "Polars DataFrames",
            "content_type": "article",
            "is_trending": True,
            "is_ai_recommended": True,
            "estimated_minutes": 12,
            "difficulty": 0.35,
            "discovered_at": now_iso,
            "expires_at": expires_iso,
        },
    ]


def _fallback_trending() -> list[dict]:
    from app.hf.trend_discovery import _fallback_topics

    now_iso = _now_iso()
    return [
        {
            "id": str(uuid.uuid4()),
            "domain": t["domain"],
            "subtopic": t["subtopic"],
            "description": t["description"],
            "is_trending": True,
            "discovered_at": now_iso,
        }
        for t in _fallback_topics()
    ]
