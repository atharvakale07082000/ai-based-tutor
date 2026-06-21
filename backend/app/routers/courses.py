"""Course Planning & AI Interview router."""

import asyncio
import subprocess
import sys

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.auth.jwt import get_current_user_id

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
log = structlog.get_logger()

_MAX_OUTPUT = 4000  # chars
_CODE_TIMEOUT = 10  # seconds
_MEM_LIMIT_BYTES = 128 * 1024 * 1024  # 128 MB virtual memory per subprocess
_CPU_LIMIT_S = 8  # seconds CPU time (< _CODE_TIMEOUT so it fires first)


# ─── Schemas ──────────────────────────────────────────────────────────────────


class PlanRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=500)


class AnswerRequest(BaseModel):
    question_id: int = Field(ge=1, le=100)
    answer_text: str = Field(min_length=1, max_length=5_000)


class RunCodeRequest(BaseModel):
    code: str = Field(max_length=10_000)
    language: str = Field(default="python", max_length=20)


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


@router.post("/{plan_id}/modules/{module_id}/interview/{interview_id}/run-code")
async def run_code(
    plan_id: str,
    module_id: str,
    interview_id: str,
    body: RunCodeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Execute a code snippet in a sandboxed subprocess and return stdout/stderr."""
    interview = await get_interview(interview_id)
    if not interview or interview["user_id"] != user_id:
        raise HTTPException(404, "Interview not found")

    if body.language not in ("python", "python3"):
        raise HTTPException(400, "Only Python execution is supported")

    code = body.code.strip()
    if not code:
        return {"stdout": "", "stderr": "", "exit_code": 0}

    def _preexec_limits() -> None:
        """Apply OS-level resource limits inside the child process (Unix only)."""
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (_MEM_LIMIT_BYTES, _MEM_LIMIT_BYTES))
            resource.setrlimit(resource.RLIMIT_CPU, (_CPU_LIMIT_S, _CPU_LIMIT_S))
        except Exception:
            pass  # Windows or no resource module — skip silently

    def _run() -> dict:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=_CODE_TIMEOUT,
                preexec_fn=_preexec_limits if sys.platform != "win32" else None,
            )
            return {
                "stdout": proc.stdout[:_MAX_OUTPUT],
                "stderr": proc.stderr[:_MAX_OUTPUT],
                "exit_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": f"Execution timed out after {_CODE_TIMEOUT}s", "exit_code": 124}
        except Exception as e:
            return {"stdout": "", "stderr": str(e)[:500], "exit_code": 1}

    result = await asyncio.to_thread(_run)
    return result


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
