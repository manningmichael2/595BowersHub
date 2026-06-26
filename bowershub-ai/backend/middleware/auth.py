"""
Authentication middleware: JWT validation and user injection.
"""

from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.services.auth import AuthService
from backend.services import authz
from backend.database import get_pool
from backend.config import Config


security = HTTPBearer(auto_error=False)


async def get_auth_service(request: Request) -> AuthService:
    """Dependency: get AuthService instance."""
    config: Config = request.app.state.config
    pool = get_pool()
    return AuthService(pool, config)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    """
    Dependency: validate JWT and return current user.
    Raises 401 if token is missing, invalid, or expired.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = auth_service.validate_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Authorize on the LIVE bh_users row, never the JWT payload. The token's
    # `role` claim (if any) is informational-only — a demotion/deactivation must
    # take effect before the token expires (R1.6), so role + is_active are read
    # fresh here on every request and no downstream gate trusts the JWT's role.
    user = await auth_service.get_user_by_id(payload["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    return user


def require_role(min_role: str):
    """Dependency factory: require role rank >= rank(min_role) (R1.2).

    Reads the live role from get_current_user. An unknown `min_role` key fails
    closed (always 403), so a typo can never widen access."""
    async def _require_role(user: dict = Depends(get_current_user)) -> dict:
        threshold = authz.ROLE_RANK.get(min_role)
        if threshold is None or authz.rank(user["role"]) < threshold:
            raise HTTPException(status_code=403, detail=f"Requires {min_role} role")
        return user
    return _require_role


def require_capability(cap: str):
    """Dependency factory: require authz.resolve(user, cap) (R1.4 / R5.2).

    The preferred gate for finance/admin endpoints — it carries the per-user
    feature override + admin floor that require_role can't (added in Task 9).
    Registers `cap` at import time so the boot self-check can verify it has a
    bh_capabilities row."""
    authz.register_capability(cap)

    async def _require_capability(user: dict = Depends(get_current_user)) -> dict:
        if not authz.resolve(user, cap):
            raise HTTPException(status_code=403, detail=f"Capability '{cap}' required")
        return user
    return _require_capability


# Preserved name — ~30 existing call sites depend on it unchanged (R1.2).
require_admin = require_role("admin")
