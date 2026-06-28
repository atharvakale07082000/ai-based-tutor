"""
Marker-gated DeepEval quality suite (run with `pytest -m evals`).

These hit the live NVIDIA judge and make several LLM calls per metric, so they're opt-in and excluded
from the normal test run. They use the domain golden dataset (tutoring / career-switch content).
"""

import pytest

pytest.importorskip(
    "deepeval"
)  # opt-in dep; install with `uv pip install deepeval instructor`

from app.evals.deepeval_judge import get_judge
from app.evals.deepeval_metrics import (
    _conversation_metrics,
    _faithfulness_metric,
    _single_turn_metrics,
)

from tests.evals.datasets import FAITHFUL_DOUBT, TUTOR_CONVERSATION, UNFAITHFUL_DOUBT

pytestmark = pytest.mark.evals


def test_faithfulness_separates_faithful_from_unfaithful():
    judge = get_judge()
    _, good = _faithfulness_metric(judge, 0.6)
    good.measure(FAITHFUL_DOUBT)
    _, bad = _faithfulness_metric(judge, 0.6)
    bad.measure(UNFAITHFUL_DOUBT)
    assert good.score >= 0.6, f"faithful answer scored low: {good.score}"
    assert good.score > bad.score, (
        f"faithful({good.score}) should beat unfaithful({bad.score})"
    )


def test_single_turn_metrics_score_a_good_tutor_answer():
    judge = get_judge()
    for eval_type, metric in _single_turn_metrics(judge, 0.6):
        metric.measure(FAITHFUL_DOUBT)
        assert 0.0 <= (metric.score or 0.0) <= 1.0, eval_type


def test_conversation_metrics_run_on_tutor_dialogue():
    judge = get_judge()
    for eval_type, metric in _conversation_metrics(judge, 0.6):
        metric.measure(TUTOR_CONVERSATION)
        assert 0.0 <= (metric.score or 0.0) <= 1.0, eval_type
