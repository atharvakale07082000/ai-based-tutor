"""
Interview Scoring Agent — LangGraph workflow that cross-checks all Q&A pairs
against module knowledge and produces a comprehensive scoring matrix + final score/10.

Graph: analyze_answers → build_scoring_matrix → compute_final_score → END
"""

from __future__ import annotations

import json
import re
from typing import TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

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

    prompt = f"""You are a senior technical interviewer assessing answers for the module: "{state["module_title"]}"
Key topics: {", ".join(state["module_topics"][:8])}

Analyze each candidate answer below for factual correctness and conceptual depth.
Return ONLY a JSON array (one entry per question):

{qa_block}

[
  {{
    "question_id": <same integer id as shown in [Qx]>,
    "correctness": "correct|partial|incorrect",
    "concepts_addressed": ["concept1", "concept2"],
    "key_gaps": ["gap1", "gap2"],
    "depth_achieved": "surface|adequate|deep"
  }}
]
Return ONLY the JSON array."""

    text = _chat(prompt, 900, 0.1)
    match = re.search(r"\[[\s\S]*\]", text)
    try:
        analyses = json.loads(match.group(0)) if match else []
    except Exception:
        analyses = []

    log.info("scorer_analyzed", count=len(analyses))
    return {"analyses": analyses}


# ─── Node 2: Build Scoring Matrix ─────────────────────────────────────────────


def _node_build_scoring_matrix(state: ScoringState) -> dict:
    """Assign numeric scores 0-10 to each answer based on the analysis."""
    if not state["analyses"]:
        log.warning("scorer_no_analyses", transcription_count=len(state["transcriptions"]))
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

    prompt = f"""Based on this analysis of interview answers for "{state["module_title"]}":

{analyses_text}

Assign a numeric score 0-10 to each answer using this rubric:
0-3 = incorrect, missing, or off-topic
4-6 = partially correct, key points missing
7-8 = good understanding demonstrated
9-10 = excellent, comprehensive, well-articulated

Return ONLY a JSON array:
[
  {{
    "question_id": <id>,
    "score": <integer 0-10>,
    "justification": "one clear sentence explaining the score",
    "concepts_covered": ["c1", "c2"],
    "concepts_missed": ["m1", "m2"]
  }}
]
Return ONLY the JSON array."""

    text = _chat(prompt, 900, 0.1)
    match = re.search(r"\[[\s\S]*\]", text)
    try:
        matrix = json.loads(match.group(0)) if match else []
    except Exception:
        matrix = []

    log.info("scorer_matrix_built", entries=len(matrix))
    return {"scoring_matrix": matrix}


# ─── Node 3: Compute Final Score ──────────────────────────────────────────────


def _node_compute_final_score(state: ScoringState) -> dict:
    """Compute final score out of 10 and generate a holistic summary."""
    matrix = state["scoring_matrix"]
    if not matrix:
        return {"final_score": 0.0, "summary": "No answers were evaluated.", "passed": False}

    scores = [int(entry.get("score", 0)) for entry in matrix]
    avg = sum(scores) / len(scores)

    prompt = f"""Interview performance summary for module "{state["module_title"]}":

Scoring matrix:
{json.dumps(matrix, indent=2)}

Average score: {avg:.1f}/10

Write exactly 2 sentences: first sentence highlights what the candidate did well,
second sentence identifies the most important area to improve.
Be specific and constructive. Return ONLY the 2 sentences."""

    summary = _chat(prompt, 200, 0.3)
    final_score = round(avg, 1)
    passed = final_score >= 6.0

    log.info("scorer_final", score=final_score, passed=passed)
    return {"final_score": final_score, "summary": summary, "passed": passed}


# ─── Graph assembly ───────────────────────────────────────────────────────────


def _build_graph():
    g = StateGraph(ScoringState)
    g.add_node("analyze_answers", _node_analyze_answers)
    g.add_node("build_scoring_matrix", _node_build_scoring_matrix)
    g.add_node("compute_final_score", _node_compute_final_score)
    g.set_entry_point("analyze_answers")
    g.add_edge("analyze_answers", "build_scoring_matrix")
    g.add_edge("build_scoring_matrix", "compute_final_score")
    g.add_edge("compute_final_score", END)
    return g.compile()


_graph = _build_graph()


def run_scoring_agent(
    module_title: str,
    module_topics: list[str],
    questions: list[dict],
    transcriptions: list[dict],
) -> dict:
    """Synchronous entry point — call via asyncio.to_thread in async contexts."""
    result = _graph.invoke(
        {
            "module_title": module_title,
            "module_topics": module_topics,
            "questions": questions,
            "transcriptions": transcriptions,
            "analyses": [],
            "scoring_matrix": [],
            "final_score": 0.0,
            "summary": "",
            "passed": False,
        }
    )
    return {
        "scoring_matrix": result["scoring_matrix"],
        "final_score": result["final_score"],
        "summary": result["summary"],
        "passed": result["passed"],
    }
