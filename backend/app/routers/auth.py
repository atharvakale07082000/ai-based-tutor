"""
Authentication API.

Endpoints:
  POST /auth/login   — auto-register on first call, then issue JWT access + refresh tokens
  POST /auth/refresh — exchange existing access token for a new one
  POST /auth/logout  — client-side logout (stateless; tokens expire naturally)
"""

import asyncio
import secrets
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.errors import DuplicateKeyError
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.jwt import create_access_token, create_refresh_token, get_current_user_id, hash_password, verify_password
from app.config import settings
from app.db.mongo import col_learners, col_reset_tokens, col_users
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    ResetConfirmBody,
    ResetRequestBody,
    UserSchema,
)

router = APIRouter()
log = structlog.get_logger()
limiter = Limiter(key_func=get_remote_address)

PROJ = {"_id": 0}


@router.post("/login", response_model=LoginResponse)
@limiter.limit("20/minute")
async def login(request: Request, body: LoginRequest):
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


# ─── Password reset ───────────────────────────────────────────────────────────


def _send_reset_email(to_email: str, token: str) -> None:
    """Send a password-reset email via SMTP (runs in a thread)."""
    reset_url = f"{settings.APP_BASE_URL}/reset-password?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your Atelier password"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    plain = f"Click this link to reset your password (expires in 1 hour):\n\n{reset_url}\n\nIf you did not request this, ignore this email."
    html = f"""
<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px 24px">
  <h2 style="font-size:22px;font-weight:400;margin-bottom:8px">Reset your password</h2>
  <p style="color:#555;margin-bottom:24px">Click the button below. This link expires in 1 hour.</p>
  <a href="{reset_url}" style="display:inline-block;padding:12px 24px;background:#111;color:#fff;text-decoration:none;border-radius:8px;font-size:14px">Reset password</a>
  <p style="margin-top:24px;color:#888;font-size:12px">If you didn't request this, you can safely ignore this email.</p>
</div>"""

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())


@router.post("/reset-request")
@limiter.limit("5/hour")
async def request_password_reset(request: Request, body: ResetRequestBody):
    """Send a one-time password-reset link to the given email address."""
    user = await col_users().find_one({"email": body.email}, {"_id": 0})
    # Always return 200 to avoid leaking which emails are registered
    if not user:
        return {"message": "If that email is registered you will receive a reset link."}

    token = secrets.token_urlsafe(48)
    await col_reset_tokens().insert_one(
        {
            "token": token,
            "user_id": user["id"],
            "email": body.email,
            "created_at": datetime.now(timezone.utc),
        }
    )

    if settings.SMTP_USER and settings.SMTP_PASSWORD:
        try:
            await asyncio.to_thread(_send_reset_email, body.email, token)
            log.info("reset_email_sent", email=body.email)
        except Exception as e:
            log.error("reset_email_failed", error=str(e)[:200])
    else:
        log.warning("reset_email_skipped", reason="SMTP not configured", token_preview=token[:8])

    return {"message": "If that email is registered you will receive a reset link."}


@router.post("/reset-confirm")
async def confirm_password_reset(body: ResetConfirmBody):
    """Validate a reset token and update the user's password."""
    record = await col_reset_tokens().find_one({"token": body.token}, {"_id": 0})
    if not record:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token.")

    new_hash = hash_password(body.new_password)
    await col_users().update_one(
        {"id": record["user_id"]},
        {"$set": {"hashed_password": new_hash}},
    )
    # Consume the token immediately so it can't be reused
    await col_reset_tokens().delete_one({"token": body.token})

    log.info("password_reset_complete", user_id=record["user_id"])
    return {"message": "Password updated. You can now sign in with your new password."}
