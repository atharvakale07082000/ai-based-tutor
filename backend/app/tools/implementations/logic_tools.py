"""
Pure-logic tool implementations.

No I/O, no external calls — just CPU-bound functions wrapped as async handlers.
"""
from __future__ import annotations

import structlog

from app.tools.schemas import Tool

log = structlog.get_logger()


# ── Handlers ──────────────────────────────────────────────────────────────────

async def _calculate_elo(
    current_elo: float,
    score: float,
    expected_score: float = 0.5,
) -> dict:
    from app.agents.progress_agent import calculate_elo_update
    new_elo = calculate_elo_update(current_elo, score, expected_score)
    log.info(
        "calculate_elo_done",
        current_elo=current_elo,
        new_elo=new_elo,
        delta=new_elo - current_elo,
    )
    return {
        "old_elo": current_elo,
        "new_elo": new_elo,
        "delta": new_elo - current_elo,
    }


async def _check_guardrail(text: str) -> dict:
    from app.guardrails import check_input
    result = check_input(text)
    return {
        "passed": result.passed,
        "reason": result.reason,
        "sanitized": result.sanitized,
    }


# ── Tool descriptors ──────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="calculate_elo",
        description="Calculate updated Elo score after a quiz attempt using K-factor formula",
        parameters={
            "type": "object",
            "properties": {
                "current_elo": {
                    "type": "number",
                    "description": "current Elo 0-1000",
                },
                "score": {
                    "type": "number",
                    "description": "quiz score 0.0-1.0",
                },
                "expected_score": {
                    "type": "number",
                    "default": 0.5,
                },
            },
            "required": ["current_elo", "score"],
        },
        handler=_calculate_elo,
        category="logic",
        timeout_s=1.0,
    ),
    Tool(
        name="check_guardrail",
        description="Check if text passes safety guardrails (blocks injection, inappropriate content)",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        },
        handler=_check_guardrail,
        category="logic",
        timeout_s=1.0,
    ),
]
