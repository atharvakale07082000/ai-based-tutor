import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.jwt import create_access_token, create_refresh_token, get_current_user_id, hash_password, verify_password
from app.db.mongo import col_learners, col_users
from app.schemas.auth import LoginRequest, LoginResponse, RefreshResponse, UserSchema

router = APIRouter()
log = structlog.get_logger()

PROJ = {"_id": 0}


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    user = col_users().find_one({"email": body.email}, PROJ)

    if not user:
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        user = {
            "id": user_id,
            "email": body.email,
            "hashed_password": hash_password(body.password),
            "role": "learner",
            "is_active": True,
            "created_at": now,
        }
        col_users().insert_one({**user})

        learner_id = str(uuid.uuid4())
        col_learners().insert_one(
            {
                "id": learner_id,
                "user_id": user_id,
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

    if user.get("hashed_password") and not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    payload = {"sub": str(user["id"])}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)

    learner = col_learners().find_one({"user_id": user["id"]}, PROJ)
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
    return RefreshResponse(access_token=create_access_token({"sub": user_id}))


@router.post("/logout")
async def logout():
    return {"message": "Logged out"}
