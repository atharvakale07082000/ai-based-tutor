"""
Strands ``@tool`` adapters over the master tool registry (``app/tools``).

The registry keeps ownership of execution (timeouts, latency capture, structured
logging); these adapters only expose each tool to the Strands agent loop with an
LLM-facing docstring. Errors come back as ``{"error": ...}`` payloads so the
model can read the observation and adjust, exactly like the old ReAct loop.
"""

from __future__ import annotations

from typing import Any

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
async def get_topic_graph() -> dict:
    """Fetch the topic dependency graph and available learning domains."""
    return await _call("get_topic_graph", {})


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


# ── Learner-scoped tools ──────────────────────────────────────────────────────
#
# These four act on ONE learner's data. They used to take ``learner_id`` as a normal
# tool parameter, which made the model responsible for copying the right UUID out of a
# JSON blob on every call — i.e. the server asked the model who the user was.
#
# Two things went wrong with that. The security shape is backwards: a write path must
# never take its subject from model output. And the reliability cost was live — when the
# model omitted or garbled the id, ``_get_proficiency`` returned
# ``{"proficiency": {}, "xp": 0, "streak": 0}`` and the specialist then told the learner,
# confidently and with no error anywhere, that they had no progress.
#
# So the id is bound here instead, by closure, from the authenticated request. The model
# cannot see it, cannot pass it, and cannot get it wrong.
#
# Tool NAMES must stay stable: ``stream_adapter._ACTION_TOOLS`` maps ``save_quiz`` /
# ``save_progress`` to the action cards the chat UI renders. Strands takes the tool name
# from the function name, and nesting these in a factory does not change that.


def learner_scoped_tools(learner_id: str) -> dict[str, Any]:
    """Build this request's learner-bound tools, keyed by tool name.

    Called once per specialist construction (agents are already built per request), so
    the closure can never outlive the request whose learner it is bound to.
    """

    @tool
    async def get_proficiency() -> dict:
        """Fetch the current learner's proficiency map (per-topic Elo), XP, and streak."""
        return await _call("get_proficiency", {"learner_id": learner_id})

    @tool
    async def save_quiz(topic: str, bloom_level: str, questions: list) -> dict:
        """Persist a generated quiz for the current learner; returns quiz_id and URL."""
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
    async def get_due_topics() -> dict:
        """List topics due for spaced-repetition review for the current learner."""
        return await _call("get_due_topics", {"learner_id": learner_id})

    return {
        "get_proficiency": get_proficiency,
        "save_quiz": save_quiz,
        "save_progress": save_progress,
        "get_due_topics": get_due_topics,
    }


# Every tool name `learner_scoped_tools` can return. Specialists name the subset they
# want via `SpecialistSpec.learner_tools`.
LEARNER_SCOPED: frozenset[str] = frozenset(
    {"get_proficiency", "save_quiz", "save_progress", "get_due_topics"}
)


# ── Stateless tool groups ─────────────────────────────────────────────────────
# Safe to share across requests: none of them touch a specific learner's records.
DOUBT_TOOLS = [check_guardrail, generate_explanation, web_search]
QUIZ_TOOLS = [score_difficulty, generate_quiz]
CURRICULUM_TOOLS = [classify_topic, get_topic_graph, web_search]
PROGRESS_TOOLS = [calculate_elo, analyze_sentiment]
ASSISTANT_TOOLS = [
    classify_topic,
    analyze_sentiment,
    score_difficulty,
    generate_quiz,
    get_embeddings,
    generate_explanation,
    get_topic_graph,
    calculate_elo,
    check_guardrail,
    web_search,
]
