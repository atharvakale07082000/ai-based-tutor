"""ObservabilityMiddleware — structured logging at subagent boundaries."""

from __future__ import annotations

import time

import structlog

from app.agents_v3.middleware.base import AgentMiddleware
from app.agents_v3.schemas import AgentContext, AgentReport

log = structlog.get_logger()

_START_TIMES: dict[str, float] = {}


class ObservabilityMiddleware(AgentMiddleware):
    async def pre_process(self, ctx: AgentContext) -> AgentContext:
        key = f"{ctx.learner_id}:{id(ctx)}"
        _START_TIMES[key] = time.monotonic()
        log.info(
            "deep_agent.subagent_start",
            learner_id=ctx.learner_id,
            query_len=len(ctx.query),
            blocked=ctx.blocked,
        )
        return ctx

    async def post_process(self, ctx: AgentContext, report: AgentReport) -> AgentReport:
        key = f"{ctx.learner_id}:{id(ctx)}"
        elapsed_ms = int((time.monotonic() - _START_TIMES.pop(key, time.monotonic())) * 1000)
        log.info(
            "deep_agent.subagent_done",
            agent=report.agent_name,
            display_name=report.display_name,
            learner_id=ctx.learner_id,
            cot_steps=len(report.cot_chain),
            tool_calls=len(report.tool_calls),
            confidence=report.confidence,
            latency_ms=elapsed_ms,
        )
        report.latency_ms = elapsed_ms
        return report
