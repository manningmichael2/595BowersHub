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
    # Optional — elevated credentials used ONLY for the short-lived startup
    # migration connection (project-review.md C1/C7). Schema DDL (ALTER/DROP on
    # legacy postgres-owned objects, CREATE EXTENSION, triggers) needs privilege
    # the least-privilege runtime role (DB_USER=bowershub_app) lacks; the
    # 2026-06-19 deploy crash-looped because migrations ran as the non-owner app
    # role. When set, run_migrations() opens a dedicated connection as this role,
    # applies migrations, and closes it — request-handling code never holds these
    # creds. Defaults to DB_USER/DB_PASSWORD when unset (no behaviour change, e.g.
    # local/test where DB_USER is already superuser). See docs/c7-db-roles-cutover.md.
    MIGRATION_DB_USER: str = ""
    MIGRATION_DB_PASSWORD: str = ""
    JWT_SECRET: str = ""
    N8N_BASE: str = ""
    FILES_ROOT: str = "/files"
    KNOWLEDGE_ROOT: str = "/knowledge"
    # Filewriter service base URL. Env-overridable so the host isn't hardcoded
    # (project-review.md C7); default keeps the current Tailscale address working.
    FILEWRITER_URL: str = "http://100.106.180.101:5001"

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

    # Optional — public origin + CORS. PUBLIC_URL is the deployed frontend origin
    # (also used for password-reset links). CORS_ORIGINS is a comma-separated
    # allowlist of additional origins. Wildcard is never used: allow_credentials
    # requires an explicit origin list. See resolve_cors_origins().
    PUBLIC_URL: Optional[str] = None
    CORS_ORIGINS: Optional[str] = None

    # Optional — initial admin (used on first run if no users exist)
    ADMIN_EMAIL: str = "admin@bowershub.local"
    ADMIN_PASSWORD: str = ""

    # Model IDs are no longer hardcoded here — they are DB-driven and resolved via
    # backend.services.model_catalog.resolve_role(...) (spec: dynamic-model-discovery).

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def migration_db_user(self) -> str:
        """The role migrations run as. Falls back to the runtime role when no
        dedicated migration role is configured (local/test, where DB_USER is
        already privileged)."""
        return self.MIGRATION_DB_USER or self.DB_USER

    @property
    def migration_db_password(self) -> str:
        """Password for migration_db_user. Falls back only when no dedicated
        migration *user* is set — a custom migration user with a blank password
        is honoured rather than silently borrowing the runtime password."""
        if self.MIGRATION_DB_USER:
            return self.MIGRATION_DB_PASSWORD
        return self.DB_PASSWORD

    @property
    def uses_dedicated_migration_role(self) -> bool:
        """True when migrations should open their own elevated connection
        instead of reusing the runtime pool."""
        return bool(self.MIGRATION_DB_USER) and self.MIGRATION_DB_USER != self.DB_USER

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


def resolve_cors_origins() -> list:
    """Resolve the CORS allowlist from the environment.

    Safe to call at import time (does not validate required vars). Combines the
    comma-separated CORS_ORIGINS, the deployed PUBLIC_URL, and the local dev
    origins, de-duplicated. A literal "*" is dropped — it is invalid alongside
    allow_credentials=True and would silently disable credentialed CORS.
    """
    origins: list = []
    raw = os.environ.get("CORS_ORIGINS")
    if raw:
        origins.extend(o.strip().rstrip("/") for o in raw.split(",") if o.strip())
    public_url = os.environ.get("PUBLIC_URL")
    if public_url:
        origins.append(public_url.strip().rstrip("/"))
    # Local development (vite dev server).
    origins.extend(["http://localhost:5173", "http://127.0.0.1:5173"])
    resolved: list = []
    for o in origins:
        if o and o != "*" and o not in resolved:
            resolved.append(o)
    return resolved


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
        MIGRATION_DB_USER=os.environ.get("MIGRATION_DB_USER", ""),
        MIGRATION_DB_PASSWORD=os.environ.get("MIGRATION_DB_PASSWORD", ""),
        JWT_SECRET=os.environ["JWT_SECRET"],
        N8N_BASE=os.environ["N8N_BASE"],
        FILES_ROOT=os.environ.get("FILES_ROOT", "/files"),
        KNOWLEDGE_ROOT=os.environ.get("KNOWLEDGE_ROOT", "/knowledge"),
        FILEWRITER_URL=os.environ.get("FILEWRITER_URL", "http://100.106.180.101:5001"),
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
        PUBLIC_URL=os.environ.get("PUBLIC_URL"),
        CORS_ORIGINS=os.environ.get("CORS_ORIGINS"),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "admin@bowershub.local"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
    )
