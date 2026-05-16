"""
DoubtAgent — answers learner questions clearly and accurately, first
checking safety guardrails. Overrides stream_final_answer to use the
high-quality DOUBT_SOLVER streaming path instead of the generic Qwen call.
"""
from __future__ import annotations

from typing import AsyncIterator

import structlog

from app.agents_v2.base import BaseAgent
from app.hf.doubt_solver import stream_doubt_response

log = structlog.get_logger()


class DoubtAgent(BaseAgent):
    name = "DoubtAgent"
    role_description = (
        "You answer learner questions clearly and accurately, first checking safety guardrails."
    )
    tool_names = ["check_guardrail", "get_proficiency", "generate_explanation"]

    async def stream_final_answer(
        self,
        final_answer: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """
        Override: use stream_doubt_response for higher-quality, long-form answers
        instead of the generic Qwen streaming in BaseAgent.
        """
        context = getattr(self, "_current_context", {})
        current_topic = context.get("current_topic", "")
        history = context.get("history", [])

        log.info("doubt_agent_stream_final", topic=current_topic, answer_len=len(final_answer))

        try:
            token_stream = await stream_doubt_response(
                question=final_answer,
                context=current_topic,
                history=history,
            )
            async for token in token_stream:
                yield token
        except Exception as e:
            log.error("doubt_agent_stream_error", error=str(e))
            yield "An error occurred while generating the answer. Please try again."
