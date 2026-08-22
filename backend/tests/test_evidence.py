"""Tests for the Evidence Ledger — the append-only record behind every verified claim."""

import pytest

from app.agents.evidence import build_evidence, record_evidence, verify_evidence


def _row(**overrides):
    base = dict(
        learner_id="L1",
        skill="SQL",
        kind="quiz",
        score_0_1=0.8,
        bar_0_1=0.7,
        source_collection="quiz_sessions",
        source_id="Q1",
        occurred_at="2026-08-15T10:00:00+00:00",
    )
    return build_evidence(**{**base, **overrides})


def test_row_carries_the_verdict_against_its_own_bar():
    assert _row(score_0_1=0.8, bar_0_1=0.7)["passed"] is True
    assert _row(score_0_1=0.5, bar_0_1=0.7)["passed"] is False
    # Exactly on the bar clears it, matching how rounds are graded.
    assert _row(score_0_1=0.7, bar_0_1=0.7)["passed"] is True


def test_scores_are_clamped_to_the_unit_range():
    assert _row(score_0_1=1.7)["score_0_1"] == 1.0
    assert _row(score_0_1=-3)["score_0_1"] == 0.0
    assert _row(bar_0_1=99)["bar_0_1"] == 1.0


def test_hash_is_stable_for_identical_content():
    """Two rows describing the same graded event hash the same, despite distinct ids."""
    a, b = _row(), _row()
    assert a["id"] != b["id"]  # ids are per-row
    assert a["content_hash"] == b["content_hash"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("learner_id", "someone-else"),
        ("skill", "Python"),
        ("kind", "interview_round"),
        ("score_0_1", 0.9),
        ("bar_0_1", 0.6),
        ("occurred_at", "2020-01-01T00:00:00+00:00"),
        ("source_id", "Q2"),
    ],
)
def test_hash_changes_when_any_graded_fact_changes(field, value):
    """Tampering with any load-bearing field must break the row's own hash."""
    assert _row()["content_hash"] != _row(**{field: value})["content_hash"]


def test_verify_detects_tampering():
    row = _row()
    assert verify_evidence(row) is True

    row["score_0_1"] = 1.0  # someone edits the score in the database
    assert verify_evidence(row) is False


def test_verify_rejects_a_row_with_no_hash():
    row = _row()
    del row["content_hash"]
    assert verify_evidence(row) is False


@pytest.mark.asyncio
async def test_interview_evidence_is_keyed_by_the_learner_profile_id(monkeypatch):
    """One collection, one identifier.

    Interviews store the *user* id while every other collection keys on the
    learner-profile id. Writing both into the ledger would split a learner's evidence
    across two keys, and no query could ever retrieve all of it.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.pipelines import interview_review

    learners = MagicMock()
    learners.find_one = AsyncMock(
        return_value={"id": "learner-doc-id", "user_id": "user-id"}
    )
    monkeypatch.setattr("app.db.mongo.col_learners", lambda: learners)

    written: list[dict] = []

    async def _capture(**kwargs):
        written.append(kwargs)

    monkeypatch.setattr("app.agents.evidence.record_evidence", _capture)

    await interview_review._record_interview_evidence(
        {
            "interview_id": "iv-1",
            "user_id": "user-id",
            "module_title": "Coding round",
            "module_topics": ["Python"],
            "context": {"kind": "loop", "loop_id": "l-1", "round_key": "2-coding"},
        },
        8.0,
        7.5,
        "2026-08-15T10:00:00+00:00",
    )

    assert written, "no evidence recorded"
    assert all(row["learner_id"] == "learner-doc-id" for row in written)
    assert all(row["learner_id"] != "user-id" for row in written)
    assert {row["skill"] for row in written} == {"Coding round", "Python"}
    assert all(row["kind"] == "interview_round" for row in written)


@pytest.mark.asyncio
async def test_recording_never_raises_when_the_write_fails(monkeypatch):
    """The learner already earned the score — a ledger failure must not lose it."""

    def _boom():
        raise RuntimeError("mongo is down")

    monkeypatch.setattr("app.agents.evidence.col_evidence", _boom)

    result = await record_evidence(
        learner_id="L1",
        skill="SQL",
        kind="quiz",
        score_0_1=0.8,
        bar_0_1=0.7,
        source_collection="quiz_sessions",
        source_id="Q1",
    )
    assert result is None
