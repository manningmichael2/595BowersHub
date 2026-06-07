"""Pydantic models for authentication requests and responses."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=1, description="User password")


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class RegisterRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")
    display_name: str = Field(..., min_length=1, max_length=100)
    invite_token: str = Field(..., description="Invite token from admin")


class InviteRequest(BaseModel):
    role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class InviteResponse(BaseModel):
    token: str
    expires_at: datetime
    invite_url: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class TokenPayload(BaseModel):
    """Decoded JWT payload."""
    user_id: int
    email: str
    role: str
    exp: int  # expiry timestamp
