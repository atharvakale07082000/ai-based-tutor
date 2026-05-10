"""
LLM-based supervisor agent.

Reads structured reports written by each specialist agent and uses an LLM
to decide which agent to invoke next.  This replaces the old rule-based
planner_agent_node with genuine LLM-driven multi-agent coordination.

Routing options returned by the supervisor:
  curriculum  → build / refresh the learner's curriculum path
  quiz        → generate adaptive quiz for current_topic (then waits for human)
  progress    → update Elo after quiz result is available
  doubt       → answer a learner question (then waits for human)
  FINISH      → session complete, exit graph
"""
import json
import re
import structlog

from app.agents.state import AgentState
from app.tracing import get_tracer

log = structlog.get_logger()

VALID_AGENTS = {"curriculum", "quiz", "progress", "doubt", "FINISH"}

_SYSTEM_PROMPT = """\
You are the supervisor of an AI tutoring system that coordinates specialist agents.

Specialist agents available:
- curriculum  : Builds a personalized learning path from learner goals + proficiency gaps
- quiz        : Generates Bloom-calibrated quiz questions for the current topic
- progress    : Re-scores Elo proficiency after a quiz attempt
- doubt       : Answers a learner's question (only when messages contain a new question)
- FINISH      : End the session (all topics mastered, quota reached, or nothing left to do)

Rules:
1. If there is no curriculum_path yet → curriculum.
2. If curriculum exists but quiz_questions is empty and task_type is "quiz" → quiz.
3. If progress_delta contains a new score that hasn't been processed → progress.
4. If the latest message is a human question and task_type is "doubt" → doubt.
5. If all topics in curriculum_path are mastered (Elo ≥ mastery_threshold) → FINISH.
6. If iteration_count ≥ max_iterations → FINISH.
7. Otherwise use agent_reports to decide: what did agents find, what is still missing?

Reply with ONLY a JSON object: {"next": "<agent_name>", "reason": "<one sentence>"}
"""


def _build_state_summary(state: AgentState) -> str:
    curriculum = state.get("curriculum_path") or []
    proficiency = state.get("topic_proficiency") or {}
    mastery_threshold = state.get("mastery_threshold") or 700.0
    mastered = sum(1 for item in curriculum if proficiency.get(item["subtopic"], 0) >= mastery_threshold)
    reports = state.get("agent_reports") or []

    last_reports_text = ""
    for r in reports[-3:]:  # only last 3 to keep prompt short
        last_reports_text += f"\n  [{r.get('agent')}] {r.get('summary', '')}"

    return f"""
task_type: {state.get("task_type", "?")}
iteration: {state.get("iteration_count", 0)} / {state.get("max_iterations", 8)}
curriculum_topics: {len(curriculum)} total, {mastered} mastered
current_topic: {state.get("current_topic", "none")}
quiz_questions_ready: {bool(state.get("quiz_questions"))}
progress_delta: {json.dumps(state.get("progress_delta") or {})}
session_complete: {state.get("session_complete", False)}
recent_agent_reports:{last_reports_text or " none yet"}
""".strip()


async def supervisor_node(state: AgentState) -> dict:
    """LLM supervisor: reads agent reports and decides what to call next."""
    tracer = get_tracer()

    iteration = (state.get("iteration_count") or 0) + 1
    max_iter = state.get("max_iterations") or 8

    with tracer.trace("supervisor", input={"iteration": iteration}) as span:
        # Hard guards — no LLM call needed
        if iteration >= max_iter:
            log.info("supervisor_max_iterations", count=iteration)
            span.update(output={"decision": "FINISH", "reason": "max iterations"})
            return {
                "supervisor_decision": "FINISH",
                "iteration_count": iteration,
                "session_complete": True,
            }

        curriculum = state.get("curriculum_path") or []
        proficiency = state.get("topic_proficiency") or {}
        mastery_threshold = state.get("mastery_threshold") or 700.0
        all_mastered = curriculum and all(
            proficiency.get(item["subtopic"], 0) >= mastery_threshold
            for item in curriculum
        )
        if all_mastered:
            log.info("supervisor_all_mastered")
            span.update(output={"decision": "FINISH", "reason": "all mastered"})
            return {
                "supervisor_decision": "FINISH",
                "iteration_count": iteration,
                "session_complete": True,
            }

        # Rule-based routing first — deterministic and fast.
        # LLM is called only for the genuinely ambiguous adaptive case.
        decision, reason = _rule_based_fallback(state)
        if decision == "FINISH" and not _is_ambiguous(state):
            # Rule-based says FINISH and nothing is ambiguous — trust it
            pass
        elif decision == "FINISH":
            # Ambiguous: ask LLM
            decision, reason = await _llm_decide(state)

        log.info("supervisor_decision", decision=decision, reason=reason, iteration=iteration)
        span.update(output={"decision": decision, "reason": reason})

        update: dict = {
            "supervisor_decision": decision,
            "iteration_count": iteration,
            "session_complete": decision == "FINISH",
            "next_action": decision.lower() if decision != "FINISH" else "end",
            "agent_reports": [{"agent": "supervisor", "summary": f"Decided → {decision}: {reason}"}],
        }

        # When routing to quiz, ensure current_topic is set
        if decision == "quiz":
            if not state.get("current_topic"):
                curriculum = state.get("curriculum_path") or []
                proficiency = state.get("topic_proficiency") or {}
                mastery_threshold = state.get("mastery_threshold") or 700.0
                unmastered = [i for i in curriculum if proficiency.get(i["subtopic"], 0) < mastery_threshold]
                if unmastered:
                    update["current_topic"] = unmastered[0]["subtopic"]

            # Negative mood → soften Bloom level to "remember" on the same topic
            progress_delta = state.get("progress_delta") or {}
            current_topic = update.get("current_topic") or state.get("current_topic", "")
            if (
                progress_delta.get("mood") == "NEGATIVE"
                and progress_delta.get("topic") == current_topic
            ):
                update["bloom_level"] = "remember"
                log.info("supervisor_bloom_softened", topic=current_topic)

        return update


