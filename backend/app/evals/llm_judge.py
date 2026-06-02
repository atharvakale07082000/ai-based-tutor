"""
LLM-as-judge: scores agent outputs against a structured rubric.

Uses the same HF Together client as the supervisor — no new credentials needed.
Falls back to 0.5 per criterion on any failure so evals never crash a test run.
"""
from __future__ import annotations
import asyncio
import json
import re
import structlog

log = structlog.get_logger()

_MODEL = "Qwen/Qwen2.5-7B-Instruct"
_TIMEOUT = 20.0

_SYSTEM_PROMPT = """\
You are an impartial educational quality assessor.
Given the context below, rate it on each criterion from 1 (very poor) to 5 (excellent).
Reply ONLY with compact JSON mapping each criterion name to an integer score.
Example output: {"correctness": 4, "clarity": 3}
Do not include any explanation or extra text."""


async def score(
    user_prompt: str,
    criteria: list[str],
    *,
    timeout: float = _TIMEOUT,
) -> dict[str, float]:
    """
    Ask the LLM judge to score `user_prompt` on each criterion.

    Returns per-criterion normalized scores in [0.0, 1.0] (mapped from 1–5 scale).
    Falls back to 0.5 for each criterion if the LLM is unavailable or times out.
    """
    fallback = {c: 0.5 for c in criteria}
    try:
        from app.hf.client import get_hf_client
        client = get_hf_client("together")
        criteria_lines = "\n".join(f"- {c}" for c in criteria)
        full_prompt = f"{user_prompt}\n\nRate on these criteria (1–5 each):\n{criteria_lines}"

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat_completion,
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": full_prompt},
                ],
                max_tokens=120,
                temperature=0.0,
            ),
            timeout=timeout,
        )
        raw = response.choices[0].message.content.strip()
        return _parse_scores(raw, criteria)

    except asyncio.TimeoutError:
        log.warning("llm_judge_timeout")
        return fallback
    except Exception as e:
        log.warning("llm_judge_failed", error=str(e)[:200])
        return fallback


def _parse_scores(raw: str, criteria: list[str]) -> dict[str, float]:
    """Parse JSON from LLM output and normalize each score from [1–5] to [0.0–1.0]."""
    try:
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().removesuffix("```").strip()
        data = json.loads(cleaned)
        result: dict[str, float] = {}
        for c in criteria:
            val = float(data.get(c, 3))        # default to mid-scale if key missing
            result[c] = max(0.0, min(1.0, (val - 1) / 4))  # [1–5] → [0.0–1.0]
        return result
    except Exception:
        return {c: 0.5 for c in criteria}
