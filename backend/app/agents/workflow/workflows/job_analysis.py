"""
jd_analyze workflow: parse → match → recommend.

Wraps the JD skill-gap analysis previously inlined in the jobs router. Task ids/labels match
``STEP_PLANS["jd_analyze"]`` so the streamed steps are unchanged. The ``parse`` task short-circuits
when ``required_skills`` is supplied (the re-analyze path), skipping the LLM JD parse.
"""

from __future__ import annotations

from app.agents.workflow.base import Task
from app.agents.workflow.planner import register_workflow
from app.agents.workflow.registry import register


@register("jd.parse")
async def _parse(ctx, task):
    """Extract company/role/skills from the JD — or pass through supplied skills (re-analyze)."""
    req = ctx.request
    if req.get("required_skills") is not None:
        return {"company": "", "role": "", "seniority": "", "required_skills": req["required_skills"]}
    from app.agents.skill_gap_agent import parse_jd

    return await parse_jd(req["jd_text"])


@register("jd.match")
async def _match(ctx, task):
    """Score required skills against the learner's proficiency map (pure)."""
    from app.agents.skill_gap_agent import analyze_gap

    parsed = ctx.result("parse")
    return analyze_gap(parsed.get("required_skills") or [], ctx.request.get("proficiency") or {})


@register("jd.recommend")
async def _recommend(ctx, task):
    """Recommendations are produced inside ``analyze_gap``; this is the closing progress step."""
    return {}


register_workflow(
    "jd_analyze",
    [
        Task("parse", "Reading the job description", "jd.parse"),
        Task("match", "Matching against your skills", "jd.match"),
        Task("recommend", "Finding ways to close the gaps", "jd.recommend"),
    ],
)
