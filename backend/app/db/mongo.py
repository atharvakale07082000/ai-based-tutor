"""
Central pymongo async client and typed collection accessors.

All operations are async (pymongo's native AsyncMongoClient, available since
pymongo 4.9) and must be awaited from async FastAPI handlers/agents.

Celery tasks run in sync workers and use the separate sync client in
app/db/mongo_sync.py instead.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

_client: AsyncMongoClient | None = None


def get_client() -> AsyncMongoClient:
    global _client
    if _client is None:
        from app.config import settings

        _client = AsyncMongoClient(
            settings.MONGO_URL,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=50,
            minPoolSize=5,
            maxIdleTimeMS=30_000,
            compressors=["zlib"],
            zlibCompressionLevel=3,
        )
    return _client


def get_db() -> AsyncDatabase:
    from app.config import settings

    return get_client()[settings.MONGO_DATABASE]


# ─── Collection shorthands ────────────────────────────────────────────────────


def col_users() -> AsyncCollection:
    return get_db()["users"]


def col_learners() -> AsyncCollection:
    return get_db()["learner_profiles"]


def col_quizzes() -> AsyncCollection:
    return get_db()["quiz_sessions"]


def col_progress() -> AsyncCollection:
    return get_db()["progress_records"]


def col_curricula() -> AsyncCollection:
    return get_db()["curriculum_paths"]


def col_doubts() -> AsyncCollection:
    return get_db()["doubt_sessions"]


def col_content() -> AsyncCollection:
    return get_db()["content_items"]


def col_course_plans() -> AsyncCollection:
    return get_db()["course_plans"]


def col_interviews() -> AsyncCollection:
    return get_db()["module_interviews"]


def col_evals() -> AsyncCollection:
    return get_db()["agent_evals"]


# DEPRECATED: chat evals now write to agent_evals via app/evals/mongo.insert_eval.
# Keep this accessor for read-only migration queries against old data only.
def col_chat_evals() -> AsyncCollection:
    return get_db()["chat_evals"]


def col_trending_topics() -> AsyncCollection:
    return get_db()["trending_topics"]


def col_feed_items() -> AsyncCollection:
    return get_db()["feed_items"]


def col_feed_interactions() -> AsyncCollection:
    return get_db()["feed_interactions"]


def col_study_sessions() -> AsyncCollection:
    return get_db()["study_sessions"]


def col_xp_events() -> AsyncCollection:
    return get_db()["xp_events"]


def col_quiz_bank() -> AsyncCollection:
    return get_db()["quiz_bank"]


def col_activity_logs() -> AsyncCollection:
    return get_db()["activity_logs"]


def col_reset_tokens() -> AsyncCollection:
    return get_db()["password_reset_tokens"]


def col_job_applications() -> AsyncCollection:
    return get_db()["job_applications"]


# ─── Startup ──────────────────────────────────────────────────────────────────


async def ensure_indexes() -> None:
    """Create indexes (idempotent — safe to call on every startup)."""
    await col_users().create_index("email", unique=True)
    await col_learners().create_index("user_id", unique=True)
    await col_quizzes().create_index([("learner_id", ASCENDING)])
    await col_progress().create_index([("learner_id", ASCENDING), ("recorded_at", ASCENDING)])
    await col_curricula().create_index([("learner_id", ASCENDING), ("is_active", ASCENDING)])
    await col_doubts().create_index([("learner_id", ASCENDING)])
    await col_content().create_index("topic")
    await col_course_plans().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await col_interviews().create_index([("plan_id", ASCENDING), ("module_id", ASCENDING)])
    await col_trending_topics().create_index([("discovered_at", DESCENDING)])
    await col_trending_topics().create_index([("domain", ASCENDING)])
    await col_feed_items().create_index([("discovered_at", DESCENDING)])
    await col_feed_items().create_index([("expires_at", ASCENDING)])
    await col_feed_interactions().create_index([("user_id", ASCENDING), ("item_id", ASCENDING)])
    await col_study_sessions().create_index([("learner_id", ASCENDING), ("recorded_at", DESCENDING)])
    await col_xp_events().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await col_quiz_bank().create_index([("topic", ASCENDING), ("bloom_level", ASCENDING)], unique=True)

    await col_activity_logs().create_index([("user_id", ASCENDING)])
    await col_activity_logs().create_index([("timestamp", DESCENDING)])
    await col_activity_logs().create_index([("user_id", ASCENDING), ("timestamp", DESCENDING)])
    await col_activity_logs().create_index("timestamp", expireAfterSeconds=90 * 24 * 3600)
    # Reset tokens expire automatically after 1 hour via MongoDB TTL index
    await col_reset_tokens().create_index("created_at", expireAfterSeconds=3600)
    await col_reset_tokens().create_index("token", unique=True)

    await col_job_applications().create_index([("learner_id", ASCENDING), ("updated_at", DESCENDING)])
