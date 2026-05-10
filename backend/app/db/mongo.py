"""
Central pymongo client and typed collection accessors.

All operations are synchronous — pymongo is called directly from async handlers.
Atlas round-trip is <10 ms so blocking the event loop is acceptable for this scale.
"""
from __future__ import annotations

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        from app.config import settings
        _client = MongoClient(settings.MONGO_URL, serverSelectionTimeoutMS=5000)
    return _client


def get_db() -> Database:
    from app.config import settings
    return get_client()[settings.MONGO_DATABASE]


# ─── Collection shorthands ────────────────────────────────────────────────────

def col_users() -> Collection:               return get_db()["users"]
def col_learners() -> Collection:            return get_db()["learner_profiles"]
def col_quizzes() -> Collection:             return get_db()["quiz_sessions"]
def col_progress() -> Collection:            return get_db()["progress_records"]
def col_curricula() -> Collection:           return get_db()["curriculum_paths"]
def col_doubts() -> Collection:              return get_db()["doubt_sessions"]
def col_content() -> Collection:             return get_db()["content_items"]
def col_course_plans() -> Collection:        return get_db()["course_plans"]
def col_interviews() -> Collection:          return get_db()["module_interviews"]
def col_evals() -> Collection:               return get_db()["agent_evals"]
def col_chat_evals() -> Collection:          return get_db()["chat_evals"]
def col_trending_topics() -> Collection:     return get_db()["trending_topics"]
def col_feed_items() -> Collection:          return get_db()["feed_items"]
def col_feed_interactions() -> Collection:   return get_db()["feed_interactions"]
def col_study_sessions() -> Collection:      return get_db()["study_sessions"]
def col_xp_events() -> Collection:           return get_db()["xp_events"]
def col_quiz_bank() -> Collection:           return get_db()["quiz_bank"]


# ─── Startup ──────────────────────────────────────────────────────────────────

def ensure_indexes() -> None:
    """Create indexes (idempotent — safe to call on every startup)."""
    col_users().create_index("email", unique=True)
    col_learners().create_index("user_id", unique=True)
    col_quizzes().create_index([("learner_id", ASCENDING)])
    col_progress().create_index([("learner_id", ASCENDING), ("recorded_at", ASCENDING)])
    col_curricula().create_index([("learner_id", ASCENDING), ("is_active", ASCENDING)])
    col_doubts().create_index([("learner_id", ASCENDING)])
    col_content().create_index("topic")
    col_course_plans().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    col_interviews().create_index([("plan_id", ASCENDING), ("module_id", ASCENDING)])
    col_trending_topics().create_index([("discovered_at", DESCENDING)])
    col_trending_topics().create_index([("domain", ASCENDING)])
    col_feed_items().create_index([("discovered_at", DESCENDING)])
    col_feed_items().create_index([("expires_at", ASCENDING)])
    col_feed_interactions().create_index([("user_id", ASCENDING), ("item_id", ASCENDING)])
    col_study_sessions().create_index([("learner_id", ASCENDING), ("recorded_at", DESCENDING)])
    col_xp_events().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    col_quiz_bank().create_index([("topic", ASCENDING), ("bloom_level", ASCENDING)], unique=True)
