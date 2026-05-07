import asyncio
import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()


async def get_embeddings(text: str) -> list[float]:
    """Get sentence embeddings from all-MiniLM-L6-v2."""
    client = get_hf_client()
    model_id = HF_MODELS["EMBEDDINGS"]["model_id"]

    log.info("embeddings_start", text=text[:60])

    result = await asyncio.to_thread(
        client.feature_extraction,
        text,
        model=model_id,
    )

    # Result may be nested for sentence transformers
    if isinstance(result, list) and isinstance(result[0], list):
        return result[0]
    return list(result) if hasattr(result, '__iter__') else []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(y ** 2 for y in b) ** 0.5
    return dot / (norm_a * norm_b + 1e-8)