async def _llm_decide(state: AgentState) -> tuple[str, str]:
    """Ask the LLM which agent to run next. Falls back to rule-based if LLM fails."""
    try:
        from huggingface_hub import InferenceClient
        from app.config import settings

        client = InferenceClient(
            provider="together",
            api_key=settings.HF_TOKEN,
        )

        state_summary = _build_state_summary(state)
        user_msg = f"Current state:\n{state_summary}\n\nWhat should run next?"

        response = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=80,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        return _parse_decision(raw)

    except Exception as e:
        log.warning("supervisor_llm_failed", error=str(e))
        return _rule_based_fallback(state)


def _parse_decision(raw: str) -> tuple[str, str]:
    """Extract {next, reason} from LLM output. Tolerates markdown fences."""
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
        data = json.loads(cleaned)
        decision = str(data.get("next", "FINISH")).strip()
        reason = str(data.get("reason", ""))
        if decision in VALID_AGENTS:
            return decision, reason
    except Exception:
        pass

    # Plain-text fallback: look for any valid agent name in the response
    for agent in VALID_AGENTS:
        if agent.lower() in raw.lower():
            return agent, "extracted from plain text"

    return "FINISH", "could not parse LLM response"


def _is_ambiguous(state: AgentState) -> bool:
    """Return True only when no deterministic rule clearly applies."""
    curriculum = state.get("curriculum_path") or []
    progress_delta = state.get("progress_delta") or {}
    task = state.get("task_type", "")
    if not curriculum:
        return False  # clear: need curriculum
    if task in {"quiz", "doubt"}:
        return False  # clear: task is set
    if progress_delta.get("score") is not None and not progress_delta.get("elo_processed"):
        return False  # clear: need progress update
    return True  # curriculum exists, no pending task → genuinely ambiguous


def _rule_based_fallback(state: AgentState) -> tuple[str, str]:
    """Deterministic fallback when LLM is unavailable."""
    task = state.get("task_type", "")
    curriculum = state.get("curriculum_path") or []
    proficiency = state.get("topic_proficiency") or {}
    mastery_threshold = state.get("mastery_threshold") or 700.0
    progress_delta = state.get("progress_delta") or {}

    if not curriculum:
        return "curriculum", "no curriculum exists yet"

    if task == "quiz" and not state.get("quiz_questions"):
        return "quiz", "quiz requested, no questions yet"

    if task == "doubt":
        return "doubt", "doubt requested"

    if progress_delta.get("score") is not None and not progress_delta.get("elo_processed"):
        return "progress", "quiz score needs Elo update"

    unmastered = [i for i in curriculum if proficiency.get(i["subtopic"], 0) < mastery_threshold]
    if unmastered:
        mood = progress_delta.get("mood", "NEUTRAL")
        if mood == "NEGATIVE" and progress_delta.get("topic") == unmastered[0]["subtopic"]:
            return "quiz", f"NEGATIVE mood on '{unmastered[0]['subtopic']}', re-queuing at lower Bloom"
        return "quiz", f"{len(unmastered)} topics still unmastered"

    return "FINISH", "all topics mastered"
