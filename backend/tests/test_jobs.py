"""Tests for the Job Tracker skill-gap agent (pure logic) and analysis stream."""

import pytest
from app.agents.skill_gap_agent import _match_elo, analyze_gap


def test_match_elo_bidirectional_and_best():
    prof = {"Python Programming": 820.0, "SQL": 560.0}
    # skill ⊆ topic
    assert _match_elo("Python", prof) == 820.0
    # topic ⊆ skill
    assert _match_elo("SQL queries", prof) == 560.0
    # no match
    assert _match_elo("Kubernetes", prof) is None


def test_analyze_gap_classifies_and_scores():
    prof = {"Python Programming": 820.0, "SQL": 560.0}
    out = analyze_gap(["Python", "SQL", "Kubernetes"], prof)

    statuses = {g["skill"]: g["status"] for g in out["skill_gaps"]}
    assert statuses == {"Python": "have", "SQL": "partial", "Kubernetes": "missing"}
    # (1.0 + 0.5 + 0.0) / 3 * 100
    assert out["readiness_score"] == 50.0

    rec_by_skill = {r["skill"]: r["type"] for r in out["recommendations"]}
    assert rec_by_skill["SQL"] == "quiz"  # partial → sharpen with a quiz
    assert rec_by_skill["Kubernetes"] == "course"  # missing → build a path


def test_analyze_gap_empty_skills():
    out = analyze_gap([], {"Python": 800.0})
    assert out["readiness_score"] == 0.0
    assert out["skill_gaps"] == []
    assert out["recommendations"] == []


def test_analyze_gap_all_have_no_recommendations():
    prof = {"Python": 800.0, "SQL": 750.0}
    out = analyze_gap(["Python", "SQL"], prof)
    assert out["readiness_score"] == 100.0
    assert out["recommendations"] == []


@pytest.mark.asyncio
async def test_analysis_stream_emits_steps_then_action(monkeypatch):
    """The reanalyze-style stream (no LLM parse) emits step events then a jd_analyzed action."""
    from app.routers.jobs import _analysis_stream

    # required_skills provided → no parse_jd / LLM call.
    event_stream = _analysis_stream("", {"Python": 800.0}, required_skills=["Python", "Go"])
    frames = [frame async for frame in event_stream()]

    # SSE frames: several `data: {...}` lines then a [DONE].
    assert frames[-1].strip() == "data: [DONE]"
    types = []
    import json

    for f in frames[:-1]:
        payload = json.loads(f[len("data: ") :].strip())
        types.append(payload["type"])
    assert "step" in types
    assert types[-1] == "action"
