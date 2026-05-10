from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "ai_tutor",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.task_definitions"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "weekly-curriculum-regeneration": {
        "task": "app.tasks.task_definitions.regenerate_curriculum",
        "schedule": crontab(day_of_week=1, hour=0, minute=0),  # Monday midnight UTC
    },
    "daily-trend-discovery": {
        "task": "app.tasks.task_definitions.discover_trending_topics",
        "schedule": crontab(hour=3, minute=0),  # Every day at 03:00 UTC
    },
}
