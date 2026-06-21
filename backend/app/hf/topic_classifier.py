"""Topic classification using zero-shot inference via the HuggingFace Inference API."""

import asyncio
import threading

import structlog
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()

CANDIDATE_LABELS = [
    "Python Programming",
    "Machine Learning",
    "Data Science",
    "Web Development",
    "Mathematics",
    "Statistics",
    "Deep Learning",
    "Natural Language Processing",
    "Computer Vision",
    "Software Engineering",
    "Cloud Computing",
    "DevOps",
]

# Topic labels are stable for a given text — 1h TTL avoids unnecessary HF API
# calls when the same topic string is classified repeatedly across sessions.
_classify_cache: TTLCache = TTLCache(maxsize=512, ttl=3600)
_classify_lock = threading.Lock()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def classify_topic(text: str, candidate_labels: list[str] | None = None) -> dict:
    """Classify text into the closest matching topic label using zero-shot classification."""
    labels = candidate_labels or CANDIDATE_LABELS
    cache_key = (text, tuple(labels))
    with _classify_lock:
        cached = _classify_cache.get(cache_key)
    if cached is not None:
        return cached

    model_cfg = HF_MODELS["TOPIC_CLASSIFIER"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]

    log.info("topic_classifier_start", text=text[:60])

    result = await asyncio.to_thread(
        client.zero_shot_classification,
        text,
        labels,
        model=model_id,
    )

    # huggingface_hub >= 1.0 returns list[ZeroShotClassificationOutputElement]
    # each element has .label (str) and .score (float)
    if isinstance(result, list):
        sorted_items = sorted(result, key=lambda x: x.score, reverse=True)
        output = {
            "labels": [item.label for item in sorted_items],
            "scores": [item.score for item in sorted_items],
        }
    else:
        # Legacy: single object with .labels and .scores lists
        output = {"labels": result.labels, "scores": result.scores}

    with _classify_lock:
        _classify_cache[cache_key] = output
    return output
