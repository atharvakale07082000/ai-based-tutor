"""
Learner profile and activity log API.

Endpoints:
  GET    /profile/activity-logs   — paginated activity log for the learner
  GET    /profile/activity-stats  — aggregated stats (actions per day, top endpoints)
  DELETE /profile/activity-logs   — clear all activity logs for the learner
"""

import structlog
from fastapi import APIRouter, Depends, Query

from app.auth.jwt import get_current_user_id
from app.services import activity_log_service

router = APIRouter()
log = structlog.get_logger()


@router.get("/activity-logs")
async def get_activity_logs(
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    action_filter: str | None = None,
    user_id: str = Depends(get_current_user_id),
):
    """Return a paginated activity log for the current user, optionally filtered by action type."""
    logs, total = await activity_log_service.get_user_logs(user_id, limit=limit, skip=skip, action_filter=action_filter)
    return {"logs": logs, "total": total}


@router.get("/activity-stats")
async def get_activity_stats(user_id: str = Depends(get_current_user_id)):
    """Return aggregated stats — actions per day and most-used endpoints — for the current user."""
    return await activity_log_service.get_log_stats(user_id)


@router.delete("/activity-logs")
async def clear_activity_logs(user_id: str = Depends(get_current_user_id)):
    """Delete all activity log entries for the current user and return the deleted count."""
    deleted = await activity_log_service.delete_user_logs(user_id)
    return {"deleted": True, "count": deleted, "message": f"Deleted {deleted} activity log entries"}
