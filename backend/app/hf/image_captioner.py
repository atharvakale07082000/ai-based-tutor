import asyncio

import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()


async def caption_image(image_bytes: bytes) -> str:
    """Generate caption for image using BLIP."""
    client = get_hf_client()
    model_id = HF_MODELS["IMAGE_CAPTIONER"]["model_id"]

    log.info("image_captioner_start", image_size_bytes=len(image_bytes))

    result = await asyncio.to_thread(
        client.image_to_text,
        image_bytes,
        model=model_id,
    )

    if isinstance(result, list):
        return result[0].generated_text if result else ""
    return result.generated_text if hasattr(result, "generated_text") else str(result)
