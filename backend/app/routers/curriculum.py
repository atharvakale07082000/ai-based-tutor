import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.learner import LearnerProfile
from app.models.user import User
from app.models.curriculum import CurriculumPath
from app.agents.orchestrator import orchestrator
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()


@router.get("")
async def get_curriculum(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner_result = await db.execute(
        select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
    )
    learner = learner_result.scalar_one_or_none()
    if not learner:
        return []

    curriculum_result = await db.execute(
        select(CurriculumPath)
        .where(CurriculumPath.learner_id == learner.id, CurriculumPath.is_active == True)
        .order_by(CurriculumPath.generated_at.desc())
        .limit(1)
    )
    curriculum = curriculum_result.scalar_one_or_none()
    return curriculum.topics if curriculum else []


@router.post("/generate")
async def generate_curriculum(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner_result = await db.execute(
        select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
    )
    learner = learner_result.scalar_one_or_none()
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")

    log.info("curriculum_generate_start", learner_id=str(learner.id))

    state = {
        "learner_id": str(learner.id),
        "task_type": "curriculum",
        "messages": [],
        "learner_profile": {
            "goal_vector": learner.goal_vector or [],
            "learning_style": learner.learning_style,
        },
        "topic_proficiency": learner.topic_proficiency_map or {},
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

    # Mark old curricula inactive
    old_result = await db.execute(
        select(CurriculumPath).where(CurriculumPath.learner_id == learner.id, CurriculumPath.is_active == True)
    )
    for old in old_result.scalars():
        old.is_active = False

    new_curriculum = CurriculumPath(
        learner_id=learner.id,
        version=learner.curriculum_version + 1,
        topics=curriculum_path,
        is_active=True,
    )
    learner.curriculum_version += 1
    db.add(new_curriculum)
    await db.commit()

    return {"items": curriculum_path, "version": learner.curriculum_version}
