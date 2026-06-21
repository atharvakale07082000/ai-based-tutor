"""GuardrailMiddleware — validates input before the ReAct loop and output after."""

from __future__ import annotations

import re

import structlog

from app.agents_v3.middleware.base import AgentMiddleware
from app.agents_v3.schemas import AgentContext, AgentReport
from app.tools import tool_registry

log = structlog.get_logger()

_MAX_OUTPUT_CHARS = 4000

# Queries matching this pattern are unambiguously educational — skip the LLM
# guardrail call (~500ms saved per request for the common case).
_SAFE_PATTERN = re.compile(
    r"\b(explain|what is|how does|how do|why|understand|learn|study|quiz|"
    r"flashcard|question|topic|concept|difference between|define|example|"
    r"practice|progress|curriculum|course|lesson|tutorial|help me|can you|"
    r"tell me|show me|teach me)\b",
    re.IGNORECASE,
)


def _is_obviously_safe(query: str) -> bool:
    """Return True for queries that are clearly educational — no LLM guardrail needed."""
    stripped = query.strip()
    # Very short queries (< 5 chars) or very long ones (injection attempts) skip fast-path
    if len(stripped) < 5 or len(stripped) > 1000:
        return False
    return bool(_SAFE_PATTERN.search(stripped))


class GuardrailMiddleware(AgentMiddleware):
    async def pre_process(self, ctx: AgentContext) -> AgentContext:
        """Skip LLM guardrail for clearly safe educational queries; check ambiguous ones."""
        if _is_obviously_safe(ctx.query):
            log.debug("deep_agent.guardrail_fast_pass", learner_id=ctx.learner_id)
            return ctx
        try:
            result = await tool_registry.call("check_guardrail", {"text": ctx.query})
            if result.result and result.result.get("blocked"):
                ctx.blocked = True
                ctx.block_reason = result.result.get("reason", "Content policy violation")
                log.warning(
                    "deep_agent.guardrail_blocked",
                    learner_id=ctx.learner_id,
                    reason=ctx.block_reason,
                )
        except Exception as e:
            # Guardrail failure is non-fatal — log and continue
            log.error("deep_agent.guardrail_error", error=str(e)[:200])
        return ctx

    async def post_process(self, ctx: AgentContext, report: AgentReport) -> AgentReport:
        if len(report.result) > _MAX_OUTPUT_CHARS:
            report.result = report.result[:_MAX_OUTPUT_CHARS] + "\n\n*(Response truncated)*"
        return report
