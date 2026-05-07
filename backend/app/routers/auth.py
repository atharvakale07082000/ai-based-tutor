import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.learner import LearnerProfile
from app.schemas.auth import LoginRequest, LoginResponse, RefreshResponse, UserSchema
from app.auth.jwt import hash_password, verify_password, create_access_token, create_refresh_token, get_current_user_id

router = APIRouter()
log = structlog.get_logger()


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user:
        # Auto-create user for demo
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            email=body.email,
            hashed_password=hash_password(body.password),
            role="learner",
        )
        db.add(user)
        learner = LearnerProfile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=body.email.split("@")[0],
        )
        db.add(learner)
        await db.commit()
        await db.refresh(user)

    if user.hashed_password and not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    payload = {"sub": str(user.id)}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)

    learner_result = await db.execute(select(LearnerProfile).where(LearnerProfile.user_id == user.id))
    learner = learner_result.scalar_one_or_none()

    log.info("auth_login", user_id=str(user.id))
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserSchema(id=str(user.id), email=user.email, name=learner.name if learner else "", role=user.role),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(user_id: str = Depends(get_current_user_id)):
    access_token = create_access_token({"sub": user_id})
    return RefreshResponse(access_token=access_token)


@router.post("/logout")
async def logout():
    return {"message": "Logged out"}
