import asyncio
import json
import re
import uuid

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.hf.client import get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS
from app.prompts.loader import get_quiz_limits

log = structlog.get_logger()

_SYSTEM_PROMPT = """You are an expert quiz question generator for an AI tutoring platform.

Output ONLY a JSON object in this exact schema — no prose, no markdown fences:
{
  "question": "<full question sentence, at least 10 words>",
  "options": ["<correct answer>", "<wrong 1>", "<wrong 2>", "<wrong 3>"],
  "correct_index": 0,
  "explanation": "<one sentence why the correct answer is right>"
}

Rules:
- options must be exactly 4 real, specific answers (never placeholders like Option A)
- correct_index is always 0 (shuffle happens client-side)
- question must be directly about the specified topic
- distractors must be plausible but clearly wrong on reflection
"""

_USER_TEMPLATE = {
    "remember": "Generate a factual recall question about: {topic}.",
    "understand": "Generate a comprehension/explanation question about: {topic}. Ask the learner to explain or paraphrase the concept.",
    "apply": "Generate an application question about: {topic}. Include a real-world scenario in the question stem.",
    "analyze": "Generate an analysis question about: {topic}. The learner must identify relationships, causes, or components.",
    "evaluate": "Generate an evaluation question about: {topic}. The learner must judge, critique, or justify a design decision.",
    "create": "Generate a synthesis question about: {topic}. The learner must propose, design, or construct something.",
}


def _parse_response(text: str, topic: str, bloom_level: str) -> dict | None:
    """Extract a question dict from LLM output. Returns None if unparseable."""
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

    # Try direct JSON parse
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find first {...} block
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return None

    question = str(data.get("question", "")).strip()
    options = data.get("options", [])
    correct_index = int(data.get("correct_index", 0))
    explanation = str(data.get("explanation", f"Tests {bloom_level}-level knowledge of {topic}.")).strip()

    # Validate
    if not question or len(question) < 10:
        return None
    if not isinstance(options, list) or len(options) < 4:
        return None
    options = [str(o).strip() for o in options[:4]]
    # Reject placeholder options
    bad = {"option a", "option b", "option c", "option d", "concept a", "concept b", "a)", "b)"}
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
async def generate_quiz_questions(topic: str, bloom_level: str, count: int = 5) -> list[dict]:
    """Generate multiple-choice quiz questions for a topic at the given Bloom level via LLM."""
    model_cfg = HF_MODELS["QUIZ_GENERATOR"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]
    limits = get_quiz_limits()

    user_prompt = _USER_TEMPLATE.get(bloom_level, _USER_TEMPLATE["understand"]).format(topic=topic)
    log.info("quiz_generator_start", topic=topic, bloom_level=bloom_level, count=count)

    questions: list[dict] = []
    for i in range(count):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat_completion,
                    model=model_id,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=limits.get("max_tokens", 300),
                    temperature=limits.get("temperature", 0.7),
                ),
                timeout=40.0,
            )
            record_auth_success(model_cfg["provider"])
            text = result.choices[0].message.content or ""
            q = _parse_response(text, topic, bloom_level)
            if q:
                questions.append(q)
            else:
                log.warning("quiz_parse_failed", index=i, raw=text[:200])
        except asyncio.TimeoutError:
            log.error("quiz_generation_timeout", index=i, topic=topic)
        except Exception as e:
            err = str(e)
            if "401" in err or "403" in err:
                record_auth_failure(model_cfg["provider"])
            log.warning("quiz_generation_failed", index=i, topic=topic, error=err[:200])

    log.info("quiz_generator_done", topic=topic, generated=len(questions), requested=count)
    return questions
