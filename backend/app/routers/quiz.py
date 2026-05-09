import uuid
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

from app.db.mongo import col_learners, col_quizzes, col_progress
from app.schemas.quiz import QuizGenerateRequest, QuizSessionSchema, QuizQuestion, QuizSubmitRequest, QuizSubmitResult, EloUpdate
from app.agents.orchestrator import orchestrator
from app.agents.progress_agent import calculate_elo_update
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


def _get_learner_or_404(user_id: str) -> dict:
    learner = col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(status_code=404, detail="Learner not found")
    return learner


@router.post("/generate", response_model=QuizSessionSchema)
async def generate_quiz(
    body: QuizGenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
    learner = _get_learner_or_404(user_id)
    log.info("quiz_generate_start", topic=body.topic, learner_id=learner["id"])

    state = {
        "learner_id": learner["id"],
        "task_type": "quiz",
        "messages": [],
        "learner_profile": {},
        "topic_proficiency": learner.get("topic_proficiency_map") or {},
        "current_topic": body.topic,
        "quiz_questions": [],
        "curriculum_path": [],
        "doubt_response": "",
        "progress_delta": {},
        "bloom_level": body.bloom_level or "",
        "error": None,
    }

    result = await orchestrator.ainvoke(state)
    questions = result.get("quiz_questions", [])
    bloom_level = result.get("bloom_level", "understand")

    quiz_id = str(uuid.uuid4())
    col_quizzes().insert_one({
        "id": quiz_id,
        "learner_id": learner["id"],
        "topic": body.topic,
        "bloom_level": bloom_level,
        "questions": questions,
        "answers": [],
        "score": None,
        "weak_topics": [],
        "sentiment_mood": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    })

    return QuizSessionSchema(
        quiz_id=quiz_id,
        topic=body.topic,
        bloom_level=bloom_level,
        questions=[QuizQuestion(**q) for q in questions],
        time_per_question=60,
    )


@router.get("/{quiz_id}", response_model=QuizSessionSchema)
async def get_quiz(quiz_id: str, user_id: str = Depends(get_current_user_id)):
    quiz = col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return QuizSessionSchema(
        quiz_id=quiz["id"],
        topic=quiz["topic"],
        bloom_level=quiz["bloom_level"],
        questions=[QuizQuestion(**q) for q in quiz.get("questions", [])],
        time_per_question=60,
    )


@router.post("/{quiz_id}/submit", response_model=QuizSubmitResult)
async def submit_quiz(
    quiz_id: str,
    body: QuizSubmitRequest,
    user_id: str = Depends(get_current_user_id),
):
    quiz = col_quizzes().find_one({"id": quiz_id}, PROJ)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    learner = _get_learner_or_404(user_id)

    questions = quiz.get("questions") or []
    answers = body.answers or []
    correct_count = 0
    weak_topics: list[str] = []

    for i, q in enumerate(questions):
        user_answer = answers[i] if i < len(answers) else -1
        if user_answer == q.get("correct_index", 0):
            correct_count += 1
        else:
            weak_topics.append(quiz["topic"])

    score = correct_count / max(len(questions), 1)

    proficiency = dict(learner.get("topic_proficiency_map") or {})
    old_elo = proficiency.get(quiz["topic"], 500.0)
    new_elo = calculate_elo_update(old_elo, score)
    proficiency[quiz["topic"]] = new_elo

    now = datetime.now(timezone.utc).isoformat()
    col_learners().update_one(
        {"user_id": user_id},
        {"$set": {
            "topic_proficiency_map": proficiency,
            "xp": learner.get("xp", 0) + int(score * 100),
            "updated_at": now,
        }},
    )

    col_progress().insert_one({
        "id": str(uuid.uuid4()),
        "learner_id": learner["id"],
        "topic": quiz["topic"],
        "elo_score": new_elo,
        "recorded_at": now,
    })

    col_quizzes().update_one(
        {"id": quiz_id},
        {"$set": {
            "answers": answers,
            "score": score,
            "weak_topics": list(set(weak_topics)),
            "completed_at": now,
        }},
    )

    log.info("quiz_submitted", quiz_id=quiz_id, score=score)
    return QuizSubmitResult(
        score=score,
        correct_count=correct_count,
        weak_topics=list(set(weak_topics))[:5],
        elo_update=EloUpdate(topic=quiz["topic"], old_elo=old_elo, new_elo=new_elo),
    )
