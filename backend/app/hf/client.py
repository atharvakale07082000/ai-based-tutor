from huggingface_hub import InferenceClient
import structlog

from app.config import settings

log = structlog.get_logger()

_clients: dict[str, InferenceClient] = {}


def get_hf_client(provider: str = "hf-inference") -> InferenceClient:
    """Return a cached InferenceClient for the given provider."""
    global _clients
    if not settings.HF_TOKEN:
        log.warning("hf_token_missing", msg="HF_TOKEN not set — inference calls will fail")

    if provider not in _clients:
        _clients[provider] = InferenceClient(token=settings.HF_TOKEN, provider=provider)
    return _clients[provider]
