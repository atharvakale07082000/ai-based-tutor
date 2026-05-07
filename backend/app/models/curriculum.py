import uuid
from datetime import datetime, timezone
from sqlalchemy import Integer, Boolean, DateTime, ForeignKey, String
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CurriculumPath(Base):
    __tablename__ = "curriculum_paths"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
