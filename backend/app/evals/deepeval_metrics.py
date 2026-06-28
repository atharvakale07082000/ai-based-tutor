"""
DeepEval metric factory + persistence + online sampling.

Metrics are **reference-free** so they can run on live production requests (no gold answer needed):
  - faithfulness          → FaithfulnessMetric (output vs retrieval_context)   [single-turn, grounded]
  - answer_correctness    → GEval: does the response correctly answer the input  [single-turn]
  - answer_accuracy       → GEval: are the response's factual claims accurate     [single-turn]
  - conversation_*        → ConversationalGEval(consistency) + KnowledgeRetention + RoleAdherence

Each metric's score (0–1) + pass is written to the existing `agent_evals` store via insert_eval, so
results appear on the evals dashboard. `should_sample()` random-gates online evaluation; runs are
fire-and-forget so they never add latency to the request.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import random

import structlog

from app.config import settings
from app.evals.mongo import insert_eval
from app.evals.schemas import EvalRecord

log = structlog.get_logger()

# Keep DeepEval quiet + offline (set before any lazy `import deepeval` below).
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_DISABLE_PROGRESS_BAR", "YES")
os.environ.setdefault("CONFIDENT_API_KEY", "")

# deepeval is an optional (opt-in) dependency — see pyproject. When it's not installed, online
# sampling silently no-ops so the app runs cleanly without it.
_DEEPEVAL_AVAILABLE = importlib.util.find_spec("deepeval") is not None

# Keep references to fire-and-forget eval tasks so they aren't GC'd mid-flight.
_BG_TASKS: set[asyncio.Task] = set()

# Rate-limit guard: cap simultaneous judge (NVIDIA) calls from evals so online sampling never
# floods the endpoint alongside real generation traffic.
_EVAL_SEMAPHORE = asyncio.Semaphore(settings.EVAL_MAX_CONCURRENCY)


def should_sample() -> bool:
    """Randomly decide whether to evaluate this request (50/50, per requirement).

    Disabled entirely when the master switch is off or under pytest — online evals make real judge
    LLM + Mongo calls, which must never fire during the test suite (they fight per-test loop teardown
    and slow everything down).
    """
    if (
        not _DEEPEVAL_AVAILABLE
        or not settings.EVALS_ONLINE_SAMPLING
        or os.environ.get("PYTEST_CURRENT_TEST")
    ):
        return False
    return random.choice([True, False])


def _backlog_full() -> bool:
    """True if too many eval tasks are already queued — drop new sampling to respect rate limits."""
    if len(_BG_TASKS) >= settings.EVAL_MAX_PENDING:
        log.warning("eval_backlog_full", pending=len(_BG_TASKS))
        return True
    return False


# ── Metric factories (reference-free) ─────────────────────────────────────────


def _single_turn_metrics(judge, threshold: float):
    """(eval_type, metric) pairs that need only input + output (no gold reference)."""
    from deepeval.metrics import GEval
    from deepeval.test_case import SingleTurnParams as P

    return [
        (
            "answer_correctness",
            GEval(
                name="Correctness",
                criteria="Does the response correctly, directly, and completely answer the user's question?",
                evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT],
                model=judge,
                threshold=threshold,
                async_mode=False,
            ),
        ),
        (
            "answer_accuracy",
            GEval(
                name="Accuracy",
                criteria="Are all factual claims in the response accurate and not misleading or hallucinated?",
                evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT],
                model=judge,
                threshold=threshold,
                async_mode=False,
            ),
        ),
    ]


def _faithfulness_metric(judge, threshold: float):
    from deepeval.metrics import FaithfulnessMetric

    return (
        "faithfulness",
        FaithfulnessMetric(model=judge, threshold=threshold, async_mode=False),
    )


def _conversation_metrics(judge, threshold: float):
    from deepeval.metrics import (
        ConversationalGEval,
        KnowledgeRetentionMetric,
        RoleAdherenceMetric,
    )
    from deepeval.test_case import TurnParams

    return [
        (
            "conversation_consistency",
            ConversationalGEval(
                name="Consistency",
                criteria="Across the whole conversation the assistant stays consistent and never contradicts itself.",
                evaluation_params=[TurnParams.ROLE, TurnParams.CONTENT],
                model=judge,
                threshold=threshold,
            ),
        ),
        (
            "conversation_knowledge_retention",
            KnowledgeRetentionMetric(
                model=judge, threshold=threshold, async_mode=False
            ),
        ),
        (
            "conversation_role_adherence",
            RoleAdherenceMetric(model=judge, threshold=threshold, async_mode=False),
        ),
    ]


# ── Scoring + persistence ─────────────────────────────────────────────────────


async def _measure_and_store(
    eval_type, metric, test_case, *, agent, input, output, learner_id="", session_id=""
):
    """Run one metric (off-thread) and persist an EvalRecord; swallow errors (evals never break a flow)."""
    try:
        # Bounded concurrency: at most EVAL_MAX_CONCURRENCY judge calls in flight across all evals.
        async with _EVAL_SEMAPHORE:
            await asyncio.to_thread(metric.measure, test_case)
        score = float(metric.score if metric.score is not None else 0.0)
        passed = bool(
            getattr(
                metric,
                "success",
                score >= getattr(metric, "threshold", settings.EVAL_THRESHOLD),
            )
        )
        reason = getattr(metric, "reason", "") or ""
    except Exception as e:  # noqa: BLE001
        log.warning("deepeval_metric_failed", eval_type=eval_type, error=str(e)[:200])
        return None

    record = EvalRecord(
        eval_type=eval_type,
        agent=agent,
        learner_id=learner_id,
        session_id=session_id,
        input=input,
        output=output,
        score=round(score, 4),
        passed=passed,
        details={"reason": reason[:600], "metric": metric.__class__.__name__},
    )
    try:
        await insert_eval(record.to_mongo())
    except Exception as e:  # noqa: BLE001
        log.warning("deepeval_store_failed", eval_type=eval_type, error=str(e)[:200])
    log.info(
        "deepeval_scored",
        eval_type=eval_type,
        agent=agent,
        score=record.score,
        passed=record.passed,
    )
    return record


async def evaluate_single_turn(
    agent, query, answer, *, retrieval_context=None, learner_id="", session_id=""
):
    """Run the single-turn metrics on one agent answer and store each result."""
    from deepeval.test_case import LLMTestCase

    from app.evals.deepeval_judge import get_judge

    judge = get_judge()
    th = settings.EVAL_THRESHOLD
    tc = LLMTestCase(
        input=query, actual_output=answer, retrieval_context=retrieval_context or None
    )
    metrics = list(_single_turn_metrics(judge, th))
    if retrieval_context:
        metrics = [_faithfulness_metric(judge, th)] + metrics

    io = {"query": query[:1000]}
    oo = {"answer": answer[:2000]}
    for eval_type, metric in metrics:
        await _measure_and_store(
            eval_type,
            metric,
            tc,
            agent=agent,
            input=io,
            output=oo,
            learner_id=learner_id,
            session_id=session_id,
        )


async def evaluate_conversation(
    agent, turns, *, chatbot_role="a warm, accurate tutor", learner_id="", session_id=""
):
    """Run multi-turn conversation metrics over a list of {role, content} turns and store results.

    ``turns`` is normalized [{role: 'user'|'assistant', content: str}, ...] including the latest turn.
    """
    from deepeval.test_case import ConversationalTestCase, Turn

    from app.evals.deepeval_judge import get_judge

    if len(turns) < 2:
        return  # nothing multi-turn to assess yet

    judge = get_judge()
    th = settings.EVAL_THRESHOLD
    dt_turns = [
        Turn(role=t["role"], content=str(t["content"])[:2000])
        for t in turns
        if t.get("content")
    ]
    tc = ConversationalTestCase(turns=dt_turns, chatbot_role=chatbot_role)

    io = {"turns": len(dt_turns)}
    oo = {"last": dt_turns[-1].content[:1000] if dt_turns else ""}
    for eval_type, metric in _conversation_metrics(judge, th):
        await _measure_and_store(
            eval_type,
            metric,
            tc,
            agent=agent,
            input=io,
            output=oo,
            learner_id=learner_id,
            session_id=session_id,
        )


# ── Online sampling entry points (fire-and-forget) ────────────────────────────


def _fire(coro) -> None:
    """Schedule a coroutine as a tracked background task (no added request latency)."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


