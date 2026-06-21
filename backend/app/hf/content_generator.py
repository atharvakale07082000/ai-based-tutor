import asyncio

import structlog

from app.hf.client import get_hf_client

log = structlog.get_logger()

_SYSTEM_PROMPT = "You are an expert technical educator. Generate comprehensive, detailed course content in markdown."

_USER_TEMPLATE = """\
Generate detailed course content for the following:

Topic: {topic}
Subtopic: {subtopic}
Content type: {content_type}
Difficulty level: {difficulty_label} ({difficulty:.2f}/1.0)

Write exactly five sections using the headings and depth described below:

## Introduction
Write 3-4 paragraphs explaining what this subtopic is, why it matters, and what prerequisites the learner should have.

## Core Concepts
Provide a detailed explanation of the key concepts with definitions, bullet points, and code examples in ```python``` blocks where appropriate.

## Examples
Give 2-3 fully worked examples with code, explaining each step clearly.

## Practice
Provide 3-5 practice exercises with clear instructions. Include starter code where useful.

## Summary
List the key takeaways, summarise what was learned, and suggest what to study next.
"""


def _difficulty_label(difficulty: float) -> str:
    if difficulty < 0.3:
        return "Beginner"
    if difficulty < 0.6:
        return "Intermediate"
    if difficulty < 0.8:
        return "Advanced"
    return "Expert"


def _fallback_body(topic: str, subtopic: str) -> str:
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

    user_prompt = _USER_TEMPLATE.format(
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
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
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
