"""course_gen pipeline: research -> design -> finalize (save + quiz pregen)."""

from __future__ import annotations

import asyncio

import structlog

from app.agents.steps import StepEmit, StepTimeline, step_emitter
from app.observability import traced_pipeline

log = structlog.get_logger()


async def run_course_gen(goal: str, user_id: str, emit: StepEmit = None) -> dict:
    """Build + persist a course plan, streaming research/design/finalize steps."""
    from app.agents.course_planner import (
        _build_plan,
        _generate_plan_json,
        _pregenerate_quizzes_for_plan,
        _save_plan,
        _search_web,
    )

    tl = StepTimeline("course_plan")

    async with (
        traced_pipeline(
            "generate-course-plan",
            input={"goal": goal},
            user_id=user_id,
            tags=["course-gen"],
        ) as root,
        step_emitter(emit) as _e,
    ):
        await _e(tl.start("research"))
        research = await asyncio.to_thread(_search_web, goal)
        await _e(tl.done("research"))

        await _e(tl.start("design"))
        design = await _generate_plan_json(goal, research or [])
        await _e(tl.done("design"))

        await _e(tl.start("finalize"))
        plan = _build_plan(goal, user_id, design or {})
        await _save_plan(plan)
        log.info("course_plan_saved", plan_id=plan["plan_id"])
        bg = asyncio.create_task(_pregenerate_quizzes_for_plan(plan))
        bg.add_done_callback(
            lambda t: (
                log.error("quiz_pregenerate_task_failed", error=str(t.exception()))
                if t.exception()
                else None
            )
        )
        await _e(tl.done("finalize"))
        root.update(
            output={
                "plan_id": plan["plan_id"],
                "title": plan.get("title"),
                "modules": [m.get("title") for m in plan.get("modules") or []],
            }
        )
        return plan
