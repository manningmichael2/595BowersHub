"""
Authentication service: user creation, password verification, JWT management,
invite links, and refresh token rotation.
"""

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt
import jwt
import asyncpg

from backend.config import Config


class AuthService:
    """Handles all authentication operations."""

    ACCESS_TOKEN_EXPIRY = timedelta(minutes=30)
    REFRESH_TOKEN_EXPIRY = timedelta(days=90)
    INVITE_EXPIRY = timedelta(hours=72)

    def __init__(self, pool: asyncpg.Pool, config: Config):
        self.pool = pool
        self.config = config

    # --- Password hashing ---

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password with bcrypt."""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a password against its bcrypt hash."""
        return bcrypt.checkpw(password.encode(), password_hash.encode())

    # --- JWT tokens ---

    def generate_access_token(self, user_id: int, email: str, role: str) -> str:
        """Generate a short-lived JWT access token."""
        payload = {
            "user_id": user_id,
            "email": email,
            "role": role,
            "exp": int((datetime.now(timezone.utc) + self.ACCESS_TOKEN_EXPIRY).timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        return jwt.encode(payload, self.config.JWT_SECRET, algorithm="HS256")

    def validate_access_token(self, token: str) -> Optional[dict]:
        """Validate and decode a JWT access token. Returns payload or None."""
        try:
            payload = jwt.decode(token, self.config.JWT_SECRET, algorithms=["HS256"])
            return payload
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

    # --- Refresh tokens ---

    @staticmethod
    def _hash_token(token: str) -> str:
        """SHA-256 hash a refresh token for storage."""
        return hashlib.sha256(token.encode()).hexdigest()

    async def generate_refresh_token(self, user_id: int) -> str:
        """Generate an opaque refresh token and store its hash."""
        token = secrets.token_urlsafe(48)
        token_hash = self._hash_token(token)
        expires_at = datetime.now(timezone.utc) + self.REFRESH_TOKEN_EXPIRY

        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO public.bh_refresh_tokens (user_id, token_hash, expires_at)
                   VALUES ($1, $2, $3)""",
                user_id, token_hash, expires_at,
            )
        return token

    async def validate_refresh_token(self, token: str) -> Optional[int]:
        """
        Validate a refresh token. Returns user_id if valid.
        Implements rotation: the used token is revoked.
        """
        token_hash = self._hash_token(token)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, user_id, expires_at, revoked_at
                   FROM public.bh_refresh_tokens
                   WHERE token_hash = $1""",
                token_hash,
            )

            if not row:
                return None

            # Check if revoked (potential token theft — revoke all for this user)
            if row["revoked_at"] is not None:
                await conn.execute(
                    """UPDATE public.bh_refresh_tokens
                       SET revoked_at = now()
                       WHERE user_id = $1 AND revoked_at IS NULL""",
                    row["user_id"],
                )
                return None

            # Check expiry
            if row["expires_at"] < datetime.now(timezone.utc):
                return None

            # Revoke this token (rotation)
            await conn.execute(
                "UPDATE public.bh_refresh_tokens SET revoked_at = now() WHERE id = $1",
                row["id"],
            )

            return row["user_id"]

    async def revoke_all_tokens(self, user_id: int):
        """Revoke all refresh tokens for a user (logout everywhere)."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE public.bh_refresh_tokens
                   SET revoked_at = now()
                   WHERE user_id = $1 AND revoked_at IS NULL""",
                user_id,
            )

    # --- User management ---

    async def create_user(self, email: str, password: str, display_name: str, role: str = "member") -> dict:
        """Create a new user. Returns the user record."""
        password_hash = self.hash_password(password)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO public.bh_users (email, password_hash, display_name, role)
                   VALUES ($1, $2, $3, $4)
                   RETURNING id, email, display_name, role, is_active, created_at, last_login_at""",
                email, password_hash, display_name, role,
            )
        return dict(row)

    async def authenticate(self, email: str, password: str) -> Optional[dict]:
        """Verify email/password. Returns user record or None."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, email, password_hash, display_name, role, is_active, created_at, last_login_at
                   FROM public.bh_users WHERE email = $1""",
                email,
            )

        if not row:
            return None
        if not row["is_active"]:
            return None
        if not self.verify_password(password, row["password_hash"]):
            return None

        # Update last login
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.bh_users SET last_login_at = now() WHERE id = $1",
                row["id"],
            )

        return dict(row)

    async def get_user_by_id(self, user_id: int) -> Optional[dict]:
        """Get user by ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, email, display_name, role, is_active, created_at, last_login_at, settings_json
                   FROM public.bh_users WHERE id = $1""",
                user_id,
            )
        return dict(row) if row else None

    # --- Invite links ---

    async def create_invite(self, created_by: int, role: str = "member") -> Tuple[str, datetime]:
        """Create an invite link. Returns (token, expires_at)."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + self.INVITE_EXPIRY

        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO public.bh_invite_links (token, created_by, role, expires_at)
                   VALUES ($1, $2, $3, $4)""",
                token, created_by, role, expires_at,
            )
        return token, expires_at

    async def use_invite(self, token: str) -> Optional[str]:
        """
        Validate and consume an invite token.
        Returns the role if valid, None if expired/used/invalid.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, role, expires_at, used_by
                   FROM public.bh_invite_links WHERE token = $1""",
                token,
            )

        if not row:
            return None
        if row["used_by"] is not None:
            return None
        if row["expires_at"] < datetime.now(timezone.utc):
            return None

        return row["role"]

    async def mark_invite_used(self, token: str, user_id: int):
        """Mark an invite as used."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE public.bh_invite_links
                   SET used_by = $1, used_at = now()
                   WHERE token = $2""",
                user_id, token,
            )

    # --- First-run admin seed ---

    async def ensure_admin_exists(self):
        """On first startup, create admin user if no users exist."""
        async with self.pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM public.bh_users")

        if count == 0 and self.config.ADMIN_PASSWORD:
            user = await self.create_user(
                email=self.config.ADMIN_EMAIL,
                password=self.config.ADMIN_PASSWORD,
                display_name="Michael",
                role="admin",
            )
            # Assign admin to all workspaces
            async with self.pool.acquire() as conn:
                workspaces = await conn.fetch("SELECT id FROM public.bh_workspaces")
                for ws in workspaces:
                    await conn.execute(
                        """INSERT INTO public.bh_workspace_users (workspace_id, user_id, role)
                           VALUES ($1, $2, 'owner') ON CONFLICT DO NOTHING""",
                        ws["id"], user["id"],
                    )
            print(f"  ✓ Admin user created: {self.config.ADMIN_EMAIL}")
        elif count == 0:
            print("  ⚠ No users exist and ADMIN_PASSWORD not set. Set ADMIN_PASSWORD env var to create initial admin.")
