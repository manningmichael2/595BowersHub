"""
Native send-email skill — replaces the n8n Send Email workflow.

Uses SMTP (Gmail App Password) to send emails directly from Python.
No n8n hop needed.
"""
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

logger = logging.getLogger(__name__)

# SMTP config from environment
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USER = os.environ.get("GMAIL_SMTP_USER", os.environ.get("ADMIN_EMAIL", ""))
SMTP_PASSWORD = os.environ.get("GMAIL_SMTP_PASSWORD", "")


async def send_email(
    to: str,
    subject: str,
    body: str,
    is_html: bool = False,
) -> dict:
    """
    Send an email via Gmail SMTP.
    
    Args:
        to: Recipient email address
        subject: Email subject line
        body: Email body (plain text or HTML)
        is_html: Whether body is HTML
    """
    if not to or "@" not in to:
        return {"error": f"Invalid recipient: '{to}'", "_display": f"⚠️ Invalid email address: `{to}`"}
    if not subject:
        return {"error": "Subject is required", "_display": "⚠️ Subject is required."}
    if not body:
        return {"error": "Body is required", "_display": "⚠️ Email body is required."}
    
    if not SMTP_USER or not SMTP_PASSWORD:
        return {
            "error": "SMTP credentials not configured",
            "_display": "⚠️ Email sending is not configured. Set GMAIL_SMTP_USER and GMAIL_SMTP_PASSWORD env vars.",
        }

    # Build the message
    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject

    if is_html:
        msg.attach(MIMEText(body, "html"))
    else:
        msg.attach(MIMEText(body, "plain"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            use_tls=True,
        )
        logger.info(f"Email sent: to={to}, subject={subject[:50]}")
        return {
            "success": True,
            "to": to,
            "subject": subject,
            "_display": f"✅ Email sent to **{to}**\n\nSubject: {subject}",
        }
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return {
            "error": f"Failed to send: {e}",
            "_display": f"⚠️ Failed to send email: {e}",
        }
