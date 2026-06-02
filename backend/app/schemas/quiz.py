from typing import Literal

from pydantic import BaseModel, Field

BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]


class QuizQuestion(BaseModel):
    id: str
    question: str
    options: list[str]
    correct_index: int
    explanation: str
    bloom_level: str


class QuizGenerateRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    bloom_level: BloomLevel | None = None
    count: int = Field(default=5, ge=3, le=20)


class QuizSessionSchema(BaseModel):
    quiz_id: str
    topic: str
    bloom_level: str
    questions: list[QuizQuestion]
    time_per_question: int = 60


class QuizSubmitRequest(BaseModel):
    answers: list[int] = Field(max_length=50)
    reflection: str | None = Field(None, max_length=2000)


class EloUpdate(BaseModel):
    topic: str
    old_elo: float
    new_elo: float


class QuizSubmitResult(BaseModel):
    score: float
    correct_count: int
    weak_topics: list[str]
    elo_update: EloUpdate
