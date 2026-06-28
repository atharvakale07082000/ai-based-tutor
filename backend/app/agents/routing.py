"""
Shared query routing for every agent generation (v2 AgentRouter, v3 graph).

Two-phase routing:
  1. ``keyword_route`` — O(1) keyword match, no LLM call.
  2. ``llm_route`` — single classification call, used only when phase 1 ties or misses.

This module is the single source of truth: the keyword map, system prompt, and
fallback logic previously lived (duplicated, and prone to drift) in both
``agents_v2/router.py`` and ``agents_v3/graph.py``.
"""

from __future__ import annotations

import asyncio
import json
import re

import structlog

from app.hf.client import get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS, TOKEN_BUDGETS

log = structlog.get_logger()

VALID_AGENTS: set[str] = {"quiz", "curriculum", "progress", "doubt", "assistant"}

# Internal route key → user-facing product name (single source of truth for chat display).
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "doubt": "Learning Assistant",
    "quiz": "Quiz Creator",
    "curriculum": "Learning Path Builder",
    "progress": "Progress Tracker",
}

# Module-level constant — a byte-identical prefix on every routing call lets the
# provider KV cache hit without reprocessing in-flight tokens.
ROUTING_SYSTEM_PROMPT = (
    "Route the learner query to the correct agent. "
    "Agents: quiz, curriculum, progress, doubt, assistant. "
    'Reply ONLY with JSON: {"agent": "<name>", "reason": "<one sentence>"}'
)

# Keyword sets are matched as whole words (see ``_word_in``) so that, e.g.,
# "why" does not fire inside "anywhere" and short keywords don't over-trigger.
KEYWORD_MAP: dict[str, set[str]] = {
    "quiz": {"quiz", "test me", "question", "assess", "examine"},
    "curriculum": {"learn", "path", "roadmap", "curriculum", "plan my", "study plan", "learning goal"},
    "progress": {"score", "elo", "my progress", "how am i doing", "update my", "progress"},
    "doubt": {"explain", "what is", "how does", "why", "confused", "understand", "clarify", "difference between"},
}


def _word_in(keyword: str, lower_query: str) -> bool:
    """Whole-word/phrase containment test — avoids substring false positives."""
    return re.search(rf"\b{re.escape(keyword)}\b", lower_query) is not None


def keyword_route(query: str) -> tuple[str, str] | None:
    """Return ``(agent, reason)`` via O(1) keyword matching, or ``None`` on a tie/miss."""
    lower = query.lower()
    hit_counts: dict[str, list[str]] = {}
    for agent_name, keywords in KEYWORD_MAP.items():
        matched = [kw for kw in keywords if _word_in(kw, lower)]
        if matched:
            hit_counts[agent_name] = matched

    if not hit_counts:
        return None
    if len(hit_counts) == 1:
        agent = next(iter(hit_counts))
        return agent, f"keyword match: {hit_counts[agent][0]}"

    best = max(hit_counts, key=lambda a: len(hit_counts[a]))
    tied = [a for a, h in hit_counts.items() if len(h) == len(hit_counts[best])]
    if len(tied) == 1:
        return best, f"keyword match: {hit_counts[best][0]}"
    return None  # true tie — fall through to the LLM


async def llm_route(query: str) -> tuple[str, str]:
    """Single non-streaming classification call; falls back to ``assistant`` on any failure."""
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    provider = model_cfg["provider"]
    model_id = model_cfg["model_id"]
    try:
        client = get_hf_client(provider=provider)
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat_completion,
                model=model_id,
                messages=[
                    {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                max_tokens=TOKEN_BUDGETS["routing"],
                temperature=0.0,
            ),
            timeout=5.0,
        )
        record_auth_success(provider)
        # Guard against None content (NVIDIA reasoning models can leave it empty).
        raw = (response.choices[0].message.content or "").strip()
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data = json.loads(cleaned)
        agent = str(data.get("agent", "assistant")).strip().lower()
        reason = str(data.get("reason", "llm routing"))
        if agent not in VALID_AGENTS:
            return "assistant", "routing parse error: unknown agent name"
        return agent, reason
    except asyncio.TimeoutError:
        log.warning("routing_llm_timeout", query=query[:80])
        return "assistant", "routing timeout"
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.warning("routing_llm_parse_error", error=str(e), query=query[:80])
        return "assistant", "routing parse error"
    except Exception as e:
        err = str(e)
        if "401" in err or "403" in err:
            record_auth_failure(provider)
        log.error("routing_llm_error", error=err[:200])
        return "assistant", "routing error"


async def route(query: str) -> tuple[str, str]:
    """Full two-phase route: keyword first, LLM fallback only when needed."""
    return keyword_route(query) or await llm_route(query)
