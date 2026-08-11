import asyncio
import uuid

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.json_utils import extract_json
from app.config import settings
from app.hf.client import get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS
from app.prompts.loader import get_quiz_limits, get_section, render_prompt

log = structlog.get_logger()


def _parse_response(text: str, topic: str, bloom_level: str) -> dict | None:
    """Extract a question dict from LLM output. Returns None if unparseable."""
    data = extract_json(text)
    if data is None:
        return None

    question = str(data.get("question", "")).strip()
    options = data.get("options", [])
    correct_index = int(data.get("correct_index", 0))
    explanation = str(
        data.get("explanation", f"Tests {bloom_level}-level knowledge of {topic}.")
    ).strip()

    # Validate
    if not question or len(question) < 10:
        return None
    if not isinstance(options, list) or len(options) < 4:
        return None
    options = [str(o).strip() for o in options[:4]]
    # Reject placeholder options
    bad = {
        "option a",
        "option b",
        "option c",
        "option d",
        "concept a",
        "concept b",
        "a)",
        "b)",
    }
    if any(o.lower() in bad or len(o) < 3 for o in options):
        return None
    if not 0 <= correct_index <= 3:
        correct_index = 0

    return {
        "id": str(uuid.uuid4()),
        "question": question,
        "options": options,
        "correct_index": correct_index,
        "explanation": explanation,
        "bloom_level": bloom_level,
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
async def generate_quiz_questions(
    topic: str, bloom_level: str, count: int = 5
) -> list[dict]:
    """Generate multiple-choice quiz questions for a topic at the given Bloom level via LLM."""
    model_cfg = HF_MODELS["QUIZ_GENERATOR"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]
    limits = get_quiz_limits()

    system_prompt = get_section("quiz_generator", "system", "base")
    templates = get_section("quiz_generator", "user_templates")
    user_prompt = templates.get(bloom_level, templates["understand"]).format(
        topic=topic
    )
    log.info("quiz_generator_start", topic=topic, bloom_level=bloom_level, count=count)

    questions: list[dict] = []
    for i in range(count):
        # Each question is a separate call, so without this the model converges on the same
        # question every time — feed back what's already been asked to force distinct questions.
        asked = [q["question"] for q in questions]
        turn_prompt = user_prompt
        if asked:
            turn_prompt += render_prompt(
                "quiz_generator", "dedup_suffix", asked="\n- ".join(asked[-8:])
            )
        # Up to 2 attempts per question so a single bad generation doesn't shrink the quiz.
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.chat_completion,
                        model=model_id,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": turn_prompt},
                        ],
                        max_tokens=limits.get("max_tokens", 300),
                        temperature=limits.get("temperature", 0.7),
                        # Strict JSON needs the instruct model (NVIDIA_MODEL), never the rotation's
                        # reasoning model — that one emits degenerate/looping text that won't parse.
                        response_format={"type": "json_object"},
                        pin_nvidia_model=settings.NVIDIA_MODEL,
                    ),
                    # Generous ceiling — the instruct provider can be slow under load; better to
                    # wait than to abandon the question and shrink the quiz. Still bounded so a
                    # genuinely hung connection can't block the request forever.
                    timeout=90.0,
                )
                record_auth_success(model_cfg["provider"])
                text = result.choices[0].message.content or ""
                q = _parse_response(text, topic, bloom_level)
                if q:
                    questions.append(q)
                    break
                log.warning(
                    "quiz_parse_failed", index=i, attempt=attempt, raw=text[:200]
                )
            except asyncio.TimeoutError:
                log.error("quiz_generation_timeout", index=i, topic=topic)
                break
            except Exception as e:
                err = str(e)
                if "401" in err or "403" in err:
                    record_auth_failure(model_cfg["provider"])
                log.warning(
                    "quiz_generation_failed", index=i, topic=topic, error=err[:200]
                )
                break

    log.info(
        "quiz_generator_done", topic=topic, generated=len(questions), requested=count
    )
    return questions
