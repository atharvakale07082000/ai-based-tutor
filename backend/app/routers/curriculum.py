"""
Curriculum API.

Endpoints:
  GET  /curriculum         — return the learner's current active curriculum topics
  POST /curriculum/generate — queue a background AI curriculum generation (non-blocking)
  GET  /curriculum/graph   — return the topic dependency graph (nodes + edges)
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.agents.orchestrator import orchestrator
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_curricula, col_learners

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


@router.get("")
async def get_curriculum(user_id: str = Depends(get_current_user_id)):
    """Return the learner's current active curriculum as an ordered list of topics."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return []
    curriculum = await col_curricula().find_one(
        {"learner_id": learner["id"], "is_active": True},
        PROJ,
        sort=[("generated_at", -1)],
    )
    return curriculum["topics"] if curriculum else []


async def _do_generate_curriculum(user_id: str, learner: dict) -> None:
    """Background worker: invoke the curriculum orchestrator and persist the result."""
    learner_id = learner["id"]
    log.info("curriculum_generate_start_bg", learner_id=learner_id)
    try:
        state = {
            "learner_id": learner_id,
            "task_type": "curriculum",
            "messages": [],
            "learner_profile": {
                "goal_vector": learner.get("goal_vector") or [],
                "learning_style": learner.get("learning_style", "visual"),
            },
            "topic_proficiency": learner.get("topic_proficiency_map") or {},
            "current_topic": "",
            "quiz_questions": [],
            "curriculum_path": [],
            "doubt_response": "",
            "progress_delta": {},
            "bloom_level": "",
            "error": None,
        }

        result = await orchestrator.ainvoke(state)
        curriculum_path = result.get("curriculum_path", [])

        await col_curricula().update_many(
            {"learner_id": learner_id, "is_active": True},
            {"$set": {"is_active": False}},
        )

        new_version = learner.get("curriculum_version", 1) + 1
        await col_curricula().insert_one(
            {
                "id": str(uuid.uuid4()),
                "learner_id": learner_id,
                "version": new_version,
                "topics": curriculum_path,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "is_active": True,
            }
        )
        await col_learners().update_one(
            {"user_id": user_id},
            {"$set": {"curriculum_version": new_version, "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        log.info("curriculum_generated_bg", learner_id=learner_id, topics=len(curriculum_path))
    except Exception as exc:
        log.error("curriculum_generate_failed", learner_id=learner_id, error=str(exc))


@router.post("/generate")
async def generate_curriculum(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
):
    """
    Queue a background AI curriculum generation for the learner.

    Returns immediately with status='queued'. The client should poll
    GET /curriculum until topics appear.
    """
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")

    background_tasks.add_task(_do_generate_curriculum, user_id, learner)
    return {"status": "queued", "learner_id": learner["id"]}


@router.get("/graph")
async def get_curriculum_graph(user_id: str = Depends(get_current_user_id)):
    """
    Return the topic dependency graph as nodes and directed edges.

    Used by the Progress page dependency visualisation. Each node carries
    the learner's current ELO for that topic (None if not started).
    """
    from app.prompts.loader import get_curriculum_config

    cfg = get_curriculum_config()
    topic_graph: dict[str, list[str]] = cfg.get("topic_graph", {})
    prerequisites: dict[str, list[str]] = cfg.get("prerequisites", {})

    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    proficiency = (learner or {}).get("topic_proficiency_map", {})

    nodes = [
        {
            "id": st,
            "domain": domain,
            "elo": proficiency.get(st),
            "mastered": proficiency.get(st) is not None and proficiency.get(st) >= 700,
            "started": proficiency.get(st) is not None,
        }
        for domain, subtopics in topic_graph.items()
        for st in subtopics
    ]

    edges = [{"from": prereq, "to": topic} for topic, prereqs in prerequisites.items() for prereq in prereqs]

    return {"nodes": nodes, "edges": edges}
