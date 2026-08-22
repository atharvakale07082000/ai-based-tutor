"""interview_review pipeline: evaluate -> score -> feedback (persist)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from app.agents.bar import DEFAULT_BAR
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
        # A module interview carries no bar and grades at the platform default; a job-loop
        # round carries the seniority-calibrated one set when the loop was designed.
        bar = float(interview.get("bar") or DEFAULT_BAR)
        scoring = await asyncio.to_thread(
            run_scoring_agent,
            interview["module_title"],
            interview.get("module_topics", []),
            interview["questions"],
            transcriptions,
            bar,
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
        # A loop round has no course module to update; only module interviews do.
        context = interview.get("context") or {}
        if context.get("kind") != "loop":
            status = "passed" if passed else "failed"
            await _update_module_interview(
                plan_id, module_id, status, round(final_score / 10, 2)
            )

        await _record_interview_evidence(interview, final_score, bar, completed_at)
        await _e(tl.done("feedback"))

        return {
            "interview_id": interview_id,
            "final_score": final_score,
            "passed": passed,
            "bar": bar,
            "scoring_matrix": scoring["scoring_matrix"],
            "summary": scoring["summary"],
            "total_questions": len(answers),
            "completed_at": completed_at,
        }


async def _record_interview_evidence(
    interview: dict, final_score: float, bar: float, completed_at: str
) -> None:
    """Append ledger rows for a graded interview: one overall, one per subject skill."""
    from app.agents.evidence import record_evidence
    from app.db.mongo import PROJ, col_learners

    # The ledger is keyed by the learner-profile id, the same id every other collection
    # uses. Interviews store the *user* id, so resolve it — writing both ids into one
    # collection would split a learner's evidence across two keys and no query could
    # ever retrieve all of it.
    learner = await col_learners().find_one({"user_id": interview["user_id"]}, PROJ)
    if not learner:
        log.warning("evidence_learner_missing", user_id=interview["user_id"])
        return

    context = interview.get("context") or {}
    kind = "interview_round" if context.get("kind") == "loop" else "module_interview"
    subject = interview.get("module_title") or "interview"
    common = {
        "learner_id": learner["id"],
        "kind": kind,
        "score_0_1": final_score / 10,
        "bar_0_1": bar / 10,
        "source_collection": "module_interviews",
        "source_id": interview["interview_id"],
        "context": {
            k: v
            for k, v in {
                "company": context.get("company"),
                "role": context.get("role"),
                "round_key": context.get("round_key"),
                "loop_id": context.get("loop_id"),
                "subject": subject,
            }.items()
            if v
        },
        "occurred_at": completed_at,
    }
    await record_evidence(skill=subject, **common)
    for skill in (interview.get("module_topics") or [])[:12]:
        if skill and skill != subject:
            await record_evidence(skill=skill, **common)
