"""interview_review pipeline: evaluate -> score -> feedback (persist)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from app.agents.steps import StepEmit, StepTimeline, step_emitter

log = structlog.get_logger()


async def run_interview_review(
    interview_id: str, plan_id: str, module_id: str, emit: StepEmit = None
) -> dict:
    """Score a completed interview, persist the result, update module pass/fail."""
    from app.agents.course_planner import _update_module_interview
    from app.agents.interview_scorer import run_scoring_agent
    from app.db.mongo import col_interviews

    tl = StepTimeline("interview_review")

    async with step_emitter(emit) as _e:
        # evaluate — load interview + answers
        await _e(tl.start("evaluate"))
        interview = await col_interviews().find_one({"interview_id": interview_id})
        if not interview:
            raise ValueError("Interview not found")
        answers = interview.get("answers", [])
        if not answers:
            raise ValueError("No answers submitted")
        transcriptions = [
            {
                "question_id": a.get("question_id"),
                "answer_text": a.get("answer_text", ""),
            }
            for a in answers
        ]
        await _e(tl.done("evaluate"))

        # score — run the (LangGraph-free) scoring agent off-thread
        await _e(tl.start("score"))
        scoring = await asyncio.to_thread(
            run_scoring_agent,
            interview["module_title"],
            interview.get("module_topics", []),
            interview["questions"],
            transcriptions,
        )
        await _e(tl.done("score"))

        # feedback — persist + update module
        await _e(tl.start("feedback"))
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
        await _update_module_interview(
            plan_id, module_id, status, round(final_score / 10, 2)
        )
        await _e(tl.done("feedback"))

        return {
            "interview_id": interview_id,
            "final_score": final_score,
            "passed": passed,
            "scoring_matrix": scoring["scoring_matrix"],
            "summary": scoring["summary"],
            "total_questions": len(answers),
            "completed_at": completed_at,
        }
