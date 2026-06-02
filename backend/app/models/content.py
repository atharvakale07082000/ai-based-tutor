import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subtopic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    difficulty: Mapped[float] = mapped_column(Float, default=0.5)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=15)
    body: Mapped[str] = mapped_column(Text, default="")
    video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_ai_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
