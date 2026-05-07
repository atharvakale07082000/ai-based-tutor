import uuid
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.learner import LearnerProfile
from app.models.user import User
from app.models.quiz import QuizSession, ProgressRecord
from app.models.curriculum import CurriculumPath
from app.agents.orchestrator import orchestrator
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()

_DEFAULT_STATE_EXTRAS = {
    "next_action": "",
    "resume_action": "",
    "iteration_count": 0,
    "max_iterations": 10,
    "session_complete": False,
    "mastery_threshold": 700.0,
}


class SessionStartResponse(BaseModel):
    session_id: str
    curriculum_path: list[dict]
    current_topic: str
    bloom_level: str
    quiz_questions: list[dict]
    session_complete: bool
    iteration_count: int


class SessionAdvanceRequest(BaseModel):
    quiz_id: str
    answers: list[int]
    reflection: str = ""


class SessionAdvanceResponse(BaseModel):
    topic_proficiency: dict
    progress_delta: dict
    current_topic: str
    bloom_level: str
    quiz_questions: list[dict]
    session_complete: bool
    iteration_count: int


async def _get_learner(user_id: str, db: AsyncSession) -> LearnerProfile:
    result = await db.execute(
        select(LearnerProfile)
        .join(User, User.id == LearnerProfile.user_id)
        .where(User.id == user_id)
    )
    learner = result.scalar_one_or_none()
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")
    return learner


async def _load_active_curriculum(learner_id, db: AsyncSession) -> tuple[list[dict], CurriculumPath | None]:
    result = await db.execute(
        select(CurriculumPath)
        .where(CurriculumPath.learner_id == learner_id, CurriculumPath.is_active == True)
        .order_by(CurriculumPath.generated_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()
    return (record.topics if record else []), record


@router.post("/start", response_model=SessionStartResponse)
async def start_session(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Start an autonomous learning session.

    The graph executes autonomously:
      planner → (curriculum if needed) → planner → quiz → END

    Returns the generated curriculum and first quiz in one call.
    """
    learner = await _get_learner(user_id, db)
    existing_path, _ = await _load_active_curriculum(learner.id, db)

    state = {
        "learner_id": str(learner.id),
        "task_type": "start",
        "messages": [],
        "learner_profile": {
            "goal_vector": learner.goal_vector or [],
            "learning_style": learner.learning_style,
        },
        "topic_proficiency": learner.topic_proficiency_map or {},
        "current_topic": "",
        "quiz_questions": [],
        "curriculum_path": existing_path,
        "doubt_response": "",
        "progress_delta": {},
        "bloom_level": "",
        "error": None,
        **_DEFAULT_STATE_EXTRAS,
    }

    log.info("session_start", learner_id=str(learner.id), existing_curriculum=bool(existing_path))
    final = await orchestrator.ainvoke(state)

    # Persist rebuilt curriculum if the planner triggered a new one
    new_path = final.get("curriculum_path", existing_path)
    if new_path and new_path != existing_path:
        old_result = await db.execute(
            select(CurriculumPath).where(
                CurriculumPath.learner_id == learner.id,
                CurriculumPath.is_active == True,
            )
        )
        for old in old_result.scalars():
            old.is_active = False
        db.add(CurriculumPath(
            learner_id=learner.id,
            version=learner.curriculum_version + 1,
            topics=new_path,
            is_active=True,
        ))
        learner.curriculum_version += 1

    # Persist the quiz session that the planner chose to generate
    questions = final.get("quiz_questions", [])
    session_id = str(uuid.uuid4())
    if questions:
        db.add(QuizSession(
            id=session_id,
            learner_id=learner.id,
            topic=final.get("current_topic", ""),
            bloom_level=final.get("bloom_level", "understand"),
            questions=questions,
        ))

    await db.commit()
    log.info("session_start_done", session_id=session_id, topic=final.get("current_topic"))

    return SessionStartResponse(
        session_id=session_id,
        curriculum_path=new_path,
        current_topic=final.get("current_topic", ""),
        bloom_level=final.get("bloom_level", "understand"),
        quiz_questions=questions,
        session_complete=final.get("session_complete", False),
        iteration_count=final.get("iteration_count", 1),
    )


@router.post("/advance", response_model=SessionAdvanceResponse)
async def advance_session(
    body: SessionAdvanceRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit quiz answers and advance the session autonomously.

    The graph executes autonomously:
      progress_agent → planner → quiz (next topic) → END
      (or planner → END if all topics mastered)

    Returns updated proficiency and the next quiz, or session_complete=True.
    """
    result_q = await db.execute(select(QuizSession).where(QuizSession.id == body.quiz_id))
    quiz = result_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    learner = await _get_learner(user_id, db)
    curriculum_path, _ = await _load_active_curriculum(learner.id, db)

    # Grade answers
    questions = quiz.questions or []
    answers = body.answers or []
    correct_count = sum(
        1 for i, q in enumerate(questions)
        if i < len(answers) and answers[i] == q.get("correct_index", 0)
    )
    score = correct_count / max(len(questions), 1)

    state = {
        "learner_id": str(learner.id),
        "task_type": "progress",
        "messages": [],
        "learner_profile": {},
        "topic_proficiency": learner.topic_proficiency_map or {},
        "current_topic": quiz.topic,
        "quiz_questions": [],
        "curriculum_path": curriculum_path,
        "doubt_response": "",
        "progress_delta": {"score": score, "reflection": body.reflection},
        "bloom_level": "",
        "error": None,
        **_DEFAULT_STATE_EXTRAS,
    }

    log.info("session_advance", learner_id=str(learner.id), topic=quiz.topic, score=score)
    final = await orchestrator.ainvoke(state)

    # Persist updated proficiency
    proficiency = final.get("topic_proficiency", {})
    learner.topic_proficiency_map = proficiency
    learner.xp += int(score * 100)

    # Record the Elo change
    delta = final.get("progress_delta", {})
    db.add(ProgressRecord(
        id=str(uuid.uuid4()),
        learner_id=learner.id,
        topic=quiz.topic,
        elo_score=delta.get("new_elo", proficiency.get(quiz.topic, 500.0)),
    ))

    # Close out the submitted quiz
    quiz.answers = answers
    quiz.score = score
    quiz.completed_at = datetime.now(timezone.utc)

    # Persist the next quiz the planner chose to generate (if any)
    next_questions = final.get("quiz_questions", [])
    next_session_id = str(uuid.uuid4())
    if next_questions:
        db.add(QuizSession(
            id=next_session_id,
            learner_id=learner.id,
            topic=final.get("current_topic", ""),
            bloom_level=final.get("bloom_level", "understand"),
            questions=next_questions,
        ))

    await db.commit()
    log.info(
        "session_advance_done",
        next_topic=final.get("current_topic"),
        session_complete=final.get("session_complete"),
    )

    return SessionAdvanceResponse(
        topic_proficiency=proficiency,
        progress_delta=delta,
        current_topic=final.get("current_topic", ""),
        bloom_level=final.get("bloom_level", "understand"),
        quiz_questions=next_questions,
        session_complete=final.get("session_complete", False),
        iteration_count=final.get("iteration_count", 1),
    )
