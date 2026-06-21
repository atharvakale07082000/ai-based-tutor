"""
DoubtSubAgent — answers learner questions via guardrail → proficiency → dedicated
doubt-solver stream (same high-quality path as v2 DoubtAgent).
"""

from __future__ import annotations

import structlog

from app.agents_v3.middleware.base import MiddlewareChain
from app.agents_v3.schemas import AgentReport
from app.agents_v3.subagents.base import BaseSubAgent
from app.hf.doubt_solver import stream_doubt_response

log = structlog.get_logger()


class DoubtSubAgent(BaseSubAgent):
    name = "doubt"
    role_description = (
        "a warm, patient tutor who makes complex ideas feel effortless. "
        "You meet learners exactly where they are — whether they're just starting out or "
        "going deep. You use vivid analogies, concrete examples, and a conversational tone. "
        "You celebrate curiosity and make every question feel like a great one. "
        "Before answering, you check the learner's proficiency so your depth is always just right. "
        "Your explanations read like a thoughtful mentor talking, not a textbook."
    )
    tool_names = ["check_guardrail", "get_proficiency", "generate_explanation"]

    def __init__(self, middleware: MiddlewareChain) -> None:
        super().__init__(middleware)

    async def run(self, query: str, context: dict) -> AgentReport:
        # Run the standard ReAct loop to gather CoT + tool calls
        report = await super().run(query, context)

        # Replace generic result with a high-quality streamed answer from the
        # dedicated doubt-solver model (same as v2 DoubtAgent.stream_final_answer)
        if not report.blocked and report.result and "unavailable" not in report.result.lower():
            current_topic = context.get("current_topic", "")
            history = context.get("history", [])
            try:
                token_stream = await stream_doubt_response(
                    question=report.result,
                    context=current_topic,
                    history=history,
                )
                full_text = ""
                async for token in token_stream:
                    full_text += token
                if full_text.strip():
                    report.result = full_text
            except Exception as e:
                log.error("doubt_subagent.stream_error", error=str(e)[:200])
                # Keep the ReAct result as fallback

        return report
