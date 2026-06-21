"""Pydantic schemas for authentication request/response bodies."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserSchema(BaseModel):
    id: str
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserSchema


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ResetRequestBody(BaseModel):
    email: EmailStr


class ResetConfirmBody(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)
