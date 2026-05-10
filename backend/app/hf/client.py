from huggingface_hub import InferenceClient
import structlog

from app.config import settings

log = structlog.get_logger()

_clients: dict[str, InferenceClient] = {}


def _make_client(provider: str) -> InferenceClient:
    """
    Create an InferenceClient for the given provider.

    huggingface_hub < 0.29 does not accept the `provider` keyword.
    We try with it first and fall back to a basic client so the app
    remains functional even if the pinned version hasn't propagated yet.
    """
    token = settings.HF_TOKEN or None
    if not token:
        log.warning("hf_token_missing", msg="HF_TOKEN not set — inference calls will fail")

    try:
        return InferenceClient(token=token, provider=provider)
    except TypeError:
        # Installed huggingface_hub is older and doesn't support provider=
        log.warning(
            "hf_client_no_provider_support",
            provider=provider,
            msg="huggingface_hub<0.29 detected — upgrade to >=0.29 for provider routing",
        )
        return InferenceClient(token=token)


def get_hf_client(provider: str = "hf-inference") -> InferenceClient:
    """Return a cached InferenceClient for the given provider."""
    if provider not in _clients:
        _clients[provider] = _make_client(provider)
    return _clients[provider]


def reset_clients() -> None:
    """Clear the client cache — useful after token rotation or in tests."""
    _clients.clear()
