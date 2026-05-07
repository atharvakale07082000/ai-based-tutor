from huggingface_hub import InferenceClient
import structlog

from app.config import settings

log = structlog.get_logger()

_client_classify: InferenceClient | None = None
_client_generate: InferenceClient | None = None


def get_hf_client(provider: str = "hf-inference") -> InferenceClient:
    """Return a cached InferenceClient for the given provider.

    provider="hf-inference"  — classification / embedding tasks (free tier)
    provider="together"      — text generation / chat tasks
    """
    global _client_classify, _client_generate
    if not settings.HF_TOKEN:
        log.warning("hf_token_missing", msg="HF_TOKEN not set — inference calls will fail")

    if provider == "together":
        if _client_generate is None:
            _client_generate = InferenceClient(token=settings.HF_TOKEN, provider="together")
        return _client_generate
    else:
        if _client_classify is None:
            _client_classify = InferenceClient(token=settings.HF_TOKEN, provider="hf-inference")
        return _client_classify
