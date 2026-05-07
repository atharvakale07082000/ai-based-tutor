import asyncio
from typing import AsyncIterator
import structlog

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS
from app.prompts.loader import get_system_prompt, get_doubt_limits

log = structlog.get_logger()


async def stream_doubt_response(
    question: str,
    context: str = "",
    history: list[dict] | None = None,
    bloom_level: str = "",
) -> AsyncIterator[str]:
    """
    Stream Qwen2.5-7B response token by token via Together provider.
    System prompt and limits are loaded from prompts/doubt_solver.yaml.
    """
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    client = get_hf_client(provider=model_cfg["provider"])
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
    max_turns = limits.get("max_history_turns", 6)
    for msg in history[-max_turns:]:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": question})

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

        stream = await asyncio.to_thread(_sync_stream)
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return _generate()
