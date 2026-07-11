import asyncio

import structlog

from app.hf.client import get_hf_client
from app.hf.models import TOKEN_BUDGETS
from app.prompts.loader import get_section, render_prompt

log = structlog.get_logger()


def _difficulty_label(difficulty: float) -> str:
    """Convert a 0–1 difficulty float to a human-readable label."""
    if difficulty < 0.3:
        return "Beginner"
    if difficulty < 0.6:
        return "Intermediate"
    if difficulty < 0.8:
        return "Advanced"
    return "Expert"


def _fallback_body(topic: str, subtopic: str) -> str:
    """Return a placeholder body shown while AI generation is in progress."""
    return f"""\
## {subtopic}

We're putting the finishing touches on this lesson within **{topic}**.
Come back in a moment — it'll be ready and waiting for you.

## Coming Up

Your personalised content for {subtopic} is being prepared now.

## Examples

Worked examples for {subtopic} will be shown here.

## Practice

Practice exercises for {subtopic} will be listed here.

## Summary

A summary of {subtopic} will appear here once the content is fully generated.
"""


# The five sections the prompt asks for. Structural guardrail: a valid body must be
# substantial and carry most of these headings, or we retry before accepting it.
_REQUIRED_SECTIONS = (
    "introduction",
    "core concepts",
    "examples",
    "practice",
    "summary",
)
_MIN_BODY_LEN = 300


def is_valid_content(body: str) -> bool:
    """Structured check that a generated lesson body is usable (length + section headings)."""
    if not body or len(body.strip()) < _MIN_BODY_LEN:
        return False
    low = body.lower()
    hits = sum(1 for s in _REQUIRED_SECTIONS if f"## {s}" in low or f"##{s}" in low)
    return hits >= 3


async def generate_content_body(
    topic: str,
    subtopic: str,
    content_type: str,
    difficulty: float,
) -> str:
    """Generate a rich markdown body for a content item using Qwen2.5-7B-Instruct.

    Returns fully formatted markdown with five sections (Introduction, Core Concepts,
    Examples, Practice, Summary). Validates structure and retries once for a well-formed
    body; keeps real content over the skeleton, and only falls back to the skeleton if the
    model returns nothing usable. No wall-clock timeout — generation is allowed to take its
    time (bounded only by the HTTP client), so slow-but-valid output is never discarded.
    """
    client = get_hf_client(provider="together")
    model_id = "Qwen/Qwen2.5-7B-Instruct"

    user_prompt = render_prompt(
        "content_generator",
        "user",
        topic=topic,
        subtopic=subtopic,
        content_type=content_type,
        difficulty=difficulty,
        difficulty_label=_difficulty_label(difficulty),
    )
    system_prompt = get_section("content_generator", "system", "base")

    log.info(
        "content_generator_start",
        topic=topic,
        subtopic=subtopic,
        content_type=content_type,
        difficulty=difficulty,
    )

    last_body = ""
    for attempt in range(2):
        try:
            result = await asyncio.to_thread(
                client.chat_completion,
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=TOKEN_BUDGETS["content_body"],
                # Lower temperature ⇒ steadier structure across runs (consistency).
                temperature=0.4,
            )
            body = (result.choices[0].message.content or "").strip()
            if not body:
                raise ValueError("Empty response from model")
            last_body = body
            if is_valid_content(body):
                log.info(
                    "content_generator_done",
                    topic=topic,
                    subtopic=subtopic,
                    body_length=len(body),
                    attempt=attempt,
                )
                return body
            log.warning(
                "content_generator_invalid_structure",
                topic=topic,
                subtopic=subtopic,
                attempt=attempt,
                body_length=len(body),
            )
        except Exception as exc:
            log.warning(
                "content_generator_failed",
                topic=topic,
                subtopic=subtopic,
                attempt=attempt,
                error=str(exc),
            )

    # Prefer real (if imperfect) content over the placeholder skeleton.
    if last_body:
        log.warning(
            "content_generator_returning_unvalidated", topic=topic, subtopic=subtopic
        )
        return last_body
    return _fallback_body(topic, subtopic)
