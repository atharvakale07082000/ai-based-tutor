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

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pymongo import ReturnDocument

from app.agents.skill_gap import analyze_gap
from app.agents.steps import StepTimeline
from app.auth.jwt import get_current_learner
from app.db.mongo import PROJ, col_job_applications
from app.schemas.jobs import JDParseRequest, JobApplication, JobCreate, JobUpdate
from app.sse import sse_response

router = APIRouter()
log = structlog.get_logger()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _analysis_run(jd_text: str, proficiency: dict, required_skills: list[str] | None):
    """Build the ``run`` worker for JD analysis / reanalysis (framed by ``sse_response``).

    If ``required_skills`` is given (reanalyze), skip LLM parsing and only re-score.
    """

    async def run(emit):
        from app.agents.pipelines import run_jd_analyze

        result = await run_jd_analyze(
            {
                "jd_text": jd_text,
                "proficiency": proficiency,
                "required_skills": required_skills,
            },
            emit=emit,
        )
        parsed = result["parsed"]
        analysis = result["gap"]
        payload = {**parsed, **analysis, "source_jd": jd_text[:20_000]}
        await emit({"type": "action", "kind": "jd_analyzed", "payload": payload})

        # Online eval sampling: is the extracted role/skills faithful to the pasted JD?
        from app.evals.deepeval_metrics import maybe_eval_single_turn

        summary = (
            f"Role: {parsed.get('role', '')} ({parsed.get('seniority', '')}). Required skills: "
            + ", ".join(parsed.get("required_skills") or [])
        )
        maybe_eval_single_turn(
            "skill_gap",
            "Extract the role and required skills from this job description.",
            summary,
            retrieval_context=[jd_text[:4000]] if jd_text else None,
        )

    return run


@router.post("/analyze/stream")
async def analyze_jd_stream(
    body: JDParseRequest, learner: dict = Depends(get_current_learner)
):
    """Parse a pasted JD and stream a live skill-gap analysis against the learner's proficiency."""
    proficiency = learner.get("topic_proficiency_map") or {}
    return sse_response(
        _analysis_run(body.jd_text.strip(), proficiency, required_skills=None)
    )


@router.post("", response_model=JobApplication)
@router.post("/", response_model=JobApplication)
async def create_job(body: JobCreate, learner: dict = Depends(get_current_learner)):
    """Save a job application (typically from an analyzed JD)."""
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "learner_id": learner["id"],
        **body.model_dump(),
        "created_at": now,
        "updated_at": now,
    }
    await col_job_applications().insert_one({**doc})
    log.info(
        "job_created",
        job_id=doc["id"],
        stage=doc["stage"],
        readiness=doc["readiness_score"],
    )
    return JobApplication(**doc)


@router.get("")
@router.get("/")
async def list_jobs(learner: dict = Depends(get_current_learner)):
    """Return all of the learner's job applications, most-recently-updated first."""
    jobs = (
        await col_job_applications()
        .find({"learner_id": learner["id"]}, PROJ)
        .sort("updated_at", -1)
        .to_list(length=None)
    )
    return {"jobs": jobs}


@router.get("/{job_id}", response_model=JobApplication)
async def get_job(job_id: str, learner: dict = Depends(get_current_learner)):
    """Fetch a single job application owned by the learner."""
    job = await col_job_applications().find_one(
        {"id": job_id, "learner_id": learner["id"]}, PROJ
    )
    if not job:
        raise HTTPException(404, "Job application not found")
    return JobApplication(**job)


@router.patch("/{job_id}", response_model=JobApplication)
async def update_job(
    job_id: str, body: JobUpdate, learner: dict = Depends(get_current_learner)
):
    """Move stage or edit fields on a job application."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates["updated_at"] = _now()
    # Update and read back in one round trip rather than update_one + find_one.
    job = await col_job_applications().find_one_and_update(
        {"id": job_id, "learner_id": learner["id"]},
        {"$set": updates},
        projection=PROJ,
        return_document=ReturnDocument.AFTER,
    )
    if not job:
        raise HTTPException(404, "Job application not found")
    return JobApplication(**job)


@router.delete("/{job_id}")
async def delete_job(job_id: str, learner: dict = Depends(get_current_learner)):
    """Remove a job application."""
    result = await col_job_applications().delete_one(
        {"id": job_id, "learner_id": learner["id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Job application not found")
    return {"deleted": True, "id": job_id}


@router.post("/{job_id}/reanalyze/stream")
async def reanalyze_job_stream(
    job_id: str, learner: dict = Depends(get_current_learner)
):
    """Recompute a saved job's readiness/gaps against the learner's current proficiency.

    Persists the refreshed analysis, then streams the same `jd_analyzed` action so the UI updates.
    """
    job = await col_job_applications().find_one(
        {"id": job_id, "learner_id": learner["id"]}, PROJ
    )
    if not job:
        raise HTTPException(404, "Job application not found")
    proficiency = learner.get("topic_proficiency_map") or {}
    required = job.get("required_skills") or []

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
        await emit(
            {"type": "action", "kind": "jd_analyzed", "payload": {**job, **analysis}}
        )

    return sse_response(run)
