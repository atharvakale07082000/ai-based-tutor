"""
course_gen workflow: research → design → persist.

Each task is a thin wrapper over the existing helpers in app.agents.course_planner, so behaviour
(and the streamed step events) are identical to the previous hand-rolled orchestration. Task ids and
labels match the original ``STEP_PLANS["course_plan"]`` so the SSE output is byte-for-byte the same.
"""

from __future__ import annotations

import asyncio

import structlog

from app.agents.workflow.base import Task
from app.agents.workflow.planner import register_workflow
from app.agents.workflow.registry import register

log = structlog.get_logger()


@register("course.research")
async def _research(ctx, task):
    """Web-research the goal (off-thread; blocking DDG search)."""
    from app.agents.course_planner import _search_web

    return await asyncio.to_thread(_search_web, ctx.request["goal"])


@register("course.design")
async def _design(ctx, task):
    """Design the structured plan JSON from the goal + research context (LLM)."""
    from app.agents.course_planner import _generate_plan_json

    return await _generate_plan_json(ctx.request["goal"], ctx.result("research") or [])


@register("course.persist")
async def _persist(ctx, task):
    """Build + save the plan, and kick off background quiz pre-generation. Returns the saved plan."""
    from app.agents.course_planner import _build_plan, _pregenerate_quizzes_for_plan, _save_plan

    plan = _build_plan(ctx.request["goal"], ctx.request["user_id"], ctx.result("design") or {})
    await _save_plan(plan)
    log.info("course_planner_plan_saved", plan_id=plan["plan_id"])
    bg = asyncio.create_task(_pregenerate_quizzes_for_plan(plan))
    bg.add_done_callback(
        lambda t: log.error("quiz_pregenerate_task_failed", error=str(t.exception())) if t.exception() else None
    )
    return plan


register_workflow(
    "course_gen",
    [
        Task("research", "Researching the topic", "course.research"),
        Task("design", "Designing your curriculum", "course.design"),
        Task("finalize", "Saving your plan", "course.persist"),
    ],
)
