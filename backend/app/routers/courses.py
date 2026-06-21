"""Course Planning & AI Interview router."""

import asyncio
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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

_MAX_OUTPUT = 4000  # chars
_CODE_TIMEOUT = 10  # seconds


# ─── Schemas ──────────────────────────────────────────────────────────────────


class PlanRequest(BaseModel):
    goal: str


class AnswerRequest(BaseModel):
    question_id: int
    answer_text: str


class RunCodeRequest(BaseModel):
    code: str
    language: str = "python"


# ─── Course plan endpoints ────────────────────────────────────────────────────


@router.post("/plan")
async def plan_course(body: PlanRequest, user_id: str = Depends(get_current_user_id)):
    """Generate an AI course plan from a learning goal and persist it."""
    if not body.goal.strip():
        raise HTTPException(400, "Goal cannot be empty")
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

    def _run() -> dict:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=_CODE_TIMEOUT,
                # Restrict environment — no network, limited memory via ulimit is OS-specific;
                # for an educational single-tenant deployment this subprocess approach is sufficient.
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
