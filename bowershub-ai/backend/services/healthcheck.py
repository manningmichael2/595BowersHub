"""
Health Check Service — verifies all service connections and dependencies are working.

Checks: Postgres, Ollama, Filewriter (+ IMAP), SimpleFin, Anthropic, n8n, Pushover.
Returns a formatted status report.
"""
import logging
import os
import time
from typing import Dict, Optional, Tuple

import httpx
from backend.http_client import get_http_client

from backend.database import get_pool

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
FILEWRITER_URL = os.environ.get("FILEWRITER_URL", "http://filewriter:5001")
SIMPLEFIN_AUTH = os.environ.get("SIMPLEFIN_AUTH", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")
N8N_URL = os.environ.get("N8N_BASE", "http://n8n:5678")


async def check_postgres() -> Tuple[bool, str, float]:
    """Check Postgres connection and basic query."""
    start = time.time()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM finance.transactions")
            elapsed = time.time() - start
            return True, f"{row['cnt']:,} transactions", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


async def check_ollama() -> Tuple[bool, str, float]:
    """Check Ollama is reachable and has models loaded."""
    start = time.time()
    try:
        client = get_http_client()
        resp = await client.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
        elapsed = time.time() - start
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}", elapsed
        models = resp.json().get("models", [])
        names = [m["name"] for m in models[:5]]
        return True, f"{len(models)} model(s): {', '.join(names)}", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


async def check_filewriter() -> Tuple[bool, str, float]:
    """Check Filewriter is reachable."""
    start = time.time()
    try:
        client = get_http_client()
        resp = await client.get(f"{FILEWRITER_URL}/health", timeout=5.0)
        elapsed = time.time() - start
        if resp.status_code == 200:
            return True, "OK", elapsed
        return False, f"HTTP {resp.status_code}", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


async def check_imap() -> Tuple[bool, str, float]:
    """Check IMAP/email connectivity via Filewriter."""
    start = time.time()
    try:
        client = get_http_client()
        resp = await client.post(
            f"{FILEWRITER_URL}/imap/fetch-recent",
            json={"folder": "INBOX", "since_minutes": 60, "limit": 1},
        )
        elapsed = time.time() - start
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return True, f"Connected ({data.get('count', 0)} recent)", elapsed
            return False, data.get("error", "Unknown error"), elapsed
        return False, f"HTTP {resp.status_code}", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


async def check_simplefin() -> Tuple[bool, str, float]:
    """Check SimpleFin Bridge connectivity (light check — just auth, no full pull)."""
    start = time.time()
    if not SIMPLEFIN_AUTH:
        return False, "Not configured (SIMPLEFIN_AUTH)", 0
    try:
        # Fetch with a very small window (1 hour) to minimize data
        import time as t
        ts = int(t.time()) - 3600
        client = get_http_client()
        resp = await client.get(
            f"https://beta-bridge.simplefin.org/simplefin/accounts?start-date={ts}",
            headers={"Authorization": SIMPLEFIN_AUTH},
        )
        elapsed = time.time() - start
        if resp.status_code == 200:
            data = resp.json()
            errs = data.get("errors", [])
            accts = data.get("accounts", [])
            if errs:
                return True, f"{len(accts)} accounts OK, {len(errs)} need re-auth", elapsed
            return True, f"{len(accts)} accounts connected", elapsed
        return False, f"HTTP {resp.status_code}", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


async def check_anthropic() -> Tuple[bool, str, float]:
    """Check Anthropic API key is valid (just hits /v1/models)."""
    start = time.time()
    if not ANTHROPIC_API_KEY:
        return False, "Not configured", 0
    try:
        client = get_http_client()
        resp = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
        )
        elapsed = time.time() - start
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            return True, f"{len(models)} models available", elapsed
        return False, f"HTTP {resp.status_code} (key invalid?)", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


async def check_n8n() -> Tuple[bool, str, float]:
    """Check n8n is reachable."""
    start = time.time()
    try:
        client = get_http_client()
        resp = await client.get(f"{N8N_URL}/healthz", timeout=5.0)
        elapsed = time.time() - start
        if resp.status_code == 200:
            return True, "Running", elapsed
        return False, f"HTTP {resp.status_code}", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


async def check_pushover() -> Tuple[bool, str, float]:
    """Check Pushover credentials are configured (can't validate without sending)."""
    start = time.time()
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False, "Not configured", 0
    try:
        client = get_http_client()
        resp = await client.post(
            "https://api.pushover.net/1/users/validate.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY},
        )
        elapsed = time.time() - start
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == 1:
                return True, "Credentials valid", elapsed
            return False, "Invalid credentials", elapsed
        return False, f"HTTP {resp.status_code}", elapsed
    except Exception as e:
        return False, str(e)[:100], time.time() - start


# Service registry
SERVICES = {
    "postgres": ("🐘 Postgres", check_postgres),
    "ollama": ("🦙 Ollama (local AI)", check_ollama),
    "filewriter": ("📁 Filewriter", check_filewriter),
    "imap": ("📬 IMAP (Gmail)", check_imap),
    "simplefin": ("🏦 SimpleFin Bridge", check_simplefin),
    "anthropic": ("🤖 Anthropic API", check_anthropic),
    "n8n": ("⚙️ n8n", check_n8n),
    "pushover": ("📱 Pushover", check_pushover),
}


async def run_healthcheck(service: Optional[str] = None) -> dict:
    """
    Run health checks on all services (or a specific one).
    
    Args:
        service: Optional service key to check (postgres, ollama, etc.)
    
    Returns dict with _display for rendering.
    """
    checks_to_run = {}
    if service:
        # Check specific service
        key = service.lower().strip()
        if key in SERVICES:
            checks_to_run[key] = SERVICES[key]
        else:
            available = ", ".join(SERVICES.keys())
            return {
                "_display": f"⚠️ Unknown service: `{service}`\n\nAvailable: {available}",
            }
    else:
        checks_to_run = SERVICES

    results = {}
    for key, (label, check_fn) in checks_to_run.items():
        ok, detail, elapsed = await check_fn()
        results[key] = {"ok": ok, "label": label, "detail": detail, "elapsed": elapsed}

    # Build display
    lines = ["**🏥 System Health Check**\n"]
    
    all_ok = all(r["ok"] for r in results.values())
    
    for key, r in results.items():
        status = "✅" if r["ok"] else "❌"
        ms = f"{r['elapsed']*1000:.0f}ms" if r["elapsed"] else ""
        lines.append(f"- {status} **{r['label']}** — {r['detail']}" + (f" _{ms}_" if ms else ""))

    if all_ok:
        lines.append("\n_All systems operational._")
    else:
        failed = [r["label"] for r in results.values() if not r["ok"]]
        lines.append(f"\n⚠️ **{len(failed)} service(s) have issues.**")

    return {
        "all_ok": all_ok,
        "results": results,
        "_display": "\n".join(lines),
    }
