"""
Sync pymongo client for Celery tasks.

Celery prefork workers run plain sync `def` tasks with no event loop, so they
cannot use the async client in app/db/mongo.py. This module provides a small
parallel sync client with only the collection accessors task_definitions.py
needs.
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        from app.config import settings

        _client = MongoClient(
            settings.MONGO_URL,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=10,
            minPoolSize=2,
            maxIdleTimeMS=30_000,
            compressors=["zlib"],
            zlibCompressionLevel=3,
        )
    return _client


def get_db() -> Database:
    from app.config import settings

    return get_client()[settings.MONGO_DATABASE]


# ─── Collection shorthands ────────────────────────────────────────────────────


def col_users() -> Collection:
    return get_db()["users"]


def col_learners() -> Collection:
    return get_db()["learner_profiles"]


def col_quizzes() -> Collection:
    return get_db()["quiz_sessions"]


def col_trending_topics() -> Collection:
    return get_db()["trending_topics"]


def col_feed_items() -> Collection:
    return get_db()["feed_items"]
