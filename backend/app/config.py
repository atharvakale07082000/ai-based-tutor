import json
import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    JSON_LOGS: bool = True

    # JWT
    SECRET_KEY: str = "change-this-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Hugging Face
    HF_TOKEN: str = ""

    # NVIDIA NIM (OpenAI-compatible) — fallback for generation agents (doubt
    # solver, quiz generator, supervisor, course planner, interview scorer,
    # content generator) when the primary HF "together" provider call fails.
    # The two models are rotated on successive fallbacks.
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL: str = "qwen/qwen3-next-80b-a3b-instruct"
    NVIDIA_FALLBACK_MODEL: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

    # MongoDB — primary datastore + evals storage
    MONGO_URL: str = "mongodb://localhost:27017"
    MONGO_DATABASE: str = "ai_tutor_evals"
    MONGO_COLLECTION_EVALS: str = "agent_evals"

    # Redis (Celery broker + result backend)
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # User activity logging — middleware records every request to MongoDB
    ACTIVITY_LOGGING_ENABLED: bool = True

    # CORS — comma-separated list or JSON array
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        v = self.CORS_ORIGINS.strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]

    # Langfuse — leave empty to disable tracing
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # OpenTelemetry — leave empty to disable OTLP export
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "ai-tutor"
    OTEL_ENABLED: str = "true"

    # Resilience tunables (see app/resilience.py)
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_BASE_DELAY_S: float = 1.0
    RETRY_MAX_DELAY_S: float = 16.0
    CB_FAILURE_THRESHOLD: int = 5
    CB_WINDOW_S: float = 60.0
    CB_RECOVERY_S: float = 30.0

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


settings = Settings()

# ── Startup safety checks ─────────────────────────────────────────────────────

if "change-this" in settings.SECRET_KEY and settings.is_production:
    raise RuntimeError("SECRET_KEY must be changed before deploying to production")

if not settings.HF_TOKEN and settings.is_production:
    warnings.warn(
        "HF_TOKEN is not set — all AI inference calls will fail in production",
        stacklevel=1,
    )

if settings.MONGO_URL == "mongodb://localhost:27017" and settings.is_production:
    warnings.warn(
        "MONGO_URL points to localhost in production — set it to your Atlas URI",
        stacklevel=1,
    )
