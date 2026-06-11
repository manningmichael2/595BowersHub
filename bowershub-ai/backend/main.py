"""
BowersHub AI — FastAPI application entry point.
"""

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import load_config, Config
from backend.database import init_pool, close_pool, run_migrations

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# App startup time for uptime calculation
_start_time: float = 0.0


def get_start_time() -> float:
    return _start_time


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    global _start_time
    _start_time = time.time()

    # Load configuration
    config = load_config()
    app.state.config = config
    logger.info("Configuration loaded")

    # Initialize database pool
    retries = 5
    pool = None
    for attempt in range(1, retries + 1):
        try:
            pool = await init_pool(config)
            break
        except Exception as e:
            if attempt == retries:
                logger.error(f"Failed to connect to database after {retries} attempts: {e}")
                raise SystemExit(f"Database connection failed after {retries} retries")
            logger.warning(f"Database connection attempt {attempt}/{retries} failed: {e}. Retrying in 2s...")
            import asyncio
            await asyncio.sleep(2)

    # Run migrations
    await run_migrations(pool)
    app.state.pool = pool

    # Warm the model-catalog resolver cache (T1: after migrations, before scheduler) so
    # role/alias + cost lookups never take a per-call DB round-trip and never race an
    # empty cache on the first request.
    from backend.services.model_catalog import init_resolver
    await init_resolver(pool)

    # Seed admin user on first run
    from backend.services.auth import AuthService
    auth_service = AuthService(pool, config)
    await auth_service.ensure_admin_exists()

    # Initialize model provider
    from backend.services.model_provider import ModelProvider
    model_provider = ModelProvider(config)
    app.state.model_provider = model_provider

    # Initialize WebSocket manager
    from backend.websocket.manager import WebSocketManager
    ws_manager = WebSocketManager()
    app.state.ws_manager = ws_manager

    # Initialize hook engine
    from backend.services.hook_engine import HookEngine
    hook_engine = HookEngine(model_provider, config)
    await hook_engine.startup()
    app.state.hook_engine = hook_engine

    # Initialize background scheduler for in-process jobs
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from backend.services.categorizer import run_categorizer
    from backend.services.alerts import check_budgets, check_inbox, check_reminders
    from backend.services.gameday_alerts import check_gameday_alerts

    scheduler = AsyncIOScheduler()
    # Run categorizer at 2:30am daily (after SimpleFin nightly sync at 2am)
    scheduler.add_job(
        run_categorizer,
        CronTrigger(hour=2, minute=30),
        id="categorizer",
        name="Transaction Categorizer (local model)",
        replace_existing=True,
    )
    # Budget alerts — check every hour
    scheduler.add_job(
        check_budgets,
        IntervalTrigger(hours=1),
        id="budget_alerts",
        name="Budget threshold alerts",
        replace_existing=True,
    )
    # Inbox monitoring — check every 30 minutes
    scheduler.add_job(
        check_inbox,
        IntervalTrigger(minutes=30),
        id="inbox_alerts",
        name="Inbox file count alerts",
        replace_existing=True,
    )
    # Reminders — check every minute
    scheduler.add_job(
        check_reminders,
        IntervalTrigger(minutes=1),
        id="reminder_delivery",
        name="Reminder delivery",
        replace_existing=True,
    )
    # Game-day alerts — check every 30 minutes for upcoming tracked team games
    scheduler.add_job(
        check_gameday_alerts,
        IntervalTrigger(minutes=30),
        id="gameday_alerts",
        name="Game-day alerts (Pushover)",
        replace_existing=True,
    )
    # Morning briefing — 7:00 AM daily
    async def _deliver_briefing():
        try:
            from backend.services.briefing import BriefingService
            from backend.services.skill_executor import SkillExecutor
            mp = app.state.model_provider
            se = SkillExecutor(config)
            svc = BriefingService(mp, se, config)
            # Deliver to admin user (id=1) in General workspace (id=1)
            await svc.deliver(user_id=1, workspace_id=1)
        except Exception as e:
            logger.error(f"Morning briefing failed: {e}")

    scheduler.add_job(
        _deliver_briefing,
        CronTrigger(hour=7, minute=0),
        id="morning_briefing",
        name="Morning Briefing",
        replace_existing=True,
    )

    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Background scheduler started (categorizer 2:30am, briefing 7am, alerts every 30-60min, reminders every 1min, gameday every 30min)")

    # Discover and register native skill handlers
    from backend.services.skill_registry import discover_skills
    discover_skills()

    logger.info("BowersHub AI started successfully")

    yield

    # Shutdown
    if hasattr(app.state, 'scheduler'):
        app.state.scheduler.shutdown(wait=False)
    if hasattr(app.state, 'hook_engine'):
        await app.state.hook_engine.shutdown()
    await close_pool()
    logger.info("BowersHub AI shut down")


