"""
Course Planner Agent — searches the web and generates a structured 0-to-pro
learning plan stored in MongoDB. Also handles AI interview evaluation.
"""
from __future__ import annotations
import asyncio
import json
import uuid
import re
from datetime import datetime, timezone
from typing import TypedDict, Optional

import structlog
from ddgs import DDGS

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS
from app.db.mongo import col_course_plans, col_interviews

log = structlog.get_logger()

PROJ = {"_id": 0}


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
    return col_course_plans().find_one({"plan_id": plan_id}, PROJ)


async def list_plans(user_id: str) -> list[dict]:
    return list(
        col_course_plans().find({"user_id": user_id}, PROJ).sort("created_at", -1)
    )


def _save_plan_sync(plan: dict) -> None:
    col_course_plans().insert_one({**plan})


async def _save_plan(plan: dict) -> None:
    await asyncio.to_thread(_save_plan_sync, plan)


def _update_module_interview_sync(plan_id: str, module_id: str, status: str, score: float) -> None:
    col_course_plans().update_one(
        {"plan_id": plan_id, "modules.id": module_id},
        {"$set": {
            "modules.$.interview_status": status,
            "modules.$.interview_score": score,
        }},
    )


async def _update_module_interview(plan_id: str, module_id: str, status: str, score: float) -> None:
    await asyncio.to_thread(_update_module_interview_sync, plan_id, module_id, status, score)


async def get_interview(interview_id: str) -> dict | None:
    return col_interviews().find_one({"interview_id": interview_id}, PROJ)


