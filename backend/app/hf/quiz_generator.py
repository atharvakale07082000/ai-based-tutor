import asyncio
import uuid
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS
from app.prompts.loader import get_bloom_prompt, get_quiz_limits

log = structlog.get_logger()


def _parse_quiz_response(text: str, topic: str, bloom_level: str) -> dict:
    """Parse model output into a structured question dict."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    question = f"What is a key concept in {topic}?"
    options = ["Option A", "Option B", "Option C", "Option D"]
    correct_index = 0

    for line in lines:
        if line.startswith("Q:"):
            question = line[2:].strip()
        elif line.startswith("A)"):
            options[0] = line[2:].strip()
        elif line.startswith("B)"):
            options[1] = line[2:].strip()
        elif line.startswith("C)"):
            options[2] = line[2:].strip()
        elif line.startswith("D)"):
            options[3] = line[2:].strip()
        elif "ANSWER:" in line:
            ans = line.split("ANSWER:")[-1].strip()
            correct_index = {"A": 0, "B": 1, "C": 2, "D": 3}.get(
                ans.upper()[0] if ans else "A", 0
            )

    return {
        "id": str(uuid.uuid4()),
        "question": question,
        "options": options,
        "correct_index": correct_index,
        "explanation": f"The correct answer relates to {topic} at the {bloom_level} cognitive level.",
        "bloom_level": bloom_level,
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def generate_quiz_questions(topic: str, bloom_level: str, count: int = 5) -> list[dict]:
    """
    Generate `count` quiz questions for `topic` at `bloom_level`.
    Prompts are loaded from prompts/quiz_generator.yaml.
    """
    model_cfg = HF_MODELS["QUIZ_GENERATOR"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]
    limits = get_quiz_limits()

    # Load prompt from YAML
    user_prompt = get_bloom_prompt(topic, bloom_level)
    system_prompt = (
        "You are an expert quiz question generator. "
        "Output only the question in the exact format requested, nothing else."
    )

    log.info("quiz_generator_start", topic=topic, bloom_level=bloom_level, count=count)

    questions: list[dict] = []
    for i in range(count):
        try:
            result = await asyncio.to_thread(
                client.chat_completion,
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=limits.get("max_tokens", 250),
                temperature=limits.get("temperature", 0.8),
            )
            text = result.choices[0].message.content or ""
            q = _parse_quiz_response(text, topic, bloom_level)
            questions.append(q)
        except Exception as e:
            log.warning("quiz_generation_failed", index=i, error=str(e))
            questions.append({
                "id": str(uuid.uuid4()),
                "question": f"What is a key concept in {topic}?",
                "options": ["Concept A", "Concept B", "Concept C", "Concept D"],
                "correct_index": 0,
                "explanation": f"This question tests {bloom_level}-level knowledge of {topic}.",
                "bloom_level": bloom_level,
            })

    return questions
