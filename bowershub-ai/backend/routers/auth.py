"""
Authentication API routes: login, register, refresh, invite, logout.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.models.auth import (
    LoginRequest, LoginResponse, RegisterRequest,
    InviteRequest, InviteResponse, RefreshRequest, UserResponse,
)
from backend.services.auth import AuthService
from backend.middleware.auth import (
    get_auth_service, get_current_user, require_admin, require_capability,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, auth_service: AuthService = Depends(get_auth_service)):
    """Authenticate with email and password. Returns JWT access + refresh tokens."""
    from backend.middleware.audit import AuditLogger
    from backend.middleware.rate_limit import rate_limiter, client_ip

    # Throttle password guessing: 5 attempts/min per client IP (raises 429).
    rate_limiter.check(client_ip(request), "login")

    user = await auth_service.authenticate(body.email, body.password)
    if not user:
        await AuditLogger.log(None, "login_failed", details={"email": body.email},
                              ip_address=request.client.host if request.client else None)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = auth_service.generate_access_token(user["id"], user["email"], user["role"])
    refresh_token = await auth_service.generate_refresh_token(user["id"])

    await AuditLogger.log(user["id"], "login",
                          ip_address=request.client.host if request.client else None)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            display_name=user["display_name"],
            role=user["role"],
            is_active=user["is_active"],
            created_at=user["created_at"],
            last_login_at=user["last_login_at"],
        ),
    )


@router.post("/refresh")
async def refresh(body: RefreshRequest, auth_service: AuthService = Depends(get_auth_service)):
    """Exchange a refresh token for a new access + refresh token pair (rotation)."""
    user_id = await auth_service.validate_refresh_token(body.refresh_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = await auth_service.get_user_by_id(user_id)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    access_token = auth_service.generate_access_token(user["id"], user["email"], user["role"])
    refresh_token = await auth_service.generate_refresh_token(user["id"])

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    user: dict = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Revoke the refresh token (logout this session)."""
    await auth_service.revoke_all_tokens(user["id"])
    return {"ok": True}


@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    body: InviteRequest,
    request: Request,
    user: dict = Depends(require_admin),
    auth_service: AuthService = Depends(get_auth_service),
):
    """(Admin) Generate an invite link for a new user."""
    token, expires_at = await auth_service.create_invite(user["id"], body.role)

    # Build invite URL (frontend handles the registration form)
    base_url = str(request.base_url).rstrip("/")
    invite_url = f"{base_url}/register?token={token}"

    return InviteResponse(token=token, expires_at=expires_at, invite_url=invite_url)


@router.post("/invites/{invite_id}/revoke")
async def revoke_invite(
    invite_id: int,
    user: dict = Depends(require_capability("users.manage")),
    auth_service: AuthService = Depends(get_auth_service),
):
    """(users.manage) Revoke an unused invite so it can no longer register (R2.2)."""
    revoked = await auth_service.revoke_invite(invite_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Invite not found, already used, or already expired")
    return {"ok": True, "invite_id": invite_id}


@router.post("/users/{user_id}/reset-link")
async def admin_reset_link(
    user_id: int,
    request: Request,
    user: dict = Depends(require_capability("users.manage")),
    auth_service: AuthService = Depends(get_auth_service),
):
    """(users.manage) Mint a one-time password-reset link for a user and return it
    directly — lets an admin reset a household member's password without email (R2.4)."""
    target = await auth_service.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    raw_token = await auth_service.create_password_reset_token(user_id)
    import os
    base_url = str(request.base_url).rstrip("/")
    public_url = os.environ.get("PUBLIC_URL", base_url)
    return {"ok": True, "user_id": user_id,
            "reset_url": f"{public_url}/reset-password?token={raw_token}"}


@router.post("/register", response_model=UserResponse)
async def register(body: RegisterRequest, auth_service: AuthService = Depends(get_auth_service)):
    """Register a new user using an invite token."""
    # Password policy (R2.3) — enforced here AND on the reset path.
    policy_error = AuthService.check_password_policy(body.password)
    if policy_error:
        raise HTTPException(status_code=400, detail=policy_error)

    # Validate invite
    role = await auth_service.use_invite(body.invite_token)
    if not role:
        raise HTTPException(status_code=400, detail="Invalid, expired, or already-used invite token")

    # Check email not taken + resolve the default/shared workspace to seed.
    from backend.database import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM public.bh_users WHERE email = $1", body.email
        )
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")
        # The designated shared workspace = the first (General) workspace (R2.5).
        default_ws = await conn.fetchval(
            "SELECT id FROM public.bh_workspaces ORDER BY id LIMIT 1")

    # Create the user AND seed workspace membership transactionally (R2.5).
    if default_ws is not None:
        user = await auth_service.create_invited_user(
            email=body.email, password=body.password,
            display_name=body.display_name, role=role, workspace_id=default_ws,
        )
    else:
        user = await auth_service.create_user(
            email=body.email, password=body.password,
            display_name=body.display_name, role=role,
        )

    # Mark invite as used (single-use)
    await auth_service.mark_invite_used(body.invite_token, user["id"])

    return UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        role=user["role"],
        is_active=user["is_active"],
        created_at=user["created_at"],
        last_login_at=user["last_login_at"],
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    return UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        role=user["role"],
        is_active=user["is_active"],
        created_at=user["created_at"],
        last_login_at=user["last_login_at"],
    )


