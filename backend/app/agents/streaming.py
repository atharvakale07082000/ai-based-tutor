"""
Shared real-time token streaming for final agent answers.

``stream_answer`` yields tokens as the model produces them (genuine streaming),
rather than chunking a precomputed string with artificial sleeps. If streaming
fails it falls back to the already-computed answer so the user never sees nothing.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import AsyncIterator

import structlog

from app.hf.client import HF_SEMAPHORE, get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS

log = structlog.get_logger()


@lru_cache(maxsize=16)
def _stream_system_prompt(agent_name: str) -> str:
    """Conversational delivery prompt, cached per agent display name."""
    return (
        f"You are {agent_name}, a warm and knowledgeable tutor. "
        "Deliver this answer conversationally — like a brilliant friend explaining something. "
        "Use markdown: **bold** for key terms, `code` for code, numbered lists for steps. "
        "Keep paragraphs short. Never say 'Certainly!' or 'Great question!'. Just answer directly and warmly."
    )


async def stream_answer(agent_name: str, answer: str, *, max_tokens: int = 600) -> AsyncIterator[str]:
    """Stream a polished version of ``answer`` token-by-token via the Qwen model.

    On timeout or error, yields the precomputed ``answer`` once so the caller still
    delivers a complete response.
    """
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    provider = model_cfg["provider"]
    model_id = model_cfg["model_id"]
    stream_messages = [
        {"role": "system", "content": _stream_system_prompt(agent_name)},
        {"role": "user", "content": answer},
    ]

    def _sync_stream():
        """Open the blocking streaming completion in a worker thread."""
        client = get_hf_client(provider=provider)
        return client.chat_completion(
            model=model_id,
            messages=stream_messages,
            max_tokens=max_tokens,
            stream=True,
            temperature=0.4,
        )

    try:
        async with HF_SEMAPHORE:
            stream = await asyncio.wait_for(asyncio.to_thread(_sync_stream), timeout=45.0)
        record_auth_success(provider)
    except asyncio.TimeoutError:
        log.error("stream_answer_timeout", agent=agent_name)
        yield answer
        return
    except Exception as e:
        err = str(e)
        if "401" in err or "403" in err:
            record_auth_failure(provider)
        log.error("stream_answer_error", agent=agent_name, error=err[:200])
        yield answer
        return

    streamed_any = False
    try:
        for chunk in stream:
            if not chunk.choices:  # NVIDIA emits empty-choices usage chunks
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                streamed_any = True
                yield delta
    except Exception as e:
        log.error("stream_answer_chunk_error", agent=agent_name, error=str(e)[:200])

    if not streamed_any:
        # Stream produced nothing usable — deliver the precomputed answer.
        yield answer
