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


async def generate_content_body(
    topic: str,
    subtopic: str,
    content_type: str,
    difficulty: float,
) -> str:
    """Generate a rich markdown body for a content item using Qwen2.5-7B-Instruct.

    Returns fully formatted markdown with five sections (Introduction, Core Concepts,
    Examples, Practice, Summary). Falls back to a minimal skeleton on any error.
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

    log.info(
        "content_generator_start",
        topic=topic,
        subtopic=subtopic,
        content_type=content_type,
        difficulty=difficulty,
    )

    try:
        result = await asyncio.to_thread(
            client.chat_completion,
            model=model_id,
            messages=[
                {
                    "role": "system",
                    "content": get_section("content_generator", "system", "base"),
                },
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=TOKEN_BUDGETS["content_body"],
            temperature=0.6,
        )
        body = (result.choices[0].message.content or "").strip()
        if not body:
            raise ValueError("Empty response from model")

        log.info(
            "content_generator_done",
            topic=topic,
            subtopic=subtopic,
            body_length=len(body),
        )
        return body

    except Exception as exc:
        log.warning(
            "content_generator_failed",
            topic=topic,
            subtopic=subtopic,
            error=str(exc),
        )
        return _fallback_body(topic, subtopic)
