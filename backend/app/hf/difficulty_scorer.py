import asyncio
import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()

_DIFFICULTY_LABELS = ["beginner", "intermediate", "advanced"]
_LABEL_SCORES = {"beginner": 0.2, "intermediate": 0.5, "advanced": 0.85}


async def score_difficulty(text: str) -> float:
    """Return a difficulty score 0.0–1.0 via zero-shot classification."""
    model_cfg = HF_MODELS["DIFFICULTY_SCORER"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]

    log.info("difficulty_scorer_start", text=text[:60])

    try:
        result = await asyncio.to_thread(
            client.zero_shot_classification,
            text,
            candidate_labels=_DIFFICULTY_LABELS,
            model=model_id,
        )
        # result is a ClassificationOutput with .labels and .scores sorted by confidence
        labels = result.labels if hasattr(result, "labels") else [r["label"] for r in result]
        top_label = labels[0] if labels else "intermediate"
        return _LABEL_SCORES.get(top_label, 0.5)
    except Exception as e:
        log.warning("difficulty_scorer_error", error=str(e))
        return 0.5
