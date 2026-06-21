"""
BaseSubAgent — ReAct loop that returns a typed AgentReport.

Extends the v2 BaseAgent pattern but:
- run() returns AgentReport instead of AsyncIterator
- Applies MiddlewareChain pre/post
- Extracts CoT steps per ReAct iteration via extract_cot_steps()
- Rate-limit aware: shares the existing _HF_SEMAPHORE (cap 40 concurrent LLM calls)
"""

from __future__ import annotations

import asyncio
import json
import re
import time

import structlog

from app.agents_v3.middleware.base import MiddlewareChain
from app.agents_v3.middleware.cot import extract_cot_steps
from app.agents_v3.schemas import (
    AGENT_DISPLAY_NAMES,
    AgentContext,
    AgentReport,
    CoTStep,
    SideEffect,
    ToolCallRecord,
)
from app.hf.client import hf_chat_completion_with_resilience, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS, TOKEN_BUDGETS
from app.resilience import CircuitOpenError
from app.tools import tool_registry

log = structlog.get_logger()

# Shared semaphore from v2 — keeps total outbound LLM calls ≤ 40 (respects 40 RPM limit)
_HF_SEMAPHORE = asyncio.Semaphore(40)

_DEFAULT_MAX_STEPS = 6


class BaseSubAgent:
    name: str = "base"
    role_description: str = ""
    tool_names: list[str] = []
    max_steps: int = _DEFAULT_MAX_STEPS

    def __init__(self, middleware: MiddlewareChain) -> None:
        """Inject the middleware chain used by pre/post processing hooks."""
        self._middleware = middleware

    def _build_system_prompt(self) -> str:
        """Render the agent's system prompt with tool descriptions and CoT instructions."""
        tools_desc = tool_registry.describe_tools(self.tool_names)
        display = AGENT_DISPLAY_NAMES.get(self.name, self.name)
        return (
            f"You are {display}, {self.role_description}\n\n"
            f"## Your communication style\n"
            f"- Write like a brilliant friend who happens to be an expert — warm, clear, conversational.\n"
            f"- Use concrete examples and analogies. Avoid jargon unless defining it.\n"
            f"- Keep paragraphs short. Use markdown: **bold** for key terms, `code` for code, "
            f"numbered lists for steps, bullet points for options.\n"
            f"- Vary sentence rhythm. Short punchy sentences for emphasis. Longer ones to explain nuance.\n"
            f"- Never be robotic. Never say 'Certainly!' or 'Great question!'. Just answer warmly and directly.\n"
            f"- End with a natural follow-up hook when relevant: 'Want me to quiz you on this?'\n\n"
            f"## Tools available\n{tools_desc}\n\n"
            f"## How to respond\n"
            f"Think through each step, then output JSON:\n"
            f'{{"cot_steps":[{{"step":1,"reasoning":"...","decision":"..."}}],'
            f'"thought":"<your reasoning>","action":{{"tool":"<name>","args":{{...}}}}}}\n\n'
            f"When you have a complete answer:\n"
            f'{{"cot_steps":[...],"thought":"<reasoning>","final_answer":"<your full answer in markdown>","side_effects":[]}}\n\n'
            f"Rules: valid JSON only, no markdown fences, use listed tools only, max {self.max_steps} steps."
        )

    async def _decide_step(self, messages: list[dict]) -> dict:
        """Call the LLM for one ReAct step; return parsed JSON or a safe error fallback."""
        model_cfg = HF_MODELS["DOUBT_SOLVER"]
        provider = model_cfg["provider"]
        model_id = model_cfg["model_id"]
        # Use the agent-specific token budget, falling back to cot_step for intermediate steps
        budget = TOKEN_BUDGETS.get(self.name, TOKEN_BUDGETS["cot_step"])
        try:
            async with _HF_SEMAPHORE:
                raw = await hf_chat_completion_with_resilience(
                    provider=provider,
                    model_id=model_id,
                    messages=messages,
                    max_tokens=budget,
                    temperature=0.1,
                    timeout_s=20.0,
                )
            record_auth_success(provider)
            cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            return json.loads(cleaned)
        except (asyncio.TimeoutError, CircuitOpenError) as e:
            log.error("subagent.decide_timeout", agent=self.name, error=str(e)[:100])
            return {
                "thought": "timeout",
                "final_answer": "I'm taking longer than expected on this — give me another go and I'll be quicker.",
                "side_effects": [],
            }
        except json.JSONDecodeError as e:
            log.error("subagent.decide_parse_error", agent=self.name, error=str(e)[:100])
            return {
                "thought": "parse error",
                "final_answer": "I got a bit tangled up there — let me try again with a fresh approach.",
                "side_effects": [],
            }
        except Exception as e:
            err = str(e)
            if "401" in err or "403" in err:
                record_auth_failure(provider)
            log.error("subagent.decide_error", agent=self.name, error=err[:200])
            return {
                "thought": "error",
                "final_answer": "Something unexpected happened on my end — please send your question again and I'll pick right up.",
                "side_effects": [],
            }

    async def run(self, query: str, context: dict) -> AgentReport:
        """Execute the full ReAct loop with middleware and return a structured AgentReport."""
        start_ms = time.monotonic()
        display_name = AGENT_DISPLAY_NAMES.get(self.name, self.name)

        # Build middleware context
        ctx = AgentContext(
            learner_id=context.get("learner_id", "unknown"),
            query=query,
            context=context,
            system_prompt=self._build_system_prompt(),
        )

        # Pre-process (CoT injection, guardrail check, observability start)
        ctx = await self._middleware.apply_pre(ctx)

        if ctx.blocked:
            report = AgentReport(
                agent_name=self.name,
                display_name=display_name,
                task=query,
                result=f"I can't help with that: {ctx.block_reason}",
                confidence=0.0,
                latency_ms=int((time.monotonic() - start_ms) * 1000),
                blocked=True,
            )
            return await self._middleware.apply_post(ctx, report)

        # Build initial messages with CoT-enriched system prompt
        context_str = json.dumps(
            {k: v for k, v in context.items() if k != "history"},
            default=str,
        )
        messages: list[dict] = [
            {"role": "system", "content": ctx.system_prompt},
            {"role": "user", "content": f"Learner context: {context_str}\n\nQuery: {query}"},
        ]

        cot_chain: list[CoTStep] = []
        tool_calls: list[ToolCallRecord] = []
        side_effects: list[SideEffect] = []
        result_text = ""

        for step in range(1, self.max_steps + 1):
            step_result = await self._decide_step(messages)

            # Extract CoT steps from this iteration
            cot_chain.extend(extract_cot_steps(step_result, step))

            if "action" in step_result:
                action = step_result["action"]
                tool_name = action.get("tool", "")
                tool_args = action.get("args", {})

                tool_result = await tool_registry.call(tool_name, tool_args)
                payload = tool_result.result if tool_result.result is not None else {"error": tool_result.error}

                tool_calls.append(
                    ToolCallRecord(
                        name=tool_name,
                        args=tool_args,
                        result=payload,
                        latency_ms=tool_result.latency_ms,
                    )
                )

                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps({"thought": step_result.get("thought", ""), "action": action}),
                    }
                )
                messages.append(
                    {"role": "user", "content": f"Observation from {tool_name}: {json.dumps(payload, default=str)}"}
                )

            elif "final_answer" in step_result:
                result_text = step_result["final_answer"]
                for fx in step_result.get("side_effects", []):
                    if isinstance(fx, dict):
                        side_effects.append(SideEffect(kind=fx.get("kind", ""), payload=fx.get("payload", {})))
                break

            else:
                log.warning("subagent.unexpected_shape", agent=self.name, step=step, keys=list(step_result.keys()))
                messages.append({"role": "assistant", "content": json.dumps(step_result)})

        if not result_text:
            result_text = "I explored this thoroughly but need a slightly different angle — try rephrasing your question and I'll get you a sharper answer."

        report = AgentReport(
            agent_name=self.name,
            display_name=display_name,
            task=query,
            cot_chain=cot_chain,
            tool_calls=tool_calls,
            result=result_text,
            side_effects=side_effects,
            confidence=1.0,
            latency_ms=int((time.monotonic() - start_ms) * 1000),
        )

        return await self._middleware.apply_post(ctx, report)
