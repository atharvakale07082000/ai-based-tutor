import asyncio

import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()


async def analyze_sentiment(text: str) -> dict:
    """Analyze sentiment using DistilBERT-SST-2. Returns {'label': 'POSITIVE'/'NEGATIVE', 'score': float}."""
    model_cfg = HF_MODELS["SENTIMENT"]
    client = get_hf_client(provider=model_cfg["provider"])
    model_id = model_cfg["model_id"]

    log.info("sentiment_start", text=text[:80])

    result = await asyncio.to_thread(
        client.text_classification,
        text,
        model=model_id,
    )

    # huggingface_hub >= 1.0 returns list[TextClassificationOutputElement]
    items = result if isinstance(result, list) else [result]
    if items:
        # Pick highest-score label
        best = max(items, key=lambda x: x.score)
        return {"label": best.label.upper(), "score": float(best.score)}
    return {"label": "NEUTRAL", "score": 0.5}
