"""loop_setup pipeline: research -> design -> calibrate.

Turns a saved job application into an interview loop: what rounds this employer
probably runs, what each round is about, and what score clears the bar at this
seniority. Returns the persisted loop document.

The research step reads third-party web content. It is passed to the model inside a
delimited block and every prompt in ``prompts/interview_loop.yaml`` states that it is
data, never instructions — scraped text must never be able to steer the design step.
"""

from __future__ import annotations

import asyncio

import structlog

from app.agents.steps import StepEmit, StepTimeline, step_emitter

log = structlog.get_logger()

# Cap on research text handed to the model, and on how long the search may take.
_RESEARCH_CHARS = 2500
_SEARCH_TIMEOUT_S = 20.0


def _search_process(company: str, role: str) -> list[dict]:
    """DDG search for how this company interviews. Best-effort — never raises."""
    from ddgs import DDGS

    queries = [
        f"{company} {role} interview process rounds",
        f"{company} interview experience {role}",
    ]
    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            for q in queries:
                for r in ddgs.text(q, max_results=5):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "body": (r.get("body", "") or "")[:300],
                            "href": r.get("href", ""),
                        }
                    )
    except Exception as e:  # noqa: BLE001 - research is optional, the loop is not
        log.warning("loop_research_error", company=company[:60], error=str(e)[:200])
    return results[:10]


def _research_block(results: list[dict]) -> str:
    if not results:
        return "No reliable information about this company's process was found."
    joined = "\n".join(f"- {r['title']}: {r['body']}" for r in results)
    return joined[:_RESEARCH_CHARS]


async def run_loop_setup(job: dict, learner_id: str, emit: StepEmit = None) -> dict:
    """Design and persist an interview loop for one saved job application."""
    from app.agents.course_planner import _chat
    from app.agents.json_utils import extract_json_array
    from app.agents.loops import build_loop, normalize_rounds
    from app.db.mongo import col_interview_loops, col_job_applications
    from app.prompts.loader import render_prompt

    company = job.get("company") or "the company"
    role = job.get("role") or "the role"
    seniority = job.get("seniority") or ""
    skills = list(job.get("required_skills") or [])[:20]

    tl = StepTimeline("loop_setup")

    async with step_emitter(emit) as _e:
        # research — what does this company's process actually look like?
        await _e(tl.start("research"))
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(_search_process, company, role),
                timeout=_SEARCH_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001 - research degrades, it never fails setup
            log.warning("loop_research_unavailable", error=str(e)[:200])
            results = []
        research = _research_block(results)
        await _e(tl.done("research"))

        # design — the round ladder, grounded in the JD's own skills
        await _e(tl.start("design"))
        raw_rounds = None
        try:
            prompt = render_prompt(
                "interview_loop",
                "design_rounds",
                company=company,
                role=role,
                seniority=seniority or "unspecified",
                skills=", ".join(skills) or "unspecified",
                research=research,
            )
            text = await asyncio.to_thread(_chat, prompt, 700, 0.2)
            raw_rounds = extract_json_array(text)
        except Exception as e:  # noqa: BLE001 - fall back to the default ladder
            log.warning("loop_design_failed", error=str(e)[:200])
        # normalize_rounds validates the model's proposal and falls back on its own if
        # the shape, the kinds, or the count are unusable.
        rounds = normalize_rounds(raw_rounds, skills, seniority)

        summary = ""
        try:
            summary_prompt = render_prompt(
                "interview_loop",
                "process_summary",
                company=company,
                role=role,
                research=research,
            )
            summary = (await asyncio.to_thread(_chat, summary_prompt, 250, 0.3)).strip()
        except Exception as e:  # noqa: BLE001 - a missing summary is cosmetic
            log.warning("loop_summary_failed", error=str(e)[:200])
        await _e(tl.done("design"))

        # calibrate — bars are already set per round by normalize_rounds; persist here
        await _e(tl.start("calibrate"))
        loop = build_loop(
            learner_id=learner_id,
            job=job,
            rounds=rounds,
            company_signals={
                "process_summary": summary,
                "sources": [r["href"] for r in results if r.get("href")][:5],
            },
        )
        await col_interview_loops().insert_one({**loop})
        # Link it back so the tracker card can find the loop it spawned.
        await col_job_applications().update_one(
            {"id": job.get("id"), "learner_id": learner_id},
            {"$set": {"loop_id": loop["loop_id"]}},
        )
        await _e(tl.done("calibrate"))

        log.info(
            "interview_loop_created",
            loop_id=loop["loop_id"],
            company=company[:60],
            rounds=[r["kind"] for r in rounds],
            sources=len(results),
        )
        return loop
