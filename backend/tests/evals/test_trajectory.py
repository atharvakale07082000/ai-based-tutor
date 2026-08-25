"""
Marker-gated agent-trajectory suite (`pytest -m evals`), built on `strands-agents-evals`.

This is the *offline* half of evaluation and is deliberately not what the Langfuse
LLM-as-a-Judge rules do. Those score what production actually said, after the fact;
these score whether the agent took the right **path** on a fixed set of cases:

- did the orchestrator route the query to the right specialist?
- did the specialist call the tools it should have?

That makes this the automatable form of the manual ritual in the repo's model-swap
checklist: point it at a candidate NIM model and read the pass rate instead of eyeballing
a few turns by hand.

Opt-in because every case makes live NIM calls. Run with:
    RUN_EVALS=1 uv run pytest -m evals tests/evals/test_trajectory.py
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("strands_evals")

from strands_evals import (
    Case,
    Experiment,
    StrandsEvalsTelemetry,
    TracedHandler,
    eval_task,
)  # noqa: E402
from strands_evals.evaluators import ToolCalled  # noqa: E402

pytestmark = pytest.mark.evals

_RUN = os.getenv("RUN_EVALS") == "1"

# Routing cases: the query, and the specialist the orchestrator must choose.
# Kept small and unambiguous — a case a human would not argue about, so a failure
# means the model degraded, not that the label was debatable.
ROUTING_CASES = [
    ("I don't understand recursion, can you explain it?", "doubt"),
    ("Give me a quiz on binary search trees", "quiz"),
    ("How am I doing on my topics so far?", "progress"),
    ("Build me a study plan for learning Rust", "curriculum"),
]


@pytest.mark.skipif(not _RUN, reason="set RUN_EVALS=1 to run live-model evals")
@pytest.mark.asyncio
async def test_orchestrator_routes_to_expected_specialist():
    """The orchestrator must pick the right specialist, via real structured output.

    This is check (1) of the model-swap checklist: a model whose structured output
    degrades falls back to the keyword heuristic, and `reason == "heuristic fallback"`
    is the only tell — so that is asserted explicitly rather than inferred from the
    routing result, which the heuristic can still get right by luck.
    """
    from app.agents import orchestrator

    router = orchestrator.build_router()
    misroutes: list[str] = []
    for query, expected in ROUTING_CASES:
        agents, reason = await orchestrator.route(query, router)
        assert reason != "heuristic fallback", (
            f"structured output degraded on {query!r} — the model is not usable"
        )
        if expected not in agents:
            misroutes.append(f"{query!r} -> {agents} (wanted {expected})")

    assert not misroutes, "orchestrator misrouted:\n  " + "\n  ".join(misroutes)


@pytest.mark.skipif(not _RUN, reason="set RUN_EVALS=1 to run live-model evals")
@pytest.mark.asyncio
async def test_doubt_specialist_calls_explanation_tool():
    """A 'please explain X' turn should reach the explanation tool.

    Uses the strands-evals `ToolCalled` evaluator over an `Experiment`, which is the
    piece Langfuse has no equivalent for: it grades the trajectory, not the wording of
    the final answer.
    """
    from app.agents.specialists import build_specialist

    cases = [
        Case(
            name="explain-memoization",
            input="Explain memoization to me in depth, with an example.",
        )
    ]
    experiment = Experiment(
        cases=cases,
        evaluators=[ToolCalled(tool_name="generate_explanation")],
    )

    # Trajectory evaluators need the agent's OTel spans, which only `TracedHandler`
    # collects — with the plain default handler the evaluator scores 0 with
    # "no trajectory provided", i.e. it silently grades nothing.
    StrandsEvalsTelemetry().setup_in_memory_exporter()

    @eval_task(TracedHandler())
    def task(case: Case):
        return build_specialist("doubt")

    # `run_evaluations` is sync and drives its own event loop, which trips the app's
    # async Mongo client ("Cannot use AsyncMongoClient in different event loop") when a
    # tool touches the database. The async runner stays on the test's loop.
    # max_workers=1 is required: TracedHandler shares one span exporter across calls.
    try:
        report = await experiment.run_evaluations_async(task, max_workers=1)
    finally:
        # The experiment runner drives the agent on its own worker loop, so any Mongo
        # client a DB tool created there is bound to *that* loop. conftest's autouse
        # fixture then calls `await client.close()` on the test loop and raises
        # "Cannot use AsyncMongoClient in different event loop" at teardown. Drop the
        # reference so the fixture has nothing to close; the worker loop is gone anyway.
        from app.db import mongo as _mongo

        _mongo._client = None

    # Assert the trajectory, not merely that a report object came back: an
    # `assert report is not None` can never fail and would be exactly the kind of
    # control that looks like coverage without backing anything.
    assert report.overall_score is not None, "experiment produced no score"
    assert report.overall_score == pytest.approx(1.0), (
        "doubt specialist did not call generate_explanation; "
        f"score={report.overall_score} reasons={report.reasons}"
    )
