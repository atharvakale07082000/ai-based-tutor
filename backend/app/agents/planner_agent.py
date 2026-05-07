import structlog

from app.agents.state import AgentState
from app.agents.tools import call_tool
from app.tracing import get_tracer

log = structlog.get_logger()

MASTERY_DEFAULT = 700.0
MAX_ITER_DEFAULT = 10


async def planner_agent_node(state: AgentState) -> dict:
    """
    Meta-agent: autonomously decides the next learning action.

    Decision rules (in priority order):
    1. Iteration cap reached → end session.
    2. No curriculum → delegate to curriculum sub-agent.
    3. All topics mastered → end session.
    4. Mood is NEGATIVE after last reflection → repeat current topic at a lower Bloom level.
    5. Otherwise → quiz the first unmastered topic in curriculum order.

    Delegation: calls `classify_topic` sub-agent when the learner has no
    curriculum yet to validate that we're about to build the right one.
    """
    tracer = get_tracer()

    with tracer.trace("planner_agent", input=dict(state)) as span:
        try:
            result = await _plan(state)
            span.update(output=result)
            return result
        except Exception as e:
            log.error("planner_agent_error", error=str(e))
            span.update(output={"error": str(e)})
            return {"next_action": "end", "session_complete": True, "error": str(e)}


async def _plan(state: AgentState) -> dict:
    curriculum_path = state.get("curriculum_path", [])
    proficiency = state.get("topic_proficiency", {})
    iteration_count = state.get("iteration_count", 0) + 1
    max_iterations = state.get("max_iterations", MAX_ITER_DEFAULT)
    mastery_threshold = state.get("mastery_threshold", MASTERY_DEFAULT)
    progress_delta = state.get("progress_delta", {})

    log.info(
        "planner_agent",
        iteration=iteration_count,
        max_iterations=max_iterations,
        curriculum_size=len(curriculum_path),
    )

    # Rule 1: iteration cap
    if iteration_count >= max_iterations:
        log.info("planner_max_iterations_reached", count=iteration_count)
        return {"next_action": "end", "session_complete": True, "iteration_count": iteration_count}

    # Rule 2: no curriculum — build one first
    if not curriculum_path:
        log.info("planner_no_curriculum")
        # Optionally validate learner goals via classify_topic before triggering curriculum build
        goals = state.get("learner_profile", {}).get("goal_vector", [])
        if goals:
            try:
                classification = await call_tool("classify_topic", text=" ".join(goals[:3]))
                log.info("planner_goal_domain", domain=classification["labels"][0])
            except Exception:
                pass
        return {"next_action": "curriculum", "iteration_count": iteration_count, "session_complete": False}

    # Rule 3: find unmastered topics
    unmastered = [
        item for item in curriculum_path
        if proficiency.get(item["subtopic"], 500.0) < mastery_threshold
    ]

    if not unmastered:
        log.info("planner_all_topics_mastered", total=len(curriculum_path))
        return {"next_action": "end", "session_complete": True, "iteration_count": iteration_count}

    next_topic = unmastered[0]["subtopic"]
    next_elo = proficiency.get(next_topic, 500.0)

    # Rule 4: if learner mood was NEGATIVE after last attempt on this topic,
    # re-queue same topic but signal to quiz agent to soften the Bloom level
    mood = progress_delta.get("mood", "NEUTRAL")
    if mood == "NEGATIVE" and progress_delta.get("topic") == next_topic:
        log.info("planner_negative_mood_soften", topic=next_topic)
        return {
            "next_action": "quiz",
            "current_topic": next_topic,
            "bloom_level": "remember",   # override to easiest level
            "iteration_count": iteration_count,
            "session_complete": False,
        }

    # Rule 5: standard advancement
    log.info("planner_next_topic", topic=next_topic, elo=next_elo, remaining=len(unmastered))
    return {
        "next_action": "quiz",
        "current_topic": next_topic,
        "bloom_level": "",   # let quiz_agent decide from Elo
        "iteration_count": iteration_count,
        "session_complete": False,
    }
