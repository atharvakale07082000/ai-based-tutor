"""
Course Planner Agent — searches the web and generates a structured 0-to-pro
learning plan stored in MongoDB. Also handles AI interview evaluation.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, TypedDict

import structlog
from ddgs import DDGS

from app.db.mongo import col_course_plans, col_interviews
from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS
from app.prompts.loader import render_prompt

log = structlog.get_logger()

PROJ = {"_id": 0}

# Type of the optional step-emit callback forwarded to a workflow run: it receives a step/event
# dict and forwards it to the SSE stream. None = no live timeline.
StepEmit = Optional[Callable[[dict], Awaitable[None]]]


def _chat(prompt: str, max_tokens: int = 2000, temperature: float = 0.2) -> str:
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    client = get_hf_client(model_cfg["provider"])
    resp = client.chat_completion(
        model=model_cfg["model_id"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


# ─── MongoDB helpers ──────────────────────────────────────────────────────────


async def get_plan(plan_id: str) -> dict | None:
    return await col_course_plans().find_one({"plan_id": plan_id}, PROJ)


async def list_plans(user_id: str) -> list[dict]:
    return (
        await col_course_plans()
        .find({"user_id": user_id}, PROJ)
        .sort("created_at", -1)
        .to_list(length=None)
    )


async def _save_plan(plan: dict) -> None:
    await col_course_plans().insert_one({**plan})


async def _update_module_interview(
    plan_id: str, module_id: str, status: str, score: float
) -> None:
    await col_course_plans().update_one(
        {"plan_id": plan_id, "modules.id": module_id},
        {
            "$set": {
                "modules.$.interview_status": status,
                "modules.$.interview_score": score,
            }
        },
    )


async def get_interview(interview_id: str) -> dict | None:
    return await col_interviews().find_one({"interview_id": interview_id}, PROJ)


async def get_module_interview(
    plan_id: str, module_id: str, user_id: str
) -> dict | None:
    return await col_interviews().find_one(
        {"plan_id": plan_id, "module_id": module_id, "user_id": user_id},
        PROJ,
        sort=[("created_at", -1)],
    )


# ─── State ────────────────────────────────────────────────────────────────────


class PlannerState(TypedDict):
    goal: str
    user_id: str
    search_results: list[dict]
    plan: Optional[dict]
    plan_id: Optional[str]
    error: Optional[str]


# ─── Nodes ────────────────────────────────────────────────────────────────────


def _search_web(goal: str) -> list[dict]:
    results: list[dict] = []
    queries = [
        f"learn {goal} from beginner to advanced complete roadmap",
        f"{goal} full course curriculum syllabus modules",
        f"best free resources to learn {goal} 2024",
    ]
    try:
        with DDGS() as ddgs:
            for q in queries:
                for r in ddgs.text(q, max_results=5):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "body": r.get("body", "")[:300],
                            "href": r.get("href", ""),
                        }
                    )
    except Exception as e:
        log.warning("ddg_search_error", error=str(e))
    return results[:20]


async def _generate_plan_json(goal: str, search_results: list[dict]) -> dict:
    ctx = "\n".join(f"- {r['title']}: {r['body']}" for r in search_results[:12])
    prompt = render_prompt("course_planner", "plan_generation", goal=goal, ctx=ctx)

    raw = await asyncio.wait_for(
        asyncio.to_thread(_chat, prompt, 3000, 0.2), timeout=90.0
    )
    raw = raw.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    text = match.group(0) if match else raw
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error("course_plan_json_parse_failed", error=str(e), raw_snippet=raw[:300])
        raise ValueError(f"LLM did not return valid JSON: {e}") from e


def _build_plan(goal: str, user_id: str, raw: dict) -> dict:
    plan_id = str(uuid.uuid4())
    modules = []
    for i, m in enumerate(raw.get("modules", [])):
        modules.append(
            {
                "id": str(uuid.uuid4()),
                "title": m.get("title", f"Module {i + 1}"),
                "description": m.get("description", ""),
                "topics": m.get("topics", []),
                "duration_days": int(m.get("duration_days", 7)),
                "resources": m.get("resources", []),
                "order": i + 1,
                "interview_status": "pending",
                "interview_score": None,
            }
        )
    return {
        "plan_id": plan_id,
        "user_id": user_id,
        "goal": goal,
        "title": raw.get("title", f"Learn {goal}"),
        "description": raw.get("description", ""),
        "total_duration_weeks": int(raw.get("total_duration_weeks", len(modules))),
        "modules": modules,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }


# ─── Public API ───────────────────────────────────────────────────────────────


async def _pregenerate_quizzes_for_plan(plan: dict) -> None:
    """Background task: pre-generate quiz questions for all module topics."""
    from app.hf.quiz_questions import pregenerate_topic_questions

    for module in plan.get("modules", []):
        for topic in module.get("topics", []):
            try:
                await pregenerate_topic_questions(topic)
            except Exception as e:
                log.warning("quiz_pregenerate_error", topic=topic, error=str(e))


async def create_course_plan(goal: str, user_id: str, emit: StepEmit = None) -> dict:
    """Build and persist a course plan via the ``course_gen`` pipeline.

    Thin entry point: research → design → finalize run as a plain sequential
    pipeline (``app.agents.pipelines.course_gen``). If ``emit`` is given, it
    streams live timeline steps identical to before. Returns the saved plan.
    """
    from app.agents.pipelines import run_course_gen

    log.info("course_planner_start", goal=goal, user_id=user_id)
    return await run_course_gen(goal, user_id, emit=emit)


# ─── Interview ────────────────────────────────────────────────────────────────


async def start_interview(
    plan_id: str, module_id: str, user_id: str, module_title: str, topics: list[str]
) -> dict:
    log.info("interview_generating", module=module_title, topics=topics[:6])
    topics_str = ", ".join(topics[:6])
    prompt = render_prompt(
        "course_planner",
        "interview_questions",
        module_title=module_title,
        topics_str=topics_str,
    )

    t0 = time.perf_counter()
    text = await asyncio.to_thread(_chat, prompt, 800, 0.4)
    text = text.strip()
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        text = match.group(0)
    questions = json.loads(text)
    coding_qs = [q for q in questions if q.get("is_coding_question")]
    log.info(
        "interview_questions_generated",
        module=module_title,
        total=len(questions),
        coding=len(coding_qs),
        latency_ms=round((time.perf_counter() - t0) * 1000),
        preview=[q["text"][:60] for q in questions],
    )

    interview = {
        "interview_id": str(uuid.uuid4()),
        "plan_id": plan_id,
        "module_id": module_id,
        "user_id": user_id,
        "module_title": module_title,
        "module_topics": topics,
        "questions": questions,
        "answers": [],
        "final_score": None,
        "passed": None,
        "scoring_matrix": [],
        "summary": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }

    await col_interviews().insert_one({**interview})
    log.info("interview_started", interview_id=interview["interview_id"])
    return interview


async def evaluate_answer(
    interview_id: str, question_id: int, answer_text: str
) -> dict:
    interview = await col_interviews().find_one({"interview_id": interview_id})
    if not interview:
        raise ValueError("Interview not found")

    question = next((q for q in interview["questions"] if q["id"] == question_id), None)
    if not question:
        raise ValueError("Question not found")

    answer_preview = answer_text[:120].replace("\n", " ")
    log.info(
        "answer_evaluating",
        interview_id=interview_id,
        q_id=question_id,
        q_type="coding" if question.get("is_coding_question") else "verbal",
        answer_preview=answer_preview,
    )

    prompt = render_prompt(
        "course_planner",
        "evaluate_answer",
        module_title=interview["module_title"],
        question_text=question["text"],
        expected_depth=question.get("expected_depth", "conceptual"),
        answer_text=answer_text,
    )

    t0 = time.perf_counter()
    text = await asyncio.to_thread(_chat, prompt, 300, 0.1)
    text = text.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    evaluation = json.loads(text)
    evaluation["question_id"] = question_id
    evaluation["answer_text"] = answer_text

    score = evaluation.get("score", "?")
    log.info(
        "answer_evaluated",
        interview_id=interview_id,
        q_id=question_id,
        score=score,
        key_points=evaluation.get("key_points_covered", []),
        feedback=evaluation.get("feedback", "")[:100],
        latency_ms=round((time.perf_counter() - t0) * 1000),
    )

    await col_interviews().update_one(
        {"interview_id": interview_id},
        {"$push": {"answers": evaluation}},
    )
    return evaluation


async def complete_interview(
    interview_id: str, plan_id: str, module_id: str, emit: StepEmit = None
) -> dict:
    """Score an interview via the ``interview_review`` pipeline (evaluate → score → feedback).

    Thin entry point: the steps run as a plain sequential pipeline
    (``app.agents.pipelines.interview_review``). If ``emit`` is given, it streams
    live timeline steps identical to before. Returns the result payload.
    """
    from app.agents.pipelines import run_interview_review

    result = await run_interview_review(interview_id, plan_id, module_id, emit=emit)

    log.info(
        "interview_complete",
        interview_id=interview_id,
        final_score=result["final_score"],
        passed=result["passed"],
        status="PASSED ✓" if result["passed"] else "FAILED ✗",
    )
    return result
