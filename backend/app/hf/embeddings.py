import asyncio
import threading

import structlog
from cachetools import TTLCache

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()

# Embeddings are deterministic for a given model + text pair.
# 2h TTL balances memory and avoiding needless API calls for repeated topics.
_embed_cache: TTLCache = TTLCache(maxsize=1024, ttl=7200)
_embed_lock = threading.Lock()


async def get_embeddings(text: str) -> list[float]:
    """Get sentence embeddings from all-MiniLM-L6-v2, with TTL cache."""
    with _embed_lock:
        cached = _embed_cache.get(text)
    if cached is not None:
        return cached

    client = get_hf_client()
    model_id = HF_MODELS["EMBEDDINGS"]["model_id"]

    log.info("embeddings_start", text=text[:60])

    result = await asyncio.to_thread(
        client.feature_extraction,
        text,
        model=model_id,
    )

    # HF returns numpy arrays or nested lists; always coerce to native Python floats
    if hasattr(result, "ndim"):  # numpy array
        flat = result[0] if result.ndim == 2 else result
        vector = [float(x) for x in flat.tolist()]
    elif isinstance(result, list) and result and isinstance(result[0], list):
        vector = [float(x) for x in result[0]]
    else:
        vector = [float(x) for x in result] if hasattr(result, "__iter__") else []

    with _embed_lock:
        _embed_cache[text] = vector
    return vector


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity in [0, 1] between two equal-length vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x**2 for x in a) ** 0.5
    norm_b = sum(y**2 for y in b) ** 0.5
    return dot / (norm_a * norm_b + 1e-8)
