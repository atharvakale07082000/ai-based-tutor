"""
Interview Scoring Agent — a fixed 3-step pipeline that cross-checks all Q&A pairs
against module knowledge and produces a scoring matrix + final score/10.

Pipeline: analyze_answers → build_scoring_matrix → compute_final_score.
(Plain sequential functions — no graph engine; each step is a single LLM call.)
"""

from __future__ import annotations

import json
from typing import TypedDict

import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS
from app.agents.bar import DEFAULT_BAR
from app.agents.json_utils import extract_json_array
from app.prompts.loader import render_prompt

log = structlog.get_logger()


def _chat(prompt: str, max_tokens: int = 1200, temperature: float = 0.1) -> str:
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    provider = model_cfg["provider"]
    client = get_hf_client(provider)
    # Truncate oversized prompts before sending
    prompt = prompt[:7000]
    try:
        resp = client.chat_completion(
            model=model_cfg["model_id"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        from app.hf.client import record_auth_success

        record_auth_success(provider)
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        err = str(e)
        if "401" in err or "403" in err:
            from app.hf.client import record_auth_failure

            record_auth_failure(provider)
        log.error("interview_scorer_llm_error", error=err[:200])
        raise


class ScoringState(TypedDict):
    module_title: str
    module_topics: list[str]
    questions: list[dict]  # [{id, text, expected_depth}]
    transcriptions: list[dict]  # [{question_id, answer_text}]
    bar: float  # 0-10 pass threshold (see agents/bar.py)
    analyses: list[dict]  # set by analyze_answers node
    scoring_matrix: list[dict]  # set by build_scoring_matrix node
    final_score: float  # 0-10, set by compute_final_score node
    summary: str
    passed: bool


# ─── Node 1: Analyze Answers ──────────────────────────────────────────────────


def _node_analyze_answers(state: ScoringState) -> dict:
    """Cross-check each transcription against expected knowledge for each question."""
    q_map = {q["id"]: q for q in state["questions"]}
    pairs = []
    for t in state["transcriptions"]:
        q = q_map.get(t.get("question_id"))
        if q:
            pairs.append(
                f"[Q{q['id']}] {q['text']}\n"
                f"Expected depth: {q.get('expected_depth', 'conceptual')}\n"
                f'Candidate answer: "{t.get("answer_text", "").strip() or "[No answer provided]"}"'
            )

    qa_block = "\n\n".join(pairs) if pairs else "No Q&A pairs available."

    prompt = render_prompt(
        "interview_scorer",
        "analyze_answers",
        module_title=state["module_title"],
        topics=", ".join(state["module_topics"][:8]),
        qa_block=qa_block,
    )

    try:
        text = _chat(prompt, 900, 0.1)
        analyses = extract_json_array(text) or []
    except Exception as e:
        log.error("scorer_analyze_failed", error=str(e)[:200])
        analyses = []

    log.info("scorer_analyzed", count=len(analyses))
    return {"analyses": analyses}


# ─── Node 2: Build Scoring Matrix ─────────────────────────────────────────────


def _node_build_scoring_matrix(state: ScoringState) -> dict:
    """Assign numeric scores 0-10 to each answer based on the analysis."""
    if not state["analyses"]:
        log.warning(
            "scorer_no_analyses", transcription_count=len(state["transcriptions"])
        )
        matrix = [
            {
                "question_id": t.get("question_id"),
                "score": 0,
                "justification": "Answer analysis failed — LLM returned no structured output.",
                "concepts_covered": [],
                "concepts_missed": [],
            }
            for t in state["transcriptions"]
        ]
        return {"scoring_matrix": matrix}

    analyses_text = json.dumps(state["analyses"], indent=2)

    prompt = render_prompt(
        "interview_scorer",
        "scoring_matrix",
        module_title=state["module_title"],
        analyses_text=analyses_text,
    )

    try:
        text = _chat(prompt, 900, 0.1)
        matrix = extract_json_array(text) or []
    except Exception as e:
        log.error("scorer_matrix_failed", error=str(e)[:200])
        # Degrade gracefully: assign mid-range score for each analysed entry
        matrix = [
            {
                "question_id": a.get("question_id"),
                "score": 5,
                "justification": "Could not score — evaluation service temporarily unavailable.",
                "concepts_covered": a.get("concepts_addressed", []),
                "concepts_missed": a.get("key_gaps", []),
            }
            for a in state["analyses"]
        ]

    log.info("scorer_matrix_built", entries=len(matrix))
    return {"scoring_matrix": matrix}


# ─── Node 3: Compute Final Score ──────────────────────────────────────────────


def _node_compute_final_score(state: ScoringState) -> dict:
    """Compute final score out of 10 and generate a holistic summary."""
    matrix = state["scoring_matrix"]
    bar = state["bar"]
    if not matrix:
        return {
            "final_score": 0.0,
            "summary": "No answers were evaluated.",
            "passed": False,
        }

    scores = [int(entry.get("score", 0)) for entry in matrix]
    avg = sum(scores) / len(scores)

    prompt = render_prompt(
        "interview_scorer",
        "final_summary",
        module_title=state["module_title"],
        matrix_json=json.dumps(matrix, indent=2),
        avg=f"{avg:.1f}",
    )

    try:
        summary = _chat(prompt, 200, 0.3)
    except Exception as e:
        log.error("scorer_summary_failed", error=str(e)[:200])
        summary = f"Average score: {avg:.1f}/10. Keep practising the key concepts."
    final_score = round(avg, 1)
    passed = final_score >= bar

    log.info("scorer_final", score=final_score, bar=bar, passed=passed)
    return {"final_score": final_score, "summary": summary, "passed": passed}


# ─── Pipeline assembly ────────────────────────────────────────────────────────


_SCORING_TIMEOUT_S = 120  # hard cap so a hanging LLM call never blocks forever


def run_scoring_agent(
    module_title: str,
    module_topics: list[str],
    questions: list[dict],
    transcriptions: list[dict],
    bar: float = DEFAULT_BAR,
) -> dict:
    """Synchronous entry point — call via asyncio.to_thread in async contexts.

    Runs analyze → matrix → final score in sequence, threading a plain state dict.

    ``bar`` is the 0-10 pass threshold: ``DEFAULT_BAR`` for a module interview, or the
    round's seniority-calibrated bar for a job-loop round (see ``agents/bar.py``).
    """
    import signal
    import threading

    def _timeout_handler(signum, frame):
        raise TimeoutError(f"Scoring agent timed out after {_SCORING_TIMEOUT_S}s")

    # signal.alarm only works in the main thread. This function is designed to be called via
    # asyncio.to_thread (a worker thread), where installing a SIGALRM handler raises
    # "signal only works in main thread of the main interpreter" and 500s the whole interview
    # completion. Only arm the alarm when we truly are on the main thread; otherwise rely on the
    # per-call network timeouts of the underlying LLM client (same as the Windows fallback).
    use_alarm = (
        hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    )
    if use_alarm:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(_SCORING_TIMEOUT_S)

    state: ScoringState = {
        "module_title": module_title,
        "module_topics": module_topics,
        "questions": questions,
        "transcriptions": transcriptions,
        "bar": bar,
        "analyses": [],
        "scoring_matrix": [],
        "final_score": 0.0,
        "summary": "",
        "passed": False,
    }

    try:
        state.update(_node_analyze_answers(state))
        state.update(_node_build_scoring_matrix(state))
        state.update(_node_compute_final_score(state))
    finally:
        if use_alarm:
            signal.alarm(0)  # cancel any pending alarm

    return {
        "scoring_matrix": state["scoring_matrix"],
        "final_score": state["final_score"],
        "summary": state["summary"],
        "passed": state["passed"],
        "bar": bar,
    }
