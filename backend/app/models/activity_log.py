"""Pydantic model for learner activity log entries."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ActivityLog(BaseModel):
    id: str
    user_id: str
    action: str
    method: str
    endpoint: str
    ip_address: str | None = None
    user_agent: str | None = None
    status_code: int
    duration_ms: int
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
