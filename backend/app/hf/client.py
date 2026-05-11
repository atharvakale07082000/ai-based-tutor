from __future__ import annotations

from huggingface_hub import InferenceClient
import structlog

from app.config import settings

log = structlog.get_logger()

_clients: dict[str, InferenceClient] = {}

# Track consecutive auth failures per provider to fail-fast early
_auth_failures: dict[str, int] = {}
_AUTH_FAILURE_THRESHOLD = 3


def _make_client(provider: str) -> InferenceClient:
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


def get_hf_client(provider: str = "hf-inference") -> InferenceClient:
    """Return a cached InferenceClient. Resets on repeated auth failures."""
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
        # Force re-creation on next call
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
