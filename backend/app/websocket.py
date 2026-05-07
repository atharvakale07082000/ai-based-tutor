import socketio
import structlog

log = structlog.get_logger()

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None):
    log.info("ws_connect", sid=sid)


@sio.event
async def disconnect(sid: str):
    log.info("ws_disconnect", sid=sid)


@sio.event
async def join_room(sid: str, data: dict):
    learner_id = data.get("learner_id")
    if learner_id:
        await sio.enter_room(sid, learner_id)
        log.info("ws_join_room", sid=sid, learner_id=learner_id)


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
