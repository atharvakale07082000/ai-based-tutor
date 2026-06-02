import structlog

from app.agents.quiz_agent import get_bloom_level
from app.agents.state import AgentState
from app.agents.tools import call_tool
from app.guardrails import check_input, check_output, check_topic_grounding
from app.hf.doubt_solver import stream_doubt_response
from app.tracing import get_tracer

log = structlog.get_logger()

_GUARDRAIL_FALLBACK = (
    "I'm not able to answer that question. Please ask something related to your "
    "current study topic and I'll be happy to help."
)


async def doubt_agent_node(state: AgentState) -> dict:
    """
    Answer learner doubts using a streaming LLM.

    Delegation:
    - `classify_topic` sub-agent to verify the question is on-topic before sending
      to the expensive LLM call.
    - `analyze_sentiment` sub-agent to capture the learner's emotional state.

    Guardrails:
    - Input validated (length, injection patterns) before any processing.
    - Output validated (length, topic grounding) before returning.
    """
    tracer = get_tracer()
    messages = state.get("messages", [])
    context = state.get("current_topic", "")

    # Extract latest question and history from LangGraph messages
    question = ""
    history: list[dict] = []
    for msg in messages:
        if hasattr(msg, "type"):
            if msg.type == "human":
                question = msg.content
            history.append({"role": msg.type, "content": msg.content})
    if not question:
        question = "Can you help me understand this topic better?"

    with tracer.trace(
        "doubt_agent",
        input={"question": question[:120], "context": context},
    ) as span:
        log.info("doubt_agent_start", question=question[:80], context=context)

        # ── Input guardrail ──────────────────────────────────────────────────
        guard = check_input(question, context="doubt_agent")
        if not guard.passed:
            log.warning("doubt_agent_input_blocked", reason=guard.reason)
            span.update(output={"blocked": True, "reason": guard.reason})
            return {
                "doubt_response": _GUARDRAIL_FALLBACK,
                "error": f"guardrail:{guard.reason}",
            }
        question = guard.sanitized  # use sanitized (possibly truncated) version

        # ── Topic grounding + bloom calibration via classify_topic ──────────────
        proficiency = state.get("topic_proficiency", {})
        # Start from current topic's Elo so we have a sensible default
        bloom_level = get_bloom_level(proficiency.get(context, 500.0))
        try:
            classification = await call_tool("classify_topic", text=question)
            detected_domain = classification["labels"][0] if classification["labels"] else context
            if context and detected_domain.lower() not in (context.lower(), ""):
                log.info(
                    "doubt_agent_topic_check",
                    expected=context,
                    detected=detected_domain,
                )
            # Refine bloom_level using the detected domain's proficiency so the
            # explanation depth matches what the learner has actually mastered.
            bloom_level = get_bloom_level(proficiency.get(detected_domain, proficiency.get(context, 500.0)))
        except Exception:
            detected_domain = context

        # ── LLM call via doubt-solver HF module ──────────────────────────────
        try:
            stream = await stream_doubt_response(
                question,
                context,
                history[:-1],
                bloom_level=bloom_level,
            )
            full_response = ""
            async for token in stream:
                full_response += token
        except Exception as e:
            log.error("doubt_agent_llm_error", error=str(e))
            return {
                "doubt_response": "I'm having trouble answering right now. Please try again.",
                "error": str(e),
            }

        # ── Output guardrail ─────────────────────────────────────────────────
        out_guard = check_output(full_response, context="doubt_agent")
        if not out_guard.passed:
            log.warning("doubt_agent_output_blocked", reason=out_guard.reason)
            full_response = _GUARDRAIL_FALLBACK
        else:
            full_response = out_guard.sanitized

        # Topic grounding check (warn only — don't block)
        grounding = check_topic_grounding(full_response, context)
        if not grounding.passed:
            log.warning("doubt_agent_grounding_warning", topic=context)

        # ── Learner sentiment via analyze_sentiment sub-agent ─────────────────
        learner_mood_score = 0.5
        try:
            sentiment = await call_tool("analyze_sentiment", text=question)
            learner_mood = sentiment.get("label", "NEUTRAL")
            learner_mood_score = sentiment.get("score", 0.5)
        except Exception:
            learner_mood = "NEUTRAL"

        span.update(
            output={
                "response_len": len(full_response),
                "topic_grounded": grounding.passed,
                "learner_mood": learner_mood,
                "bloom_level": bloom_level,
            }
        )
        report = {
            "agent": "doubt",
            "summary": (
                f"Answered question on '{context}'. "
                f"Response length: {len(full_response)} chars. "
                f"Learner mood: {learner_mood}. "
                f"Bloom level: {bloom_level}. "
                f"Topic grounded: {grounding.passed}."
            ),
        }
        log.info("doubt_agent_done", response_length=len(full_response), mood=learner_mood, bloom=bloom_level)

        return {
            "doubt_response": full_response,
            # Promote mood to first-class state so quiz_agent/supervisor can read it.
            "learner_mood": learner_mood,
            "learner_mood_score": learner_mood_score,
            "error": None,
            "agent_reports": [report],
        }
