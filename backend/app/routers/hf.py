import asyncio
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.auth.jwt import get_current_user_id
from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

router = APIRouter()
log = structlog.get_logger()

_model_status: dict[str, dict] = {}


async def _probe_model(model_key: str, model_id: str) -> dict:
    """Probe a model with a minimal inference call."""
    start = time.time()
    try:
        client = get_hf_client()
        task = HF_MODELS[model_key]["task"]

        if task == "text-generation":
            await asyncio.to_thread(client.text_generation, "hello", model=model_id, max_new_tokens=1)
        elif task == "text2text-generation":
            await asyncio.to_thread(client.text_generation, "hello", model=model_id, max_new_tokens=1)
        elif task == "zero-shot-classification":
            await asyncio.to_thread(client.zero_shot_classification, "hello", ["test"], model=model_id)
        elif task == "feature-extraction":
            await asyncio.to_thread(client.feature_extraction, "hello", model=model_id)
        elif task == "text-classification":
            await asyncio.to_thread(client.text_classification, "hello", model=model_id)

        latency = round((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency, "last_used": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200], "latency_ms": None, "last_used": None}


@router.get("/status")
async def hf_status(user_id: str = Depends(get_current_user_id)):
    """Return cached status for all 8 HF models."""
    return {key: _model_status.get(key, {"status": "ok", "latency_ms": None, "last_used": None}) for key in HF_MODELS}


@router.post("/test/{model_key}")
async def test_model(
    model_key: str,
    user_id: str = Depends(get_current_user_id),
):
    if model_key not in HF_MODELS:
        raise HTTPException(status_code=404, detail=f"Model key '{model_key}' not found")

    model_id = HF_MODELS[model_key]["model_id"]
    log.info("hf_test_start", model_key=model_key, model_id=model_id)

    status = await _probe_model(model_key, model_id)
    _model_status[model_key] = status

    return {
        "model_key": model_key,
        "model_id": model_id,
        "task": HF_MODELS[model_key]["task"],
        **status,
    }
