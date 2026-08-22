"""Interview loop router — company-specific multi-round mock interviews.

A loop turns a saved job application into the interview process that employer probably
runs, and grades each round against a bar calibrated to the job's seniority.

Every round is conducted by the same interrupt-driven agent that powers module
interviews (``agents/interview_agent.py``), against the same ``module_interviews``
document shape, so the turn loop, resume, code runner and scorer are shared rather
than duplicated. These endpoints are the loop-scoped entry points into them.

Endpoints (prefix /api/v1/loops):
  POST /stream                             — job_id → design + persist a loop (SSE)
  GET  /                                   — the learner's loops
  GET  /{loop_id}                          — one loop
  POST /{loop_id}/rounds/{key}/start       — begin a round, stream its first question
  GET  /{loop_id}/rounds/{key}             — resume an in-flight round (plain JSON)
  POST /{loop_id}/rounds/{key}/answer      — score an answer, stream the next question
  POST /{loop_id}/rounds/{key}/run-code    — check code from a coding round
  POST /{loop_id}/rounds/{key}/complete/stream — grade the round, unlock the next
  POST /{loop_id}/rounds/{key}/retry       — reset a resolved round for another attempt
  POST /{loop_id}/debrief/stream           — once every round is resolved
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agents.course_planner import interview_state, start_interview
from app.agents.interview_agent import stream_answer, stream_start
from app.agents.loops import (
    ROUND_AVAILABLE,
    ROUND_IN_PROGRESS,
    apply_round_result,
    find_round,
    is_resolved,
    loop_view,
)
from app.auth.jwt import get_current_learner
from app.db.mongo import PROJ, col_interview_loops, col_interviews, col_job_applications
from app.sse import SSE_DONE, sse_frame, sse_response, sse_stream_response

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
log = structlog.get_logger()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class LoopCreateRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=64)


class AnswerRequest(BaseModel):
    question_id: int = Field(ge=1, le=100)
    answer_text: str = Field(min_length=1, max_length=5_000)


class RunCodeRequest(BaseModel):
    code: str = Field(max_length=10_000)
    language: str = Field(default="python", max_length=40)
    stdin: str = Field(default="", max_length=10_000)


# ─── Ownership helpers ────────────────────────────────────────────────────────


async def _owned_loop(loop_id: str, learner_id: str) -> dict:
    """Fetch a loop the caller owns, or 404 (same 404 for missing and foreign)."""
    loop = await col_interview_loops().find_one(
        {"loop_id": loop_id, "learner_id": learner_id}, PROJ
    )
    if not loop:
        raise HTTPException(404, "Interview loop not found")
    return loop


async def _owned_round(
    loop_id: str, round_key: str, learner_id: str
) -> tuple[dict, dict]:
    """Fetch (loop, round) the caller owns, or 404."""
    loop = await _owned_loop(loop_id, learner_id)
    rnd = find_round(loop, round_key)
    if not rnd:
        raise HTTPException(404, "Round not found")
    return loop, rnd


async def _round_interview(rnd: dict, user_id: str) -> dict:
    """Fetch the interview backing a round, or 404 if it hasn't been started."""
    interview_id = rnd.get("interview_id")
    if not interview_id:
        raise HTTPException(409, "This round has not been started yet")
    interview = await col_interviews().find_one(
        {"interview_id": interview_id, "user_id": user_id}, PROJ
    )
    if not interview:
        raise HTTPException(404, "Interview not found")
    return interview


async def _save_rounds(loop: dict) -> None:
    """Persist the loop's mutated round list and status."""
    await col_interview_loops().update_one(
        {"loop_id": loop["loop_id"]},
        {
            "$set": {
                "rounds": loop["rounds"],
                "status": loop.get("status"),
                "updated_at": loop.get("updated_at"),
                "completed_at": loop.get("completed_at"),
            }
        },
    )


