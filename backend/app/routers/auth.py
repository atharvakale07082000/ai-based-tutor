"""
Authentication API.

Endpoints:
  POST /auth/login   — auto-register on first call, then issue JWT access + refresh tokens
  POST /auth/refresh — exchange existing access token for a new one
  POST /auth/logout  — client-side logout (stateless; tokens expire naturally)
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.auth.jwt import create_access_token, create_refresh_token, get_current_user_id, hash_password, verify_password
from app.db.mongo import col_learners, col_users
from app.schemas.auth import LoginRequest, LoginResponse, RefreshResponse, UserSchema

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """Auto-register on first call; verify password on subsequent calls. Returns JWT pair."""
    user = await col_users().find_one({"email": body.email}, PROJ)

    if not user:
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        new_user = {
            "id": user_id,
            "email": body.email,
            "hashed_password": hash_password(body.password),
            "role": "learner",
            "is_active": True,
            "created_at": now,
        }
        try:
            await col_users().insert_one(new_user)
            user = new_user
        except DuplicateKeyError:
            # A concurrent request (e.g. a double-submitted signup form)
            # already created this user — fetch what it inserted.
            user = await col_users().find_one({"email": body.email}, PROJ)

        learner_id = str(uuid.uuid4())
        try:
            await col_learners().insert_one(
                {
                    "id": learner_id,
                    "user_id": user["id"],
                    "email": body.email,
                    "name": body.email.split("@")[0],
                    "goal_vector": [],
                    "topic_proficiency_map": {},
                    "learning_style": "visual",
                    "xp": 0,
                    "streak": 0,
                    "session_cadence": {},
                    "curriculum_version": 1,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        except DuplicateKeyError:
            # Learner profile already created by a concurrent request.
            pass

    if user.get("hashed_password") and not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    payload = {"sub": str(user["id"])}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)

    learner = await col_learners().find_one({"user_id": user["id"]}, PROJ)
    log.info("auth_login", user_id=user["id"])

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserSchema(
            id=str(user["id"]),
            email=user["email"],
            name=learner["name"] if learner else "",
            role=user.get("role", "learner"),
        ),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(user_id: str = Depends(get_current_user_id)):
    """Issue a new access token for the authenticated user."""
    return RefreshResponse(access_token=create_access_token({"sub": user_id}))


@router.post("/logout")
async def logout():
    """Stateless logout — clients must discard their tokens; server cannot invalidate JWTs."""
    return {"message": "Logged out"}
