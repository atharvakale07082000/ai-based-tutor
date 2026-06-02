"""
Socket.IO server configuration and event handlers.

Security:
- The `connect` handler validates the JWT from auth.token or
  the Authorization header before accepting any connection.
- `join_room` verifies the connecting user owns the requested learner_id,
  preventing cross-learner data leakage via WebSocket subscriptions.
- cors_allowed_origins is restricted to settings.cors_origins (not "*").
"""
import structlog
import socketio

from app.config import settings

log = structlog.get_logger()

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.cors_origins,
    logger=False,
    engineio_logger=False,
)

# sid → user_id mapping for authorization checks in subsequent events.
_sid_to_user: dict[str, str] = {}


def _extract_user_id_from_token(token: str) -> str | None:
    """Decode JWT and return the subject (user_id), or None if invalid."""
    try:
        from app.auth.jwt import decode_token
        payload = decode_token(token)
        return payload.get("sub")
    except Exception:
        return None


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None):
    """
    Validate JWT on connect.  Rejects unauthenticated connections.

    The client must pass: {'token': '<jwt>'} as the auth payload,
    or include an Authorization: Bearer <jwt> header in the handshake.
    """
    token = None

    if auth and isinstance(auth, dict):
        token = auth.get("token") or auth.get("Authorization", "").removeprefix("Bearer ").strip()

    if not token:
        # Try HTTP Authorization header forwarded by Socket.IO
        raw_auth = environ.get("HTTP_AUTHORIZATION", "")
        if raw_auth.startswith("Bearer "):
            token = raw_auth[7:]

    if not token:
        log.warning("ws_connect_rejected", sid=sid, reason="no_token")
        return False  # Socket.IO treats False return as rejection

    user_id = _extract_user_id_from_token(token)
    if not user_id:
        log.warning("ws_connect_rejected", sid=sid, reason="invalid_token")
        return False

    _sid_to_user[sid] = user_id
    log.info("ws_connect", sid=sid, user_id=user_id)


@sio.event
async def disconnect(sid: str):
    user_id = _sid_to_user.pop(sid, "unknown")
    log.info("ws_disconnect", sid=sid, user_id=user_id)


@sio.event
async def join_room(sid: str, data: dict):
    """
    Subscribe to a learner room.  Only allowed if the authenticated user
    owns the requested learner_id (prevent cross-user subscription).
    """
    learner_id = data.get("learner_id")
    if not learner_id:
        log.warning("ws_join_room_rejected", sid=sid, reason="no_learner_id")
        return

    user_id = _sid_to_user.get(sid)
    if not user_id:
        log.warning("ws_join_room_rejected", sid=sid, reason="unauthenticated")
        return

    # Verify the authenticated user owns this learner profile
    try:
        from app.db.mongo import col_learners
        learner = col_learners().find_one(
            {"id": learner_id, "user_id": user_id},
            {"_id": 0, "id": 1},
        )
        if not learner:
            log.warning(
                "ws_join_room_rejected",
                sid=sid,
                user_id=user_id,
                learner_id=learner_id,
                reason="not_owner",
            )
            return
    except Exception as exc:
        log.error("ws_join_room_db_error", sid=sid, error=str(exc))
        return

    await sio.enter_room(sid, learner_id)
    log.info("ws_join_room", sid=sid, user_id=user_id, learner_id=learner_id)


# ── Emit helpers (exact event names matching frontend WS_EVENTS) ─────────────

async def emit_agent_status(data: dict):
    """Broadcast agent status to all connected clients."""
    await sio.emit("agent:status", data)


async def emit_curriculum_update(learner_id: str, data: dict):
    """Send curriculum update to a specific learner's room."""
    await sio.emit("curriculum:update", data, room=learner_id)


async def emit_quiz_ready(learner_id: str, quiz_id: str, topic: str):
    """Notify a learner that their quiz is ready."""
    await sio.emit("quiz:ready", {"quiz_id": quiz_id, "topic": topic}, room=learner_id)


async def emit_progress_update(learner_id: str, data: dict):
    """Push Elo / proficiency update to a specific learner."""
    await sio.emit("progress:update", data, room=learner_id)


async def emit_doubt_stream_token(sid: str, token: str, session_id: str):
    """Stream a single token to the requester's socket."""
    await sio.emit("doubt:stream", {"token": token, "session_id": session_id}, to=sid)
