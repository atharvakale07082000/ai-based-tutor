"""
Agentic RAG Chat Orchestrator.

Entry point: run_assistant() — an async generator that yields SSE-ready dicts.

Flow:
  user message
    → fetch RAG context (learner profile, progress, active plans)
    → LLM: classify intent + plan action (structured JSON, non-streaming)
    → guardrail check
    → dispatch to specialist agent
    → agent may delegate to another agent (depth ≤ 2)
    → stream response back as typed events

Event shapes:
  {"type": "routing",    "agent": str, "reason": str, "delegated_from": str|None}
  {"type": "token",      "content": str}
  {"type": "action",     "kind": str,  "payload": dict}   # quiz_created, plan_created, navigate
  {"type": "delegation", "from": str,  "to": str, "reason": str}
  {"type": "guardrail",  "message": str}
  {"type": "done",       "agent": str}
  {"type": "error",      "message": str}
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS
from app.hf.doubt_solver import stream_doubt_response

log = structlog.get_logger()

# ─── Agent registry ───────────────────────────────────────────────────────────

AGENT_REGISTRY = {
    "doubt_solver": {
        "label": "Doubt-Solver",
        "emoji": "💡",
        "scope": "Explains concepts, answers academic questions, resolves learning doubts on any subject.",
        "out_of_scope": "Quiz generation, course planning, navigation, progress stats.",
    },
    "quiz_agent": {
        "label": "Quiz Agent",
        "emoji": "📝",
        "scope": "Generates topic quizzes and starts interactive knowledge tests.",
        "out_of_scope": "Explaining concepts in depth, course roadmaps.",
    },
    "course_planner": {
        "label": "Course Planner",
        "emoji": "🗺️",
        "scope": "Creates comprehensive 0-to-pro multi-week learning roadmaps for any skill.",
        "out_of_scope": "Answering one-off questions, quiz generation.",
    },
    "curriculum_agent": {
        "label": "Curriculum Agent",
        "emoji": "📚",
        "scope": "Shows or builds the personalised topic learning path for this user.",
        "out_of_scope": "One-off questions, full course plans.",
    },
    "progress_agent": {
        "label": "Progress Tracker",
        "emoji": "📊",
        "scope": "Shows learning analytics: Elo scores per topic, quiz history, streak, recommendations.",
        "out_of_scope": "Teaching content, generating quizzes.",
    },
    "navigator": {
        "label": "Navigator",
        "emoji": "🧭",
        "scope": "Navigates the user to any section of the app (dashboard, learn, doubts, progress, courses, quiz, admin).",
        "out_of_scope": "Answering questions, generating content.",
    },
    "general": {
        "label": "Assistant",
        "emoji": "🤖",
        "scope": "Platform help, general learning advice, anything that doesn't fit a specialist agent.",
        "out_of_scope": "",
    },
}

PAGE_MAP = {
    "dashboard": "/dashboard",
    "learn": "/learn",
    "doubts": "/doubts",
    "doubt": "/doubts",
    "progress": "/progress",
    "courses": "/courses",
    "quiz": "/quiz",
    "admin": "/admin",
    "assistant": "/assistant",
}

GUARDRAIL_TOPICS = [
    "movies", "gaming", "entertainment", "politics", "religion",
    "illegal", "violence", "adult", "dating", "betting", "crypto trading",
]
INJECTION_PATTERNS = [
    "ignore previous", "forget your", "jailbreak", "pretend you are",
    "you are now", "bypass", "override instructions", "act as",
]

# ─── Helper: single non-streaming LLM call ────────────────────────────────────

def _llm_call(prompt: str, max_tokens: int = 512, temperature: float = 0.1) -> str:
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    client = get_hf_client(model_cfg["provider"])
    resp = client.chat_completion(
        model=model_cfg["model_id"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


# ─── RAG context fetch ────────────────────────────────────────────────────────

async def _fetch_user_context(user_id: str, db: AsyncSession) -> dict:
    """Pull learner profile + recent quiz stats from SQLite for RAG context."""
    from app.models.learner import LearnerProfile
    from app.models.user import User
    from app.models.quiz import QuizSession

    try:
        lp_result = await db.execute(
            select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
        )
        learner = lp_result.scalar_one_or_none()
        if not learner:
            return {}

        quizzes_result = await db.execute(
            select(QuizSession)
            .where(QuizSession.learner_id == learner.id, QuizSession.completed_at != None)
            .order_by(QuizSession.completed_at.desc())
            .limit(5)
        )
        recent_quizzes = quizzes_result.scalars().all()

        proficiency = learner.topic_proficiency_map or {}
        sorted_topics = sorted(proficiency.items(), key=lambda x: x[1], reverse=True)

        return {
            "learner_name": learner.name,
            "goal_vector": learner.goal_vector or [],
            "xp": learner.xp,
            "streak": learner.streak,
            "top_topics": [{"topic": t, "elo": round(e)} for t, e in sorted_topics[:5]],
            "weak_topics": [{"topic": t, "elo": round(e)} for t, e in sorted_topics[-3:] if e < 600],
            "recent_quizzes": [
                {"topic": q.topic, "score": round((q.score or 0) * 100), "bloom": q.bloom_level}
                for q in recent_quizzes
            ],
        }
    except Exception as e:
        log.warning("rag_context_fetch_error", error=str(e))
        return {}


# ─── Intent classification ────────────────────────────────────────────────────

async def _classify_intent(
    message: str, history: list[dict], user_ctx: dict
) -> dict:
    """
    Ask the LLM to classify the intent and pick the best agent.
    Returns a dict with keys: agent, reason, guardrail_pass, guardrail_reason,
    extracted (topic etc.), navigate_url, delegation.
    """
    # Fast guardrail: injection patterns
    msg_lower = message.lower()
    for pat in INJECTION_PATTERNS:
        if pat in msg_lower:
            return {
                "guardrail_pass": False,
                "guardrail_reason": "That request looks like an attempt to override my instructions.",
                "agent": None,
            }

    registry_desc = "\n".join(
        f'  - "{k}": {v["scope"]}' for k, v in AGENT_REGISTRY.items()
    )
    ctx_str = json.dumps(user_ctx, indent=2) if user_ctx else "{}"
    history_str = "\n".join(
        f'{m["role"].upper()}: {m["content"][:120]}' for m in history[-6:]
    ) if history else "None"

    prompt = f"""You are an intent classifier for an AI learning platform. Classify the user message and select the best agent.

