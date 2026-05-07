import uuid
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.learner import LearnerProfile
from app.models.user import User
from app.models.quiz import QuizSession, ProgressRecord
from app.schemas.quiz import QuizGenerateRequest, QuizSessionSchema, QuizQuestion, QuizSubmitRequest, QuizSubmitResult, EloUpdate
from app.agents.orchestrator import orchestrator
from app.agents.progress_agent import calculate_elo_update
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()


async def _get_learner(user_id: str, db: AsyncSession) -> LearnerProfile:
    result = await db.execute(
        select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
    )
    learner = result.scalar_one_or_none()
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")
    return learner


@router.post("/generate", response_model=QuizSessionSchema)
async def generate_quiz(
    body: QuizGenerateRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner = await _get_learner(user_id, db)
    log.info("quiz_generate_start", topic=body.topic, learner_id=str(learner.id))

    state = {
        "learner_id": str(learner.id),
        "task_type": "quiz",
        "messages": [],
        "learner_profile": {},
        "topic_proficiency": learner.topic_proficiency_map or {},
        "current_topic": body.topic,
        "quiz_questions": [],
        "curriculum_path": [],
        "doubt_response": "",
        "progress_delta": {},
        "bloom_level": body.bloom_level or "",
        "error": None,
    }

    result = await orchestrator.ainvoke(state)
    questions = result.get("quiz_questions", [])
    bloom_level = result.get("bloom_level", "understand")

    quiz_session = QuizSession(
        id=str(uuid.uuid4()),
        learner_id=learner.id,
        topic=body.topic,
        bloom_level=bloom_level,
        questions=questions,
    )
    db.add(quiz_session)
    await db.commit()

    return QuizSessionSchema(
        quiz_id=str(quiz_session.id),
        topic=body.topic,
        bloom_level=bloom_level,
        questions=[QuizQuestion(**q) for q in questions],
        time_per_question=60,
    )


@router.get("/{quiz_id}", response_model=QuizSessionSchema)
async def get_quiz(
    quiz_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(QuizSession).where(QuizSession.id == quiz_id))
    quiz = result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    return QuizSessionSchema(
        quiz_id=str(quiz.id),
        topic=quiz.topic,
        bloom_level=quiz.bloom_level,
        questions=[QuizQuestion(**q) for q in quiz.questions],
        time_per_question=60,
    )


@router.post("/{quiz_id}/submit", response_model=QuizSubmitResult)
async def submit_quiz(
    quiz_id: str,
    body: QuizSubmitRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(QuizSession).where(QuizSession.id == quiz_id))
    quiz = result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    learner = await _get_learner(user_id, db)

    # Grade answers
    correct_count = 0
    weak_topics: list[str] = []
    questions = quiz.questions or []
    answers = body.answers or []

    for i, q in enumerate(questions):
        correct_index = q.get("correct_index", 0)
        user_answer = answers[i] if i < len(answers) else -1
        if user_answer == correct_index:
            correct_count += 1
        else:
            weak_topics.append(quiz.topic)

    score = correct_count / max(len(questions), 1)

    # Elo update via progress agent
    old_elo = (learner.topic_proficiency_map or {}).get(quiz.topic, 500.0)
    new_elo = calculate_elo_update(old_elo, score)

    # Update learner profile
    proficiency = dict(learner.topic_proficiency_map or {})
    proficiency[quiz.topic] = new_elo
    learner.topic_proficiency_map = proficiency
    learner.xp += int(score * 100)

    # Record progress
    db.add(ProgressRecord(
        id=str(uuid.uuid4()),
        learner_id=learner.id,
        topic=quiz.topic,
        elo_score=new_elo,
    ))

    # Update quiz session
    quiz.answers = answers
    quiz.score = score
    quiz.weak_topics = list(set(weak_topics))
    quiz.completed_at = datetime.now(timezone.utc)
    if body.reflection:
        quiz.sentiment_mood = "NEUTRAL"  # Updated by Celery task

    await db.commit()
    log.info("quiz_submitted", quiz_id=quiz_id, score=score, elo_update=new_elo - old_elo)

    return QuizSubmitResult(
        score=score,
        correct_count=correct_count,
        weak_topics=list(set(weak_topics))[:5],
        elo_update=EloUpdate(topic=quiz.topic, old_elo=old_elo, new_elo=new_elo),
    )
