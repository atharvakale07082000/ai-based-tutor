import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.agents.orchestrator import orchestrator
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_curricula, col_learners

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


@router.get("")
async def get_curriculum(user_id: str = Depends(get_current_user_id)):
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return []
    curriculum = await col_curricula().find_one(
        {"learner_id": learner["id"], "is_active": True},
        PROJ,
        sort=[("generated_at", -1)],
    )
    return curriculum["topics"] if curriculum else []


@router.post("/generate")
async def generate_curriculum(user_id: str = Depends(get_current_user_id)):
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")

    log.info("curriculum_generate_start", learner_id=learner["id"])

    state = {
        "learner_id": learner["id"],
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

    # Deactivate old curricula
    await col_curricula().update_many(
        {"learner_id": learner["id"], "is_active": True},
        {"$set": {"is_active": False}},
    )

    new_version = learner.get("curriculum_version", 1) + 1
    await col_curricula().insert_one(
        {
            "id": str(uuid.uuid4()),
            "learner_id": learner["id"],
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

    return {"items": curriculum_path, "version": new_version}


@router.get("/graph")
async def get_curriculum_graph(user_id: str = Depends(get_current_user_id)):
    """
    Return the topic dependency graph as nodes + directed edges.
    Used for the Progress page dependency visualization.
    """
    from app.prompts.loader import get_curriculum_config

    cfg = get_curriculum_config()
    topic_graph: dict[str, list[str]] = cfg.get("topic_graph", {})
    prerequisites: dict[str, list[str]] = cfg.get("prerequisites", {})

    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    proficiency = (learner or {}).get("topic_proficiency_map", {})

    nodes = []
    for domain, subtopics in topic_graph.items():
        for st in subtopics:
            elo = proficiency.get(st)
            nodes.append(
                {
                    "id": st,
                    "domain": domain,
                    "elo": elo,
                    "mastered": elo is not None and elo >= 700,
                    "started": elo is not None,
                }
            )

    edges = [{"from": prereq, "to": topic} for topic, prereqs in prerequisites.items() for prereq in prereqs]

    return {"nodes": nodes, "edges": edges}
