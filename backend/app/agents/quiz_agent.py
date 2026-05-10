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
            # Delegate: verify difficulty via difficulty-scorer sub-agent
            try:
                diff_result = await call_tool("score_difficulty", text=topic)
                difficulty_score = diff_result.get("score", 0.5)
                # If topic difficulty is high (>0.75) but learner Elo is low (<400),
                # drop one Bloom level to avoid overwhelming the learner
                if difficulty_score > 0.75 and elo < 400 and bloom_level != "remember":
                    idx = [lvl for _, lvl in BLOOM_LEVEL_BY_ELO].index(bloom_level)
                    bloom_level = [lvl for _, lvl in BLOOM_LEVEL_BY_ELO][max(0, idx - 1)]
                    log.info("quiz_bloom_adjusted", new_level=bloom_level, difficulty=difficulty_score)
            except Exception:
                pass  # difficulty sub-agent failure is non-fatal

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
            span.update(output={"question_count": len(questions), "bloom_level": bloom_level})
            log.info("quiz_agent_done", question_count=len(questions))
            return {"quiz_questions": questions, "bloom_level": bloom_level, "error": None, "agent_reports": [report]}

        except Exception as e:
            log.error("quiz_agent_error", error=str(e))
            span.update(output={"error": str(e)})
            return {"quiz_questions": [], "error": str(e), "agent_reports": [{"agent": "quiz", "summary": f"Failed: {e}"}]}
