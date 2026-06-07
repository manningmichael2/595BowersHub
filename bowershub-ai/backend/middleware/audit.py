"""
Audit logging middleware: logs admin actions for accountability.
"""

import json
import logging
from typing import Any, Dict, Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)


class AuditLogger:
    """Logs admin and security-relevant actions to bh_audit_log."""

    @staticmethod
    async def log(
        user_id: Optional[int],
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ):
        """
        Log an auditable action.

        Actions: login, login_failed, logout, create_user, deactivate_user,
                 modify_skill, create_workspace, modify_permissions, delete_conversation, etc.
        """
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO public.bh_audit_log
                        (user_id, action, target_type, target_id, details, ip_address)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                """, user_id, action, target_type, target_id,
                    json.dumps(details) if details else None, ip_address)
        except Exception as e:
            # Never block the request for audit logging failures
            logger.warning(f"Audit log write failed: {e}")

    @staticmethod
    async def get_recent(limit: int = 50, user_id: Optional[int] = None) -> list:
        """Get recent audit log entries."""
        pool = get_pool()
        async with pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch("""
                    SELECT al.*, u.email as user_email
                    FROM public.bh_audit_log al
                    LEFT JOIN public.bh_users u ON u.id = al.user_id
                    WHERE al.user_id = $1
                    ORDER BY al.created_at DESC LIMIT $2
                """, user_id, limit)
            else:
                rows = await conn.fetch("""
                    SELECT al.*, u.email as user_email
                    FROM public.bh_audit_log al
                    LEFT JOIN public.bh_users u ON u.id = al.user_id
                    ORDER BY al.created_at DESC LIMIT $1
                """, limit)
        return [dict(r) for r in rows]
