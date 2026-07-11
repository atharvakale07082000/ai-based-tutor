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


_compiled_regexes: list[tuple[str, re.Pattern]] | None = None


def _blocked_regexes() -> list[tuple[str, re.Pattern]]:
    """Compile (and cache) the optional regex injection patterns from config."""
    global _compiled_regexes
    if _compiled_regexes is None:
        raw = _config()["input"].get("blocked_regexes", []) or []
        _compiled_regexes = [(p, re.compile(p, re.IGNORECASE)) for p in raw]
    return _compiled_regexes


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
        log.warning(
            "guardrail_input_truncated", original_len=len(text), context=context
        )

    lower = stripped.lower()
    for pattern in _blocked_patterns():
        if pattern.lower() in lower:
            log.warning("guardrail_blocked_pattern", pattern=pattern, context=context)
            return GuardrailResult(passed=False, reason=f"blocked_pattern:{pattern}")

    # Regex layer: catches injections with filler words the substring list misses
    # (e.g. "ignore all previous instructions", "reveal your system prompt").
    for raw, rx in _blocked_regexes():
        if rx.search(lower):
            log.warning("guardrail_blocked_pattern", pattern=raw, context=context)
            return GuardrailResult(passed=False, reason=f"blocked_pattern:{raw}")

    return GuardrailResult(passed=True, sanitized=stripped)


# ── Topic moderation (generation entry points) ────────────────────────────────

# Human-facing messages for a rejected topic, keyed by GuardrailResult.reason.
TOPIC_REJECT_MESSAGES = {
    "topic_empty": "Please enter a learning goal.",
    "topic_too_short": "That's too short — name a specific skill, tool, or role you want to learn.",
    "topic_not_a_subject": "That doesn't look like a learning topic — try naming a skill, tool, or role.",
    "vague_topic": "That's a bit too vague — try something specific like “SQL for data analysts” or “React fundamentals”.",
    "blocked_topic": "Atelier builds courses for professional and technical skills, so we can't create one for that topic.",
}


def topic_reject_message(reason: str) -> str:
    """Friendly message for a failed check_topic(), safe for API responses."""
    return TOPIC_REJECT_MESSAGES.get(
        reason,
        "Atelier builds courses for professional and technical skills — try naming a specific one.",
    )


def check_topic(topic: str) -> GuardrailResult:
    """
    Gate a topic/goal before any content generation (course, quiz, curriculum).

    Rejects empty, too-short, purely-vague, and explicit/off-domain topics so this
    educational-jobs platform never generates a course for something it shouldn't.
    Blocked terms match on word boundaries to avoid false positives ("assignment").
    """
    cfg = _config().get("topic", {})

    if not topic or not topic.strip():
        return GuardrailResult(passed=False, reason="topic_empty")

    t = topic.strip()
    if len(t) < cfg.get("min_length", 3):
        return GuardrailResult(passed=False, reason="topic_too_short")

    low = t.lower()
    if not re.search(r"[a-z]", low):  # numbers/symbols only — not a subject
        return GuardrailResult(passed=False, reason="topic_not_a_subject")

    words = set(re.findall(r"[a-z]+", low))
    vague = {v.lower() for v in cfg.get("vague_terms", [])}
    if words and words <= vague:  # every word is a filler token
        return GuardrailResult(passed=False, reason="vague_topic")

    for term in cfg.get("blocked_terms", []):
        if re.search(rf"\b{re.escape(term.lower())}\b", low):
            log.warning("guardrail_blocked_topic", term=term)
            return GuardrailResult(passed=False, reason="blocked_topic")

    return GuardrailResult(passed=True, sanitized=t)


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
        log.warning(
            "guardrail_output_truncated", original_len=len(text), context=context
        )
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

    if (
        not isinstance(q["options"], list)
        or len(q["options"]) < cfg["min_option_count"]
    ):
        return GuardrailResult(passed=False, reason="insufficient_options")

    if not valid_range[0] <= q["correct_index"] <= valid_range[1]:
        return GuardrailResult(passed=False, reason="invalid_correct_index")

    if not q["question"] or len(q["question"]) < cfg["min_question_length"]:
        return GuardrailResult(passed=False, reason="question_too_short")

    if bloom_level and q.get("bloom_level") != bloom_level:
        log.warning(
            "guardrail_bloom_mismatch", expected=bloom_level, got=q.get("bloom_level")
        )

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