async def _agent_sse(source, error_message: str, **log_ctx):
    """Frame an agent event stream as SSE, converting any failure to a generic error."""
    try:
        async for ev in source:
            yield sse_frame(ev)
    except Exception as e:  # noqa: BLE001 - generic to client, detail in logs
        log.error("loop_stream_error", error=str(e)[:300], **log_ctx)
        yield sse_frame({"type": "error", "message": error_message})
    yield SSE_DONE


# ─── Loop lifecycle ───────────────────────────────────────────────────────────


@router.post("/stream")
@limiter.limit("6/hour")
async def create_loop_stream(
    request: Request,
    body: LoopCreateRequest,
    learner: dict = Depends(get_current_learner),
):
    """Design an interview loop from a saved job application, streaming the timeline."""
    job = await col_job_applications().find_one(
        {"id": body.job_id, "learner_id": learner["id"]}, PROJ
    )
    if not job:
        raise HTTPException(404, "Job application not found")
    if job.get("loop_id"):
        existing = await col_interview_loops().find_one(
            {"loop_id": job["loop_id"], "learner_id": learner["id"]}, PROJ
        )
        if existing:
            raise HTTPException(409, "This application already has an interview loop")

    async def run(emit):
        from app.agents.pipelines import run_loop_setup

        loop = await run_loop_setup(job, learner["id"], emit=emit)
        await emit(
            {"type": "action", "kind": "loop_created", "payload": loop_view(loop)}
        )

    return sse_response(run)


@router.get("")
@router.get("/")
async def list_loops(learner: dict = Depends(get_current_learner)):
    """All of the learner's interview loops, most recently updated first."""
    loops = (
        await col_interview_loops()
        .find({"learner_id": learner["id"]}, PROJ)
        .sort("updated_at", -1)
        .to_list(length=None)
    )
    return {"loops": [loop_view(loop) for loop in loops]}


@router.get("/{loop_id}")
async def get_loop(loop_id: str, learner: dict = Depends(get_current_learner)):
    """One interview loop, projected for the client."""
    return loop_view(await _owned_loop(loop_id, learner["id"]))


# ─── Rounds ───────────────────────────────────────────────────────────────────


@router.post("/{loop_id}/rounds/{round_key}/start")
async def start_round(
    loop_id: str, round_key: str, learner: dict = Depends(get_current_learner)
):
    """Begin a round: create its interview and stream the agent's first question."""
    loop, rnd = await _owned_round(loop_id, round_key, learner["id"])
    if rnd["status"] not in (ROUND_AVAILABLE, ROUND_IN_PROGRESS):
        raise HTTPException(
            409, "That round isn't available yet — finish the previous one first"
        )
    if rnd.get("interview_id"):
        raise HTTPException(409, "That round is already in progress")

    interview = await start_interview(
        plan_id="",  # a loop round belongs to no course plan
        module_id="",
        user_id=learner["user_id"],
        module_title=rnd["title"],
        topics=rnd.get("focus_skills") or loop.get("target_skills") or [],
        context={
            "kind": "loop",
            "loop_id": loop_id,
            "round_key": round_key,
            "round_kind": rnd["kind"],
            "company": loop.get("company", ""),
            "role": loop.get("role", ""),
            "attempt": int(rnd.get("attempt", 0)) + 1,
        },
        bar=rnd.get("bar"),
        min_questions=rnd.get("min_questions"),
        max_questions=rnd.get("max_questions"),
        prior_questions=rnd.get("prior_questions") or [],
    )

    rnd["interview_id"] = interview["interview_id"]
    rnd["status"] = ROUND_IN_PROGRESS
    rnd["attempt"] = int(rnd.get("attempt", 0)) + 1
    await _save_rounds(loop)

    async def event_stream():
        yield sse_frame(
            {
                "type": "interview_started",
                "interview_id": interview["interview_id"],
                "module_title": rnd["title"],
                "round_key": round_key,
                "round_kind": rnd["kind"],
                "max_questions": interview["max_questions"],
                "bar": interview["bar"],
            }
        )
        async for frame in _agent_sse(
            stream_start(interview),
            "Could not start this round.",
            interview_id=interview["interview_id"],
        ):
            yield frame

    return sse_stream_response(event_stream())