# Create FastAPI app
app = FastAPI(
    title="BowersHub AI",
    description="Personal AI Assistant Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — explicit allowlist (PUBLIC_URL + CORS_ORIGINS + local dev origins).
# A wildcard is invalid here: allow_credentials=True is incompatible with "*",
# and this proxy is reachable beyond the Tailscale network.
from backend.config import resolve_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Routes ---

from backend.routers.auth import router as auth_router
app.include_router(auth_router)

from backend.routers.workspaces import router as workspaces_router
app.include_router(workspaces_router)

from backend.routers.conversations import router as conversations_router
app.include_router(conversations_router)

from backend.routers.skills import router as skills_router
app.include_router(skills_router)

from backend.routers.hooks import router as hooks_router
app.include_router(hooks_router)

from backend.routers.files import router as files_router
app.include_router(files_router)

from backend.routers.search import router as search_router
app.include_router(search_router)

from backend.routers.admin import router as admin_router
app.include_router(admin_router)

from backend.routers.branding import router as branding_router
app.include_router(branding_router)

from backend.routers.themes import router as themes_router
app.include_router(themes_router)

from backend.routers.settings import router as settings_router
app.include_router(settings_router)

from backend.routers.briefing import router as briefing_router
app.include_router(briefing_router)

from backend.routers.quick_capture import router as quick_capture_router
app.include_router(quick_capture_router)

from backend.routers.scheduled_prompts import router as scheduled_prompts_router
app.include_router(scheduled_prompts_router)

from backend.routers.dashboard import router as dashboard_router
app.include_router(dashboard_router)

from backend.routers.db_browser import router as db_browser_router
app.include_router(db_browser_router)


# --- Slash commands endpoint (used by frontend autocomplete) ---

@app.get("/api/slash-commands")
async def list_slash_commands(workspace_id: int = 0):
    """List available slash commands for a workspace, including flags."""
    from backend.database import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT command, description, COALESCE(flags, '[]'::jsonb) as flags
            FROM public.bh_slash_commands
            WHERE is_active = true
            AND (workspace_id = $1 OR workspace_id IS NULL)
            ORDER BY command
        """, workspace_id)
    return [{"command": r["command"], "description": r["description"], "flags": json.loads(r["flags"]) if isinstance(r["flags"], str) else (r["flags"] or [])} for r in rows]


# --- Models endpoint ---

@app.get("/api/models")
async def list_models():
    """List available AI models."""
    if hasattr(app.state, 'model_provider'):
        models = await app.state.model_provider.list_models()
        return [m.model_dump() for m in models]
    return []


# --- WebSocket endpoint ---

from fastapi import WebSocket as WS

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WS):
    """WebSocket endpoint for real-time chat streaming."""
    from backend.websocket.handlers import websocket_chat_handler
    await websocket_chat_handler(
        websocket=websocket,
        ws_manager=app.state.ws_manager,
        config=app.state.config,
        model_provider=app.state.model_provider,
    )


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    from backend.database import get_pool
    pool = get_pool()

    # Check DB connectivity
    db_ok = False
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        pass

    uptime = time.time() - get_start_time()

    # Check providers
    providers = {}
    if hasattr(app.state, "model_provider"):
        for name in app.state.model_provider.providers:
            providers[name] = True

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "providers": providers,
        "active_websockets": app.state.ws_manager.active_count if hasattr(app.state, 'ws_manager') else 0,
        "uptime_seconds": int(uptime),
        "version": "0.1.0",
    }


# --- Static file serving (React PWA) ---

static_dir = Path(__file__).parent.parent / "static"

# Branding assets — `/icons/<file>` is served from `/files/branding/active/`
# so admin uploads are picked up live without touching the React bundle
# (R2.5). The manifest URLs reference the same paths with a versioned
# query string.
def _ensure_branding_active_initialized():
    """
    On first boot the host bind-mount `/files/branding/active/` is empty.
    Materialize the built-in default icon set there so `/icons/icon-*.png`
    serves valid PNGs from the very first request, before any admin upload.
    """
    from backend.services import branding_store as _bs

    branding_root = _bs._branding_root()
    active_dir = branding_root / "active"
    if active_dir.exists() and any(active_dir.iterdir()):
        return
    try:
        defaults = _bs._generate_default_set()
        _bs._write_set(active_dir, defaults)
        logger.info("Initialized default branding icons at %s", active_dir)
    except Exception as e:
        # Don't block startup — the static mount will simply 404 individual
        # icons until the admin uploads or reverts. Logged so it surfaces
        # in container logs.
        logger.warning("Could not initialize default branding icons: %s", e)


_ensure_branding_active_initialized()

# Re-derive from env (Config object isn't loaded at module import time).
import os as _os

_branding_active_dir = (
    Path(_os.environ.get("FILES_ROOT", "/files")) / "branding" / "active"
)
_branding_active_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/icons",
    StaticFiles(directory=_branding_active_dir),
    name="icons",
)

# Serve user-uploaded files (images, documents, etc.) from /files
_files_root = Path(_os.environ.get("FILES_ROOT", "/files"))
if _files_root.exists():
    app.mount("/files", StaticFiles(directory=_files_root), name="files")
    logger.info("Static file serving enabled at /files → %s", _files_root)
else:
    logger.warning("FILES_ROOT %s does not exist — /files static serving disabled", _files_root)


async def _current_icon_version() -> str:
    """Read the current icon version string from `bh_platform_settings`."""
    from backend.database import get_pool

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT value_json FROM public.bh_platform_settings
                WHERE key = 'app_icon_version'
                """
            )
        if row and row["value_json"]:
            return str(row["value_json"].get("version") or "0")
    except Exception as e:
        logger.warning("Could not read app_icon_version: %s", e)
    return "0"


