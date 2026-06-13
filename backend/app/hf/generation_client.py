"""Resilient generation client for the Qwen2.5-7B-Instruct chat agents
(doubt solver, quiz generator, supervisor, course planner, interview scorer,
content generator, agents_v2).

Primary: Hugging Face "together" provider (Qwen2.5-7B-Instruct).
Fallback: NVIDIA NIM (OpenAI-compatible) on any HF failure, rotating between
two NVIDIA models so a single bad/rate-limited model doesn't take down the
fallback path too.
"""

from __future__ import annotations

from typing import Iterator

import structlog
from huggingface_hub import InferenceClient
from openai import OpenAI

from app.config import settings

log = structlog.get_logger()


class ResilientGenerationClient:
    """Mimics `huggingface_hub.InferenceClient.chat_completion()`."""

    def __init__(self, hf_client: InferenceClient, nvidia_client: OpenAI) -> None:
        self._hf = hf_client
        self._nvidia = nvidia_client
        self._fallback_models = (settings.NVIDIA_MODEL, settings.NVIDIA_FALLBACK_MODEL)
        self._rotation = 0

    def _next_nvidia_model(self) -> str:
        model = self._fallback_models[self._rotation % len(self._fallback_models)]
        self._rotation += 1
        return model

    @staticmethod
    def _nvidia_extra_body() -> dict:
        # Disable chain-of-thought "thinking" mode so reasoning models (e.g.
        # nemotron) put the answer directly in `content` instead of consuming
        # the whole max_tokens budget on `reasoning_content` and leaving
        # `content` as None.
        return {"chat_template_kwargs": {"enable_thinking": False}}

    def chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.1,
        stream: bool = False,
    ):
        if not stream:
            try:
                return self._hf.chat_completion(
                    model=model, messages=messages, max_tokens=max_tokens, temperature=temperature
                )
            except Exception as e:
                nvidia_model = self._next_nvidia_model()
                log.warning("hf_generation_failed", error=str(e)[:200], fallback="nvidia", model=nvidia_model)
                return self._nvidia.chat.completions.create(
                    model=nvidia_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_body=self._nvidia_extra_body(),
                )

        return self._stream_with_fallback(model, messages, max_tokens, temperature)

    def _stream_with_fallback(self, model: str, messages: list[dict], max_tokens: int, temperature: float) -> Iterator:
        try:
            hf_stream = self._hf.chat_completion(
                model=model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True
            )
            first_chunk = next(hf_stream)
        except Exception as e:
            nvidia_model = self._next_nvidia_model()
            log.warning("hf_generation_stream_failed", error=str(e)[:200], fallback="nvidia", model=nvidia_model)
            return self._nvidia.chat.completions.create(
                model=nvidia_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                extra_body=self._nvidia_extra_body(),
            )

        def _resume():
            yield first_chunk
            yield from hf_stream

        return _resume()


_client: ResilientGenerationClient | None = None


def get_resilient_generation_client() -> ResilientGenerationClient:
    global _client
    if _client is None:
        if not settings.HF_TOKEN:
            log.error("hf_token_missing", msg="HF_TOKEN not set — generation calls go straight to NVIDIA fallback")
        if not settings.NVIDIA_API_KEY:
            log.error("nvidia_api_key_missing", msg="NVIDIA_API_KEY not set — fallback generation calls will fail")
        hf_client = InferenceClient(token=settings.HF_TOKEN or None, provider="together")
        nvidia_client = OpenAI(base_url=settings.NVIDIA_BASE_URL, api_key=settings.NVIDIA_API_KEY)
        _client = ResilientGenerationClient(hf_client, nvidia_client)
    return _client