@router.get("/{loop_id}/rounds/{round_key}")
async def get_round(
    loop_id: str, round_key: str, learner: dict = Depends(get_current_learner)
):
    """Read an in-flight round back so a reloaded tab can resume it (plain JSON)."""
    _, rnd = await _owned_round(loop_id, round_key, learner["id"])
    interview = await _round_interview(rnd, learner["user_id"])
    return interview_state(interview)


@router.post("/{loop_id}/rounds/{round_key}/answer")
async def answer_round(
    loop_id: str,
    round_key: str,
    body: AnswerRequest,
    learner: dict = Depends(get_current_learner),
):
    """Score the submitted answer, then stream the next question (or `finished`)."""
    _, rnd = await _owned_round(loop_id, round_key, learner["id"])
    interview = await _round_interview(rnd, learner["user_id"])

    return sse_stream_response(
        _agent_sse(
            stream_answer(interview, body.question_id, body.answer_text),
            "Could not process that answer.",
            interview_id=interview["interview_id"],
        )
    )


@router.post("/{loop_id}/rounds/{round_key}/run-code")
@limiter.limit("60/hour")
async def run_round_code(
    request: Request,
    loop_id: str,
    round_key: str,
    body: RunCodeRequest,
    learner: dict = Depends(get_current_learner),
):
    """Check a code snippet: sandboxed Piston when configured, else an LLM review.

    Rate-limited because the default path is a billed LLM call, not local execution.
    """
    from app.services.code_runner import run_code as _execute

    _, rnd = await _owned_round(loop_id, round_key, learner["id"])
    await _round_interview(rnd, learner["user_id"])
    return await _execute(body.language, body.code, body.stdin)


@router.post("/{loop_id}/rounds/{round_key}/complete/stream")
async def complete_round_stream(
    loop_id: str, round_key: str, learner: dict = Depends(get_current_learner)
):
    """Grade a finished round, record it against the bar, and unlock the next one."""
    loop, rnd = await _owned_round(loop_id, round_key, learner["id"])
    interview = await _round_interview(rnd, learner["user_id"])

    async def run(emit):
        from app.agents.pipelines import run_interview_review

        result = await run_interview_review(
            interview["interview_id"], "", "", emit=emit
        )
        apply_round_result(loop, round_key, result["final_score"])
        await _save_rounds(loop)
        log.info(
            "loop_round_completed",
            loop_id=loop_id,
            round_key=round_key,
            score=result["final_score"],
            bar=result.get("bar"),
            loop_status=loop["status"],
        )
        await emit(
            {
                "type": "action",
                "kind": "round_scored",
                "payload": {**result, "loop": loop_view(loop)},
            }
        )

    return sse_response(run)


@router.post("/{loop_id}/rounds/{round_key}/retry")
async def retry_round(
    loop_id: str, round_key: str, learner: dict = Depends(get_current_learner)
):
    """Reset a graded round for another attempt, remembering what was already asked.

    The previous attempt's questions are carried onto the round so the next one cannot
    re-ask them — a retry that repeats the same questions measures recall of the
    feedback, not the skill. Previous attempts stay in the ledger and are not deleted.
    """
    loop, rnd = await _owned_round(loop_id, round_key, learner["id"])
    if rnd["status"] == ROUND_IN_PROGRESS:
        raise HTTPException(409, "That round is still in progress")
    if not rnd.get("interview_id"):
        raise HTTPException(409, "That round hasn't been attempted yet")

    previous = await col_interviews().find_one(
        {"interview_id": rnd["interview_id"], "user_id": learner["user_id"]}, PROJ
    )
    asked = [
        q.get("text", "")
        for q in (previous or {}).get("questions") or []
        if q.get("text")
    ]
    rnd["prior_questions"] = ((rnd.get("prior_questions") or []) + asked)[-24:]
    rnd["interview_id"] = None
    rnd["status"] = ROUND_AVAILABLE
    rnd["score"] = None
    loop["status"] = "in_progress"
    loop["completed_at"] = None
    await _save_rounds(loop)

    log.info(
        "loop_round_retry",
        loop_id=loop_id,
        round_key=round_key,
        attempt=rnd.get("attempt"),
        carried_questions=len(rnd["prior_questions"]),
    )
    return loop_view(loop)


