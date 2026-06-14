import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.auth.jwt import get_current_user_id
from app.db.mongo import col_doubts, col_learners
from app.hf.doubt_solver import stream_doubt_response
from app.hf.image_captioner import caption_image
from app.hf.speech_to_text import transcribe_audio
from app.schemas.doubts import DoubtStreamRequest

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


@router.post("/stream")
async def stream_doubt(
    body: DoubtStreamRequest,
    user_id: str = Depends(get_current_user_id),
):
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    log.info("doubt_stream_start", question=body.question[:80], topic=body.topic_context)

    async def event_generator():
        try:
            stream = await stream_doubt_response(
                body.question,
                body.topic_context,
                [m.model_dump() for m in body.history],
            )
            full_response = ""
            async for token in stream:
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            yield "data: [DONE]\n\n"

            if learner:
                now = datetime.now(timezone.utc).isoformat()
                session_id = body.session_id or str(uuid.uuid4())
                existing = await col_doubts().find_one({"id": session_id}, PROJ)
                new_msgs = [
                    {"role": "user", "content": body.question, "timestamp": now},
                    {"role": "assistant", "content": full_response, "timestamp": now},
                ]
                if existing:
                    await col_doubts().update_one(
                        {"id": session_id},
                        {"$push": {"messages": {"$each": new_msgs}}},
                    )
                else:
                    await col_doubts().insert_one(
                        {
                            "id": session_id if len(session_id) == 36 else str(uuid.uuid4()),
                            "learner_id": learner["id"],
                            "topic_context": body.topic_context or None,
                            "messages": new_msgs,
                            "sentiment_mood": None,
                            "started_at": now,
                            "ended_at": None,
                        }
                    )

        except Exception as e:
            log.error("doubt_stream_error", error=str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_AUDIO_TYPES = {"audio/mpeg", "audio/mp4", "audio/wav", "audio/webm", "audio/ogg", "audio/x-m4a"}
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    if audio.content_type not in _AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio type: {audio.content_type}. Allowed: mp3, mp4, wav, webm, ogg, m4a.",
        )
    audio_bytes = await audio.read()
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file exceeds 10 MB limit.")
    transcript = await transcribe_audio(audio_bytes)
    return {"transcript": transcript}


@router.post("/caption")
async def caption(image: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    if image.content_type not in _IMAGE_TYPES:
        raise HTTPException(
            status_code=415, detail=f"Unsupported image type: {image.content_type}. Allowed: jpeg, png, gif, webp."
        )
    image_bytes = await image.read()
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image file exceeds 5 MB limit.")
    caption_text = await caption_image(image_bytes)
    return {"caption": caption_text}


@router.get("/sessions")
async def get_sessions(user_id: str = Depends(get_current_user_id)):
    learner = await col_learners().find_one({"user_id": user_id}, PROJ)
    if not learner:
        return []
    sessions = (
        await col_doubts()
        .find({"learner_id": learner["id"]}, PROJ)
        .sort("started_at", -1)
        .limit(20)
        .to_list(length=None)
    )
    return [
        {
            "id": s["id"],
            "topic_context": s.get("topic_context"),
            "sentiment_mood": s.get("sentiment_mood"),
            "started_at": s.get("started_at"),
            "ended_at": s.get("ended_at"),
            "message_count": len(s.get("messages") or []),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user_id: str = Depends(get_current_user_id)):
    session = await col_doubts().find_one({"id": session_id}, PROJ)
    if not session:
        return {"messages": []}
    return {
        "id": session["id"],
        "messages": session.get("messages") or [],
        "topic_context": session.get("topic_context"),
    }
