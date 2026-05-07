from pydantic import BaseModel, ConfigDict


class MessageSchema(BaseModel):
    role: str
    content: str


class DoubtStreamRequest(BaseModel):
    question: str
    topic_context: str = ""
    session_id: str | None = None
    history: list[MessageSchema] = []


class DoubtSessionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_context: str | None
    sentiment_mood: str | None
    started_at: str
    ended_at: str | None
    message_count: int
