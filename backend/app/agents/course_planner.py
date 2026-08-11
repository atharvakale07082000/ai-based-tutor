"""
Course Planner Agent — searches the web and generates a structured 0-to-pro
learning plan stored in MongoDB. Also handles AI interview evaluation.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

import structlog
from ddgs import DDGS

from app.config import settings
from app.db.mongo import PROJ, col_course_plans, col_interviews, col_learners
from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS
from app.agents.json_utils import extract_json
from app.agents.steps import StepEmit
from app.prompts.loader import render_prompt

log = structlog.get_logger()


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
    plan = extract_json(raw)
    if plan is None:
        log.error("course_plan_json_parse_failed", raw_snippet=raw[:300])
        raise ValueError("LLM did not return valid JSON")
    return plan


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
    """Create an empty interview the live agent will drive.

    Questions are no longer pre-generated — the interrupt-driven ``interview_agent``
    asks them one at a time and appends each to ``questions`` as it goes (see
    ``agents/interview_agent.py``). We snapshot the candidate's proficiency so the
    agent can calibrate difficulty from the first question.
    """
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    full_prof = (learner or {}).get("topic_proficiency_map") or {}
    # Prefer the module's own topics; fall back to the whole map if none overlap.
    proficiency = {t: full_prof[t] for t in topics if t in full_prof} or full_prof

    interview = {
        "interview_id": str(uuid.uuid4()),
        "plan_id": plan_id,
        "module_id": module_id,
        "user_id": user_id,
        "module_title": module_title,
        "module_topics": topics,
        "candidate_proficiency": proficiency,
        "questions": [],  # appended by the agent, one per turn
        "answers": [],
        "turn_count": 0,  # questions asked so far (drives the hard cap)
        "current_interrupt_id": None,  # the paused ask_candidate interrupt awaiting an answer
        "status": "in_progress",  # in_progress → awaiting_final → complete
        "final_score": None,
        "passed": None,
        "scoring_matrix": [],
        "summary": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }

    await col_interviews().insert_one({**interview})
    log.info(
        "interview_started",
        interview_id=interview["interview_id"],
        module=module_title,
        topics=topics[:6],
    )
    return interview


def interview_state(interview: dict) -> dict:
    """Project a stored interview into the payload the interview screen resumes from.

    Used by the ``GET .../interview/{interview_id}`` read endpoint so a reloaded tab (or a
    dropped connection) can rebuild the screen mid-flight instead of starting over. The
    fields are whitelisted on purpose: the learner sees the outstanding question and the
    per-answer feedback they were already shown, never the internal calibration state
    (``candidate_proficiency`` Elo, ``current_interrupt_id``) nor the final grader's
    per-question rationale (``scoring_matrix``/``summary``, which the complete endpoint owns).

    ``status`` tells the client what to do next:
      - ``awaiting_answer`` — the agent is paused on ``current_question``; POST an answer.
      - ``awaiting_final``  — the agent concluded; POST ``.../complete`` to grade it.
      - ``complete``        — already graded (``final_score``/``passed`` are set).
      - ``in_progress``     — no question outstanding and not concluded (interrupted start).
    ``current_question`` is non-null exactly when ``status == "awaiting_answer"``.
    """
    questions = interview.get("questions") or []
    answers = interview.get("answers") or []
    question_by_id = {q.get("id"): q for q in questions}
    answered_ids = {a.get("question_id") for a in answers}
    # The outstanding question is the most recent one the agent asked but never got an answer to.
    pending = next(
        (q for q in reversed(questions) if q.get("id") not in answered_ids), None
    )

    if interview.get("completed_at") or interview.get("final_score") is not None:
        status = "complete"
    elif pending and interview.get("current_interrupt_id"):
        status = "awaiting_answer"
    elif interview.get("status") == "awaiting_final":
        status = "awaiting_final"
    else:
        status = "in_progress"

    return {
        "interview_id": interview.get("interview_id"),
        "plan_id": interview.get("plan_id"),
        "module_id": interview.get("module_id"),
        "module_title": interview.get("module_title", ""),
        "status": status,
        "current_question": (
            {
                "id": pending.get("id"),
                "text": pending.get("text", ""),
                "is_coding_question": bool(pending.get("is_coding_question")),
                "language": pending.get("language") or None,
                "expected_depth": pending.get("expected_depth") or "conceptual",
            }
            if status == "awaiting_answer" and pending
            else None
        ),
        "answers": [
            {
                "question_id": a.get("question_id"),
                "question_text": (question_by_id.get(a.get("question_id")) or {}).get(
                    "text", ""
                ),
                "answer_text": a.get("answer_text", ""),
                "score": a.get("score"),
                "feedback": a.get("feedback", ""),
                "key_points_covered": a.get("key_points_covered") or [],
            }
            for a in answers
        ],
        "answered_count": len(answers),
        "questions_asked": len(questions),
        "max_questions": settings.INTERVIEW_MAX_QUESTIONS,
        "final_score": interview.get("final_score"),
        "passed": interview.get("passed"),
        "created_at": interview.get("created_at"),
        "completed_at": interview.get("completed_at"),
    }


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
    evaluation = extract_json(text) or {}
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
