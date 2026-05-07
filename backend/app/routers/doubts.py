import uuid
import json
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.learner import LearnerProfile
from app.models.user import User
from app.models.doubts import DoubtSession
from app.schemas.doubts import DoubtStreamRequest, DoubtSessionSchema
from app.hf.doubt_solver import stream_doubt_response
from app.hf.speech_to_text import transcribe_audio
from app.hf.image_captioner import caption_image
from app.auth.jwt import get_current_user_id

router = APIRouter()
log = structlog.get_logger()


async def _get_learner(user_id: str, db: AsyncSession) -> LearnerProfile:
    result = await db.execute(
        select(LearnerProfile).join(User, User.id == LearnerProfile.user_id).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


@router.post("/stream")
async def stream_doubt(
    body: DoubtStreamRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner = await _get_learner(user_id, db)
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

            # Save session to DB
            if learner:
                session_id = body.session_id or str(uuid.uuid4())
                result = await db.execute(select(DoubtSession).where(DoubtSession.id == session_id))
                existing = result.scalar_one_or_none()
                if existing:
                    messages = list(existing.messages or [])
                    messages.append({"role": "user", "content": body.question, "timestamp": datetime.now(timezone.utc).isoformat()})
                    messages.append({"role": "assistant", "content": full_response, "timestamp": datetime.now(timezone.utc).isoformat()})
                    existing.messages = messages
                else:
                    new_session = DoubtSession(
                        id=session_id if len(session_id) == 36 else str(uuid.uuid4()),
                        learner_id=learner.id,
                        topic_context=body.topic_context or None,
                        messages=[
                            {"role": "user", "content": body.question, "timestamp": datetime.now(timezone.utc).isoformat()},
                            {"role": "assistant", "content": full_response, "timestamp": datetime.now(timezone.utc).isoformat()},
                        ],
                    )
                    db.add(new_session)
                await db.commit()

        except Exception as e:
            log.error("doubt_stream_error", error=str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    audio_bytes = await audio.read()
    log.info("transcribe_start", size=len(audio_bytes))
    transcript = await transcribe_audio(audio_bytes)
    return {"transcript": transcript}


@router.post("/caption")
async def caption(
    image: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    image_bytes = await image.read()
    log.info("caption_start", size=len(image_bytes))
    caption_text = await caption_image(image_bytes)
    return {"caption": caption_text}


@router.get("/sessions")
async def get_sessions(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    learner = await _get_learner(user_id, db)
    if not learner:
        return []

    result = await db.execute(
        select(DoubtSession)
        .where(DoubtSession.learner_id == learner.id)
        .order_by(DoubtSession.started_at.desc())
        .limit(20)
    )
    sessions = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "topic_context": s.topic_context,
            "sentiment_mood": s.sentiment_mood,
            "started_at": s.started_at.isoformat(),
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "message_count": len(s.messages or []),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DoubtSession).where(DoubtSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        return {"messages": []}

    return {
        "id": str(session.id),
        "messages": session.messages or [],
        "topic_context": session.topic_context,
    }
