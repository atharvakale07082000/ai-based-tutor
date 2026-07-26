"""
Readiness reporting — mounted at /health.

Complements the two probes defined in app/main.py:
  GET /health        → liveness only ("is the process up?")
  GET /ready         → load-balancer probe: 200 when ready, 503 when not
  GET /health/ready  → this module: always 200, returns the *detail* of why

Operators and the deploy pipeline use /health/ready to see which dependency is
missing without having to read a 503 body. It never raises and never returns
secret values — credentials are reported as booleans only.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from app.config import settings
from app.db.mongo import get_client

router = APIRouter()
log = structlog.get_logger()

# Keep this well under a load balancer's probe timeout — a readiness check that
# hangs is worse than one that reports `false`.
_MONGO_PING_TIMEOUT_MS = 2000


async def mongo_reachable() -> bool:
    """Ping MongoDB with a short timeout. Never raises — returns False on any failure."""
    try:
        await get_client().admin.command(
            "ping", serverSelectionTimeoutMS=_MONGO_PING_TIMEOUT_MS
        )
        return True
    except Exception as exc:  # noqa: BLE001 - a readiness probe must never propagate
        log.warning("readiness_mongo_unreachable", error=str(exc)[:200])
        return False


async def readiness_report() -> dict:
    """
    Build the readiness report. Booleans only — never the credential values.

    `ready` is the conjunction of every check: the app cannot serve a single
    agent turn without MongoDB plus the NVIDIA NIM key, and generation flows
    need the HF token.
    """
    checks = {
        "mongodb": await mongo_reachable(),
        "nvidia_api_key": bool(settings.NVIDIA_API_KEY),
        "hf_token": bool(settings.HF_TOKEN),
    }
    return {"ready": all(checks.values()), "checks": checks}


@router.get("/ready", tags=["ops"])
async def ready() -> dict:
    """
    Readiness detail — always 200 so the body is readable even when not ready.

    Use `GET /ready` (root) for the 200/503 probe a load balancer can act on.
    """
    return await readiness_report()