if static_dir.exists():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    # Dynamic manifest with versioned icon URLs (R2.4). The base manifest
    # JSON is read from the React build output; only the icon `src` paths
    # are rewritten to include `?v=<version>` so installed PWAs and
    # browsers re-fetch the new icon on next load.
    @app.get("/manifest.json")
    async def manifest():
        import json as _json
        from fastapi.responses import JSONResponse

        manifest_path = static_dir / "manifest.json"
        try:
            data = _json.loads(manifest_path.read_text())
        except Exception as e:
            logger.warning("Could not read base manifest.json: %s", e)
            data = {
                "name": "BowersHub AI",
                "short_name": "BowersHub",
                "start_url": "/",
                "display": "standalone",
                "icons": [],
            }

        version = await _current_icon_version()

        # Override the icons array with the canonical versioned set served
        # from /icons/ (R2.5).
        data["icons"] = [
            {
                "src": f"/icons/icon-192.png?v={version}",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": f"/icons/icon-512.png?v={version}",
                "sizes": "512x512",
                "type": "image/png",
            },
            {
                "src": f"/icons/icon-maskable-512.png?v={version}",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ]

        # Web Share Target so Android's system share sheet can deliver
        # text/url/image payloads to the Quick Capture overlay (R9.6, R9.7).
        # The base manifest in `frontend/public/manifest.json` already
        # declares this block, but we re-assert it here so the dynamic
        # response stays authoritative even if the static file drifts.
        data["share_target"] = {
            "action": "/quick-capture",
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {
                "title": "title",
                "text": "text",
                "url": "url",
                "files": [
                    {
                        "name": "files",
                        "accept": ["image/*"],
                    }
                ],
            },
        }

        return JSONResponse(
            content=data,
            headers={"Cache-Control": "no-cache"},
            media_type="application/manifest+json",
        )

    @app.get("/sw.js")
    async def service_worker():
        return FileResponse(static_dir / "sw.js", media_type="application/javascript")

    # Catch-all: serve index.html for client-side routing
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        # Don't catch API or WebSocket routes
        if path.startswith("api/") or path.startswith("ws/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Not found"}, status_code=404)

        file_path = static_dir / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

        # Inject the current icon version into the index.html `<link rel="icon">`
        # tag so browsers re-fetch the icon after admin changes (R2.4, R2.5).
        index_path = static_dir / "index.html"
        if index_path.exists():
            from fastapi.responses import HTMLResponse

            html = index_path.read_text()
            version = await _current_icon_version()
            html = html.replace(
                '<link rel="icon"',
                f'<link rel="icon" data-version="{version}"',
                1,
            )
            # Rewrite icon hrefs to point at /icons/* with version query
            # string. We rewrite both the favicon link and the apple-touch-icon
            # link so installed home-screen icons refresh too.
            import re as _re

            def _rewrite_icon_href(match: "_re.Match[str]") -> str:
                tag = match.group(0)
                # Strip any pre-existing query string before appending ours
                tag = _re.sub(
                    r'href="(/icons/[^"?]+)(\?[^"]*)?"',
                    rf'href="\1?v={version}"',
                    tag,
                )
                return tag

            html = _re.sub(
                r'<link[^>]+rel="(?:icon|apple-touch-icon)"[^>]*>',
                _rewrite_icon_href,
                html,
            )
            return HTMLResponse(
                content=html,
                headers={"Cache-Control": "no-cache"},
            )
        return FileResponse(static_dir / "index.html")
