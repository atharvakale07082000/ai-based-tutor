"""
Guardrails: validate + sanitize inputs/outputs for all agents.

Design principles:
- Fast (no external calls in the hot path — pure Python checks)
- Layered: structural checks first, semantic last
- Non-blocking: returns GuardrailResult so callers decide how to handle failures
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from app.prompts.loader import get_guardrails_config

log = structlog.get_logger()


@dataclass
class GuardrailResult:
    passed: bool
    reason: str = ""
    sanitized: str = ""  # cleaned text if applicable


_cfg: dict | None = None


def _config() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = get_guardrails_config()
    return _cfg


def _blocked_patterns() -> list[str]:
    return _config()["input"]["blocked_patterns"]


# ── Input guardrails ──────────────────────────────────────────────────────────


def check_input(text: str, *, context: str = "") -> GuardrailResult:
    """
    Validate a user-supplied string before sending to any LLM.
    Checks: length bounds, blocked injection patterns.
    """
    cfg = _config()["input"]

    if not text or not text.strip():
        return GuardrailResult(passed=False, reason="empty_input")

    stripped = text.strip()

    if len(stripped) < cfg["min_length"]:
        return GuardrailResult(passed=False, reason="too_short")

    if len(stripped) > cfg["max_length"]:
        # Truncate rather than hard-reject — long but legitimate questions exist
        stripped = stripped[: cfg["max_length"]]
        log.warning("guardrail_input_truncated", original_len=len(text), context=context)

    lower = stripped.lower()
    for pattern in _blocked_patterns():
        if pattern.lower() in lower:
            log.warning("guardrail_blocked_pattern", pattern=pattern, context=context)
            return GuardrailResult(passed=False, reason=f"blocked_pattern:{pattern}")

    return GuardrailResult(passed=True, sanitized=stripped)


# ── Output guardrails ─────────────────────────────────────────────────────────


def check_output(text: str, *, context: str = "") -> GuardrailResult:
    """Validate LLM output before returning to the caller."""
    cfg = _config()["output"]

    if not text or not text.strip():
        return GuardrailResult(passed=False, reason="empty_output")

    if len(text.strip()) < cfg["min_length"]:
        return GuardrailResult(passed=False, reason="output_too_short")

    if len(text) > cfg["max_length"]:
        truncated = text[: cfg["max_length"]]
        log.warning("guardrail_output_truncated", original_len=len(text), context=context)
        return GuardrailResult(passed=True, sanitized=truncated)

    return GuardrailResult(passed=True, sanitized=text.strip())


# ── Quiz-specific guardrails ──────────────────────────────────────────────────


def check_quiz_question(q: dict, *, bloom_level: str = "") -> GuardrailResult:
    """
    Validate a single generated quiz question dict.
    Returns GuardrailResult with reason describing the first violation.
    """
    cfg = _config()["quiz"]
    required = cfg["required_fields"]
    valid_range = cfg["valid_correct_index_range"]

    missing = [f for f in required if f not in q]
    if missing:
        return GuardrailResult(passed=False, reason=f"missing_fields:{missing}")

    if not isinstance(q["options"], list) or len(q["options"]) < cfg["min_option_count"]:
        return GuardrailResult(passed=False, reason="insufficient_options")

    if not valid_range[0] <= q["correct_index"] <= valid_range[1]:
        return GuardrailResult(passed=False, reason="invalid_correct_index")

    if not q["question"] or len(q["question"]) < cfg["min_question_length"]:
        return GuardrailResult(passed=False, reason="question_too_short")

    if bloom_level and q.get("bloom_level") != bloom_level:
        log.warning("guardrail_bloom_mismatch", expected=bloom_level, got=q.get("bloom_level"))

    return GuardrailResult(passed=True)


def sanitize_quiz_batch(questions: list[dict], bloom_level: str) -> list[dict]:
    """Filter out malformed questions and log removals."""
    valid = []
    for i, q in enumerate(questions):
        result = check_quiz_question(q, bloom_level=bloom_level)
        if result.passed:
            valid.append(q)
        else:
            log.warning("guardrail_quiz_removed", index=i, reason=result.reason)
    return valid


# ── Topic grounding check ─────────────────────────────────────────────────────


def check_topic_grounding(text: str, topic: str) -> GuardrailResult:
    """
    Lightweight check: does the output mention the topic at all?
    Uses simple token overlap — not a semantic similarity call, stays fast.
    """
    if not topic:
        return GuardrailResult(passed=True)

    topic_tokens = set(re.sub(r"[^a-z0-9 ]", "", topic.lower()).split())
    text_tokens = set(re.sub(r"[^a-z0-9 ]", "", text.lower()).split())
    overlap = topic_tokens & text_tokens

    if not overlap and len(topic_tokens) > 1:
        log.warning("guardrail_no_topic_overlap", topic=topic)
        return GuardrailResult(passed=False, reason="off_topic_response")

    return GuardrailResult(passed=True)
