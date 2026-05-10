import uuid
import re
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.mongo import col_content, col_learners
from app.auth.jwt import get_current_user_id
from app.hf.recommendation_agent import rank_content_for_learner
from app.hf.content_generator import generate_content_body

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}

SEED_CONTENT = [
    {"title": "Python Variables and Data Types Deep Dive", "content_type": "article", "topic": "Python Programming", "subtopic": "Variables & Data Types", "difficulty": 0.2, "estimated_minutes": 12, "body": "An introduction to Python's core data types.", "video_url": None, "is_ai_recommended": True},
    {"title": "Machine Learning Fundamentals with scikit-learn", "content_type": "video", "topic": "Machine Learning", "subtopic": "Linear & Logistic Regression", "difficulty": 0.4, "estimated_minutes": 25, "body": "Core concepts of supervised learning using scikit-learn.", "video_url": None, "is_ai_recommended": True},
    {"title": "Building Your First Neural Network", "content_type": "exercise", "topic": "Deep Learning", "subtopic": "Neural Networks Basics", "difficulty": 0.65, "estimated_minutes": 45, "body": "Build a 3-layer neural network from scratch using NumPy and PyTorch.", "video_url": None, "is_ai_recommended": False},
    {"title": "Pandas DataFrame Operations Masterclass", "content_type": "interactive", "topic": "Data Science", "subtopic": "Pandas DataFrames", "difficulty": 0.35, "estimated_minutes": 30, "body": "Interactive exploration of groupby, merge, pivot tables, and indexing in pandas.", "video_url": None, "is_ai_recommended": True},
    {"title": "Understanding Transformers and Attention Mechanisms", "content_type": "article", "topic": "Natural Language Processing", "subtopic": "Transformers & Attention", "difficulty": 0.75, "estimated_minutes": 20, "body": "A deep dive into the Transformer architecture and attention mechanisms.", "video_url": None, "is_ai_recommended": False},
    {"title": "React Hooks: useState, useEffect, and Custom Hooks", "content_type": "video", "topic": "Web Development", "subtopic": "React & Component Model", "difficulty": 0.45, "estimated_minutes": 35, "body": "Master React's functional component model with built-in and custom hooks.", "video_url": None, "is_ai_recommended": True},
    {"title": "Statistics: Hypothesis Testing in Practice", "content_type": "exercise", "topic": "Statistics", "subtopic": "Hypothesis Testing", "difficulty": 0.55, "estimated_minutes": 40, "body": "Hands-on practice with t-tests, chi-squared tests, and ANOVA on real datasets.", "video_url": None, "is_ai_recommended": False},
    {"title": "Linear Algebra for Machine Learning", "content_type": "article", "topic": "Mathematics", "subtopic": "Linear Algebra", "difficulty": 0.5, "estimated_minutes": 18, "body": "Vectors, matrices, eigenvalues, and SVD for ML practitioners.", "video_url": None, "is_ai_recommended": True},
]


def _ensure_seed():
    if col_content().count_documents({}) == 0:
        for item in SEED_CONTENT:
            col_content().insert_one({"id": str(uuid.uuid4()), **item})


@router.get("")
async def list_content(
    topic: str | None = Query(None),
    type: str | None = Query(None),
    search: str | None = Query(None),
    min_difficulty: float = Query(0.0),
    max_difficulty: float = Query(1.0),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
):
    _ensure_seed()

    query: dict = {
        "difficulty": {"$gte": min_difficulty, "$lte": max_difficulty},
    }
    if topic:
        query["topic"] = {"$regex": topic, "$options": "i"}
    if type:
        query["content_type"] = type
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"topic": {"$regex": search, "$options": "i"}},
        ]

    skip = (page - 1) * limit
    items = list(col_content().find(query, PROJ).skip(skip).limit(limit + 1))
    has_more = len(items) > limit
    result_items = items[:limit]

    # Semantic recommendation: rank items by learner profile (page 1 only, no filter active)
    if page == 1 and not topic and not search and not type:
        try:
            learner = col_learners().find_one({"user_id": user_id}, {"_id": 0})
            if learner:
                result_items = await rank_content_for_learner(
                    result_items,
                    goal_vector=learner.get("goal_vector") or [],
                    topic_proficiency=learner.get("topic_proficiency_map") or {},
                )
        except Exception as e:
            log.warning("recommendation_agent_skipped", error=str(e))

    return {
        "items": result_items,
        "total": len(result_items),
        "has_more": has_more,
    }


@router.get("/{item_id}")
async def get_content(item_id: str, user_id: str = Depends(get_current_user_id)):
    _ensure_seed()
    item = col_content().find_one({"id": item_id}, PROJ)
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")

    if len(item.get("body", "")) < 400:
        log.info("content_body_short_generating", item_id=item_id)
        generated_body = await generate_content_body(
            topic=item.get("topic", ""),
            subtopic=item.get("subtopic", ""),
            content_type=item.get("content_type", "article"),
            difficulty=item.get("difficulty", 0.5),
        )
        col_content().update_one({"id": item_id}, {"$set": {"body": generated_body}})
        item["body"] = generated_body

    return item


@router.post("/{item_id}/regenerate")
async def regenerate_content(item_id: str, user_id: str = Depends(get_current_user_id)):
    """Force-regenerate the AI-written body for a content item regardless of current length."""
    _ensure_seed()
    item = col_content().find_one({"id": item_id}, PROJ)
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")

    log.info("content_body_force_regenerating", item_id=item_id)
    generated_body = await generate_content_body(
        topic=item.get("topic", ""),
        subtopic=item.get("subtopic", ""),
        content_type=item.get("content_type", "article"),
        difficulty=item.get("difficulty", 0.5),
    )
    col_content().update_one({"id": item_id}, {"$set": {"body": generated_body}})
    item["body"] = generated_body
    return item
