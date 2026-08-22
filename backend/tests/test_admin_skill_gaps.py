"""Tests for the org skill-gap aggregation behind the admin dashboard.

This panel used to render eight hardcoded percentages as if they were live analytics.
It now aggregates real proficiency, so these tests pin the arithmetic, the noise filter,
and the superuser gate.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.routers.admin as admin_router
from app.agents.progress import MASTERY_ELO


@pytest.fixture
def as_superuser():
    from app.auth.jwt import require_superuser
    from app.main import app

    app.dependency_overrides[require_superuser] = lambda: "root"
    yield
    app.dependency_overrides.pop(require_superuser, None)


def _mock_aggregate(monkeypatch, rows: list[dict]) -> dict:
    """Stand in for the Mongo aggregation, capturing the pipeline it was handed."""
    captured: dict = {}
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=rows)

    async def _aggregate(pipeline):
        captured["pipeline"] = pipeline
        return cursor

    col = MagicMock()
    col.aggregate = _aggregate
    monkeypatch.setattr(admin_router, "col_learners", lambda: col)
    return captured


@pytest.mark.asyncio
async def test_skill_gaps_shape_and_arithmetic(client, as_superuser, monkeypatch):
    _mock_aggregate(
        monkeypatch,
        [
            {"_id": "Docker", "learners": 2, "below": 2, "avg_elo": 375.0},
            {"_id": "SQL", "learners": 3, "below": 2, "avg_elo": 650.0},
            {"_id": "Python", "learners": 3, "below": 1, "avg_elo": 626.6667},
        ],
    )

    r = await client.get("/api/v1/admin/skill-gaps")

    assert r.status_code == 200
    body = r.json()
    assert body["mastery_elo"] == MASTERY_ELO
    rows = {i["name"]: i for i in body["items"]}
    assert rows["Docker"]["pct"] == 1.0
    assert rows["SQL"]["pct"] == round(2 / 3, 4)
    assert rows["Python"]["pct"] == round(1 / 3, 4)
    # Raw counts travel with the percentage — 100% of 2 is not 100% of 40.
    assert rows["Docker"]["below_mastery"] == 2 and rows["Docker"]["learners"] == 2
    assert rows["Python"]["avg_elo"] == 626.7


@pytest.mark.asyncio
async def test_pipeline_filters_noise_and_uses_the_mastery_constant(
    client, as_superuser, monkeypatch
):
    """A topic one person touched is not an org signal, and 700 is never hardcoded."""
    captured = _mock_aggregate(monkeypatch, [])

    await client.get("/api/v1/admin/skill-gaps")

    pipeline = captured["pipeline"]
    stages = [next(iter(s)) for s in pipeline]
    assert "$objectToArray" in str(pipeline), (
        "must unroll the per-learner proficiency map"
    )
    assert {"$match": {"learners": {"$gte": 2}}} in pipeline
    assert "$limit" in stages and "$sort" in stages
    # The threshold comes from agents/progress.py, not a literal.
    assert str(MASTERY_ELO) in str(pipeline)


@pytest.mark.asyncio
async def test_empty_aggregation_is_not_an_error(client, as_superuser, monkeypatch):
    """A brand-new deployment has no overlapping topics; that renders an empty state."""
    _mock_aggregate(monkeypatch, [])

    r = await client.get("/api/v1/admin/skill-gaps")

    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_skill_gaps_requires_superuser(client):
    """No dependency override here — the real gate must reject an anonymous caller."""
    r = await client.get("/api/v1/admin/skill-gaps")
    assert r.status_code in (401, 403)


def test_no_hardcoded_topic_gaps_remain():
    """The fabricated eight-row constant must not come back."""
    from pathlib import Path

    page = Path(__file__).resolve().parents[2] / "frontend/src/pages/AdminPage.tsx"
    if not page.exists():  # backend-only checkouts
        pytest.skip("frontend not present")
    source = page.read_text()
    assert "TOPIC_GAPS" not in source
    assert "getSkillGaps" in source
