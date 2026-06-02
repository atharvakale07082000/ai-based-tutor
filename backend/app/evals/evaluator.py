"""
Evaluation functions for each agent type.

Each evaluator:
1. Takes agent input + output as dicts
2. Computes a score in [0.0, 1.0]
3. Returns (score, passed, details)
4. Persists to MongoDB via run_eval()

Sync evals: structural checks, pure Python, no I/O.
Async evals (suffix _accuracy / _alignment / _coherence / _routing): call the LLM judge.
"""

from __future__ import annotations

import inspect
import re

import structlog

from app.agents.state import MASTERY_THRESHOLD_DEFAULT
from app.evals import llm_judge
from app.evals.mongo import insert_eval
from app.evals.schemas import EvalRecord, EvalType
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
        item for item in curriculum_path if proficiency.get(item.get("subtopic", ""), 500.0) < mastery_threshold
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


def eval_progress_elo(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Correctness eval for progress_agent: was the Elo update valid?

    Checks:
    - elo_processed flag is True
    - Elo moved in the right direction given the quiz score (>0.5 → up, <0.5 → down)
    - new_elo stays within the [0, 1000] clamp bounds
    """
    delta = output.get("progress_delta", {})
    quiz_score = input.get("score") if input.get("score") is not None else delta.get("score")
    old_elo = delta.get("old_elo")
    new_elo = delta.get("new_elo")
    elo_processed = delta.get("elo_processed", False)

    checks: list[dict] = []
    passed_count = 0
    total = 0

    # Check 1: elo_processed flag set
    total += 1
    ok = bool(elo_processed)
    checks.append({"check": "elo_processed", "passed": ok})
    if ok:
        passed_count += 1

    # Check 2: direction matches score
    if quiz_score is not None and old_elo is not None and new_elo is not None:
        total += 1
        if quiz_score > 0.5:
            ok = new_elo > old_elo
        elif quiz_score < 0.5:
            ok = new_elo < old_elo
        else:
            ok = True  # score exactly 0.5: K*(0.5-0.5)=0, no movement expected
        checks.append(
            {"check": "direction_correct", "score": quiz_score, "old_elo": old_elo, "new_elo": new_elo, "passed": ok}
        )
        if ok:
            passed_count += 1

    # Check 3: clamped within [0, 1000]
    if new_elo is not None:
        total += 1
        ok = 0.0 <= new_elo <= 1000.0
        checks.append({"check": "elo_clamped", "new_elo": new_elo, "passed": ok})
        if ok:
            passed_count += 1

    if total == 0:
        return 0.0, False, {"reason": "no_elo_data"}

    score = passed_count / total
    return score, score == 1.0, {"checks": checks}


# ── Rule-based: supervisor routing ───────────────────────────────────────────


def eval_supervisor_routing(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Golden-set routing eval: given the input state, did the supervisor pick the
    correct next agent?  Mirrors the deterministic rules in supervisor._rule_based_fallback.

    Checks (in priority order):
    1. No curriculum → must route to 'curriculum'
    2. task_type='quiz', no questions → 'quiz'
    3. task_type='doubt' → 'doubt'
    4. Unprocessed quiz score in progress_delta → 'progress'
    5. All topics mastered → 'FINISH'
    6. Default (unmastered topics remain) → 'quiz'
    """
    curriculum_path = input.get("curriculum_path", [])
    task_type = input.get("task_type", "")
    proficiency = input.get("topic_proficiency", {})
    mastery_threshold = input.get("mastery_threshold", MASTERY_THRESHOLD_DEFAULT)
    progress_delta = input.get("progress_delta", {})
    decision = output.get("supervisor_decision", "")

    if not curriculum_path:
        expected, rule = "curriculum", "no_curriculum"
    elif task_type == "quiz" and not input.get("quiz_questions"):
        expected, rule = "quiz", "quiz_requested"
    elif task_type == "doubt":
        expected, rule = "doubt", "doubt_requested"
    elif progress_delta.get("score") is not None and not progress_delta.get("elo_processed"):
        expected, rule = "progress", "unprocessed_score"
    else:
        unmastered = [i for i in curriculum_path if proficiency.get(i["subtopic"], 500.0) < mastery_threshold]
        if not unmastered:
            expected, rule = "FINISH", "all_mastered"
        else:
            expected, rule = "quiz", "default_quiz"

    passed = decision == expected
    return (
        (1.0 if passed else 0.0),
        passed,
        {
            "rule": rule,
            "expected": expected,
            "got": decision,
        },
    )


# ── LLM-judge: doubt answer accuracy ─────────────────────────────────────────


async def eval_doubt_accuracy(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    LLM-judge eval: scores the doubt agent's response on four educational criteria.

    Criteria (each 1–5 from judge, normalized to [0.0–1.0]):
    - correctness:     Is the explanation factually accurate?
    - clarity:         Is the response easy to understand?
    - topic_relevance: Does it stay on the stated topic?
    - bloom_fit:       Does the depth match the learner's Bloom level?

    Score = average of the four normalized scores.
    Passes at score >= 0.6 (i.e., ≥3/5 average across all dimensions).
    """
    question = input.get("question", "")
    topic = input.get("context", "") or input.get("current_topic", "")
    bloom_level = input.get("bloom_level", "understand")
    response = output.get("doubt_response", "")

    if not response:
        return 0.0, False, {"reason": "empty_response"}

    user_prompt = (
        f"Topic: {topic}\n"
        f"Target Bloom level: {bloom_level}\n"
        f"Learner question: {question[:300]}\n\n"
        f"Agent response:\n{response[:600]}"
    )
    criteria = ["correctness", "clarity", "topic_relevance", "bloom_fit"]
    scores = await llm_judge.score(user_prompt, criteria)
    avg = sum(scores.values()) / len(scores)
    return avg, avg >= 0.6, {"criteria_scores": scores, "avg": round(avg, 3)}


# ── LLM-judge: quiz Bloom-level alignment ────────────────────────────────────


async def eval_quiz_bloom_alignment(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    LLM-judge eval: do generated questions actually match the claimed Bloom level?

    Samples up to 3 questions and scores each on:
    - bloom_alignment:    Does the cognitive demand match the claimed level?
    - distractor_quality: Are the wrong options plausible, not obviously wrong?

    Score = mean bloom_alignment across sampled questions (distractor_quality is
    recorded as detail but not included in the pass threshold).
    Passes at avg bloom_alignment >= 0.6.
    """
    questions = output.get("quiz_questions", [])
    bloom_level = output.get("bloom_level", "understand")

    if not questions:
        return 0.0, False, {"reason": "no_questions"}

    per_question: list[dict] = []
    for q in questions[:3]:
        q_text = q.get("question", "")
        opts = q.get("options", [])
        opts_text = "\n".join(f"  {chr(65 + i)}. {opt}" for i, opt in enumerate(opts))
        user_prompt = f"Claimed Bloom taxonomy level: {bloom_level}\n\nQuestion: {q_text}\nOptions:\n{opts_text}"
        q_scores = await llm_judge.score(user_prompt, ["bloom_alignment", "distractor_quality"])
        per_question.append({"question": q_text[:80], **q_scores})

    avg_alignment = sum(s["bloom_alignment"] for s in per_question) / len(per_question)
    return avg_alignment, avg_alignment >= 0.6, {"per_question": per_question, "avg_alignment": round(avg_alignment, 3)}


# ── LLM-judge: curriculum coherence ─────────────────────────────────────────


async def eval_curriculum_coherence(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    LLM-judge eval: is the curriculum path pedagogically coherent?

    Criteria (each 1–5 from judge, normalized to [0.0–1.0]):
    - ordering_logic:   Do topics build on each other (foundations before advanced)?
    - goal_alignment:   Do topics connect to the learner's stated goals?
    - coverage_breadth: Is there reasonable breadth across relevant concepts?

    Score = average of the three normalized criteria scores.
    Passes at score >= 0.6.
    Samples up to 8 topics to keep the prompt concise.
    """
    path = output.get("curriculum_path", [])
    goals = input.get("learner_profile", {}).get("goal_vector", [])

    if not path:
        return 0.0, False, {"reason": "empty_path"}

    topics_text = "\n".join(
        f"  {i + 1}. [{item['domain']}] {item['subtopic']} (Elo {item.get('elo', 500):.0f})"
        for i, item in enumerate(path[:8])
    )
    goals_text = ", ".join(goals[:3]) if goals else "not specified"
    user_prompt = (
        f"Learner goals: {goals_text}\n\n"
        f"Proposed curriculum path (first {min(len(path), 8)} of {len(path)} topics):\n"
        f"{topics_text}"
    )
    criteria = ["ordering_logic", "goal_alignment", "coverage_breadth"]
    scores = await llm_judge.score(user_prompt, criteria)
    avg = sum(scores.values()) / len(scores)
    return avg, avg >= 0.6, {"criteria_scores": scores, "avg": round(avg, 3), "path_length": len(path)}


# ── Chat orchestrator evals ───────────────────────────────────────────────────


def eval_chat_session(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Records a completed assistant turn.
    Score = 1.0 if no error occurred, 0.0 if the turn errored out.
    Delegation chain and response length are preserved in details.
    """
    had_error = bool(output.get("error", False))
    score = 0.0 if had_error else 1.0
    return (
        score,
        not had_error,
        {
            "delegation_chain": output.get("delegation_chain", []),
            "response_length": output.get("response_length", 0),
        },
    )


def eval_chat_guardrail(input: dict, output: dict) -> tuple[float, bool, dict]:
    """
    Records a turn blocked by the chat-level input guardrail.
    Score is always 1.0 — the guardrail firing correctly is a success signal.
    """
    return 1.0, True, {"blocked_message": input.get("message", "")[:200]}


# ── Dispatch table ────────────────────────────────────────────────────────────

_EVAL_FNS: dict[str, callable] = {
    # Structural
    "quiz_format": eval_quiz_format,
    "doubt_relevance": eval_doubt_relevance,
    "curriculum_ordering": eval_curriculum_ordering,
    "planner_decision": eval_planner_decision,
    "guardrail_triggered": eval_guardrail_triggered,
    "progress_elo": eval_progress_elo,
    "supervisor_routing": eval_supervisor_routing,
    # LLM-judge
    "doubt_accuracy": eval_doubt_accuracy,
    "quiz_bloom_alignment": eval_quiz_bloom_alignment,
    "curriculum_coherence": eval_curriculum_coherence,
    # Chat orchestrator
    "chat_session": eval_chat_session,
    "chat_guardrail": eval_chat_guardrail,
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

    result = fn(input, output)
    score, passed, details = await result if inspect.isawaitable(result) else result

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
