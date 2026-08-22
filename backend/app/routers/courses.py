"""Course Planning & AI Interview router."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agents.course_planner import (
    complete_interview,
    create_course_plan,
    get_interview,
    get_plan,
    interview_state,
    list_plans,
    start_interview,
)
from app.agents.interview_agent import stream_answer, stream_start
from app.auth.jwt import get_current_user_id
from app.guardrails import check_topic, topic_reject_message
from app.sse import SSE_DONE, sse_frame, sse_response, sse_stream_response

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
log = structlog.get_logger()


async def _owned_plan(plan_id: str, user_id: str) -> dict:
    """Fetch a plan the caller owns, or raise 404 (same 404 for missing and foreign)."""
    plan = await get_plan(plan_id)
    if not plan or plan["user_id"] != user_id:
        raise HTTPException(404, "Plan not found")
    return plan


async def _owned_interview(interview_id: str, user_id: str) -> dict:
    """Fetch an interview the caller owns, or raise 404."""
    interview = await get_interview(interview_id)
    if not interview or interview["user_id"] != user_id:
        raise HTTPException(404, "Interview not found")
    return interview


async def _agent_sse(source, error_message: str, **log_ctx):
    """Frame an agent event stream as SSE, converting any failure to a generic error frame."""
    try:
        async for ev in source:
            yield sse_frame(ev)
    except Exception as e:  # noqa: BLE001 - generic to client, detail in logs
        log.error("interview_stream_error", error=str(e)[:300], **log_ctx)
        yield sse_frame({"type": "error", "message": error_message})
    yield SSE_DONE


def _validated_goal(goal: str, user_id: str, event: str) -> str:
    """Return the trimmed goal, or raise 400 if it's empty or off-limits."""
    trimmed = goal.strip()
    if not trimmed:
        raise HTTPException(400, "Goal cannot be empty")
    guard = check_topic(trimmed)
    if not guard.passed:
        log.info(event, user_id=user_id, reason=guard.reason, goal=trimmed[:80])
        raise HTTPException(400, topic_reject_message(guard.reason))
    return trimmed


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
async def plan_course(
    request: Request, body: PlanRequest, user_id: str = Depends(get_current_user_id)
):
    """Generate an AI course plan from a learning goal and persist it."""
    goal = _validated_goal(body.goal, user_id, "course_plan_rejected")
    log.info("course_plan_generate", user_id=user_id, goal=goal[:80])
    try:
        plan = await create_course_plan(goal, user_id)
        return plan
    except Exception as e:
        raise HTTPException(500, f"Failed to generate plan: {e}")


@router.post("/plan/stream")
@limiter.limit("3/hour")
async def plan_course_stream(
    request: Request, body: PlanRequest, user_id: str = Depends(get_current_user_id)
):
    """Generate a course plan while streaming a live step timeline as SSE.

    Emits `step` events (research → design → finalize), then a `plan_created`
    action carrying the saved plan summary, then `[DONE]`.
    """
    goal = _validated_goal(body.goal, user_id, "course_plan_stream_rejected")
    log.info("course_plan_stream", user_id=user_id, goal=goal[:80])

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

        summary = (
            f"{plan['title']}: {plan.get('description', '')}\nModules: "
            + ", ".join(m.get("title", "") for m in plan["modules"])
        )
        maybe_eval_single_turn("course_planner", goal, summary, learner_id=user_id)

    return sse_response(run)


@router.get("/")
async def get_my_plans(user_id: str = Depends(get_current_user_id)):
    """Return all course plans belonging to the current learner."""
    return await list_plans(user_id)


@router.get("/{plan_id}")
async def get_course_plan(plan_id: str, user_id: str = Depends(get_current_user_id)):
    """Fetch a single course plan by ID, enforcing ownership."""
    return await _owned_plan(plan_id, user_id)


# ─── Interview endpoints ──────────────────────────────────────────────────────


@router.post("/{plan_id}/modules/{module_id}/interview/start")
async def start_module_interview(
    plan_id: str,
    module_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Begin an adaptive AI interview: create it, then stream the agent's first question as SSE.

    Emits `interview_started` (carrying interview_id, module_title and the max-question
    ceiling), live `reasoning` while the agent thinks, a `question` event, then `[DONE]`.
    """
    plan = await _owned_plan(plan_id, user_id)

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

    async def event_stream():
        yield sse_frame(
            {
                "type": "interview_started",
                "interview_id": interview["interview_id"],
                "module_title": module["title"],
                "max_questions": interview["max_questions"],
                "bar": interview["bar"],
            }
        )
        async for frame in _agent_sse(
            stream_start(interview),
            "Could not start the interview.",
            interview_id=interview["interview_id"],
        ):
            yield frame

    return sse_stream_response(event_stream())


@router.get("/{plan_id}/modules/{module_id}/interview/{interview_id}")
async def get_interview_progress(
    plan_id: str,
    module_id: str,
    interview_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Read an in-progress interview back so a reloaded tab can resume it (plain JSON, not SSE).

    Server state (the interview doc + the agent's paused session) outlives the browser tab,
    so this returns the outstanding question, the answers graded so far, and a `status`
    telling the client whether to answer, score, or show the final result. See
    `course_planner.interview_state` for the field-by-field contract.
    """
    return interview_state(await _owned_interview(interview_id, user_id))


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/answer")
async def submit_answer(
    plan_id: str,
    module_id: str,
    interview_id: str,
    body: AnswerRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Score the submitted answer, then stream the agent's next question (or `finished`) as SSE.

    Emits an `evaluation` event (the tuned per-answer score), live `reasoning`, then either a
    `question` event or a `finished` event, then `[DONE]`.
    """
    interview = await _owned_interview(interview_id, user_id)

    return sse_stream_response(
        _agent_sse(
            stream_answer(interview, body.question_id, body.answer_text),
            "Could not process that answer.",
            interview_id=interview_id,
        )
    )


@router.get("/run-code/languages")
async def run_code_languages(user_id: str = Depends(get_current_user_id)):
    """List the language ids the code runner supports (for the editor's language picker)."""
    from app.services.code_runner import supported_language_ids

    return {"languages": supported_language_ids()}


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/run-code")
@limiter.limit("60/hour")
async def run_code(
    request: Request,
    plan_id: str,
    module_id: str,
    interview_id: str,
    body: RunCodeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Check a code snippet: sandboxed Piston execution when configured, else an LLM review.

    Rate-limited because the default path is a billed LLM call, not local execution.
    """
    from app.services.code_runner import run_code as _execute

    await _owned_interview(interview_id, user_id)

    return await _execute(body.language, body.code, body.stdin)


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/complete")
async def finish_interview(
    plan_id: str,
    module_id: str,
    interview_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Mark an interview complete and update module progress."""
    await _owned_interview(interview_id, user_id)
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
    await _owned_interview(interview_id, user_id)

    async def run(emit):
        result = await complete_interview(interview_id, plan_id, module_id, emit=emit)
        await emit({"type": "action", "kind": "interview_scored", "payload": result})

    return sse_response(run)