# ---- Self-service profile (authenticated) ----

from pydantic import BaseModel as PydanticBaseModel, Field


class ProfileUpdate(PydanticBaseModel):
    model_config = {"extra": "forbid"}
    display_name: str = Field(min_length=1, max_length=80)


class ChangePassword(PydanticBaseModel):
    model_config = {"extra": "forbid"}
    current_password: str
    new_password: str


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: ProfileUpdate,
    user: dict = Depends(get_current_user),
):
    """Update the current user's own profile. Display name only — email and role
    are not self-editable (role escalation must go through an admin)."""
    from backend.database import get_pool
    from backend.middleware.audit import AuditLogger

    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Display name cannot be empty.")

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.bh_users SET display_name = $1 WHERE id = $2",
            name, user["id"],
        )
    await AuditLogger.log(user["id"], "profile_updated", "user", user["id"])

    return UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=name,
        role=user["role"],
        is_active=user["is_active"],
        created_at=user["created_at"],
        last_login_at=user["last_login_at"],
    )


@router.post("/change-password")
async def change_password(
    body: ChangePassword,
    user: dict = Depends(get_current_user),
):
    """Change the current user's password. Requires the current password, and
    enforces the same policy as register/reset. Revokes all refresh tokens so
    other sessions must re-login."""
    from backend.database import get_pool
    from backend.middleware.audit import AuditLogger

    # Same password policy as register/reset (R2.3).
    policy_error = AuthService.check_password_policy(body.new_password)
    if policy_error:
        raise HTTPException(status_code=400, detail=policy_error)

    pool = get_pool()
    async with pool.acquire() as conn:
        current_hash = await conn.fetchval(
            "SELECT password_hash FROM public.bh_users WHERE id = $1", user["id"]
        )
        if not current_hash or not AuthService.verify_password(
            body.current_password, current_hash
        ):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")

        new_hash = AuthService.hash_password(body.new_password)
        await conn.execute(
            "UPDATE public.bh_users SET password_hash = $1 WHERE id = $2",
            new_hash, user["id"],
        )
        # Force re-login everywhere else.
        await conn.execute(
            "UPDATE public.bh_refresh_tokens SET revoked_at = NOW() "
            "WHERE user_id = $1 AND revoked_at IS NULL",
            user["id"],
        )

    await AuditLogger.log(user["id"], "password_changed", "user", user["id"])
    return {"ok": True, "message": "Password changed. Other sessions have been signed out."}


# ---- Password Recovery ----


class PasswordResetRequest(PydanticBaseModel):
    email: str


class PasswordResetConfirm(PydanticBaseModel):
    token: str
    new_password: str


