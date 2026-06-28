"""Course Planning & AI Interview router."""

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agents.course_planner import (
    complete_interview,
    create_course_plan,
    evaluate_answer,
    get_interview,
    get_plan,
    list_plans,
    start_interview,
)
from app.agents.steps import sse_step_stream
from app.auth.jwt import get_current_user_id

_SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
log = structlog.get_logger()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class PlanRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=500)


class AnswerRequest(BaseModel):
    question_id: int = Field(ge=1, le=100)
    answer_text: str = Field(min_length=1, max_length=5_000)


class RunCodeRequest(BaseModel):
    code: str = Field(max_length=10_000)
    language: str = Field(default="python", max_length=40)
    stdin: str = Field(default="", max_length=10_000)


# ─── Course plan endpoints ────────────────────────────────────────────────────


@router.post("/plan")
@limiter.limit("3/hour")
async def plan_course(request: Request, body: PlanRequest, user_id: str = Depends(get_current_user_id)):
    """Generate an AI course plan from a learning goal and persist it."""
    if not body.goal.strip():
        raise HTTPException(400, "Goal cannot be empty")
    log.info("course_plan_generate", user_id=user_id, goal=body.goal[:80])
    try:
        plan = await create_course_plan(body.goal.strip(), user_id)
        return plan
    except Exception as e:
        raise HTTPException(500, f"Failed to generate plan: {e}")


@router.post("/plan/stream")
@limiter.limit("3/hour")
async def plan_course_stream(request: Request, body: PlanRequest, user_id: str = Depends(get_current_user_id)):
    """Generate a course plan while streaming a live step timeline as SSE.

    Emits `step` events (research → design → finalize), then a `plan_created`
    action carrying the saved plan summary, then `[DONE]`.
    """
    if not body.goal.strip():
        raise HTTPException(400, "Goal cannot be empty")
    goal = body.goal.strip()
    log.info("course_plan_stream", user_id=user_id, goal=goal[:80])

    async def event_stream():
        """Drive create_course_plan with a live emitter and frame events as SSE."""

        async def run(emit):
            plan = await create_course_plan(goal, user_id, emit=emit)
            await emit(
                {
                    "type": "action",
                    "kind": "plan_created",
                    "payload": {
                        "plan_id": plan["plan_id"],
                        "title": plan["title"],
                        "module_count": len(plan["modules"]),
                        "weeks": plan["total_duration_weeks"],
                        "url": f"/courses/{plan['plan_id']}",
                    },
                }
            )
            # Online eval sampling: does the generated plan correctly address the learner's goal?
            from app.evals.deepeval_metrics import maybe_eval_single_turn

            summary = f"{plan['title']}: {plan.get('description', '')}\nModules: " + ", ".join(
                m.get("title", "") for m in plan["modules"]
            )
            maybe_eval_single_turn("course_planner", goal, summary, learner_id=user_id)

        async for ev in sse_step_stream(run):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/")
async def get_my_plans(user_id: str = Depends(get_current_user_id)):
    """Return all course plans belonging to the current learner."""
    return await list_plans(user_id)


@router.get("/{plan_id}")
async def get_course_plan(plan_id: str, user_id: str = Depends(get_current_user_id)):
    """Fetch a single course plan by ID, enforcing ownership."""
    plan = await get_plan(plan_id)
    if not plan or plan["user_id"] != user_id:
        raise HTTPException(404, "Plan not found")
    return plan


# ─── Interview endpoints ──────────────────────────────────────────────────────


@router.post("/{plan_id}/modules/{module_id}/interview/start")
async def start_module_interview(
    plan_id: str,
    module_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Begin an AI interview for a specific course module."""
    plan = await get_plan(plan_id)
    if not plan or plan["user_id"] != user_id:
        raise HTTPException(404, "Plan not found")

    module = next((m for m in plan["modules"] if m["id"] == module_id), None)
    if not module:
        raise HTTPException(404, "Module not found")

    interview = await start_interview(
        plan_id=plan_id,
        module_id=module_id,
        user_id=user_id,
        module_title=module["title"],
        topics=module["topics"],
    )
    return interview


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/answer")
async def submit_answer(
    plan_id: str,
    module_id: str,
    interview_id: str,
    body: AnswerRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Submit and AI-evaluate a single interview answer."""
    interview = await get_interview(interview_id)
    if not interview or interview["user_id"] != user_id:
        raise HTTPException(404, "Interview not found")
    try:
        evaluation = await evaluate_answer(interview_id, body.question_id, body.answer_text)
        return evaluation
    except Exception as e:
        raise HTTPException(500, f"Evaluation failed: {e}")


@router.get("/run-code/languages")
async def run_code_languages(user_id: str = Depends(get_current_user_id)):
    """List the language ids the code runner supports (for the editor's language picker)."""
    from app.services.code_runner import supported_language_ids

    return {"languages": supported_language_ids()}


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/run-code")
async def run_code(
    plan_id: str,
    module_id: str,
    interview_id: str,
    body: RunCodeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Execute a code snippet (multi-language via Piston; Python subprocess fallback)."""
    from app.services.code_runner import run_code as _execute

    interview = await get_interview(interview_id)
    if not interview or interview["user_id"] != user_id:
        raise HTTPException(404, "Interview not found")

    return await _execute(body.language, body.code, getattr(body, "stdin", "") or "")


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/complete")
async def finish_interview(
    plan_id: str,
    module_id: str,
    interview_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Mark an interview complete and update module progress."""
    interview = await get_interview(interview_id)
    if not interview or interview["user_id"] != user_id:
        raise HTTPException(404, "Interview not found")
    try:
        result = await complete_interview(interview_id, plan_id, module_id)
        return result
    except Exception as e:
        raise HTTPException(500, f"Could not complete interview: {e}")


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/complete/stream")
async def finish_interview_stream(
    plan_id: str,
    module_id: str,
    interview_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Complete & score an interview while streaming a live step timeline as SSE.

    Emits `step` events (evaluate → score → feedback), then an `interview_scored`
    action carrying the full result, then `[DONE]`.
    """
    interview = await get_interview(interview_id)
    if not interview or interview["user_id"] != user_id:
        raise HTTPException(404, "Interview not found")

    async def event_stream():
        """Drive complete_interview with a live emitter and frame events as SSE."""

        async def run(emit):
            result = await complete_interview(interview_id, plan_id, module_id, emit=emit)
            await emit({"type": "action", "kind": "interview_scored", "payload": result})

        async for ev in sse_step_stream(run):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
