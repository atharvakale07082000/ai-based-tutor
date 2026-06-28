"""
JWT authentication utilities.

Provides token creation, decoding, password hashing, and the
FastAPI dependency `get_current_user_id` used by all protected routes.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.config import settings

log = structlog.get_logger()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (random salt per call)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the bcrypt-hashed password."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(data: dict[str, Any]) -> str:
    """Create a short-lived JWT access token with the given payload."""
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload["type"] = "access"
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    """Create a long-lived JWT refresh token with the given payload."""
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload["type"] = "refresh"
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT; raise HTTP 401 if invalid or expired."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    """FastAPI dependency: extract and return the user_id (sub claim) from the Bearer token."""
    payload = decode_token(token)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")
    return user_id


async def require_superuser(user_id: str = Depends(get_current_user_id)) -> str:
    """FastAPI dependency: allow only the evals superuser (role == 'superuser'); else 403."""
    from app.db.mongo import col_users

    user = await col_users().find_one({"id": user_id}, {"_id": 0, "role": 1})
    if not user or user.get("role") != "superuser":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser access required")
    return user_id


async def seed_superuser() -> None:
    """Idempotently ensure the evals superuser exists (called on startup).

    Security: never auto-seeds in production (no default-credential backdoor), and requires
    SUPERUSER_PASSWORD from the environment — there is no source default. Existing accounts only
    have their role corrected, never their password.
    """
    import uuid
    from datetime import datetime, timezone

    from app.db.mongo import col_learners, col_users

    if settings.APP_ENV.lower() in ("production", "prod"):
        log.info("superuser_seed_skipped", reason="auto-seed disabled in production")
        return
    if not settings.SUPERUSER_PASSWORD:
        log.warning(
            "superuser_seed_skipped", reason="SUPERUSER_PASSWORD unset — set it in .env to enable the evals dashboard"
        )
        return

    email = settings.SUPERUSER_EMAIL
    now = datetime.now(timezone.utc).isoformat()

    existing = await col_users().find_one({"email": email}, {"_id": 0, "id": 1, "role": 1})
    if existing:
        if existing.get("role") != "superuser":
            await col_users().update_one({"email": email}, {"$set": {"role": "superuser"}})
        return

    user_id = str(uuid.uuid4())
    await col_users().insert_one(
        {
            "id": user_id,
            "email": email,
            "hashed_password": hash_password(settings.SUPERUSER_PASSWORD),
            "role": "superuser",
            "is_active": True,
            "created_at": now,
        }
    )
    await col_learners().insert_one(
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "email": email,
            "name": "Admin",
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
