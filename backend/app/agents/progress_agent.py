import structlog

from app.agents.state import AgentState
from app.agents.tools import call_tool
from app.tracing import get_tracer

log = structlog.get_logger()

K_FACTOR = 32.0


def calculate_elo_update(current_elo: float, score: float, expected_score: float = 0.5) -> float:
    """
    Standard Elo update formula, clamped to [0, 1000].
    score: actual performance 0.0–1.0
    expected_score: prior probability of success (default 0.5)
    """
    new_elo = current_elo + K_FACTOR * (score - expected_score)
    return max(0.0, min(1000.0, new_elo))


async def progress_agent_node(state: AgentState) -> dict:
    """
    Update Elo proficiency based on quiz performance.

    Delegation: calls `analyze_sentiment` sub-agent on the learner's reflection
    text to capture mood metadata alongside the numerical Elo update.
    """
    topic = state.get("current_topic", "")
    delta = state.get("progress_delta", {})
    quiz_score = delta.get("score", 0.5)
    proficiency = dict(state.get("topic_proficiency", {}))
    current_elo = proficiency.get(topic, 500.0)

    tracer = get_tracer()

    with tracer.trace(
        "progress_agent",
        input={"topic": topic, "quiz_score": quiz_score, "current_elo": current_elo},
    ) as span:
        log.info("progress_agent_start", topic=topic, quiz_score=quiz_score, current_elo=current_elo)
        try:
            new_elo = calculate_elo_update(current_elo, quiz_score)
            proficiency[topic] = new_elo

            updated_delta: dict = {
                "topic": topic,
                "old_elo": current_elo,
                "new_elo": new_elo,
                "score": quiz_score,
            }

            # Delegate: sentiment sub-agent on learner reflection
            reflection = delta.get("reflection", "")
            if reflection:
                try:
                    sentiment = await call_tool("analyze_sentiment", text=reflection)
                    updated_delta["mood"] = sentiment.get("label", "NEUTRAL")
                    updated_delta["mood_score"] = sentiment.get("score", 0.5)
                except Exception:
                    updated_delta["mood"] = "NEUTRAL"

            mastery_threshold = state.get("mastery_threshold", 700.0)
            elo_direction = "↑" if new_elo > current_elo else "↓"
            mastered_now = new_elo >= mastery_threshold and current_elo < mastery_threshold
            report = {
                "agent": "progress",
                "summary": (
                    f"Updated Elo for '{topic}': {int(current_elo)} → {int(new_elo)} {elo_direction}. "
                    f"Score: {quiz_score:.0%}. Mood: {updated_delta.get('mood', 'NEUTRAL')}."
                    + (" Topic newly MASTERED." if mastered_now else "")
                ),
            }
            # Mark delta as processed so supervisor knows Elo is up to date
            updated_delta["elo_processed"] = True

            span.update(
                output={"old_elo": current_elo, "new_elo": new_elo, "mood": updated_delta.get("mood")}
            )
            log.info("progress_agent_done", old_elo=current_elo, new_elo=new_elo)
            return {
                "topic_proficiency": proficiency,
                "progress_delta": updated_delta,
                "error": None,
                "agent_reports": [report],
            }

        except Exception as e:
            log.error("progress_agent_error", error=str(e))
            span.update(output={"error": str(e)})
            return {"error": str(e), "agent_reports": [{"agent": "progress", "summary": f"Failed: {e}"}]}