@router.post("/request-password-reset")
async def request_password_reset(body: PasswordResetRequest, request: Request):
    """
    Request a password reset email. Always returns 200 (never reveals whether email exists).
    Rate limited: max 3 requests per email per hour.
    """
    import hashlib
    import secrets
    from datetime import datetime, timedelta, timezone
    from backend.database import get_pool
    from backend.services.email_sender import send_email

    pool = get_pool()
    email = body.email.lower().strip()

    # Always return success (never reveal if email exists)
    async with pool.acquire() as conn:
        # Rate limit: max 3 reset requests per email per hour
        recent_count = await conn.fetchval("""
            SELECT COUNT(*) FROM public.bh_password_reset_tokens t
            JOIN public.bh_users u ON u.id = t.user_id
            WHERE u.email = $1 AND t.created_at > NOW() - INTERVAL '1 hour'
        """, email)
        if recent_count and recent_count >= 3:
            # Silently succeed — don't reveal rate limit to potential attackers
            return {"ok": True, "message": "If that email exists, a reset link has been sent."}

        # Look up user
        user = await conn.fetchrow(
            "SELECT id, email, display_name FROM public.bh_users WHERE email = $1 AND is_active = true",
            email
        )

    if not user:
        # Don't reveal that email doesn't exist
        return {"ok": True, "message": "If that email exists, a reset link has been sent."}

    # Generate token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO public.bh_password_reset_tokens (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
        """, user["id"], token_hash, expires_at)

    # Build reset URL
    base_url = str(request.base_url).rstrip("/")
    # Use the HTTPS tailscale URL if available
    import os
    public_url = os.environ.get("PUBLIC_URL", base_url)
    reset_url = f"{public_url}/reset-password?token={raw_token}"

    # Send email
    email_body = f"""Hi {user['display_name']},

You requested a password reset for BowersHub AI.

Click here to reset your password:
{reset_url}

This link expires in 30 minutes.

If you didn't request this, ignore this email — your password won't change.

— BowersHub AI"""

    await send_email(
        to=user["email"],
        subject="BowersHub AI — Password Reset",
        body=email_body,
    )

    return {"ok": True, "message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: PasswordResetConfirm):
    """
    Reset password using a valid token from the reset email.
    Token is single-use and expires after 30 minutes.
    """
    import hashlib
    from datetime import datetime, timezone
    from backend.database import get_pool

    # Same password policy as register (R2.3).
    policy_error = AuthService.check_password_policy(body.new_password)
    if policy_error:
        raise HTTPException(status_code=400, detail=policy_error)

    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    pool = get_pool()

    async with pool.acquire() as conn:
        # Find valid, unconsumed token
        token_row = await conn.fetchrow("""
            SELECT id, user_id, expires_at, consumed_at
            FROM public.bh_password_reset_tokens
            WHERE token_hash = $1
        """, token_hash)

        if not token_row:
            raise HTTPException(status_code=400, detail="Invalid or expired reset link")

        if token_row["consumed_at"]:
            raise HTTPException(status_code=400, detail="This reset link has already been used")

        if token_row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="This reset link has expired")

        # Hash new password and update (AuthService is imported at module top)
        new_hash = AuthService.hash_password(body.new_password)

        await conn.execute(
            "UPDATE public.bh_users SET password_hash = $1 WHERE id = $2",
            new_hash, token_row["user_id"],
        )

        # Mark token as consumed
        await conn.execute(
            "UPDATE public.bh_password_reset_tokens SET consumed_at = NOW() WHERE id = $1",
            token_row["id"],
        )

        # Revoke all existing refresh tokens (force re-login everywhere)
        await conn.execute(
            "UPDATE public.bh_refresh_tokens SET revoked_at = NOW() WHERE user_id = $1 AND revoked_at IS NULL",
            token_row["user_id"],
        )

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(token_row["user_id"], "password_reset", "user", token_row["user_id"])

    return {"ok": True, "message": "Password has been reset. Please log in with your new password."}
