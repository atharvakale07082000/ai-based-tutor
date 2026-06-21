"""GuardrailMiddleware — validates input before the ReAct loop and output after."""

from __future__ import annotations

import structlog

from app.agents_v3.middleware.base import AgentMiddleware
from app.agents_v3.schemas import AgentContext, AgentReport
from app.tools import tool_registry

log = structlog.get_logger()

_MAX_OUTPUT_CHARS = 4000


class GuardrailMiddleware(AgentMiddleware):
    async def pre_process(self, ctx: AgentContext) -> AgentContext:
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
