"""Email reader — pull recent inbox messages over Gmail IMAP for the assistant.

Read-only counterpart to `email_sender.py` (which only sends). The dashboard's
emails widget has a lean version (count + subjects); this returns sender + subject
+ date + unread flag so the assistant can summarize the inbox ("you have 3 unread,
one from Chase about your statement…"). Uses the shared GMAIL_IMAP_* credentials.
"""

from __future__ import annotations

import asyncio
import imaplib
import logging
import os
from email.header import decode_header
from email.utils import parseaddr
from typing import Any

logger = logging.getLogger(__name__)


def _decode_header(raw: str) -> str:
    """Decode an RFC 2047 MIME-encoded header to a clean string."""
    out = ""
    for part, charset in decode_header(raw):
        if isinstance(part, bytes):
            out += part.decode(charset or "utf-8", errors="replace")
        else:
            out += part
    return out.replace("\r", "").replace("\n", "").strip()


def _fetch_recent_sync(limit: int, unread_only: bool) -> dict[str, Any]:
    """Blocking IMAP fetch — run via asyncio.to_thread."""
    imap_user = os.environ.get("GMAIL_IMAP_USER", "")
    imap_pass = os.environ.get("GMAIL_IMAP_PASSWORD", "")
    if not imap_user or not imap_pass:
        return {"emails": [], "unread_count": None, "error": "Email isn't configured on the server."}

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(imap_user, imap_pass)
        mail.select("INBOX", readonly=True)

        _, unseen_data = mail.search(None, "UNSEEN")
        unseen_ids = set(unseen_data[0].split()) if unseen_data[0] else set()
        unread_count = len(unseen_ids)

        search = "UNSEEN" if unread_only else "ALL"
        _, data = mail.search(None, search)
        ids = data[0].split() if data[0] else []
        recent = ids[-limit:] if len(ids) > limit else ids
        recent.reverse()  # most recent first

        emails = []
        for msg_id in recent:
            _, msg_data = mail.fetch(msg_id, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not (msg_data and msg_data[0] and isinstance(msg_data[0], tuple)):
                continue
            headers = msg_data[0][1].decode("utf-8", errors="replace")
            fields = {"from": "", "subject": "", "date": ""}
            for line in headers.splitlines():
                low = line.lower()
                if low.startswith("from:"):
                    name, addr = parseaddr(line[5:].strip())
                    fields["from"] = _decode_header(name) or addr
                elif low.startswith("subject:"):
                    fields["subject"] = _decode_header(line[8:].strip())
                elif low.startswith("date:"):
                    fields["date"] = line[5:].strip()
            emails.append({
                "from": fields["from"],
                "subject": fields["subject"] or "(no subject)",
                "date": fields["date"],
                "unread": msg_id in unseen_ids,
            })

        mail.logout()
        return {"emails": emails, "unread_count": unread_count, "error": None}

    except (imaplib.IMAP4.error, OSError, TimeoutError) as e:
        logger.warning(f"IMAP read failed: {e}")
        return {"emails": [], "unread_count": None, "error": "Couldn't reach the inbox right now."}


async def get_recent_emails(limit: int = 10, unread_only: bool = False) -> dict[str, Any]:
    """Recent inbox messages (sender/subject/date/unread) + unread count."""
    limit = max(1, min(int(limit or 10), 25))
    return await asyncio.to_thread(_fetch_recent_sync, limit, unread_only)
