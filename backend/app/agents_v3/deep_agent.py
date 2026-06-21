"""
DeepAgent — top-level harness wrapping the compiled LangGraph.

create_deep_agent() returns a DeepAgent instance.
DeepAgent.astream() is an async generator of typed SSE event dicts,
matching the v3 event schema (routing, cot_step, tool_call, tool_result,
token, action, done).

Token streaming: the synthesizer holds the final_response as a string.
We stream it character-by-character in ~30-char chunks to match the
real-time feel of v2's per-token streaming.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import structlog

from app.agents_v3.graph import build_graph
from app.agents_v3.schemas import AgentReport, DeepAgentState

log = structlog.get_logger()

_STREAM_CHUNK_SIZE = 30  # chars per token event


class DeepAgent:
    def __init__(self) -> None:
        self._graph = build_graph().compile()

    async def astream(self, query: str, context: dict) -> AsyncIterator[dict]:
        """
        Async generator of SSE event dicts for the v3 chat endpoint.

        Events emitted (in order):
          routing    → { agent, display_name, reason, confidence }
          cot_step   → { step, reasoning, decision }   (one per CoT step)
          tool_call  → { step, name, args }
          tool_result→ { step, name, result, latency_ms }
          token      → { content }                     (chunked final answer)
          action     → { kind, payload }               (side effects)
          done       → { steps, total_ms }
        """
        start_ms = time.monotonic()

        initial_state: DeepAgentState = {
            "messages": [],
            "learner_id": context.get("learner_id", "unknown"),
            "query": query,
            "context": context,
            "routing_decision": None,
            "agent_reports": [],
            "final_response": "",
            "iteration": 0,
        }

        try:
            final_state = await self._graph.ainvoke(initial_state)
        except Exception as e:
            log.error("deep_agent.graph_error", error=str(e)[:300])
            # Emit a warm, interactive error — never expose raw exceptions
            yield {
                "type": "token",
                "content": (
                    "I ran into an unexpected issue on my end. "
                    'Your question was: *"' + query[:120] + '"*\n\n'
                    "Please tap **Try again** — I'm ready to help you right away."
                ),
            }
            yield {"type": "done", "steps": 0, "total_ms": int((time.monotonic() - start_ms) * 1000)}
            return

        # Emit routing event
        decision = final_state.get("routing_decision")
        if decision:
            yield {
                "type": "routing",
                "agent": decision.agent,
                "display_name": decision.display_name,
                "reason": decision.reason,
                "confidence": decision.confidence,
            }
            await asyncio.sleep(0)  # yield control to event loop

        # Emit CoT steps, tool calls, and actions from all reports
        reports: list[AgentReport] = final_state.get("agent_reports", [])
        tool_step_offset = 0

        for report in reports:
            for cot in report.cot_chain:
                yield {"type": "cot_step", "step": cot.step, "reasoning": cot.reasoning, "decision": cot.decision}
                await asyncio.sleep(0)

            for i, tc in enumerate(report.tool_calls):
                step = tool_step_offset + i + 1
                yield {"type": "tool_call", "step": step, "name": tc.name, "args": tc.args}
                await asyncio.sleep(0)
                yield {
                    "type": "tool_result",
                    "step": step,
                    "name": tc.name,
                    "result": tc.result,
                    "latency_ms": tc.latency_ms,
                }
                await asyncio.sleep(0)

            tool_step_offset += len(report.tool_calls)

        # Stream final answer in chunks
        final_response: str = final_state.get("final_response", "")
        total_steps = tool_step_offset

        if final_response:
            for i in range(0, len(final_response), _STREAM_CHUNK_SIZE):
                chunk = final_response[i : i + _STREAM_CHUNK_SIZE]
                yield {"type": "token", "content": chunk}
                await asyncio.sleep(0.01)  # realistic streaming pace

        # Emit side effects (actions) from all reports
        for report in reports:
            for fx in report.side_effects:
                yield {"type": "action", "kind": fx.kind, "payload": fx.payload}
                await asyncio.sleep(0)

        total_ms = int((time.monotonic() - start_ms) * 1000)
        yield {"type": "done", "steps": total_steps, "total_ms": total_ms}


def create_deep_agent() -> DeepAgent:
    """Factory function — mirrors the LangChain DeepAgent create_deep_agent() pattern."""
    return DeepAgent()
