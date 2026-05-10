"""
Spaced Repetition Scheduler — SM-2 algorithm with HuggingFace difficulty scoring.

Computes which topics are due for review based on:
  - Last quiz date per topic
  - Current Elo score (lower Elo → shorter review interval)
  - HuggingFace DIFFICULTY_SCORER for content-level calibration

Returns a prioritized list of topics and their urgency scores.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import TypedDict

import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()


class RepetitionItem(TypedDict):
    topic: str
    elo: float
    days_since_last_quiz: float
    interval_days: float
    urgency: float          # 0–1, higher = more due for review
    is_due: bool


def _elo_to_interval(elo: float) -> float:
    """
    SM-2-inspired: lower Elo → shorter interval (needs more review).
    Elo 0   → interval 1 day
    Elo 500 → interval 7 days
    Elo 1000 → interval 21 days
    """
    return max(1.0, 1.0 + (elo / 1000.0) * 20.0)


def compute_due_topics(
    topic_proficiency: dict[str, float],
    last_quiz_dates: dict[str, str],  # {topic: iso_datetime}
    now: datetime | None = None,
) -> list[RepetitionItem]:
    """
    Pure Python SM-2 scheduler — no HF call needed for scheduling logic.
    The HF difficulty scorer is used separately to calibrate new content difficulty.
    """
    now = now or datetime.now(timezone.utc)
    results: list[RepetitionItem] = []

    for topic, elo in topic_proficiency.items():
        interval = _elo_to_interval(elo)
        last_str = last_quiz_dates.get(topic)

        if last_str:
            try:
                last_dt = datetime.fromisoformat(last_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days_elapsed = (now - last_dt).total_seconds() / 86400
            except ValueError:
                days_elapsed = interval + 1  # treat as overdue
        else:
            days_elapsed = interval + 1  # never quizzed → immediately due

        overdue_ratio = days_elapsed / interval
        urgency = min(1.0, overdue_ratio)
        is_due = overdue_ratio >= 1.0

        results.append(RepetitionItem(
            topic=topic,
            elo=elo,
            days_since_last_quiz=round(days_elapsed, 1),
            interval_days=round(interval, 1),
            urgency=round(urgency, 3),
            is_due=is_due,
        ))

    return sorted(results, key=lambda x: x["urgency"], reverse=True)


async def score_content_difficulty(text: str) -> float:
    """
    Use HuggingFace cross-encoder to estimate how difficult a piece of text is.
    Returns 0.0–1.0 (higher = harder).
    """
    model_cfg = HF_MODELS["DIFFICULTY_SCORER"]
    client = get_hf_client(model_cfg["provider"])

    try:
        result = await asyncio.to_thread(
            client.text_classification,
            text,
            model=model_cfg["model_id"],
        )
        # cross-encoder returns relevance score; we invert: high relevance → lower difficulty
        score = result[0].score if result else 0.5
        return round(1.0 - score, 3)
    except Exception as e:
        log.warning("difficulty_scorer_error", error=str(e))
        return 0.5
