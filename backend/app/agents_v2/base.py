"""
BaseAgent — ReAct (Reason + Act + Observe) loop over the tool registry.

Each agent subclass declares:
  name: str
  role_description: str
  tool_names: list[str]

Then overrides nothing — the loop is generic.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import AsyncIterator

import structlog

from app.hf.client import get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS
from app.tools import tool_registry

log = structlog.get_logger()

# Cap simultaneous outbound LLM calls to avoid exhausting Together API rate limits
# and the thread pool under high concurrency.  40 slots ≈ 200 concurrent users
# where each user makes 2 LLM calls, giving headroom for retries.
_HF_SEMAPHORE = asyncio.Semaphore(40)


class BaseAgent:
    name: str = "BaseAgent"
    role_description: str = ""
    tool_names: list[str] = []
    max_steps: int = 6

    def build_system_prompt(self) -> str:
        tools_desc = tool_registry.describe_tools(self.tool_names)
        return (
            f"You are {self.name}, {self.role_description}\n\n"
            f"You have access to these tools:\n{tools_desc}\n\n"
            f"INSTRUCTIONS:\n"
            f"Work step by step. Each step produce JSON with this exact structure:\n"
            f'{{"thought": "your reasoning here", "action": {{"tool": "tool_name", "args": {{...}}}}}}\n\n'
            f"When you have enough information to answer, produce:\n"
            f'{{"thought": "your final reasoning", "final_answer": "your answer here", "side_effects": [{{"kind": "...", "payload": {{...}}}}]}}\n\n'
            f"side_effects is an optional list of structured actions for the frontend "
            f"(e.g. quiz_created, plan_created, progress_updated). "
            f"Only produce side_effects when a concrete resource was created (quiz saved, progress updated).\n\n"
            f"Rules:\n"
            f"- Always produce valid JSON. No markdown fences, no extra text outside the JSON.\n"
            f"- Only use tools from the list above.\n"
            f"- Maximum {self.max_steps} steps before you must give a final_answer."
        )

    async def decide_step(self, messages: list[dict]) -> dict:
        """Non-streaming call to Qwen2.5-7B-Instruct via Together. Returns parsed JSON dict."""
        from app.hf.client import hf_chat_completion_with_resilience
        from app.resilience import CircuitOpenError

        model_cfg = HF_MODELS["DOUBT_SOLVER"]
        provider = model_cfg["provider"]
        model_id = model_cfg["model_id"]

        try:
            async with _HF_SEMAPHORE:
                raw = await hf_chat_completion_with_resilience(
                    provider=provider,
                    model_id=model_id,
                    messages=messages,
                    max_tokens=300,
                    temperature=0.1,
                    timeout_s=20.0,
                )

            cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            return json.loads(cleaned)

        except (asyncio.TimeoutError, CircuitOpenError) as e:
            log.error("base_agent_decide_timeout", agent=self.name, error=str(e)[:100])
            return {
                "thought": "Request timed out or service unavailable",
                "final_answer": "I'm taking longer than expected — go ahead and send your question again and I'll come back quickly.",
                "side_effects": [],
            }
        except json.JSONDecodeError as e:
            log.error("base_agent_decide_parse_error", agent=self.name, error=str(e))
            return {
                "thought": "parse error",
                "final_answer": "I got a bit tangled up there — let me try that again with a fresh approach.",
                "side_effects": [],
            }
        except Exception as e:
            err = str(e)
            if "401" in err or "403" in err:
                record_auth_failure(provider)
            log.error("base_agent_decide_error", agent=self.name, error=err[:200])
            return {
                "thought": "unexpected error",
                "final_answer": "Something unexpected happened on my end — please send your question again and I'll pick right up.",
                "side_effects": [],
            }

    async def stream_final_answer(
        self,
        final_answer: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Stream the final answer token by token using Qwen via Together."""
        model_cfg = HF_MODELS["DOUBT_SOLVER"]
        provider = model_cfg["provider"]
        model_id = model_cfg["model_id"]

        stream_messages = [
            {
                "role": "system",
                "content": (
                    f"You are {self.name}, a warm and knowledgeable tutor. "
                    f"Deliver this answer conversationally — like a brilliant friend explaining something. "
                    f"Use markdown: **bold** for key terms, `code` for code, numbered lists for steps. "
                    f"Keep paragraphs short. Never say 'Certainly!' or 'Great question!'. Just answer directly and warmly."
                ),
            },
            {"role": "user", "content": final_answer},
        ]

        def _sync_stream():
            client = get_hf_client(provider=provider)
            return client.chat_completion(
                model=model_id,
                messages=stream_messages,
                max_tokens=600,
                stream=True,
                temperature=0.4,
            )

        try:
            async with _HF_SEMAPHORE:
                stream = await asyncio.wait_for(
                    asyncio.to_thread(_sync_stream),
                    timeout=45.0,
                )
            record_auth_success(provider)
        except asyncio.TimeoutError:
            log.error("base_agent_stream_timeout", agent=self.name)
            yield "I'm taking a bit longer than usual — go ahead and ask again and I'll come back quickly."
            return
        except Exception as e:
            err = str(e)
            if "401" in err or "403" in err:
                record_auth_failure(provider)
            log.error("base_agent_stream_error", agent=self.name, error=err[:200])
            yield "Something interrupted my answer — please send your question once more and I'll get it right."
            return

        token_count = 0
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
                    token_count += 1
        except Exception as e:
            log.error("base_agent_stream_chunk_error", agent=self.name, error=str(e), tokens=token_count)

    async def run(
        self,
        query: str,
        context: dict,
    ) -> AsyncIterator[dict]:
        """
        Full ReAct loop. Async generator that yields AgentEvent dicts.
        Stores context as self._current_context so subclasses can access it
        in overridden methods (e.g. DoubtAgent.stream_final_answer).
        """
        query = query.strip()
        if not query:
            yield {"type": "error", "message": "Query cannot be empty."}
            return
        if len(query) > 2000:
            query = query[:2000]
            log.warning("base_agent_query_truncated", agent=self.name)

        self._current_context = context
        start_time = time.monotonic()

        system_prompt = self.build_system_prompt()
        context_str = json.dumps(
            {k: v for k, v in context.items() if k != "history"},
            default=str,
        )
        user_content = f"Learner context: {context_str}\n\nQuery: {query}"

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        for step in range(self.max_steps):
            step_num = step + 1

            step_result = await self.decide_step(messages)

            thought = step_result.get("thought", "")
            yield {"type": "thought", "step": step_num, "content": thought}

            if "action" in step_result:
                action = step_result["action"]
                tool_name = action.get("tool", "")
                tool_args = action.get("args", {})

                yield {
                    "type": "tool_call",
                    "step": step_num,
                    "name": tool_name,
                    "args": tool_args,
                }

                tool_result = await tool_registry.call(tool_name, tool_args)

                result_payload = tool_result.result if tool_result.result is not None else {"error": tool_result.error}
                yield {
                    "type": "tool_result",
                    "step": step_num,
                    "name": tool_result.name,
                    "result": result_payload,
                    "latency_ms": tool_result.latency_ms,
                }

                # Append assistant message (thought + action) and observation to messages
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps({"thought": thought, "action": action}),
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": f"Observation from {tool_name}: {json.dumps(result_payload, default=str)}",
                    }
                )

            elif "final_answer" in step_result:
                final_answer = step_result["final_answer"]

                async for token in self.stream_final_answer(final_answer, messages):
                    yield {"type": "token", "content": token}

                for effect in step_result.get("side_effects", []):
                    yield {
                        "type": "action",
                        "kind": effect.get("kind", ""),
                        "payload": effect.get("payload", {}),
                    }

                total_ms = int((time.monotonic() - start_time) * 1000)
                yield {"type": "done", "steps": step_num, "total_ms": total_ms}
                return

            else:
                # Unexpected response shape — treat as final answer with error
                log.warning(
                    "base_agent_unexpected_step_shape", agent=self.name, step=step_num, keys=list(step_result.keys())
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(step_result),
                    }
                )

        # Exhausted max_steps without a final_answer
        yield {"type": "error", "message": "Agent reached max steps without completing."}
