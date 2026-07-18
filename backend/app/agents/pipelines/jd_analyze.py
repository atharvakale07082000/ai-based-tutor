"""jd_analyze pipeline: parse -> match -> recommend.

The ``parse`` step short-circuits when ``required_skills`` is supplied (the
re-analyze path), skipping the LLM JD parse. Returns the gap-analysis result
(readiness_score, skill_gaps, recommendations) plus the parsed metadata.
"""

from __future__ import annotations

from app.agents.steps import StepEmit, StepTimeline


async def run_jd_analyze(request: dict, emit: StepEmit = None) -> dict:
    """Parse a JD, match required skills to proficiency, and recommend next steps."""
    from app.agents.skill_gap import analyze_gap, parse_jd

    tl = StepTimeline("jd_analyze")

    async def _e(ev: dict) -> None:
        if emit:
            await emit(ev)

    await _e(tl.start("parse"))
    if request.get("required_skills") is not None:
        parsed = {
            "company": request.get("company", ""),
            "role": request.get("role", ""),
            "seniority": request.get("seniority", ""),
            "required_skills": request["required_skills"],
        }
    else:
        parsed = await parse_jd(request["jd_text"])
    await _e(tl.done("parse"))

    await _e(tl.start("match"))
    gap = analyze_gap(
        parsed.get("required_skills") or [], request.get("proficiency") or {}
    )
    await _e(tl.done("match"))

    await _e(tl.start("recommend"))
    # Recommendations are produced inside analyze_gap; this is the closing step.
    await _e(tl.done("recommend"))

    return {"parsed": parsed, "gap": gap}
