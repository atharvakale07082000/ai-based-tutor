import asyncio

import structlog
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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def classify_topic(text: str, candidate_labels: list[str] | None = None) -> dict:
    model_cfg = HF_MODELS["TOPIC_CLASSIFIER"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]
    labels = candidate_labels or CANDIDATE_LABELS

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
        return {
            "labels": [item.label for item in sorted_items],
            "scores": [item.score for item in sorted_items],
        }

    # Legacy: single object with .labels and .scores lists
    return {"labels": result.labels, "scores": result.scores}
