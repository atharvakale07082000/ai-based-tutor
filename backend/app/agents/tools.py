"""
Strands ``@tool`` adapters over the master tool registry (``app/tools``).

The registry keeps ownership of execution (timeouts, latency capture, structured
logging); these adapters only expose each tool to the Strands agent loop with an
LLM-facing docstring. Errors come back as ``{"error": ...}`` payloads so the
model can read the observation and adjust, exactly like the old ReAct loop.
"""

from __future__ import annotations

from strands import tool

from app.tools import tool_registry


async def _call(name: str, args: dict) -> dict:
    result = await tool_registry.call(name, args)
    if result.result is not None:
        return result.result
    return {"error": result.error}


@tool
async def classify_topic(text: str, labels: list[str] | None = None) -> dict:
    """Classify free text into learning-domain labels (zero-shot).

    Args:
        text: The text to classify (e.g. a learning goal or question).
        labels: Optional candidate labels; sensible defaults are used when omitted.
    """
    return await _call("classify_topic", {"text": text, "labels": labels})


@tool
async def analyze_sentiment(text: str) -> dict:
    """Analyze the sentiment/mood of learner text (POSITIVE/NEGATIVE + score)."""
    return await _call("analyze_sentiment", {"text": text})


@tool
async def score_difficulty(text: str) -> dict:
    """Score how difficult a topic or question is, from 0.0 (easy) to 1.0 (hard)."""
    return await _call("score_difficulty", {"text": text})


@tool
async def generate_quiz(topic: str, bloom_level: str, count: int = 5) -> dict:
    """Generate Bloom-calibrated multiple-choice quiz questions for a topic.

    Args:
        topic: The subject to quiz on.
        bloom_level: Bloom taxonomy level (remember/understand/apply/analyze/evaluate/create).
        count: Number of questions (default 5).
    """
    return await _call(
        "generate_quiz", {"topic": topic, "bloom_level": bloom_level, "count": count}
    )


@tool
async def get_embeddings(text: str) -> dict:
    """Get a sentence-embedding vector for text (semantic similarity)."""
    return await _call("get_embeddings", {"text": text})


@tool
async def generate_explanation(
    topic: str, question: str, bloom_level: str = "understand"
) -> dict:
    """Generate a clear, learner-friendly explanation for a question on a topic."""
    return await _call(
        "generate_explanation",
        {"topic": topic, "question": question, "bloom_level": bloom_level},
    )


@tool
async def get_proficiency(learner_id: str) -> dict:
    """Fetch the learner's proficiency map (per-topic Elo), XP, and streak."""
    return await _call("get_proficiency", {"learner_id": learner_id})


@tool
async def get_topic_graph() -> dict:
    """Fetch the topic dependency graph and available learning domains."""
    return await _call("get_topic_graph", {})


@tool
async def save_quiz(
    learner_id: str, topic: str, bloom_level: str, questions: list
) -> dict:
    """Persist a generated quiz for the learner; returns quiz_id and URL."""
    return await _call(
        "save_quiz",
        {
            "learner_id": learner_id,
            "topic": topic,
            "bloom_level": bloom_level,
            "questions": questions,
        },
    )


@tool
async def save_progress(
    learner_id: str,
    topic: str,
    old_elo: float,
    new_elo: float,
    score: float,
    mood: str = "NEUTRAL",
) -> dict:
    """Persist a progress update (Elo change + mood) for a topic; returns XP delta."""
    return await _call(
        "save_progress",
        {
            "learner_id": learner_id,
            "topic": topic,
            "old_elo": old_elo,
            "new_elo": new_elo,
            "score": score,
            "mood": mood,
        },
    )


@tool
async def get_due_topics(learner_id: str) -> dict:
    """List topics due for spaced-repetition review for the learner."""
    return await _call("get_due_topics", {"learner_id": learner_id})


@tool
async def calculate_elo(
    current_elo: float, score: float, expected_score: float = 0.5
) -> dict:
    """Compute an updated Elo proficiency from a quiz score (K=32, clamped 0-1000)."""
    return await _call(
        "calculate_elo",
        {
            "current_elo": current_elo,
            "score": score,
            "expected_score": expected_score,
        },
    )


@tool
async def check_guardrail(text: str) -> dict:
    """Run the safety guardrail over text; returns passed/reason/sanitized."""
    return await _call("check_guardrail", {"text": text})


@tool
async def web_search(query: str, max_results: int = 6) -> dict:
    """Search the web; returns result titles, snippets, and URLs."""
    return await _call("web_search", {"query": query, "max_results": max_results})


# Grouped for the specialist builders (mirrors the old per-agent tool_names lists).
DOUBT_TOOLS = [check_guardrail, get_proficiency, generate_explanation, web_search]
QUIZ_TOOLS = [get_proficiency, score_difficulty, generate_quiz, save_quiz]
CURRICULUM_TOOLS = [classify_topic, get_topic_graph, get_proficiency, web_search]
PROGRESS_TOOLS = [get_proficiency, calculate_elo, analyze_sentiment, save_progress]
ASSISTANT_TOOLS = [
    classify_topic,
    analyze_sentiment,
    score_difficulty,
    generate_quiz,
    get_embeddings,
    generate_explanation,
    get_proficiency,
    get_topic_graph,
    save_quiz,
    save_progress,
    get_due_topics,
    calculate_elo,
    check_guardrail,
    web_search,
]
