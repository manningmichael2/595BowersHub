"""
Application configuration loaded from environment variables.
All required variables are validated at startup — missing ones cause immediate exit.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Application configuration. Loaded once at startup."""

    # Required
    ANTHROPIC_API_KEY: str = ""
    DB_HOST: str = ""
    DB_PORT: int = 5432
    DB_NAME: str = ""
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    JWT_SECRET: str = ""
    N8N_BASE: str = ""
    FILES_ROOT: str = "/files"
    KNOWLEDGE_ROOT: str = "/knowledge"

    # Optional — providers enabled only if credentials present
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    OLLAMA_URL: Optional[str] = None

    # Optional — notifications
    PUSHOVER_USER_KEY: Optional[str] = None
    PUSHOVER_API_TOKEN: Optional[str] = None
    VAPID_PRIVATE_KEY: Optional[str] = None
    VAPID_PUBLIC_KEY: Optional[str] = None

    # Optional — Google Calendar via CalDAV + App Password
    # If CALDAV_URL is not set, it's auto-constructed from CALDAV_USER.
    # CALDAV_USER defaults to GMAIL_SMTP_USER if not set separately.
    # CALDAV_PASSWORD defaults to GMAIL_SMTP_PASSWORD if not set separately.
    CALDAV_URL: Optional[str] = None
    CALDAV_USER: Optional[str] = None
    CALDAV_PASSWORD: Optional[str] = None

    # Optional — initial admin (used on first run if no users exist)
    ADMIN_EMAIL: str = "admin@bowershub.local"
    ADMIN_PASSWORD: str = ""

    # Model IDs — single source of truth for all model references.
    # Update these when Anthropic releases new versions.
    HAIKU_MODEL: str = "claude-haiku-4-5-20251001"
    SONNET_MODEL: str = "claude-sonnet-4-5-20250514"
    LOCAL_MODEL: str = "llama3.2:3b"

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def aws_enabled(self) -> bool:
        return bool(self.AWS_ACCESS_KEY_ID and self.AWS_SECRET_ACCESS_KEY)

    @property
    def ollama_enabled(self) -> bool:
        return bool(self.OLLAMA_URL)

    @property
    def pushover_enabled(self) -> bool:
        return bool(self.PUSHOVER_USER_KEY and self.PUSHOVER_API_TOKEN)

    @property
    def webpush_enabled(self) -> bool:
        return bool(self.VAPID_PRIVATE_KEY and self.VAPID_PUBLIC_KEY)


REQUIRED_VARS = [
    "ANTHROPIC_API_KEY",
    "DB_HOST",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "JWT_SECRET",
    "N8N_BASE",
]


def load_config() -> Config:
    """Load configuration from environment variables. Exits if required vars are missing."""
    missing = [var for var in REQUIRED_VARS if not os.environ.get(var)]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    return Config(
        ANTHROPIC_API_KEY=os.environ["ANTHROPIC_API_KEY"],
        DB_HOST=os.environ["DB_HOST"],
        DB_PORT=int(os.environ.get("DB_PORT", "5432")),
        DB_NAME=os.environ["DB_NAME"],
        DB_USER=os.environ["DB_USER"],
        DB_PASSWORD=os.environ["DB_PASSWORD"],
        JWT_SECRET=os.environ["JWT_SECRET"],
        N8N_BASE=os.environ["N8N_BASE"],
        FILES_ROOT=os.environ.get("FILES_ROOT", "/files"),
        KNOWLEDGE_ROOT=os.environ.get("KNOWLEDGE_ROOT", "/knowledge"),
        AWS_ACCESS_KEY_ID=os.environ.get("AWS_ACCESS_KEY_ID"),
        AWS_SECRET_ACCESS_KEY=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        AWS_REGION=os.environ.get("AWS_REGION"),
        OLLAMA_URL=os.environ.get("OLLAMA_URL"),
        PUSHOVER_USER_KEY=os.environ.get("PUSHOVER_USER_KEY"),
        PUSHOVER_API_TOKEN=os.environ.get("PUSHOVER_API_TOKEN"),
        VAPID_PRIVATE_KEY=os.environ.get("VAPID_PRIVATE_KEY"),
        VAPID_PUBLIC_KEY=os.environ.get("VAPID_PUBLIC_KEY"),
        CALDAV_URL=os.environ.get("CALDAV_URL"),
        CALDAV_USER=os.environ.get("CALDAV_USER"),
        CALDAV_PASSWORD=os.environ.get("CALDAV_PASSWORD"),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "admin@bowershub.local"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
    )
