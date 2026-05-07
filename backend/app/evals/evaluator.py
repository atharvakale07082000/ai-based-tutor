"""
Evaluation functions for each agent type.

Each evaluator:
1. Takes agent input + output as dicts
2. Computes a score in [0.0, 1.0]
3. Returns an EvalRecord
4. Persists to MongoDB asynchronously (fire-and-forget or awaited)

Call run_eval() to evaluate and store in one step.
"""
from __future__ import annotations
import re
import structlog
from datetime import datetime, timezone

from app.evals.schemas import EvalRecord, EvalType
from app.evals.mongo import insert_eval
from app.guardrails import check_quiz_question

log = structlog.get_logger()


# ── Per-agent eval functions ──────────────────────────────────────────────────

def eval_quiz_format(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Structural eval: are generated questions well-formed?
    Score = fraction of questions passing guardrail checks.
    """
    questions = output.get("quiz_questions", [])
    bloom_level = output.get("bloom_level", "")

    if not questions:
        return 0.0, False, {"reason": "no_questions"}

    passed_count = 0
    details: list[dict] = []
    for i, q in enumerate(questions):
        result = check_quiz_question(q, bloom_level=bloom_level)
        details.append({"index": i, "passed": result.passed, "reason": result.reason})
        if result.passed:
            passed_count += 1

    score = passed_count / len(questions)
    return score, score >= 0.8, {"per_question": details}


def eval_doubt_relevance(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Lightweight relevance eval: does the response mention topic tokens?
    Score: token overlap ratio between topic and response.
    """
    topic = input.get("context", "") or input.get("current_topic", "")
    response = output.get("doubt_response", "")

    if not topic or not response:
        return 0.0, False, {"reason": "missing_topic_or_response"}

    topic_tokens = set(re.sub(r"[^a-z0-9 ]", "", topic.lower()).split())
    resp_tokens = set(re.sub(r"[^a-z0-9 ]", "", response.lower()).split())
    overlap = topic_tokens & resp_tokens
    score = len(overlap) / max(len(topic_tokens), 1)

    return score, score > 0.0, {"overlap_tokens": list(overlap), "topic_tokens": list(topic_tokens)}


def eval_curriculum_ordering(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Ordering eval: does the curriculum correctly prioritize low-Elo topics?
    Score: fraction of consecutive pairs where elo[i] <= elo[i+1].
    """
    path = output.get("curriculum_path", [])
    if len(path) < 2:
        return 1.0, True, {"reason": "single_or_empty_path"}

    correct_pairs = 0
    total_pairs = len(path) - 1
    violations: list[str] = []

    for i in range(total_pairs):
        a = path[i].get("elo", 500.0)
        b = path[i + 1].get("elo", 500.0)
        if a <= b:
            correct_pairs += 1
        else:
            violations.append(f"pos {i}: {a} > {b}")

    score = correct_pairs / total_pairs
    return score, len(violations) == 0, {"violations": violations}


def eval_planner_decision(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Correctness eval: did the planner make the expected decision given state?
    Rules checked:
    - iteration >= max_iterations → must end
    - no curriculum_path → must trigger 'curriculum'
    - all mastered → must end
    - otherwise → must quiz
    """
    curriculum_path = input.get("curriculum_path", [])
    proficiency = input.get("topic_proficiency", {})
    mastery_threshold = input.get("mastery_threshold", 700.0)
    iteration_count = input.get("iteration_count", 0)
    max_iterations = input.get("max_iterations", 10)
    next_action = output.get("next_action", "")

    # Rule: iteration cap
    if iteration_count + 1 >= max_iterations:
        expected = "end"
        passed = next_action == expected
        return (1.0 if passed else 0.0), passed, {"rule": "iter_cap", "expected": expected, "got": next_action}

    # Rule: no curriculum
    if not curriculum_path:
        expected = "curriculum"
        passed = next_action == expected
        return (1.0 if passed else 0.0), passed, {"rule": "no_curriculum", "expected": expected, "got": next_action}

    # Rule: all mastered
    unmastered = [
        item for item in curriculum_path
        if proficiency.get(item.get("subtopic", ""), 500.0) < mastery_threshold
    ]
    if not unmastered:
        expected = "end"
        passed = next_action == expected
        return (1.0 if passed else 0.0), passed, {"rule": "all_mastered", "expected": expected, "got": next_action}

    # Rule: default → quiz
    expected = "quiz"
    passed = next_action == expected
    return (1.0 if passed else 0.0), passed, {"rule": "default_quiz", "expected": expected, "got": next_action}


def eval_guardrail_triggered(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Records when a guardrail fires. Score is always 1.0 (guardrail working correctly).
    """
    error = output.get("error", "")
    triggered = isinstance(error, str) and error.startswith("guardrail:")
    return 1.0, True, {"triggered": triggered, "reason": error}


# ── Dispatch table ────────────────────────────────────────────────────────────

_EVAL_FNS: dict[str, callable] = {
    "quiz_format": eval_quiz_format,
    "doubt_relevance": eval_doubt_relevance,
    "curriculum_ordering": eval_curriculum_ordering,
    "planner_decision": eval_planner_decision,
    "guardrail_triggered": eval_guardrail_triggered,
}


async def run_eval(
    eval_type: EvalType,
    agent: str,
    input: dict,
    output: dict,
    *,
    learner_id: str = "",
    trace_id: str = "",
    session_id: str = "",
    store: bool = True,
) -> EvalRecord:
    """
    Run a named evaluation and optionally persist the result to MongoDB.
    Returns the EvalRecord regardless of the `store` flag.
    """
    fn = _EVAL_FNS.get(eval_type)
    if fn is None:
        raise ValueError(f"Unknown eval_type: {eval_type!r}")

    score, passed, details = fn(input, output)

    record = EvalRecord(
        eval_type=eval_type,
        agent=agent,
        learner_id=learner_id,
        trace_id=trace_id,
        session_id=session_id,
        input=input,
        output=output,
        score=score,
        passed=passed,
        details=details,
    )

    log.info(
        "eval_result",
        eval_type=eval_type,
        agent=agent,
        score=score,
        passed=passed,
    )

    if store:
        try:
            doc_id = await insert_eval(record.to_mongo())
            log.info("eval_stored", doc_id=doc_id)
        except Exception as e:
            log.warning("eval_store_failed", error=str(e))

    return record
