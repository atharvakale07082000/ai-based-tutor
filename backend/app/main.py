import asyncio
import concurrent.futures
import os
import time
import uuid
from contextlib import asynccontextmanager

import socketio
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.config import settings
from app.db.mongo import ensure_indexes, get_client
from app.logging_config import configure_logging
from app.middleware.activity_logger import ActivityLoggingMiddleware
from app.otel import current_trace_id, get_otel_tracer
from app.routers import (
    admin,
    assistant,
    auth,
    content,
    courses,
    curriculum,
    doubts,
    evals,
    feed,
    hf,
    leaderboard,
    learner,
    profile,
    progress,
    quiz,
    session,
)
from app.routers.v2 import chat as chat_v2
from app.routers.v3 import chat as chat_v3
from app.websocket import sio

# Configure structured JSON logging before the first log call.
configure_logging(log_level=settings.LOG_LEVEL, json_logs=settings.JSON_LOGS)

log = structlog.get_logger()

VERSION = "1.0.0"


async def _mongo_keepalive():
    while True:
        await asyncio.sleep(30)
        try:
            await get_client().admin.command("ping")
            log.debug("mongo_keepalive_ok")
        except Exception as exc:
            log.warning("mongo_keepalive_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise OpenTelemetry (no-op if OTEL_EXPORTER_OTLP_ENDPOINT is unset)
    get_otel_tracer()

    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=64, thread_name_prefix="ai-tutor")
    loop.set_default_executor(executor)
    log.info("thread_pool_set", max_workers=64)

    await ensure_indexes()
    log.info("mongo_indexes_ensured")

    task = asyncio.create_task(_mongo_keepalive())
    yield
    task.cancel()
    executor.shutdown(wait=False)


app = FastAPI(
    title="AI Tutor Platform API",
    version=VERSION,
    description="Multi-agent AI tutoring platform with LangGraph + Hugging Face",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ActivityLoggingMiddleware)


# Build version — set APP_VERSION env var in your deployment pipeline (e.g. git SHA).
# Changes on every deploy, which the frontend uses to detect redeploys and auto-logout.
_APP_VERSION: str = os.environ.get("APP_VERSION") or str(int(time.time()))

# ── Request correlation middleware ────────────────────────────────────────────


@app.middleware("http")
async def correlation_middleware(request: Request, call_next) -> Response:
    """
    Injects a correlation ID into every request so all log lines emitted
    during that request share the same ID, enabling full request tracing.

    Honour X-Correlation-Id from callers (useful for tracing across services);
    generate a fresh one otherwise.
    """
    correlation_id = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
    trace_id = current_trace_id()

    clear_contextvars()
    bind_contextvars(correlation_id=correlation_id, trace_id=trace_id)

    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000)

    response.headers["X-Correlation-Id"] = correlation_id
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-App-Version"] = _APP_VERSION
    # Prevent browser HTTP cache from storing API responses
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    log.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        latency_ms=latency_ms,
    )
    return response


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(learner.router, prefix="/api/v1/learner", tags=["learner"])
app.include_router(curriculum.router, prefix="/api/v1/curriculum", tags=["curriculum"])
app.include_router(content.router, prefix="/api/v1/content", tags=["content"])
app.include_router(quiz.router, prefix="/api/v1/quiz", tags=["quiz"])
app.include_router(doubts.router, prefix="/api/v1/doubts", tags=["doubts"])
app.include_router(progress.router, prefix="/api/v1/progress", tags=["progress"])
app.include_router(hf.router, prefix="/api/v1/hf", tags=["hf"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(session.router, prefix="/api/v1/session", tags=["session"])
app.include_router(evals.router, prefix="/api/v1/evals", tags=["evals"])
app.include_router(courses.router, prefix="/api/v1/courses", tags=["courses"])
app.include_router(assistant.router, prefix="/api/v1/assistant", tags=["assistant"])
app.include_router(feed.router, prefix="/api/v1/feed", tags=["feed"])
app.include_router(leaderboard.router, prefix="/api/v1/leaderboard", tags=["leaderboard"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["profile"])
app.include_router(chat_v2.router, prefix="/api/v2", tags=["v2"])
app.include_router(chat_v3.router, prefix="/api/v3", tags=["v3"])


# ── Health endpoints ──────────────────────────────────────────────────────────


@app.get("/.well-known/agent-card.json", tags=["ops"], include_in_schema=False)
async def agent_card():
    """Serve the A2A Agent Card for discovery."""
    import json
    import pathlib

    card_path = pathlib.Path(__file__).parent.parent / ".well-known" / "agent-card.json"
    card = json.loads(card_path.read_text())
    # Inject runtime base URL
    base_url = "http://0.0.0.0:8000"
    card["url"] = base_url
    from fastapi.responses import JSONResponse

    return JSONResponse(content=card)


@app.get("/health", tags=["ops"])
async def health():
    """Liveness probe — returns 200 if the process is alive."""
    return {"status": "ok", "agent": "ai-tutor", "version": VERSION}


@app.get("/ready", tags=["ops"])
async def ready():
    """
    Readiness probe — checks every downstream dependency.
    Returns 200 only when MongoDB is reachable and the HF token is configured.
    Returns 503 if any dependency is unhealthy so the load balancer can
    route traffic away from an unready instance.
    """
    checks: dict[str, str] = {}
    healthy = True

    # MongoDB
    try:
        await get_client().admin.command("ping", serverSelectionTimeoutMS=2000)
        checks["mongodb"] = "ok"
    except Exception as exc:
        checks["mongodb"] = f"error: {exc}"
        healthy = False

    # HF token present (can't call the API here, but absence guarantees failure)
    if settings.HF_TOKEN:
        checks["hf_token"] = "ok"
    else:
        checks["hf_token"] = "missing"
        healthy = False

    from fastapi.responses import JSONResponse

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if healthy else "degraded", "checks": checks, "version": VERSION},
    )


# ── Socket.IO ─────────────────────────────────────────────────────────────────

socket_app = socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="/ws")

# Run with: uvicorn app.main:socket_app --host 0.0.0.0 --port 8000 --reload
