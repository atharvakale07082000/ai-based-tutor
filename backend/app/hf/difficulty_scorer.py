import asyncio
import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()


async def score_difficulty(text: str) -> float:
    """Return a difficulty score 0.0–1.0 using ms-marco cross-encoder."""
    client = get_hf_client()
    model_id = HF_MODELS["DIFFICULTY_SCORER"]["model_id"]

    log.info("difficulty_scorer_start", text=text[:60])

    try:
        result = await asyncio.to_thread(
            client.text_classification,
            text,
            model=model_id,
        )
        # Cross-encoder returns relevance score; we normalize to 0-1
        items = result if isinstance(result, list) else [result]
        score = items[0].score if hasattr(items[0], "score") else 0.5
        return min(max(float(score), 0.0), 1.0)
    except Exception as e:
        log.warning("difficulty_scorer_error", error=str(e))
        return 0.5
