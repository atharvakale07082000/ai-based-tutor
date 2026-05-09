import uuid
import re
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.mongo import col_content
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}

SEED_CONTENT = [
    {"title": "Python Variables and Data Types Deep Dive", "content_type": "article", "topic": "Python Programming", "subtopic": "Variables & Data Types", "difficulty": 0.2, "estimated_minutes": 12, "body": "Python supports multiple data types including integers, floats, strings, booleans, lists, tuples, sets, and dictionaries. Understanding these is foundational to all Python development.", "video_url": None, "is_ai_recommended": True},
    {"title": "Machine Learning Fundamentals with scikit-learn", "content_type": "video", "topic": "Machine Learning", "subtopic": "Linear & Logistic Regression", "difficulty": 0.4, "estimated_minutes": 25, "body": "Learn the core concepts of supervised learning using scikit-learn. We cover train/test splits, model fitting, and evaluation metrics.", "video_url": None, "is_ai_recommended": True},
    {"title": "Building Your First Neural Network", "content_type": "exercise", "topic": "Deep Learning", "subtopic": "Neural Networks Basics", "difficulty": 0.65, "estimated_minutes": 45, "body": "Hands-on exercise: build a 3-layer neural network from scratch using NumPy, then replicate it in PyTorch.", "video_url": None, "is_ai_recommended": False},
    {"title": "Pandas DataFrame Operations Masterclass", "content_type": "interactive", "topic": "Data Science", "subtopic": "Pandas DataFrames", "difficulty": 0.35, "estimated_minutes": 30, "body": "Interactive notebook covering groupby, merge, pivot tables, and advanced indexing operations in pandas.", "video_url": None, "is_ai_recommended": True},
    {"title": "Understanding Transformers and Attention Mechanisms", "content_type": "article", "topic": "Natural Language Processing", "subtopic": "Transformers & Attention", "difficulty": 0.75, "estimated_minutes": 20, "body": "A deep dive into the Transformer architecture: self-attention, multi-head attention, positional encoding, and how BERT and GPT build on this foundation.", "video_url": None, "is_ai_recommended": False},
    {"title": "React Hooks: useState, useEffect, and Custom Hooks", "content_type": "video", "topic": "Web Development", "subtopic": "React & Component Model", "difficulty": 0.45, "estimated_minutes": 35, "body": "Master React's functional component model with hooks. Learn when and how to use built-in hooks and compose them into custom hooks for shared logic.", "video_url": None, "is_ai_recommended": True},
    {"title": "Statistics: Hypothesis Testing in Practice", "content_type": "exercise", "topic": "Statistics", "subtopic": "Hypothesis Testing", "difficulty": 0.55, "estimated_minutes": 40, "body": "Work through t-tests, chi-squared tests, and ANOVA with real datasets. Learn p-values, confidence intervals, and how to avoid common pitfalls.", "video_url": None, "is_ai_recommended": False},
    {"title": "Linear Algebra for Machine Learning", "content_type": "article", "topic": "Mathematics", "subtopic": "Linear Algebra", "difficulty": 0.5, "estimated_minutes": 18, "body": "Vectors, matrices, dot products, eigenvalues, and SVD — all the linear algebra you need for understanding ML algorithms.", "video_url": None, "is_ai_recommended": True},
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

    return {
        "items": items[:limit],
        "total": len(items[:limit]),
        "has_more": has_more,
    }


@router.get("/{item_id}")
async def get_content(item_id: str, user_id: str = Depends(get_current_user_id)):
    _ensure_seed()
    item = col_content().find_one({"id": item_id}, PROJ)
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")
    return item
