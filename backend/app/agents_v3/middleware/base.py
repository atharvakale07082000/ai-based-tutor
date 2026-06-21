"""Middleware ABC and chain compositor for the DeepAgent pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.agents_v3.schemas import AgentContext, AgentReport


class AgentMiddleware(ABC):
    @abstractmethod
    async def pre_process(self, ctx: AgentContext) -> AgentContext:
        """Transform the agent context before the ReAct loop runs."""

    @abstractmethod
    async def post_process(self, ctx: AgentContext, report: AgentReport) -> AgentReport:
        """Transform the completed AgentReport after the ReAct loop finishes."""


class MiddlewareChain:
    """Composes a list of middlewares: pre runs in order, post runs in reverse."""

    def __init__(self, middlewares: list[AgentMiddleware]) -> None:
        self._middlewares = middlewares

    async def apply_pre(self, ctx: AgentContext) -> AgentContext:
        for mw in self._middlewares:
            ctx = await mw.pre_process(ctx)
            if ctx.blocked:
                break
        return ctx

    async def apply_post(self, ctx: AgentContext, report: AgentReport) -> AgentReport:
        for mw in reversed(self._middlewares):
            report = await mw.post_process(ctx, report)
        return report
