"""
Notification Service: Web Push and Pushover delivery with user preferences.
"""

import json
import logging
from datetime import time as dt_time
from datetime import datetime
from typing import Optional

import httpx
from backend.http_client import get_http_client

from backend.config import Config
from backend.database import get_pool

logger = logging.getLogger(__name__)


class NotificationService:
    """Handles push notification delivery via Web Push and Pushover."""

    def __init__(self, config: Config):
        self.config = config

    async def send(
        self, user_id: int, event_type: str, title: str, message: str,
        priority: int = 0
    ) -> bool:
        """
        Send a notification to a user, respecting their preferences.
        Returns True if at least one delivery method succeeded.
        """
        prefs = await self._get_preferences(user_id, event_type)

        # Check quiet hours
        if self._in_quiet_hours(prefs):
            logger.debug(f"Notification suppressed (quiet hours): user={user_id}, event={event_type}")
            return False

        sent = False

        # Try Web Push
        if prefs.get("web_push", True):
            try:
                await self._send_web_push(user_id, title, message)
                sent = True
            except Exception as e:
                logger.warning(f"Web Push failed for user {user_id}: {e}")

        # Try Pushover
        if prefs.get("pushover", False) or (not sent and priority > 0):
            try:
                await self._send_pushover(title, message, priority)
                sent = True
            except Exception as e:
                logger.warning(f"Pushover failed: {e}")

        return sent

    async def _get_preferences(self, user_id: int, event_type: str) -> dict:
        """Get notification preferences for a user + event type.

        Falls back to the user's global `default` row when no row exists for the
        specific event type, so the Settings UI (which writes one global row) can
        steer delivery for every event without per-event configuration.
        """
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT web_push, pushover, quiet_start, quiet_end
                FROM public.bh_notification_prefs
                WHERE user_id = $1 AND event_type = ANY($2::text[])
                ORDER BY (event_type = $3) DESC
                LIMIT 1
            """, user_id, [event_type, "default"], event_type)

        if row:
            return {
                "web_push": row["web_push"],
                "pushover": row["pushover"],
                "quiet_start": row["quiet_start"],
                "quiet_end": row["quiet_end"],
            }
        # Defaults: web push on, pushover off, no quiet hours
        return {"web_push": True, "pushover": False, "quiet_start": None, "quiet_end": None}

    def _in_quiet_hours(self, prefs: dict) -> bool:
        """Check if current time is within quiet hours."""
        quiet_start = prefs.get("quiet_start")
        quiet_end = prefs.get("quiet_end")
        if not quiet_start or not quiet_end:
            return False

        now = datetime.now().time()
        if quiet_start <= quiet_end:
            return quiet_start <= now <= quiet_end
        else:
            # Wraps midnight (e.g., 22:00 → 07:00)
            return now >= quiet_start or now <= quiet_end

    async def _send_web_push(self, user_id: int, title: str, message: str):
        """Send Web Push notification to all user's subscriptions."""
        if not self.config.webpush_enabled:
            return

        pool = get_pool()
        async with pool.acquire() as conn:
            subs = await conn.fetch(
                "SELECT subscription FROM public.bh_push_subscriptions WHERE user_id = $1",
                user_id,
            )

        if not subs:
            return

        try:
            from pywebpush import webpush, WebPushException

            payload = json.dumps({"title": title, "body": message, "icon": "/icons/icon-192.png"})

            for sub_row in subs:
                subscription_info = sub_row["subscription"]
                try:
                    webpush(
                        subscription_info=subscription_info,
                        data=payload,
                        vapid_private_key=self.config.VAPID_PRIVATE_KEY,
                        vapid_claims={"sub": f"mailto:{self.config.ADMIN_EMAIL}"},
                    )
                except WebPushException as e:
                    if "410" in str(e) or "404" in str(e):
                        # Subscription expired — remove it
                        async with pool.acquire() as conn:
                            await conn.execute(
                                "DELETE FROM public.bh_push_subscriptions WHERE user_id = $1 AND subscription = $2::jsonb",
                                user_id, json.dumps(subscription_info),
                            )
                    else:
                        raise
        except ImportError:
            logger.warning("pywebpush not available")

    async def send_pushover(
        self,
        title: str,
        message: str,
        url: Optional[str] = None,
        url_title: Optional[str] = None,
        priority: int = 0,
    ) -> bool:
        """
        Public Pushover sender. Used by `hook_engine` for scheduled prompt
        delivery (R11.6) and by anything else that wants to push outside
        the per-user `send()` preference flow.

        Returns True on a 200 response from the Pushover API, False
        otherwise (including when Pushover is not configured).
        """
        if not self.config.pushover_enabled:
            return False

        data = {
            "token": self.config.PUSHOVER_API_TOKEN,
            "user": self.config.PUSHOVER_USER_KEY,
            "title": title,
            "message": message,
            "priority": priority,
        }
        if url:
            data["url"] = url
        if url_title:
            data["url_title"] = url_title

        client = get_http_client()
        resp = await client.post(
            "https://api.pushover.net/1/messages.json",
            data=data,
        )
        if resp.status_code != 200:
            logger.warning(f"Pushover returned {resp.status_code}: {resp.text}")
            return False
        return True

    async def _send_pushover(self, title: str, message: str, priority: int = 0):
        """Backward-compatible private wrapper used by `send()`."""
        await self.send_pushover(title=title, message=message, priority=priority)

    # --- Subscription management ---

    async def subscribe(self, user_id: int, subscription: dict, user_agent: str = ""):
        """Register a Web Push subscription for a user."""
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO public.bh_push_subscriptions (user_id, subscription, user_agent)
                VALUES ($1, $2::jsonb, $3)
            """, user_id, json.dumps(subscription), user_agent)

    async def update_preferences(self, user_id: int, event_type: str, prefs: dict):
        """Update notification preferences for a user + event type."""
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO public.bh_notification_prefs (user_id, event_type, web_push, pushover, quiet_start, quiet_end)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (user_id, event_type) DO UPDATE SET
                    web_push = EXCLUDED.web_push,
                    pushover = EXCLUDED.pushover,
                    quiet_start = EXCLUDED.quiet_start,
                    quiet_end = EXCLUDED.quiet_end
            """, user_id, event_type,
                prefs.get("web_push", True), prefs.get("pushover", False),
                prefs.get("quiet_start"), prefs.get("quiet_end"))
