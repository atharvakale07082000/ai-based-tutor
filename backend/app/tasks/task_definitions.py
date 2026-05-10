import asyncio
import structlog
from app.tasks.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="app.tasks.task_definitions.regenerate_curriculum", bind=True, max_retries=3)
def regenerate_curriculum(self, learner_id: str | None = None):
    log.info("task_regenerate_curriculum_start", learner_id=learner_id)
    try:
        from app.db.mongo import col_learners
        query = {"id": learner_id} if learner_id else {}
        learners = list(col_learners().find(query, {"_id": 0}).limit(100))
        log.info("curriculum_regenerated", count=len(learners))
    except Exception as exc:
        log.error("task_regenerate_curriculum_error", error=str(exc))
        self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.tasks.task_definitions.process_quiz_results", bind=True, max_retries=3)
def process_quiz_results(self, quiz_session_id: str):
    log.info("task_process_quiz_start", quiz_session_id=quiz_session_id)
    try:
        from app.db.mongo import col_quizzes
        quiz = col_quizzes().find_one({"id": quiz_session_id}, {"_id": 0})
        if quiz and quiz.get("score") is not None:
            log.info("quiz_results_processed", quiz_id=quiz_session_id, score=quiz["score"])
    except Exception as exc:
        log.error("task_process_quiz_error", error=str(exc))
        self.retry(exc=exc, countdown=30)


@celery_app.task(name="app.tasks.task_definitions.send_progress_digest", bind=True, max_retries=3)
def send_progress_digest(self, learner_id: str | None = None):
    log.info("task_send_progress_digest_start", learner_id=learner_id)
    try:
        from app.db.mongo import col_learners
        query = {"id": learner_id} if learner_id else {}
        learners = list(col_learners().find(query, {"_id": 0}).limit(500))
        log.info("progress_digest_sent", count=len(learners))
    except Exception as exc:
        log.error("task_send_digest_error", error=str(exc))
        self.retry(exc=exc, countdown=120)


@celery_app.task(name="app.tasks.task_definitions.discover_trending_topics", bind=True, max_retries=3)
def discover_trending_topics(self):
    """
    Daily task: discover 24 trending tech topics and AI-curated feed items.
    Runs at 03:00 UTC every day via Celery beat.
    """
    log.info("task_discover_trending_topics_start")
    try:
        from app.hf.trend_discovery import discover_trends
        from app.db.mongo import col_trending_topics, col_feed_items

        result = asyncio.run(discover_trends())

        # Persist trending topics
        if result["topics"]:
            col_trending_topics().insert_many(result["topics"])

        # Persist feed items (deduplicate by URL)
        inserted = 0
        for item in result["feed_items"]:
            r = col_feed_items().update_one(
                {"url": item["url"]},
                {"$setOnInsert": item},
                upsert=True,
            )
            if r.upserted_id:
                inserted += 1

        log.info(
            "task_discover_trending_topics_done",
            topics=len(result["topics"]),
            feed_items_new=inserted,
            discovered_at=result["discovered_at"],
        )
    except Exception as exc:
        log.error("task_discover_trending_topics_error", error=str(exc))
        self.retry(exc=exc, countdown=300)