Available agents:
{registry_desc}

User context (RAG):
{ctx_str}

Recent conversation:
{history_str}

User message: "{message}"

Rules:
1. If the request is unrelated to learning, education, or the platform → guardrail_pass: false
2. Pick exactly ONE agent from the list above
3. For "quiz" requests: extract the topic (default to top_topic from context if not mentioned)
4. For "course" or "roadmap" requests: use course_planner
5. For navigation requests (go to X, open X, show me X): use navigator and fill navigate_url
6. For delegation: if the chosen agent would need to hand off part of the task, name the secondary agent

Respond with ONLY this JSON (no markdown):
{{
  "guardrail_pass": true,
  "guardrail_reason": null,
  "agent": "<agent_key>",
  "reason": "<one sentence why>",
  "extracted": {{
    "topic": "<topic if relevant, else null>",
    "goal": "<learning goal if relevant, else null>"
  }},
  "navigate_url": "<url path or null>",
  "delegation": {{
    "secondary_agent": "<agent_key or null>",
    "delegation_reason": "<why or null>"
  }}
}}"""

    text = await asyncio.to_thread(_llm_call, prompt, 400, 0.1)
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        text = match.group(0)
    try:
        result = json.loads(text)
    except Exception:
        result = {
            "guardrail_pass": True,
            "agent": "general",
            "reason": "Could not classify intent precisely",
            "extracted": {"topic": None, "goal": None},
            "navigate_url": None,
            "delegation": {"secondary_agent": None},
        }
    return result


# ─── Agent executors ──────────────────────────────────────────────────────────

async def _exec_doubt(
    message: str, history: list[dict], topic: str | None, user_ctx: dict
) -> AsyncIterator[dict]:
    context = topic or (user_ctx.get("goal_vector") or ["general learning"])[0]
    hf_history = [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
    try:
        stream = await stream_doubt_response(message, context, hf_history)
        async for token in stream:
            yield {"type": "token", "content": token}
    except Exception as e:
        yield {"type": "error", "message": str(e)}


async def _exec_quiz(
    topic: str | None, user_ctx: dict, user_id: str, db: AsyncSession
) -> AsyncIterator[dict]:
    from app.models.learner import LearnerProfile
    from app.models.user import User
    from app.models.quiz import QuizSession
    from app.agents.orchestrator import orchestrator

    resolved_topic = topic or (user_ctx.get("goal_vector") or ["Python Programming"])[0]

    yield {"type": "token", "content": f"Generating a quiz on **{resolved_topic}**…\n\n"}

    try:
        lp_result = await db.execute(
            select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
        )
        learner = lp_result.scalar_one_or_none()
        if not learner:
            yield {"type": "error", "message": "Learner profile not found"}
            return

        state = {
            "learner_id": str(learner.id),
            "task_type": "quiz",
            "messages": [],
            "learner_profile": {},
            "topic_proficiency": learner.topic_proficiency_map or {},
            "current_topic": resolved_topic,
            "quiz_questions": [],
            "curriculum_path": [],
            "doubt_response": "",
            "progress_delta": {},
            "bloom_level": "",
            "error": None,
        }

        result = await orchestrator.ainvoke(state)
        questions = result.get("quiz_questions", [])
        bloom = result.get("bloom_level", "understand")

        quiz_id = str(uuid.uuid4())
        quiz = QuizSession(
            id=quiz_id,
            learner_id=learner.id,
            topic=resolved_topic,
            bloom_level=bloom,
            questions=questions,
        )
        db.add(quiz)
        await db.commit()

        yield {"type": "token", "content": f"Ready! {len(questions)} questions at **{bloom}** level.\n"}
        yield {
            "type": "action",
            "kind": "quiz_created",
            "payload": {
                "quiz_id": quiz_id,
                "topic": resolved_topic,
                "bloom_level": bloom,
                "question_count": len(questions),
                "url": f"/quiz/{quiz_id}",
            },
        }
    except Exception as e:
        log.error("exec_quiz_error", error=str(e))
        yield {"type": "error", "message": f"Quiz generation failed: {e}"}


async def _exec_course_planner(
    goal: str | None, message: str, user_ctx: dict, user_id: str
) -> AsyncIterator[dict]:
    from app.agents.course_planner import create_course_plan

    resolved_goal = goal or message
    yield {"type": "token", "content": f"Researching and building a roadmap for **{resolved_goal}**…\n\nThis takes about 30 seconds while I search the web.\n"}

    try:
        plan = await create_course_plan(resolved_goal, user_id)
        yield {"type": "token", "content": f"\n✅ **{plan['title']}** is ready — {len(plan['modules'])} modules, {plan['total_duration_weeks']} weeks.\n"}
        yield {
            "type": "action",
            "kind": "plan_created",
            "payload": {
                "plan_id": plan["plan_id"],
                "title": plan["title"],
                "module_count": len(plan["modules"]),
                "weeks": plan["total_duration_weeks"],
                "url": f"/courses/{plan['plan_id']}",
            },
        }
    except Exception as e:
        log.error("exec_course_error", error=str(e))
        yield {"type": "error", "message": f"Course planning failed: {e}"}


async def _exec_progress(user_ctx: dict, db: AsyncSession, user_id: str) -> AsyncIterator[dict]:
    from app.models.learner import LearnerProfile
    from app.models.user import User
    from app.models.quiz import QuizSession, ProgressRecord

    try:
        lp_result = await db.execute(
            select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
        )
        learner = lp_result.scalar_one_or_none()
        if not learner:
            yield {"type": "token", "content": "No learner profile found."}
            return

        proficiency = learner.topic_proficiency_map or {}
        top = sorted(proficiency.items(), key=lambda x: x[1], reverse=True)[:5]
        weak = [(t, e) for t, e in proficiency.items() if e < 600][:3]

        lines = [
            f"Here's your learning snapshot, **{learner.name}**:\n\n",
            f"- 🔥 **Streak:** {learner.streak} days\n",
            f"- ⚡ **XP:** {learner.xp:,}\n\n",
        ]
        if top:
            lines.append("**Top skills:**\n")
            for t, e in top:
                bar = "█" * int(e / 100) + "░" * (10 - int(e / 100))
                lines.append(f"  - {t}: {bar} ({round(e)} Elo)\n")
        if weak:
            lines.append("\n**Topics to improve:**\n")
            for t, e in weak:
                lines.append(f"  - {t} ({round(e)} Elo) — consider taking a quiz\n")

        lines.append("\n")
        for line in lines:
            yield {"type": "token", "content": line}
            await asyncio.sleep(0.02)

        yield {
            "type": "action",
            "kind": "navigate",
            "payload": {"url": "/progress", "label": "View full Progress page"},
        }
    except Exception as e:
        yield {"type": "error", "message": str(e)}


async def _exec_curriculum(user_ctx: dict, db: AsyncSession, user_id: str) -> AsyncIterator[dict]:
    from app.models.learner import LearnerProfile
    from app.models.user import User
    from app.models.curriculum import CurriculumPath

    try:
        lp_result = await db.execute(
            select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
        )
        learner = lp_result.scalar_one_or_none()

        cp_result = await db.execute(
            select(CurriculumPath).where(CurriculumPath.learner_id == learner.id if learner else "")
            .order_by(CurriculumPath.created_at.desc()).limit(1)
        )
        cp = cp_result.scalar_one_or_none()

        if cp and cp.path:
            yield {"type": "token", "content": f"Your current curriculum has **{len(cp.path)} topics**:\n\n"}
            for i, item in enumerate(cp.path[:8]):
                topic = item.get("subtopic", item.get("topic", "Unknown"))
                elo = (learner.topic_proficiency_map or {}).get(topic, 500)
                status = "✅" if elo >= 700 else "🔄" if elo >= 500 else "📖"
                yield {"type": "token", "content": f"{status} {i+1}. {topic} ({round(elo)} Elo)\n"}
                await asyncio.sleep(0.02)
        else:
            yield {"type": "token", "content": "No curriculum built yet. Let me generate one based on your goals.\n"}

        yield {
            "type": "action",
            "kind": "navigate",
            "payload": {"url": "/learn", "label": "Go to Learning Feed"},
        }
    except Exception as e:
        yield {"type": "error", "message": str(e)}


async def _exec_navigator(navigate_url: str | None, message: str) -> AsyncIterator[dict]:
    # Infer URL if not classified
    url = navigate_url
    if not url:
        for key, path in PAGE_MAP.items():
            if key in message.lower():
                url = path
                break
        url = url or "/dashboard"

    label = next((k.title() for k, v in PAGE_MAP.items() if v == url), "Page")
    yield {"type": "token", "content": f"Taking you to **{label}**.\n"}
    yield {"type": "action", "kind": "navigate", "payload": {"url": url, "label": label}}


async def _exec_general(message: str, history: list[dict], user_ctx: dict) -> AsyncIterator[dict]:
    ctx_str = ""
    if user_ctx.get("learner_name"):
        ctx_str = f"The learner's name is {user_ctx['learner_name']}. "
    prompt = f"""You are a helpful AI learning platform assistant. {ctx_str}
