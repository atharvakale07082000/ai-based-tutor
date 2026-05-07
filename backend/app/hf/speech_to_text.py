import asyncio
import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe audio using Whisper-large-v3."""
    client = get_hf_client()
    model_id = HF_MODELS["SPEECH_TO_TEXT"]["model_id"]

    log.info("stt_start", audio_size_bytes=len(audio_bytes))

    result = await asyncio.to_thread(
        client.automatic_speech_recognition,
        audio_bytes,
        model=model_id,
    )

    return result.text if hasattr(result, "text") else str(result)
