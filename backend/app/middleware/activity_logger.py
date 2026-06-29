"""
ActivityLoggingMiddleware — records every authenticated API request to the
`activity_logs` MongoDB collection for the Profile > Activity page.

Designed to add (close to) zero latency to the response path:
- Skips docs/health/static paths entirely.
- Only reads the request body for small `application/json` payloads, and
  only to capture a short excerpt for the log entry.
- The Mongo insert itself is fire-and-forget (`asyncio.create_task`), wrapped
  in try/except so a slow/unreachable Mongo never delays or breaks a request.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime, timezone

import structlog
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.db.mongo import col_activity_logs

log = structlog.get_logger()

_SKIP_PATHS = {"/docs", "/redoc", "/openapi.json", "/health", "/ready", "/favicon.ico"}

# Ordered (method, path-pattern, friendly action name). First match wins, so
# more specific patterns are listed before more general ones.
_ACTION_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("POST", re.compile(r"^/api/v1/auth/login$"), "Logged In"),
    ("POST", re.compile(r"^/api/v1/auth/refresh$"), "Refreshed Session"),
    ("POST", re.compile(r"^/api/v1/auth/logout$"), "Logged Out"),
    ("GET", re.compile(r"^/api/v1/learner/profile$"), "Viewed Learner Profile"),
    ("PUT", re.compile(r"^/api/v1/learner/profile$"), "Updated Learner Profile"),
    ("POST", re.compile(r"^/api/v1/learner/onboard$"), "Completed Onboarding"),
    ("POST", re.compile(r"^/api/v1/curriculum/generate$"), "Generated Curriculum"),
    ("GET", re.compile(r"^/api/v1/curriculum/graph$"), "Viewed Curriculum Graph"),
    ("GET", re.compile(r"^/api/v1/curriculum$"), "Viewed Curriculum"),
    ("POST", re.compile(r"^/api/v1/content/[^/]+/regenerate$"), "Regenerated Content"),
    ("GET", re.compile(r"^/api/v1/content/[^/]+$"), "Viewed Content Item"),
    ("GET", re.compile(r"^/api/v1/content$"), "Browsed Content"),
    ("POST", re.compile(r"^/api/v1/quiz/generate$"), "Generated Quiz"),
    ("GET", re.compile(r"^/api/v1/quiz/flashcards$"), "Generated Flashcards"),
    ("POST", re.compile(r"^/api/v1/quiz/[^/]+/submit$"), "Submitted Quiz"),
    ("GET", re.compile(r"^/api/v1/quiz/[^/]+$"), "Viewed Quiz"),
    ("POST", re.compile(r"^/api/v1/doubts/stream$"), "Asked Doubt"),
    ("POST", re.compile(r"^/api/v1/doubts/transcribe$"), "Transcribed Audio"),
    ("POST", re.compile(r"^/api/v1/doubts/caption$"), "Captioned Image"),
    ("GET", re.compile(r"^/api/v1/doubts/sessions/[^/]+$"), "Viewed Doubt Session"),
    ("GET", re.compile(r"^/api/v1/doubts/sessions$"), "Viewed Doubt Sessions"),
    ("GET", re.compile(r"^/api/v1/progress/due-topics$"), "Viewed Due Topics"),
    ("GET", re.compile(r"^/api/v1/progress/report$"), "Viewed Progress Report"),
    ("POST", re.compile(r"^/api/v1/progress/study-session$"), "Logged Study Session"),
    ("GET", re.compile(r"^/api/v1/progress$"), "Viewed Progress"),
    ("GET", re.compile(r"^/api/v1/hf/status$"), "Checked HF Status"),
    ("POST", re.compile(r"^/api/v1/hf/test/[^/]+$"), "Tested HF Model"),
    ("GET", re.compile(r"^/api/v1/admin/learners$"), "Viewed Admin Learners"),
    ("PUT", re.compile(r"^/api/v1/admin/config$"), "Updated Admin Config"),
    ("GET", re.compile(r"^/api/v1/admin/config$"), "Viewed Admin Config"),
    ("POST", re.compile(r"^/api/v1/admin/send-digest$"), "Sent Progress Digest"),
    ("POST", re.compile(r"^/api/v1/session/start$"), "Started Session"),
    ("POST", re.compile(r"^/api/v1/session/advance$"), "Advanced Session"),
    ("POST", re.compile(r"^/api/v1/evals/run$"), "Ran Eval"),
    ("POST", re.compile(r"^/api/v1/evals/batch/quiz$"), "Ran Batch Quiz Eval"),
    ("GET", re.compile(r"^/api/v1/evals/results$"), "Viewed Eval Results"),
    ("GET", re.compile(r"^/api/v1/evals/summary$"), "Viewed Eval Summary"),
    ("POST", re.compile(r"^/api/v1/courses/plan$"), "Created Course Plan"),
    (
        "POST",
        re.compile(r"^/api/v1/courses/[^/]+/modules/[^/]+/interview/start$"),
        "Started Module Interview",
    ),
    (
        "POST",
        re.compile(r"^/api/v1/courses/[^/]+/modules/[^/]+/interview/[^/]+/answer$"),
        "Answered Module Interview",
    ),
    (
        "POST",
        re.compile(r"^/api/v1/courses/[^/]+/modules/[^/]+/interview/[^/]+/complete$"),
        "Completed Module Interview",
    ),
    ("GET", re.compile(r"^/api/v1/courses/[^/]+$"), "Viewed Course Plan"),
    ("GET", re.compile(r"^/api/v1/courses/?$"), "Viewed Course Plans"),
    ("POST", re.compile(r"^/api/v1/jobs/analyze/stream$"), "Analyzed a Job"),
    ("POST", re.compile(r"^/api/v1/jobs/[^/]+/reanalyze/stream$"), "Re-checked a Job"),
    ("PATCH", re.compile(r"^/api/v1/jobs/[^/]+$"), "Updated a Job Application"),
    ("POST", re.compile(r"^/api/v1/jobs/?$"), "Saved a Job Application"),
    ("POST", re.compile(r"^/api/v1/chat$"), "Asked the AI Assistant"),
    ("GET", re.compile(r"^/api/v1/feed/trending$"), "Viewed Trending Topics"),
    ("GET", re.compile(r"^/api/v1/feed/scheduled$"), "Viewed Scheduled Feed"),
    ("POST", re.compile(r"^/api/v1/feed/run-discovery$"), "Ran Feed Discovery"),
    ("POST", re.compile(r"^/api/v1/feed/[^/]+/snooze$"), "Snoozed Feed Item"),
    ("POST", re.compile(r"^/api/v1/feed/[^/]+/schedule$"), "Scheduled Feed Item"),
    (
        "DELETE",
        re.compile(r"^/api/v1/feed/[^/]+/interaction$"),
        "Removed Feed Interaction",
    ),
    ("GET", re.compile(r"^/api/v1/feed$"), "Viewed Feed"),
    ("GET", re.compile(r"^/api/v1/leaderboard$"), "Viewed Leaderboard"),
    ("GET", re.compile(r"^/api/v1/profile/activity-stats$"), "Viewed Activity Stats"),
    ("GET", re.compile(r"^/api/v1/profile/activity-logs$"), "Viewed Activity Logs"),
    ("DELETE", re.compile(r"^/api/v1/profile/activity-logs$"), "Cleared Activity Logs"),
]

# Only these actions are worth surfacing on the user's Activity page. Everything else
# (page views, session refreshes, status polls, admin/eval/feed reads, raw unmatched
# routes) is noise and is never recorded — keeping the log a clean, human-readable
# history of things the learner actually did.
_IMPORTANT_ACTIONS: frozenset[str] = frozenset(
    {
        "Logged In",
        "Completed Onboarding",
        "Updated Learner Profile",
        "Generated Curriculum",
        "Regenerated Content",
        "Generated Quiz",
        "Generated Flashcards",
        "Submitted Quiz",
        "Asked Doubt",
        "Logged Study Session",
        "Created Course Plan",
        "Started Module Interview",
        "Completed Module Interview",
        "Analyzed a Job",
        "Re-checked a Job",
        "Saved a Job Application",
        "Updated a Job Application",
        "Asked the AI Assistant",
    }
)

# Keep references to fire-and-forget tasks so they aren't garbage collected
# mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _resolve_action(method: str, path: str) -> str:
    for action_method, pattern, name in _ACTION_PATTERNS:
        if method == action_method and pattern.match(path):
            return name
    return f"{method} {path}"


def _extract_user_id(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    try:
        # Logging-only decode: skip signature/expiry verification so we can
        # still attribute activity from requests with a stale/expired token.
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        return None
    return claims.get("sub")


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def _insert_log(entry: dict) -> None:
    try:
        await col_activity_logs().insert_one(entry)
    except Exception as exc:
        log.warning("activity_log_insert_failed", error=str(exc)[:200])


def _schedule_log(entry: dict) -> None:
    task = asyncio.create_task(_insert_log(entry))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class ActivityLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not settings.ACTIVITY_LOGGING_ENABLED or request.url.path in _SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()

        response = await call_next(request)

        user_id = _extract_user_id(request)
        if not user_id:
            return response

        # Only record meaningful, user-facing actions; skip views/system noise so the
        # Activity page stays a clean, human-readable history (no raw method/path slugs).
        action = _resolve_action(request.method, request.url.path)
        if action not in _IMPORTANT_ACTIONS:
            return response
        # Don't record failed attempts as if they happened.
        if response.status_code >= 400:
            return response

        duration_ms = round((time.perf_counter() - start) * 1000)

        entry = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "action": action,
            # method/endpoint kept for internal/debug use; the UI shows only `action`.
            "method": request.method,
            "endpoint": request.url.path,
            "ip_address": _client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc),
        }
        _schedule_log(entry)

        return response
