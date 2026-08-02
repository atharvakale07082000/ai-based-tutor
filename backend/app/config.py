"""
Application configuration loaded from environment variables and .env files.

All settings are validated at startup via Pydantic BaseSettings.
Access via the module-level `settings` singleton.
"""

import json
import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    JSON_LOGS: bool = (
        False  # False = pretty coloured console; set JSON_LOGS=true in production
    )

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

    # ── Strands agents (NVIDIA NIM via OpenAI-compatible endpoint) ───────────
    # The orchestrator routes/delegates; specialists run the per-domain agent loops.
    # Both default to the proven NVIDIA_MODEL id (Qwen3 supports native tool-calling);
    # swap via env without code changes if delegation quality disappoints.
    NIM_ORCHESTRATOR_MODEL: str = "qwen/qwen3-next-80b-a3b-instruct"
    NIM_SPECIALIST_MODEL: str = "qwen/qwen3-next-80b-a3b-instruct"

    # Ask Atelier chat memory — Strands session persistence, keyed per chat thread.
    # AGENT_SESSIONS_DIR empty → OS temp dir (fine for local/single instance; point at a
    # durable/shared volume, or swap to S3SessionManager, for multi-instance production).
    AGENT_SESSIONS_DIR: str = ""
    CHAT_MEMORY_WINDOW: int = 40  # messages kept in context per thread (SlidingWindow)
    NIM_RPM_LIMIT: int = (
        40  # NVIDIA free-tier requests/minute; token-bucket in agents.model
    )

    # Live module interview (interrupt-driven Strands agent, agents/interview_agent.py).
    # The agent asks one question per turn and decides when it has enough signal; these bound it.
    INTERVIEW_MAX_QUESTIONS: int = (
        8  # hard cap — force-conclude after this many questions
    )
    INTERVIEW_MIN_QUESTIONS: int = (
        4  # ask at least this many before the agent may conclude
    )

    # ── Quality evals (DeepEval) ─────────────────────────────────────────────
    # The DeepEval judge wraps the NVIDIA NIM client (OpenAI-compatible) — no new creds.
    EVAL_JUDGE_MODEL: str = "qwen/qwen3-next-80b-a3b-instruct"
    EVAL_THRESHOLD: float = 0.6  # default pass threshold for the DeepEval metrics
    EVALS_ONLINE_SAMPLING: bool = True  # master switch for random online eval sampling
    # Rate-limit safety: cap concurrent judge calls + bound the background eval backlog so online
    # sampling never floods the NVIDIA endpoint. Each eval metric makes several judge calls.
    EVAL_MAX_CONCURRENCY: int = 2  # max simultaneous judge (NVIDIA) calls from evals
    EVAL_MAX_PENDING: int = (
        16  # drop new eval sampling if this many eval tasks are already queued
    )
    EVAL_JUDGE_MAX_RETRIES: int = (
        4  # OpenAI-client retries (handles NVIDIA 429s with backoff)
    )
    EVAL_JUDGE_TIMEOUT_S: float = 30.0

    # Evals dashboard superuser — the only account that can view evals.
    # NO source defaults on purpose: a shipped default password is a backdoor in every environment
    # that forgets to override it. seed_superuser() is a no-op unless BOTH are set in the
    # environment, and when they are it keeps the account's password in sync with them.
    SUPERUSER_EMAIL: str = ""
    SUPERUSER_PASSWORD: str = ""

    # ── Code checking (interview compiler) ───────────────────────────────────
    # When set, code runs in the sandboxed Piston service (60+ languages). When empty, the
    # submission is reviewed by an LLM instead — there is deliberately no local-execution
    # fallback (see services/code_runner).
    PISTON_BASE_URL: str = ""  # e.g. http://piston:2000
    CODE_RUN_TIMEOUT_MS: int = 10000

    # MongoDB — the single datastore (users, sessions, progress, evals).
    # Collection names are fixed in app/db/mongo.py, not configurable.
    MONGO_URL: str = "mongodb://localhost:27017"
    MONGO_DATABASE: str = "ai_tutor_evals"

    # Redis (Celery broker + result backend)
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # User activity logging — middleware records every request to MongoDB
    ACTIVITY_LOGGING_ENABLED: bool = True

    # CORS — comma-separated list or JSON array (explicit prod origins)
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    # Any localhost/127.0.0.1 port is allowed in dev, so the frontend still works
    # when Vite falls back to another port (e.g. 5174 when 5173 is taken) — without
    # this, those origins are blocked by CORS and login/API calls silently fail.
    CORS_ORIGIN_REGEX: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    @property
    def cors_origins(self) -> list[str]:
        v = self.CORS_ORIGINS.strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def cors_origins_ws(self) -> list[str]:
        """Allowed origins for the Socket.IO server. python-socketio can't take a
        regex, so enumerate the common localhost dev ports (Vite fallbacks) next to
        the explicit origins — the WS mirror of CORS_ORIGIN_REGEX."""
        dev = [
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in (3000, 5173, 5174, 5175, 5176, 5177)
        ]
        return list(dict.fromkeys([*self.cors_origins, *dev]))

    # Email (password reset, notifications)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "Atelier AI Tutor <noreply@atelier.ai>"
    APP_BASE_URL: str = "http://localhost:5173"

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
