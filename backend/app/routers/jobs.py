"""
Job Tracker router — Kanban application board + AI skill-gap analysis.

Endpoints (prefix /api/v1/jobs):
  POST   /analyze/stream        — paste a JD → stream skill-gap analysis (SSE step timeline)
  POST   /                      — save a job application
  GET    /                      — list the learner's applications
  GET    /{job_id}              — fetch one
  PATCH  /{job_id}              — move stage / edit fields
  DELETE /{job_id}              — remove
  POST   /{job_id}/reanalyze/stream — recompute readiness against current proficiency
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.agents.skill_gap_agent import analyze_gap
from app.agents.steps import StepTimeline, sse_step_stream
from app.auth.jwt import get_current_user_id
from app.db.mongo import col_job_applications, col_learners
from app.schemas.jobs import JDParseRequest, JobApplication, JobCreate, JobUpdate

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}
_SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}


async def _learner_or_404(user_id: str) -> dict:
    """Return the learner profile for the user or raise 404."""
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        raise HTTPException(404, "Learner not found")
    return learner


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _analysis_stream(jd_text: str, proficiency: dict, required_skills: list[str] | None):
    """Build the SSE event_stream for JD analysis / reanalysis.

    If ``required_skills`` is given (reanalyze), skip LLM parsing and only re-score.
    """

    async def event_stream():
        async def run(emit):
            from app.agents.workflow import run_workflow

            ctx = await run_workflow(
                "jd_analyze",
                {"jd_text": jd_text, "proficiency": proficiency, "required_skills": required_skills},
                emit=emit,
            )
            parsed = ctx.result("parse")
            analysis = ctx.result("match")
            payload = {**parsed, **analysis, "source_jd": jd_text[:20_000]}
            await emit({"type": "action", "kind": "jd_analyzed", "payload": payload})

            # Online eval sampling: is the extracted role/skills faithful to the pasted JD?
            from app.evals.deepeval_metrics import maybe_eval_single_turn

            summary = f"Role: {parsed.get('role', '')} ({parsed.get('seniority', '')}). Required skills: " + ", ".join(
                parsed.get("required_skills") or []
            )
            maybe_eval_single_turn(
                "skill_gap",
                "Extract the role and required skills from this job description.",
                summary,
                retrieval_context=[jd_text[:4000]] if jd_text else None,
            )

        async for ev in sse_step_stream(run):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return event_stream


@router.post("/analyze/stream")
async def analyze_jd_stream(body: JDParseRequest, user_id: str = Depends(get_current_user_id)):
    """Parse a pasted JD and stream a live skill-gap analysis against the learner's proficiency."""
    learner = await _learner_or_404(user_id)
    proficiency = learner.get("topic_proficiency_map") or {}
    stream = _analysis_stream(body.jd_text.strip(), proficiency, required_skills=None)
    return StreamingResponse(stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("", response_model=JobApplication)
@router.post("/", response_model=JobApplication)
async def create_job(body: JobCreate, user_id: str = Depends(get_current_user_id)):
    """Save a job application (typically from an analyzed JD)."""
    learner = await _learner_or_404(user_id)
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "learner_id": learner["id"],
        **body.model_dump(),
        "created_at": now,
        "updated_at": now,
    }
    await col_job_applications().insert_one({**doc})
    log.info("job_created", job_id=doc["id"], stage=doc["stage"], readiness=doc["readiness_score"])
    return JobApplication(**doc)


@router.get("")
@router.get("/")
async def list_jobs(user_id: str = Depends(get_current_user_id)):
    """Return all of the learner's job applications, most-recently-updated first."""
    learner = await _learner_or_404(user_id)
    jobs = (
        await col_job_applications()
        .find({"learner_id": learner["id"]}, PROJ)
        .sort("updated_at", -1)
        .to_list(length=None)
    )
    return {"jobs": jobs}


@router.get("/{job_id}", response_model=JobApplication)
async def get_job(job_id: str, user_id: str = Depends(get_current_user_id)):
    """Fetch a single job application owned by the learner."""
    learner = await _learner_or_404(user_id)
    job = await col_job_applications().find_one({"id": job_id, "learner_id": learner["id"]}, PROJ)
    if not job:
        raise HTTPException(404, "Job application not found")
    return JobApplication(**job)


@router.patch("/{job_id}", response_model=JobApplication)
async def update_job(job_id: str, body: JobUpdate, user_id: str = Depends(get_current_user_id)):
    """Move stage or edit fields on a job application."""
    learner = await _learner_or_404(user_id)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates["updated_at"] = _now()
    result = await col_job_applications().update_one({"id": job_id, "learner_id": learner["id"]}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Job application not found")
    job = await col_job_applications().find_one({"id": job_id, "learner_id": learner["id"]}, PROJ)
    return JobApplication(**job)


@router.delete("/{job_id}")
async def delete_job(job_id: str, user_id: str = Depends(get_current_user_id)):
    """Remove a job application."""
    learner = await _learner_or_404(user_id)
    result = await col_job_applications().delete_one({"id": job_id, "learner_id": learner["id"]})
    if result.deleted_count == 0:
        raise HTTPException(404, "Job application not found")
    return {"deleted": True, "id": job_id}


@router.post("/{job_id}/reanalyze/stream")
async def reanalyze_job_stream(job_id: str, user_id: str = Depends(get_current_user_id)):
    """Recompute a saved job's readiness/gaps against the learner's current proficiency.

    Persists the refreshed analysis, then streams the same `jd_analyzed` action so the UI updates.
    """
    learner = await _learner_or_404(user_id)
    job = await col_job_applications().find_one({"id": job_id, "learner_id": learner["id"]}, PROJ)
    if not job:
        raise HTTPException(404, "Job application not found")
    proficiency = learner.get("topic_proficiency_map") or {}
    required = job.get("required_skills") or []

    async def event_stream():
        async def run(emit):
            tl = StepTimeline("jd_analyze")
            await emit(tl.start("match"))
            analysis = analyze_gap(required, proficiency)
            await emit(tl.done("match"))
            await emit(tl.start("recommend"))
            await col_job_applications().update_one(
                {"id": job_id, "learner_id": learner["id"]},
                {"$set": {**analysis, "updated_at": _now()}},
            )
            await emit(tl.done("recommend"))
            await emit({"type": "action", "kind": "jd_analyzed", "payload": {**job, **analysis}})

        async for ev in sse_step_stream(run):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
