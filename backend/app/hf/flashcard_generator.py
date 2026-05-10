"""
AI Flashcard Generator — produces concise recall cards for spaced repetition.

Different from quiz: cards are shorter, term/definition format,
optimized for active recall rather than multiple-choice evaluation.
"""
from __future__ import annotations

import json
import re
import uuid

import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()


async def generate_flashcards(topic: str, count: int = 10) -> list[dict]:
    """
    Generate flashcards for a topic.
    Returns list[{id, front, back, hint, difficulty}]
    Falls back to topic-seeded cards if LLM fails.
    """
    import asyncio

    model_cfg = HF_MODELS["QUIZ_GENERATOR"]
    client = get_hf_client(model_cfg["provider"])

    prompt = f"""Generate exactly {count} flashcards for studying "{topic}".

Return ONLY a valid JSON array. No explanation. Format:
[
  {{
    "front": "What is a Python decorator?",
    "back": "A function that wraps another function to add behaviour without modifying it. Uses @syntax.",
    "hint": "Think: function wrapper",
    "difficulty": 0.4
  }},
  ...
]

Rules:
- front: a crisp question or term (max 12 words)
- back: concise answer + 1 concrete example (max 30 words)
- hint: 2-4 word memory hook
- difficulty: float 0.0 (easy) to 1.0 (hard)
- Cover a range of difficulty levels
- Vary between definition, application, and comparison cards
- No duplicate concepts
- Exactly {count} cards
Topic: {topic}"""

    try:
        result = await asyncio.to_thread(
            client.chat_completion,
            model=model_cfg["model_id"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0.6,
        )
        text = result.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            raw = json.loads(match.group())
            return [
                {
                    "id": str(uuid.uuid4()),
                    "front": str(c.get("front", ""))[:200],
                    "back": str(c.get("back", ""))[:400],
                    "hint": str(c.get("hint", ""))[:60],
                    "difficulty": float(max(0.0, min(1.0, c.get("difficulty", 0.5)))),
                    "topic": topic,
                }
                for c in raw[:count]
                if c.get("front") and c.get("back")
            ]
    except Exception as e:
        log.warning("flashcard_generator_error", topic=topic, error=str(e))

    return _fallback_cards(topic, count)


def _fallback_cards(topic: str, count: int) -> list[dict]:
    base = [
        {"front": f"What is the core concept of {topic}?",
         "back": f"{topic} is a foundational skill in modern technology. Master the basics first.",
         "hint": "Core principle", "difficulty": 0.2},
        {"front": f"Name 3 real-world uses of {topic}.",
         "back": f"{topic} is used in production systems, research, and tooling across the industry.",
         "hint": "Think practical", "difficulty": 0.4},
        {"front": f"What are common pitfalls when learning {topic}?",
         "back": "Skipping fundamentals, not practicing with real data, and ignoring documentation.",
         "hint": "Avoid shortcuts", "difficulty": 0.5},
        {"front": f"How does {topic} differ from related alternatives?",
         "back": "Each tool has trade-offs in performance, ease of use, and ecosystem maturity.",
         "hint": "Compare trade-offs", "difficulty": 0.6},
        {"front": f"Describe the key data structure used in {topic}.",
         "back": "Most domains use hierarchical, tabular, or graph structures depending on the problem.",
         "hint": "Structure first", "difficulty": 0.55},
    ]
    cards = []
    for i in range(count):
        c = base[i % len(base)].copy()
        c["id"] = str(uuid.uuid4())
        c["topic"] = topic
        cards.append(c)
    return cards[:count]
