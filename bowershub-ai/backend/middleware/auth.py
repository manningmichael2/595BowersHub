"""
Authentication middleware: JWT validation and user injection.
"""

from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.services.auth import AuthService
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

    user = await auth_service.get_user_by_id(payload["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency: require admin role."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
