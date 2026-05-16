from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class MessageSchema(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class DoubtStreamRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    topic_context: str = Field(default="", max_length=300)
    session_id: str | None = None
    history: list[MessageSchema] = Field(default=[], max_length=20)


class DoubtSessionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_context: str | None
    sentiment_mood: str | None
    started_at: str
    ended_at: str | None
    message_count: int
