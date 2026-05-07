from pydantic import BaseModel


class QuizQuestion(BaseModel):
    id: str
    question: str
    options: list[str]
    correct_index: int
    explanation: str
    bloom_level: str


class QuizGenerateRequest(BaseModel):
    topic: str
    bloom_level: str | None = None
    count: int = 5


class QuizSessionSchema(BaseModel):
    quiz_id: str
    topic: str
    bloom_level: str
    questions: list[QuizQuestion]
    time_per_question: int = 60


class QuizSubmitRequest(BaseModel):
    answers: list[int]
    reflection: str | None = None


class EloUpdate(BaseModel):
    topic: str
    old_elo: float
    new_elo: float


class QuizSubmitResult(BaseModel):
    score: float
    correct_count: int
    weak_topics: list[str]
    elo_update: EloUpdate
