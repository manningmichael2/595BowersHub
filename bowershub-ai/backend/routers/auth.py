"""
Authentication API routes: login, register, refresh, invite, logout.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.models.auth import (
    LoginRequest, LoginResponse, RegisterRequest,
    InviteRequest, InviteResponse, RefreshRequest, UserResponse,
)
from backend.services.auth import AuthService
from backend.middleware.auth import get_auth_service, get_current_user, require_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, auth_service: AuthService = Depends(get_auth_service)):
    """Authenticate with email and password. Returns JWT access + refresh tokens."""
    from backend.middleware.audit import AuditLogger
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


@router.post("/register", response_model=UserResponse)
async def register(body: RegisterRequest, auth_service: AuthService = Depends(get_auth_service)):
    """Register a new user using an invite token."""
    # Validate invite
    role = await auth_service.use_invite(body.invite_token)
    if not role:
        raise HTTPException(status_code=400, detail="Invalid, expired, or already-used invite token")

    # Check email not taken
    existing = await auth_service.get_user_by_id(0)  # We need a different check
    from backend.database import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM public.bh_users WHERE email = $1", body.email
        )
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Create user
    user = await auth_service.create_user(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        role=role,
    )

    # Mark invite as used
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
