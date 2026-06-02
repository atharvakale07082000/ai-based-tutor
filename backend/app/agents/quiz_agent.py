import structlog

from app.agents.state import AgentState
from app.agents.tools import call_tool
from app.guardrails import sanitize_quiz_batch
from app.tracing import get_tracer

log = structlog.get_logger()

BLOOM_LEVEL_BY_ELO: list[tuple[tuple[int, int], str]] = [
    ((0, 300), "remember"),
    ((300, 450), "understand"),
    ((450, 600), "apply"),
    ((600, 720), "analyze"),
    ((720, 870), "evaluate"),
    ((870, 1001), "create"),
]


def get_bloom_level(elo: float) -> str:
    for (low, high), level in BLOOM_LEVEL_BY_ELO:
        if low <= elo < high:
            return level
    return "understand"


async def quiz_agent_node(state: AgentState) -> dict:
    """
    Generate Bloom-calibrated quiz questions for the current topic.

    Delegation:
    - `score_difficulty` sub-agent to verify the topic difficulty aligns with
      the learner's Elo before question generation (adjusts bloom level if needed).
    - `generate_quiz` sub-agent (quiz-generator HF model) to produce questions.

    Guardrails: malformed questions are filtered out before returning.
    """
    topic = state.get("current_topic", "Python Programming")
    proficiency = state.get("topic_proficiency", {})
    elo = proficiency.get(topic, 500.0)
    bloom_level = state.get("bloom_level") or get_bloom_level(elo)

    tracer = get_tracer()

    with tracer.trace(
        "quiz_agent",
        input={"topic": topic, "elo": elo, "bloom_level": bloom_level},
    ) as span:
        log.info("quiz_agent_start", topic=topic, elo=elo, bloom_level=bloom_level)
        try:
            difficulty_score = 0.5  # default if score_difficulty call fails
            bloom_levels = [lvl for _, lvl in BLOOM_LEVEL_BY_ELO]

            # Delegate: verify difficulty via difficulty-scorer sub-agent
            try:
                diff_result = await call_tool("score_difficulty", text=topic)
                difficulty_score = float(diff_result.get("score", 0.5))
                difficulty_score = max(0.0, min(1.0, difficulty_score))  # clamp to [0,1]
                # High-difficulty topic + low Elo → drop one Bloom level to avoid overwhelming the learner
                if difficulty_score > 0.75 and elo < 400 and bloom_level in bloom_levels:
                    idx = bloom_levels.index(bloom_level)
                    bloom_level = bloom_levels[max(0, idx - 1)]
                    log.info("quiz_bloom_adjusted_difficulty", new_level=bloom_level, difficulty=difficulty_score)
            except Exception as e:
                log.warning("quiz_difficulty_check_failed", topic=topic, error=str(e))

            # NEGATIVE learner_mood (written by progress_agent / doubt_agent) → soften one more level
            state_mood = state.get("learner_mood", "NEUTRAL")
            if state_mood == "NEGATIVE" and bloom_level in bloom_levels:
                idx = bloom_levels.index(bloom_level)
                bloom_level = bloom_levels[max(0, idx - 1)]
                log.info("quiz_bloom_adjusted_mood", new_level=bloom_level, mood=state_mood)

            # Delegate: generate questions via quiz-generator sub-agent
            result = await call_tool("generate_quiz", topic=topic, bloom_level=bloom_level, count=5)
            raw_questions = result.get("questions", [])

            # Guardrails: filter malformed questions
            questions = sanitize_quiz_batch(raw_questions, bloom_level)
            if not questions:
                log.warning("quiz_agent_all_questions_rejected", topic=topic)

            report = {
                "agent": "quiz",
                "summary": (
                    f"Generated {len(questions)} questions for '{topic}' "
                    f"at Bloom '{bloom_level}' (Elo {int(elo)}). Awaiting human submission."
                ),
            }
            span.update(
                output={"question_count": len(questions), "bloom_level": bloom_level, "difficulty": difficulty_score}
            )
            log.info("quiz_agent_done", question_count=len(questions))
            return {
                "quiz_questions": questions,
                "bloom_level": bloom_level,
                "topic_difficulty": difficulty_score,  # persisted so supervisor can read it
                "error": None,
                "agent_reports": [report],
            }

        except Exception as e:
            log.error("quiz_agent_error", error=str(e))
            span.update(output={"error": str(e)})
            return {
                "quiz_questions": [],
                "error": str(e),
                "agent_reports": [{"agent": "quiz", "summary": f"Failed: {e}"}],
            }
