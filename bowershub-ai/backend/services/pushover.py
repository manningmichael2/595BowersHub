"""
Pushover notification service.

Sends push notifications to Michael's phone via the Pushover API.
Gracefully no-ops if credentials are not configured.
"""
import logging
import os
from typing import Optional

import httpx
from backend.http_client import get_http_client

logger = logging.getLogger(__name__)

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")


async def send_notification(
    title: str,
    message: str,
    priority: int = 0,
    url: Optional[str] = None,
    url_title: Optional[str] = None,
) -> bool:
    """
    Send a push notification via Pushover.
    
    Args:
        title: Notification title
        message: Body text (supports basic HTML: <b>, <i>, <u>, <a>)
        priority: -2 (silent) to 2 (emergency). 0 = normal, 1 = high priority.
        url: Optional URL to open when notification is tapped
        url_title: Label for the URL (shown as a button)
    
    Returns:
        True if sent successfully, False otherwise.
    """
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        logger.warning("Pushover credentials not configured — notification skipped")
        return False

    payload = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "title": title,
        "message": message,
        "priority": priority,
        "html": 1,  # Enable HTML formatting
    }
    if url:
        payload["url"] = url
    if url_title:
        payload["url_title"] = url_title

    try:
        client = get_http_client()
        resp = await client.post(PUSHOVER_API_URL, data=payload, timeout=10.0)
        resp.raise_for_status()
        logger.info(f"Pushover notification sent: {title}")
        return True
    except Exception as e:
        logger.error(f"Pushover notification failed: {e}")
        return False


async def is_configured() -> bool:
    """Check if Pushover credentials are present."""
    return bool(PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN)
