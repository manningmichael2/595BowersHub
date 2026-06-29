"""Native skills: send email (Gmail SMTP) and read the recent inbox (Gmail IMAP)."""

from backend.services.skill_registry import native_skill


@native_skill("send-email")
async def handle_send_email(params: dict) -> dict:
    from backend.services.email_sender import send_email

    return await send_email(
        to=params.get("to", ""),
        subject=params.get("subject", ""),
        body=params.get("body", ""),
        is_html=bool(params.get("is_html", False)),
    )


@native_skill("read-email", "check-email", "inbox")
async def handle_read_email(params: dict) -> dict:
    """Summarize the recent inbox so the assistant can answer "what's in my email",
    "any unread", "did I hear from X"."""
    from backend.services.email_reader import get_recent_emails

    limit = int(params.get("limit") or 10)
    unread_only = bool(params.get("unread_only", False))
    data = await get_recent_emails(limit=limit, unread_only=unread_only)

    if data.get("error"):
        return {"_display": f"📭 {data['error']}"}

    emails = data.get("emails", [])
    unread = data.get("unread_count")
    if not emails:
        return {"_display": "📭 Inbox is empty (or no unread mail)." }

    header = "## 📬 Inbox"
    if unread is not None:
        header += f" — {unread} unread"
    lines = [header, ""]
    for e in emails:
        dot = "🔵 " if e["unread"] else ""
        sender = e["from"] or "Unknown"
        lines.append(f"- {dot}**{sender}** — {e['subject']}")
    return {
        "unread_count": unread,
        "emails": emails,
        "_display": "\n".join(lines),
    }