async def get_module_interview(plan_id: str, module_id: str, user_id: str) -> dict | None:
    return col_interviews().find_one(
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
                    results.append({
                        "title": r.get("title", ""),
                        "body": r.get("body", "")[:300],
                        "href": r.get("href", ""),
                    })
    except Exception as e:
        log.warning("ddg_search_error", error=str(e))
    return results[:20]


async def _generate_plan_json(goal: str, search_results: list[dict]) -> dict:
    ctx = "\n".join(f"- {r['title']}: {r['body']}" for r in search_results[:12])
    prompt = f"""You are an expert curriculum designer. Create a comprehensive learning roadmap for: "{goal}"

Web research context:
{ctx}

Return ONLY a valid JSON object (no markdown, no explanation) with this exact structure:
{{
  "title": "descriptive plan title",
  "description": "2-sentence overview",
  "total_duration_weeks": <integer>,
  "modules": [
    {{
      "title": "module title",
      "description": "what the learner will achieve",
      "topics": ["topic1", "topic2", "topic3", "topic4"],
      "duration_days": <integer 5-14>,
      "resources": [
        {{"title": "resource name", "url": "https://example.com", "type": "video"}},
        {{"title": "resource name", "url": "https://docs.example.com", "type": "article"}}
      ]
    }}
  ]
}}

Requirements:
- 6-8 progressive modules (beginner → intermediate → advanced → expert)
- Each module must have 3-6 topics and 2-3 resources
- Resources must be real, freely available (YouTube, official docs, GitHub)
- Resource type must be one of: video, article, course, book, tool
- Realistic time estimates per module
- Return ONLY the JSON, nothing else."""

    raw = await asyncio.wait_for(asyncio.to_thread(_chat, prompt, 3000, 0.2), timeout=90.0)
    raw = raw.strip()
    match = re.search(r'\{[\s\S]*\}', raw)
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
        modules.append({
            "id": str(uuid.uuid4()),
            "title": m.get("title", f"Module {i+1}"),
            "description": m.get("description", ""),
            "topics": m.get("topics", []),
            "duration_days": int(m.get("duration_days", 7)),
            "resources": m.get("resources", []),
            "order": i + 1,
            "interview_status": "pending",
            "interview_score": None,
        })
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


async def create_course_plan(goal: str, user_id: str) -> dict:
    log.info("course_planner_start", goal=goal, user_id=user_id)
    search_results = await asyncio.to_thread(_search_web, goal)
    raw = await _generate_plan_json(goal, search_results)
    plan = _build_plan(goal, user_id, raw)
    await _save_plan(plan)
    log.info("course_planner_plan_saved", plan_id=plan["plan_id"])
    # Fire-and-forget: pre-populate quiz bank for all module topics
    task = asyncio.create_task(_pregenerate_quizzes_for_plan(plan))
    task.add_done_callback(
        lambda t: log.error("quiz_pregenerate_task_failed", error=str(t.exception()))
        if t.exception() else None
    )
    return plan


# ─── Interview ────────────────────────────────────────────────────────────────

async def start_interview(
    plan_id: str, module_id: str, user_id: str, module_title: str, topics: list[str]
) -> dict:
    topics_str = ", ".join(topics[:6])
    prompt = f"""You are a technical interviewer. Create exactly 4 interview questions to assess understanding of "{module_title}".

Topics covered: {topics_str}

Return ONLY a JSON array of question objects:
[
  {{"id": 1, "text": "question text here", "expected_depth": "conceptual|applied|analytical"}},
  {{"id": 2, "text": "...", "expected_depth": "..."}},
  {{"id": 3, "text": "...", "expected_depth": "..."}},
  {{"id": 4, "text": "...", "expected_depth": "..."}}
]

Requirements:
- Mix conceptual, applied, and analytical questions
- Progressive difficulty (easier first)
- Clear, concise questions a student can answer in 60-90 seconds verbally
- Return ONLY the JSON array"""

    text = await asyncio.to_thread(_chat, prompt, 800, 0.4)
    text = text.strip()
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        text = match.group(0)
    questions = json.loads(text)

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

    col_interviews().insert_one({**interview})
    log.info("interview_started", interview_id=interview["interview_id"])
    return interview


async def evaluate_answer(interview_id: str, question_id: int, answer_text: str) -> dict:
    interview = col_interviews().find_one({"interview_id": interview_id})
    if not interview:
        raise ValueError("Interview not found")

    question = next((q for q in interview["questions"] if q["id"] == question_id), None)
    if not question:
        raise ValueError("Question not found")

    prompt = f"""You are evaluating a technical interview answer.

Module: {interview['module_title']}
Question: {question['text']}
Expected depth: {question.get('expected_depth', 'conceptual')}
Candidate's answer: "{answer_text}"

Evaluate and return ONLY this JSON:
{{
  "score": <integer 0-10>,
  "feedback": "one sentence of specific, constructive feedback",
  "key_points_covered": ["point1", "point2"]
}}

Scoring guide: 0-3 incorrect/missing, 4-6 partially correct, 7-8 good, 9-10 excellent.
Return ONLY the JSON."""

    text = await asyncio.to_thread(_chat, prompt, 300, 0.1)
    text = text.strip()
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        text = match.group(0)
    evaluation = json.loads(text)
    evaluation["question_id"] = question_id
    evaluation["answer_text"] = answer_text

    col_interviews().update_one(
        {"interview_id": interview_id},
        {"$push": {"answers": evaluation}},
    )
    return evaluation


async def complete_interview(interview_id: str, plan_id: str, module_id: str) -> dict:
    """Run LangGraph scoring agent on all Q&A pairs, mark module pass/fail."""
    from app.agents.interview_scorer import run_scoring_agent

    interview = col_interviews().find_one({"interview_id": interview_id})
    if not interview:
        raise ValueError("Interview not found")

    answers = interview.get("answers", [])
    if not answers:
        raise ValueError("No answers submitted")

    transcriptions = [
        {"question_id": a.get("question_id"), "answer_text": a.get("answer_text", "")}
        for a in answers
    ]

    scoring = await asyncio.to_thread(
        run_scoring_agent,
        interview["module_title"],
        interview.get("module_topics", []),
        interview["questions"],
        transcriptions,
    )

    final_score = scoring["final_score"]
    passed = scoring["passed"]
    completed_at = datetime.now(timezone.utc).isoformat()

    col_interviews().update_one(
        {"interview_id": interview_id},
        {"$set": {
            "final_score": final_score,
            "passed": passed,
            "scoring_matrix": scoring["scoring_matrix"],
            "summary": scoring["summary"],
            "completed_at": completed_at,
        }},
    )

    status = "passed" if passed else "failed"
    await _update_module_interview(plan_id, module_id, status, round(final_score / 10, 2))

    log.info("interview_complete", interview_id=interview_id, score=final_score, passed=passed)
    return {
        "interview_id": interview_id,
        "final_score": final_score,
        "passed": passed,
        "scoring_matrix": scoring["scoring_matrix"],
        "summary": scoring["summary"],
        "total_questions": len(answers),
        "completed_at": completed_at,
    }