Answer concisely and helpfully. Focus only on learning, education, and how to use the platform.

User: {message}
Assistant:"""
    try:
        stream = await stream_doubt_response(message, "platform assistance", history[-4:])
        async for token in stream:
            yield {"type": "token", "content": token}
    except Exception as e:
        yield {"type": "error", "message": str(e)}


# ─── Eval recorder ────────────────────────────────────────────────────────────

async def _record_eval(
    session_id: str,
    user_id: str,
    message: str,
    agent: str,
    delegation_chain: list[str],
    response_length: int,
    guardrail_blocked: bool,
    error: bool,
) -> None:
    try:
        from app.evals.mongo import _get_client
        _, db = _get_client()
        col = db["chat_evals"]
        await col.insert_one({
            "session_id": session_id,
            "user_id": user_id,
            "message": message[:500],
            "agent": agent,
            "delegation_chain": delegation_chain,
            "response_length": response_length,
            "guardrail_blocked": guardrail_blocked,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        log.warning("eval_record_error", error=str(e))


# ─── Main entry point ─────────────────────────────────────────────────────────

async def run_assistant(
    message: str,
    history: list[dict],
    user_id: str,
    db: AsyncSession,
) -> AsyncIterator[dict]:
    """
    Main async generator. Yields SSE-ready event dicts.
    """
    session_id = str(uuid.uuid4())
    delegation_chain: list[str] = []
    response_chars = 0
    guardrail_blocked = False
    had_error = False
    final_agent = "general"

    # 1. Fetch RAG context
    user_ctx = await _fetch_user_context(user_id, db)

    # 2. Classify intent
    decision = await _classify_intent(message, history, user_ctx)
    log.info("chat_orchestrator_decision", decision=decision, user_id=user_id)

    # 3. Guardrail
    if not decision.get("guardrail_pass", True):
        guardrail_blocked = True
        yield {"type": "guardrail", "message": decision.get("guardrail_reason", "Request outside educational scope.")}
        yield {"type": "done", "agent": "guardrail"}
        await _record_eval(session_id, user_id, message, "guardrail", [], 0, True, False)
        return

    agent = decision.get("agent", "general")
    final_agent = agent
    reason = decision.get("reason", "")
    extracted = decision.get("extracted", {})
    navigate_url = decision.get("navigate_url")
    delegation = decision.get("delegation", {})

    yield {"type": "routing", "agent": agent, "reason": reason, "delegated_from": None}
    delegation_chain.append(agent)

    # 4. Execute primary agent
    gen: AsyncIterator[dict] | None = None
    if agent == "doubt_solver":
        gen = _exec_doubt(message, history, extracted.get("topic"), user_ctx)
    elif agent == "quiz_agent":
        gen = _exec_quiz(extracted.get("topic"), user_ctx, user_id, db)
    elif agent == "course_planner":
        gen = _exec_course_planner(extracted.get("goal"), message, user_ctx, user_id)
    elif agent == "progress_agent":
        gen = _exec_progress(user_ctx, db, user_id)
    elif agent == "curriculum_agent":
        gen = _exec_curriculum(user_ctx, db, user_id)
    elif agent == "navigator":
        gen = _exec_navigator(navigate_url, message)
    else:
        gen = _exec_general(message, history, user_ctx)

    async for event in gen:
        if event["type"] == "token":
            response_chars += len(event.get("content", ""))
        if event["type"] == "error":
            had_error = True
        yield event

    # 5. Optional delegation to secondary agent
    secondary = delegation.get("secondary_agent")
    if secondary and secondary in AGENT_REGISTRY and secondary != agent and len(delegation_chain) < 2:
        d_reason = delegation.get("delegation_reason", "Complementary task")
        yield {"type": "delegation", "from": agent, "to": secondary, "reason": d_reason}
        yield {"type": "routing", "agent": secondary, "reason": d_reason, "delegated_from": agent}
        delegation_chain.append(secondary)
        final_agent = secondary

        if secondary == "doubt_solver":
            gen2 = _exec_doubt(message, history, extracted.get("topic"), user_ctx)
        elif secondary == "navigator":
            gen2 = _exec_navigator(navigate_url, message)
        elif secondary == "progress_agent":
            gen2 = _exec_progress(user_ctx, db, user_id)
        else:
            gen2 = _exec_general(message, history, user_ctx)

        async for event in gen2:
            if event["type"] == "token":
                response_chars += len(event.get("content", ""))
            yield event

    yield {"type": "done", "agent": final_agent}

    # 6. Record eval
    await _record_eval(
        session_id, user_id, message, final_agent,
        delegation_chain, response_chars, False, had_error,
    )