# ─── Debrief ──────────────────────────────────────────────────────────────────


@router.post("/{loop_id}/debrief/stream")
async def debrief_loop_stream(
    loop_id: str, learner: dict = Depends(get_current_learner)
):
    """Write the loop-level debrief once every round has been graded."""
    loop = await _owned_loop(loop_id, learner["id"])
    if not is_resolved(loop):
        raise HTTPException(409, "Finish every round before asking for a debrief")

    async def run(emit):
        debrief = await _build_debrief(loop, emit)
        await col_interview_loops().update_one(
            {"loop_id": loop_id}, {"$set": {"debrief": debrief}}
        )
        loop["debrief"] = debrief
        await emit(
            {
                "type": "action",
                "kind": "loop_debriefed",
                "payload": loop_view(loop),
            }
        )

    return sse_response(run)


async def _build_debrief(loop: dict, emit) -> dict:
    """Summarise every round against its bar into an actionable debrief."""
    from app.agents.course_planner import _chat
    from app.agents.json_utils import extract_json
    from app.agents.steps import StepTimeline, step_emitter
    from app.prompts.loader import render_prompt

    tl = StepTimeline("loop_debrief")

    async with step_emitter(emit) as _e:
        await _e(tl.start("gather"))
        summaries = {}
        ids = [r["interview_id"] for r in loop["rounds"] if r.get("interview_id")]
        if ids:
            docs = (
                await col_interviews()
                .find({"interview_id": {"$in": ids}}, PROJ)
                .to_list(length=None)
            )
            summaries = {d["interview_id"]: d.get("summary") or "" for d in docs}
        lines = []
        for rnd in loop["rounds"]:
            lines.append(
                f"- {rnd['title']} ({rnd['kind']}): scored {rnd.get('score')}/10 "
                f"against a bar of {rnd.get('bar')}. "
                f"Focus skills: {', '.join(rnd.get('focus_skills') or []) or 'unspecified'}. "
                f"Grader's summary: {summaries.get(rnd.get('interview_id'), 'none')}"
            )
        await _e(tl.done("gather"))

        await _e(tl.start("assess"))
        prompt = render_prompt(
            "interview_loop",
            "debrief",
            company=loop.get("company") or "the company",
            role=loop.get("role") or "the role",
            seniority=loop.get("seniority") or "unspecified",
            skills=", ".join(loop.get("target_skills") or []) or "unspecified",
            rounds_block="\n".join(lines),
        )
        try:
            text = await asyncio.to_thread(_chat, prompt, 700, 0.3)
            parsed = extract_json(text) or {}
        except Exception as e:  # noqa: BLE001 - a failed debrief degrades, never 500s
            log.warning("loop_debrief_failed", error=str(e)[:200])
            parsed = {}
        await _e(tl.done("assess"))

        await _e(tl.start("advise"))
        cleared = [r for r in loop["rounds"] if r.get("status") == "passed"]
        debrief = {
            "verdict": str(parsed.get("verdict") or "").strip()
            or (
                f"You cleared {len(cleared)} of {len(loop['rounds'])} rounds "
                f"for this role."
            ),
            "strengths": [str(s) for s in (parsed.get("strengths") or [])][:6],
            "gaps": [str(g) for g in (parsed.get("gaps") or [])][:6],
            "focus_next": str(parsed.get("focus_next") or "").strip(),
            "rounds_cleared": len(cleared),
            "rounds_total": len(loop["rounds"]),
        }
        await _e(tl.done("advise"))
        return debrief
