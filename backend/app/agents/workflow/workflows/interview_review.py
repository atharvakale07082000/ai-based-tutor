"""
interview_review workflow: evaluate → score → persist feedback.

Wraps the logic previously inlined in ``course_planner.complete_interview``; task ids/labels match
``STEP_PLANS["interview_review"]`` so the streamed steps are unchanged.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.agents.workflow.base import Task
from app.agents.workflow.planner import register_workflow
from app.agents.workflow.registry import register


@register("interview.evaluate")
async def _evaluate(ctx, task):
    """Load the interview + submitted answers and build the transcription list."""
    from app.db.mongo import col_interviews

    interview = await col_interviews().find_one({"interview_id": ctx.request["interview_id"]})
    if not interview:
        raise ValueError("Interview not found")
    answers = interview.get("answers", [])
    if not answers:
        raise ValueError("No answers submitted")
    transcriptions = [{"question_id": a.get("question_id"), "answer_text": a.get("answer_text", "")} for a in answers]
    return {"interview": interview, "answers": answers, "transcriptions": transcriptions}


@register("interview.score")
async def _score(ctx, task):
    """Run the LangGraph scoring agent over all Q&A pairs (off-thread)."""
    from app.agents.interview_scorer import run_scoring_agent

    ev = ctx.result("evaluate")
    interview = ev["interview"]
    return await asyncio.to_thread(
        run_scoring_agent,
        interview["module_title"],
        interview.get("module_topics", []),
        interview["questions"],
        ev["transcriptions"],
    )


@register("interview.persist")
async def _persist(ctx, task):
    """Persist the scoring result, update module pass/fail, and return the result payload."""
    from app.agents.course_planner import _update_module_interview
    from app.db.mongo import col_interviews

    ev = ctx.result("evaluate")
    scoring = ctx.result("score")
    interview_id = ctx.request["interview_id"]
    final_score = scoring["final_score"]
    passed = scoring["passed"]
    completed_at = datetime.now(timezone.utc).isoformat()

    await col_interviews().update_one(
        {"interview_id": interview_id},
        {
            "$set": {
                "final_score": final_score,
                "passed": passed,
                "scoring_matrix": scoring["scoring_matrix"],
                "summary": scoring["summary"],
                "completed_at": completed_at,
            }
        },
    )
    status = "passed" if passed else "failed"
    await _update_module_interview(ctx.request["plan_id"], ctx.request["module_id"], status, round(final_score / 10, 2))

    return {
        "interview_id": interview_id,
        "final_score": final_score,
        "passed": passed,
        "scoring_matrix": scoring["scoring_matrix"],
        "summary": scoring["summary"],
        "total_questions": len(ev["answers"]),
        "completed_at": completed_at,
    }


register_workflow(
    "interview_review",
    [
        Task("evaluate", "Evaluating your responses", "interview.evaluate"),
        Task("score", "Scoring across the rubric", "interview.score"),
        Task("feedback", "Writing your feedback", "interview.persist"),
    ],
)