def maybe_eval_single_turn(
    agent, query, answer, *, retrieval_context=None, learner_id="", session_id=""
):
    """If sampled, evaluate a single agent answer in the background."""
    if not (query and answer) or not should_sample() or _backlog_full():
        return
    _fire(
        evaluate_single_turn(
            agent,
            query,
            answer,
            retrieval_context=retrieval_context,
            learner_id=learner_id,
            session_id=session_id,
        )
    )


def maybe_eval_conversation(
    agent, turns, *, chatbot_role="a warm, accurate tutor", learner_id="", session_id=""
):
    """If sampled, evaluate a multi-turn conversation in the background."""
    if not should_sample() or _backlog_full():
        return
    _fire(
        evaluate_conversation(
            agent,
            turns,
            chatbot_role=chatbot_role,
            learner_id=learner_id,
            session_id=session_id,
        )
    )


def maybe_eval_chat(
    agent,
    query,
    answer,
    turns,
    *,
    retrieval_context=None,
    chatbot_role="a warm, accurate tutor",
    learner_id="",
    session_id="",
):
    """One random gate per chat request: if sampled, run BOTH single-turn + conversation evals.

    Matches the requirement "randomly select true/false; if true run evals" — a single decision per
    request, not per metric. Always fire-and-forget (no request latency).
    """
    if not should_sample() or _backlog_full():
        return
    if query and answer:
        _fire(
            evaluate_single_turn(
                agent,
                query,
                answer,
                retrieval_context=retrieval_context,
                learner_id=learner_id,
                session_id=session_id,
            )
        )
    if len(turns) >= 2:
        _fire(
            evaluate_conversation(
                agent,
                turns,
                chatbot_role=chatbot_role,
                learner_id=learner_id,
                session_id=session_id,
            )
        )
