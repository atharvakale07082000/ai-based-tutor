import structlog
import socketio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_all_tables
from app.routers import auth, learner, curriculum, content, quiz, doubts, progress, hf, admin, session, evals, courses, assistant
from app.websocket import sio

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    yield


app = FastAPI(
    title="AI Tutor Platform API",
    version="1.0.0",
    description="Multi-agent AI tutoring platform with LangGraph + Hugging Face",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers
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


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# Wrap FastAPI with Socket.IO ASGI app, mounting at /ws
socket_app = socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="/ws")

# Run with: uvicorn app.main:socket_app --host 0.0.0.0 --port 8000 --reload
