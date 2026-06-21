from __future__ import annotations

import asyncio
import os

import structlog
from huggingface_hub import InferenceClient

from app.config import settings

log = structlog.get_logger()

# huggingface_hub resolves tokens as: HF_TOKEN/HUGGING_FACE_HUB_TOKEN env vars,
# then the cached ~/.cache/huggingface/token file — even when an explicit
# token is passed to InferenceClient for provider-routed calls. Force the env
# vars to the token configured in .env so a stale cached token never wins.
if settings.HF_TOKEN:
    os.environ["HF_TOKEN"] = settings.HF_TOKEN
    os.environ["HUGGING_FACE_HUB_TOKEN"] = settings.HF_TOKEN

# Providers whose Qwen2.5-7B-Instruct generation calls go through the
# resilient HF-primary / NVIDIA-fallback client (see generation_client.py)
_GENERATION_PROVIDERS = {"together", "nvidia"}

_clients: dict[str, InferenceClient] = {}

# Track consecutive auth failures per provider to fail-fast early
_auth_failures: dict[str, int] = {}
_AUTH_FAILURE_THRESHOLD = 3


def _make_client(provider: str):
    """Instantiate the correct client for a provider (ResilientGenerationClient or InferenceClient)."""
    if provider in _GENERATION_PROVIDERS:
        from app.hf.generation_client import get_resilient_generation_client

        return get_resilient_generation_client()

    token = settings.HF_TOKEN or None
    if not token:
        log.error("hf_token_missing", msg="HF_TOKEN not set — ALL inference calls will fail")

    try:
        return InferenceClient(token=token, provider=provider)
    except TypeError:
        log.warning(
            "hf_client_no_provider_support",
            provider=provider,
            msg="huggingface_hub<0.29 — upgrade for provider routing",
        )
        return InferenceClient(token=token)


def get_hf_client(provider: str = "hf-inference"):
    """Return a cached InferenceClient (or ResilientGenerationClient). Resets on repeated auth failures."""
    if _auth_failures.get(provider, 0) >= _AUTH_FAILURE_THRESHOLD:
        log.error("hf_client_circuit_open", provider=provider, failures=_auth_failures[provider])
        raise RuntimeError(f"HF provider '{provider}' circuit open after {_auth_failures[provider]} auth failures")

    if provider not in _clients:
        _clients[provider] = _make_client(provider)
    return _clients[provider]


def record_auth_failure(provider: str) -> None:
    """Call this when a 401/403 is received from a provider."""
    _auth_failures[provider] = _auth_failures.get(provider, 0) + 1
    if _auth_failures[provider] >= _AUTH_FAILURE_THRESHOLD:
        _clients.pop(provider, None)
        log.error("hf_circuit_opened", provider=provider)


def record_auth_success(provider: str) -> None:
    """Call this on a successful inference to reset the failure counter."""
    if provider in _auth_failures:
        _auth_failures.pop(provider)


def reset_clients() -> None:
    """Clear the client cache — useful after token rotation or in tests."""
    _clients.clear()
    _auth_failures.clear()


async def hf_chat_completion_with_resilience(
    provider: str,
    model_id: str,
    messages: list[dict],
    max_tokens: int = 512,
    temperature: float = 0.1,
    timeout_s: float = 30.0,
) -> str:
    """
    Non-streaming HF chat completion wrapped with retry + circuit breaker.

    Returns the response text string.  Raises on permanent failure after
    exhausting retries or when the circuit breaker is open.
    """
    from app.resilience import resilient_call

    async def _call():
        """Execute a single non-streaming chat-completion attempt."""
        client = get_hf_client(provider)
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat_completion,
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            timeout=timeout_s,
        )
        record_auth_success(provider)
        return (response.choices[0].message.content or "").strip()

    try:
        return await resilient_call(
            f"hf:{provider}",
            _call,
            timeout_s=timeout_s + 5,  # outer timeout > inner to let retries fire
        )
    except Exception as exc:
        err = str(exc)
        if "401" in err or "403" in err:
            record_auth_failure(provider)
        raise
