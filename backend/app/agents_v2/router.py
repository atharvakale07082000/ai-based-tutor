"""
AgentRouter — fast rule-based keyword routing with LLM fallback.

Phase 1: keyword matching (O(1), no LLM call).
Phase 2: LLM fallback only when Phase 1 yields no confident match.
"""

from __future__ import annotations

import asyncio
import json
import re

import structlog

from app.hf.client import get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS

log = structlog.get_logger()


class AgentRouter:
    _KEYWORD_MAP: dict[str, set[str]] = {
        "quiz": {"quiz", "test me", "question", "assess", "examine"},
        "curriculum": {"learn", "path", "roadmap", "curriculum", "plan my", "study plan", "learning goal"},
        "progress": {"score", "elo", "my progress", "how am i doing", "update my", "progress"},
        "doubt": {"explain", "what is", "how does", "why", "confused", "understand", "clarify", "difference between"},
    }

    async def route(self, query: str, context: dict | None = None) -> tuple[str, str]:
        """
        Returns (agent_name, reason).

        Phase 1: keyword matching.
          - Count how many keywords from each agent's set appear in the lowercased query.
          - If exactly one agent has matches (or one dominates), return it.
        Phase 2: LLM fallback when Phase 1 gives no confident result.
        """
        lower_query = query.lower()

        # Count keyword hits per agent
        hit_counts: dict[str, list[str]] = {}
        for agent_name, keywords in self._KEYWORD_MAP.items():
            matched = [kw for kw in keywords if kw in lower_query]
            if matched:
                hit_counts[agent_name] = matched

        if hit_counts:
            if len(hit_counts) == 1:
                # Exactly one agent matched
                agent_name = next(iter(hit_counts))
                matched_word = hit_counts[agent_name][0]
                return agent_name, f"keyword match: {matched_word}"

            # Multiple agents matched — prefer the one with the most hits
            best_agent = max(hit_counts, key=lambda a: len(hit_counts[a]))
            best_count = len(hit_counts[best_agent])
            # Check for a tie
            tied = [a for a, hits in hit_counts.items() if len(hits) == best_count]
            if len(tied) == 1:
                matched_word = hit_counts[best_agent][0]
                return best_agent, f"keyword match: {matched_word}"
            # True tie — fall through to LLM

        # Phase 2: LLM fallback
        return await self._llm_route(query)

    async def _llm_route(self, query: str) -> tuple[str, str]:
        """Single non-streaming Qwen call to classify the query."""
        model_cfg = HF_MODELS["DOUBT_SOLVER"]
        provider = model_cfg["provider"]
        model_id = model_cfg["model_id"]

        system_content = (
            "You route user queries to the correct agent. "
            "Agents: quiz, curriculum, progress, doubt, assistant. "
            'Reply ONLY with JSON: {"agent": "name", "reason": "one sentence"}'
        )

        try:
            client = get_hf_client(provider=provider)
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat_completion,
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": query},
                    ],
                    max_tokens=60,
                    temperature=0.0,
                ),
                timeout=5.0,
            )
            record_auth_success(provider)
            raw = response.choices[0].message.content.strip()

            # Strip markdown fences if present
            cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            data = json.loads(cleaned)
            agent = str(data.get("agent", "assistant")).strip().lower()
            reason = str(data.get("reason", "llm routing"))

            valid_agents = {"quiz", "curriculum", "progress", "doubt", "assistant"}
            if agent not in valid_agents:
                agent = "assistant"
                reason = "routing parse error: unknown agent name"

            return agent, reason

        except asyncio.TimeoutError:
            log.warning("agent_router_llm_timeout", query=query[:80])
            return "assistant", "routing timeout"
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            log.warning("agent_router_llm_parse_error", error=str(e), query=query[:80])
            return "assistant", "routing parse error"
        except Exception as e:
            err = str(e)
            if "401" in err or "403" in err:
                record_auth_failure(provider)
            log.error("agent_router_llm_error", error=err[:200])
            return "assistant", "routing error"
