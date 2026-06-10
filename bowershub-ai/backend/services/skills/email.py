"""Native skill: send email via Gmail SMTP."""

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
