import asyncio
from typing import AsyncIterator

import structlog

from app.hf.client import get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS
from app.hf.utils import truncate_history
from app.prompts.loader import get_doubt_limits, get_system_prompt

log = structlog.get_logger()

# Hard cap on tokens streamed back to prevent runaway responses
_MAX_STREAM_TOKENS = 800


async def stream_doubt_response(
    question: str,
    context: str = "",
    history: list[dict] | None = None,
    bloom_level: str = "",
) -> AsyncIterator[str]:
    """
    Stream Qwen2.5-7B response token by token via Together provider.
    History is truncated before sending to stay within token budget.
    """
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    provider = model_cfg["provider"]
    client = get_hf_client(provider=provider)
    model_id = model_cfg["model_id"]
    limits = get_doubt_limits()
    history = history or []

    system_content = get_system_prompt(
        "doubt_solver",
        topic_context=context or "General",
        bloom_level=bloom_level or "understand",
        curriculum_context="",
    )

    messages = [{"role": "system", "content": system_content}]
    for msg in truncate_history(history, max_turns=limits.get("max_history_turns", 6)):
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": question[:1200]})

    log.info("doubt_solver_stream", question=question[:80], context=context)

    async def _generate() -> AsyncIterator[str]:
        def _sync_stream():
            return client.chat_completion(
                model=model_id,
                messages=messages,
                max_tokens=limits.get("max_tokens", 512),
                stream=True,
                temperature=limits.get("temperature", 0.7),
            )

        try:
            stream = await asyncio.wait_for(asyncio.to_thread(_sync_stream), timeout=45.0)
            record_auth_success(provider)
        except asyncio.TimeoutError:
            log.error("doubt_solver_timeout", question=question[:60])
            yield "Sorry, the response timed out. Please try again."
            return
        except Exception as e:
            err = str(e)
            if "401" in err or "403" in err:
                record_auth_failure(provider)
            log.error("doubt_solver_stream_error", error=err)
            yield "An error occurred. Please try again."
            return

        token_count = 0
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
                    token_count += 1
                    if token_count >= _MAX_STREAM_TOKENS:
                        log.warning("doubt_solver_stream_capped", tokens=token_count)
                        break
        except Exception as e:
            log.error("doubt_solver_chunk_error", error=str(e), tokens_so_far=token_count)

    return _generate()
