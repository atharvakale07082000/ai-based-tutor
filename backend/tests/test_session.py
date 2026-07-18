"""
Behavioral tests for the study-session engine (``app.agents.session``), which
ports the old v1 curriculum/quiz/progress node logic to plain functions.

Patches ``app.agents.session._tool`` (the tool-registry boundary) so no network
or LLM is hit — matching the repo convention of patching at the agent-module level.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents import session
from app.agents.progress import calculate_elo_update


def _make_question(bloom: str = "apply") -> dict:
    return {
        "id": "q1",
        "question": "Which best illustrates the concept in practice today?",
        "options": ["A correct", "B", "C", "D"],
        "correct_index": 0,
        "explanation": "A is correct.",
        "bloom_level": bloom,
    }


async def _mock_tool(name: str, **kwargs) -> dict:
    if name == "classify_topic":
        return {"labels": ["Python Programming"], "scores": [0.9]}
    if name == "score_difficulty":
        return {"score": 0.45}
    if name == "analyze_sentiment":
        return {"label": "NEGATIVE", "score": 0.8}
    if name == "generate_quiz":
        count = kwargs.get("count", 5)
        return {
            "questions": [
                _make_question(kwargs.get("bloom_level", "apply")) for _ in range(count)
            ]
        }
    return {}


# ── get_bloom_level (ported Elo→Bloom bands) ──────────────────────────────────


@pytest.mark.parametrize(
    "elo,expected",
    [
        (100, "remember"),
        (400, "understand"),
        (500, "apply"),
        (700, "analyze"),
        (800, "evaluate"),
        (950, "create"),
    ],
)
def test_bloom_bands(elo, expected):
    assert session.get_bloom_level(elo) == expected


# ── Elo update math (ported) ──────────────────────────────────────────────────


def test_elo_increases_and_clamps():
    assert calculate_elo_update(500, 1.0) == 516.0
    assert calculate_elo_update(500, 0.0) == 484.0
    assert calculate_elo_update(995, 1.0) == 1000.0  # clamp high
    assert calculate_elo_update(5, 0.0) == 0.0  # clamp low


# ── build_curriculum ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_curriculum_prioritises_low_elo():
    with (
        patch.object(session, "_tool", side_effect=_mock_tool),
        patch.object(session, "_enrich_with_trending", side_effect=lambda g: g),
    ):
        proficiency = {}
        path = await session.build_curriculum(["I want to learn Python"], proficiency)
    assert path, "expected a non-empty curriculum path"
    assert all("subtopic" in item and "domain" in item for item in path)
    # priority is monotonic (ordered)
    assert [i["priority"] for i in path[:3]] == [0, 1, 2]


# ── run_session: start ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_session_start_generates_quiz_for_first_unmastered():
    state = {
        "task_type": "start",
        "topic_proficiency": {"Lists": 900, "Loops": 300},  # Lists mastered, Loops not
        "curriculum_path": [
            {
                "domain": "Python Programming",
                "subtopic": "Lists",
                "priority": 0,
                "elo": 900,
            },
            {
                "domain": "Python Programming",
                "subtopic": "Loops",
                "priority": 1,
                "elo": 300,
            },
        ],
        "mastery_threshold": 700.0,
    }
    with patch.object(session, "_tool", side_effect=_mock_tool):
        final = await session.run_session(state)
    assert final["current_topic"] == "Loops"  # skipped the mastered Lists
    assert final["session_complete"] is False
    assert len(final["quiz_questions"]) == 5
    assert final["bloom_level"] in {
        "remember",
        "understand",
        "apply",
        "analyze",
        "evaluate",
        "create",
    }


@pytest.mark.asyncio
async def test_run_session_complete_when_all_mastered():
    state = {
        "task_type": "start",
        "topic_proficiency": {"Lists": 900},
        "curriculum_path": [
            {
                "domain": "Python Programming",
                "subtopic": "Lists",
                "priority": 0,
                "elo": 900,
            }
        ],
        "mastery_threshold": 700.0,
    }
    with patch.object(session, "_tool", side_effect=_mock_tool):
        final = await session.run_session(state)
    assert final["session_complete"] is True
    assert final["current_topic"] == ""
    assert final["quiz_questions"] == []


# ── run_session: progress (Elo update + mood) ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_session_progress_updates_elo_and_captures_mood():
    state = {
        "task_type": "progress",
        "current_topic": "Loops",
        "topic_proficiency": {"Loops": 500},
        "curriculum_path": [
            {
                "domain": "Python Programming",
                "subtopic": "Loops",
                "priority": 0,
                "elo": 500,
            }
        ],
        "progress_delta": {
            "score": 1.0,
            "reflection": "That was really frustrating and hard.",
        },
        "mastery_threshold": 700.0,
    }
    with patch.object(session, "_tool", side_effect=_mock_tool):
        final = await session.run_session(state)
    delta = final["progress_delta"]
    assert delta["old_elo"] == 500 and delta["new_elo"] == 516.0
    assert delta["mood"] == "NEGATIVE"
    assert final["topic_proficiency"]["Loops"] == 516.0
    assert delta["elo_processed"] is True
