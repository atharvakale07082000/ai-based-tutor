"""Tests for job-readiness scoring (``app/agents/progress.py::job_readiness``).

Readiness is the dashboard's headline number, so the contract that matters most is the
negative one: with no graded evidence it must return None (the tile hides) rather than a
number invented from how many topics someone happens to be tracking.
"""

from __future__ import annotations

import pytest

from app.agents.progress import MASTERY_ELO, job_readiness


def test_no_evidence_returns_none():
    """Nothing graded yet = no readiness to report. Never 0%, which reads as a verdict."""
    assert job_readiness({}, []) is None


def test_tracked_topics_alone_are_not_evidence_of_readiness():
    """Adding topics to a plan is not achievement — the old bug rated it 10% per topic."""
    assert job_readiness({"python": 0.0, "sql": 0.0}, []) == 0.0


def test_mastery_coverage_drives_the_score_without_interviews():
    prof = {"a": MASTERY_ELO, "b": MASTERY_ELO, "c": 100.0, "d": 100.0}
    assert job_readiness(prof, []) == 50.0


def test_interviews_alone_score_against_their_own_bar():
    """A round is graded against the bar it was set, not a global 6.0."""
    assert job_readiness({}, [{"final_score": 8.0, "bar": 8.0}]) == 100.0
    assert job_readiness({}, [{"final_score": 4.0, "bar": 8.0}]) == 50.0


def test_exceeding_the_bar_does_not_score_above_100():
    assert job_readiness({}, [{"final_score": 10.0, "bar": 5.0}]) == 100.0


def test_interviews_outweigh_mastery_when_both_exist():
    """Interview performance is the stronger signal, so it carries the larger weight."""
    both = job_readiness({"a": MASTERY_ELO}, [{"final_score": 0.0, "bar": 8.0}])
    assert both is not None and both < 50.0


def test_ungraded_interviews_are_ignored():
    """An interview still in progress has no final_score and must not drag the number down."""
    assert job_readiness({}, [{"final_score": None, "bar": 8.0}]) is None


@pytest.mark.parametrize("bar", [0, None, -1])
def test_a_missing_or_nonsense_bar_falls_back_to_the_default(bar):
    from app.agents.bar import DEFAULT_BAR

    got = job_readiness({}, [{"final_score": DEFAULT_BAR, "bar": bar}])
    assert got == 100.0


def test_result_is_bounded_and_rounded():
    got = job_readiness({"a": 700.0, "b": 0.0, "c": 0.0}, [])
    assert got is not None and 0.0 <= got <= 100.0
    assert round(got, 1) == got
