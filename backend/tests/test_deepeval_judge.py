"""Fast (no-network) tests for the DeepEval NVIDIA judge wrapper + sampling gate."""

import pytest

pytest.importorskip(
    "deepeval"
)  # opt-in dep; install with `uv pip install deepeval instructor`

from app.evals.deepeval_judge import get_judge
from app.evals.deepeval_metrics import (
    _conversation_metrics,
    _single_turn_metrics,
    should_sample,
)
from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel


class _Score(BaseModel):
    label: str
    score: float


def test_judge_is_a_deepeval_model():
    j = get_judge()
    assert isinstance(j, DeepEvalBaseLLM)
    assert j.get_model_name().startswith("nvidia:")


def test_repair_extracts_and_validates_json():
    """The fallback path pulls JSON out of fenced/prose text and validates the schema."""
    j = get_judge()
    out = j._repair('Sure!\n```json\n{"label": "POSITIVE", "score": 0.9}\n```', _Score)
    assert isinstance(out, _Score)
    assert out.label == "POSITIVE" and out.score == 0.9


def test_should_sample_returns_bool():
    assert isinstance(should_sample(), bool)


def test_metric_factories_build_without_network():
    j = get_judge()
    assert [e for e, _ in _single_turn_metrics(j, 0.6)] == [
        "answer_correctness",
        "answer_accuracy",
    ]
    assert [e for e, _ in _conversation_metrics(j, 0.6)] == [
        "conversation_consistency",
        "conversation_knowledge_retention",
        "conversation_role_adherence",
    ]
