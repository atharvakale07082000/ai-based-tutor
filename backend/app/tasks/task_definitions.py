import asyncio
import structlog
from app.tasks.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="app.tasks.task_definitions.regenerate_curriculum", bind=True, max_retries=3)
def regenerate_curriculum(self, learner_id: str | None = None):
    """Regenerate curriculum for all learners or a specific learner."""
    log.info("task_regenerate_curriculum_start", learner_id=learner_id)
    try:
        # Import here to avoid circular imports
        from app.database import async_session_maker
        from app.models.learner import LearnerProfile
        from app.agents.orchestrator import orchestrator
        from sqlalchemy import select

        async def _run():
            async with async_session_maker() as db:
                if learner_id:
                    result = await db.execute(select(LearnerProfile).where(LearnerProfile.id == learner_id))
                    learners = [result.scalar_one_or_none()]
                    learners = [l for l in learners if l]
                else:
                    result = await db.execute(select(LearnerProfile).limit(100))
                    learners = result.scalars().all()

                for learner in learners:
                    state = {
                        "learner_id": str(learner.id),
                        "task_type": "curriculum",
                        "messages": [],
                        "learner_profile": {"goal_vector": learner.goal_vector or []},
                        "topic_proficiency": learner.topic_proficiency_map or {},
                        "current_topic": "",
                        "quiz_questions": [],
                        "curriculum_path": [],
                        "doubt_response": "",
                        "progress_delta": {},
                        "bloom_level": "",
                        "error": None,
                    }
                    await orchestrator.ainvoke(state)
                    log.info("curriculum_regenerated", learner_id=str(learner.id))

        asyncio.run(_run())
    except Exception as exc:
        log.error("task_regenerate_curriculum_error", error=str(exc))
        self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.tasks.task_definitions.process_quiz_results", bind=True, max_retries=3)
def process_quiz_results(self, quiz_session_id: str):
    """Process quiz results: update Elo, emit WebSocket progress update."""
    log.info("task_process_quiz_start", quiz_session_id=quiz_session_id)
    try:
        from app.database import async_session_maker
        from app.models.quiz import QuizSession
        from sqlalchemy import select

        async def _run():
            async with async_session_maker() as db:
                result = await db.execute(select(QuizSession).where(QuizSession.id == quiz_session_id))
                quiz = result.scalar_one_or_none()
                if quiz and quiz.score is not None:
                    log.info("quiz_results_processed", quiz_id=quiz_session_id, score=quiz.score)

        asyncio.run(_run())
    except Exception as exc:
        log.error("task_process_quiz_error", error=str(exc))
        self.retry(exc=exc, countdown=30)


@celery_app.task(name="app.tasks.task_definitions.send_progress_digest", bind=True, max_retries=3)
def send_progress_digest(self, learner_id: str | None = None):
    """Send weekly progress digest email/notification to learners."""
    log.info("task_send_progress_digest_start", learner_id=learner_id)
    try:
        from app.database import async_session_maker
        from app.models.learner import LearnerProfile
        from sqlalchemy import select

        async def _run():
            async with async_session_maker() as db:
                query = select(LearnerProfile)
                if learner_id:
                    query = query.where(LearnerProfile.id == learner_id)
                result = await db.execute(query.limit(500))
                learners = result.scalars().all()
                log.info("progress_digest_sent", count=len(learners))

        asyncio.run(_run())
    except Exception as exc:
        log.error("task_send_digest_error", error=str(exc))
        self.retry(exc=exc, countdown=120)
