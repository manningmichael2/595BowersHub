"""
Dashboard API routes: widget registry, layout persistence, and data endpoints.

Endpoints:
    GET  /api/dashboard/widgets  — list active widget types from the registry
    GET  /api/dashboard/layouts  — get authenticated user's layouts (generates defaults if none)
    PUT  /api/dashboard/layouts  — upsert the user's layout configuration
    GET  /api/dashboard/system-health — CPU, memory, disk, uptime
    GET  /api/dashboard/containers — Docker container list with status
    GET  /api/dashboard/finance/summary — MTD spending, top 5 categories, net change
    GET  /api/dashboard/finance/balances — accounts grouped by type + net worth
    GET  /api/dashboard/finance/recent-transactions — last 10 transactions
    GET  /api/dashboard/weather — current conditions + 3-day forecast
    GET  /api/dashboard/inventory — item counts per inventory table
    GET  /api/dashboard/knowledge — knowledge base file count
    GET  /api/dashboard/emails — recent email count + last 5 subjects
    GET  /api/dashboard/tailscale — device list with online status
    GET  /api/dashboard/api-spend — 7-day API usage breakdown
    GET  /api/dashboard/sports-scores — recent scores for tracked teams

Requirements: 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 11.1, 11.2
"""

from __future__ import annotations

import asyncio
import imaplib
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.database import get_pool
from backend.middleware.auth import get_current_user
from backend.services.docker_service import get_containers
from backend.services.system_health import get_system_health
from backend.services.sports_score import get_my_teams_scores

logger = logging.getLogger(__name__)


# ---- Finance column validation -----------------------------------------------

# Expected columns for each finance-related table
_FINANCE_EXPECTED_COLUMNS = {
    "finance.transactions": [
        "id", "account_id", "amount", "description", "category",
        "posted_date", "is_transfer",
    ],
    "finance.accounts": [
        "id", "name", "institution", "type", "current_balance",
    ],
}

_finance_columns_validated = False


async def _validate_finance_columns() -> None:
    """
    Check that expected finance columns exist. Logs warnings for any missing
    columns. Runs once (lazily on first finance endpoint request).
    """
    global _finance_columns_validated
    if _finance_columns_validated:
        return
    _finance_columns_validated = True

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            for table_ref, expected_cols in _FINANCE_EXPECTED_COLUMNS.items():
                schema, table = table_ref.split(".")
                rows = await conn.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = $1 AND table_name = $2
                    """,
                    schema,
                    table,
                )
                existing = {row["column_name"] for row in rows}
                for col in expected_cols:
                    if col not in existing:
                        logger.warning(
                            f"Finance column validation: {table_ref}.{col} "
                            f"is missing from the database schema"
                        )
    except Exception as e:
        logger.warning(f"Finance column validation failed: {e}")

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ---- Request/Response models ------------------------------------------------


class WidgetInstance(BaseModel):
    widget_key: str
    position: int
    config_overrides: dict = {}


class PageLayout(BaseModel):
    page_key: str
    widgets: list[WidgetInstance]


class LayoutUpdate(BaseModel):
    pages: list[PageLayout]


# ---- Helpers ----------------------------------------------------------------


async def _generate_default_layouts(user_id: int) -> list[dict[str, Any]]:
    """
    Generate default layouts for a user from the widget registry's
    `default_pages` column. Groups active widgets by the pages they belong to
    and assigns sequential positions.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT widget_key, default_pages, sort_order
              FROM public.bh_dashboard_widgets
             WHERE is_active = true
             ORDER BY sort_order
            """
        )

    # Build page -> widgets mapping from default_pages arrays
    pages: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        default_pages = row["default_pages"]
        # default_pages is a JSONB array like ["overview", "finance"]
        if not isinstance(default_pages, list):
            continue
        for page_key in default_pages:
            if page_key not in pages:
                pages[page_key] = []
            pages[page_key].append({
                "widget_key": row["widget_key"],
                "position": len(pages[page_key]),
                "config_overrides": {},
            })

    # Persist the generated defaults so subsequent GETs don't regenerate
    async with pool.acquire() as conn:
        for page_key, widgets in pages.items():
            await conn.execute(
                """
                INSERT INTO public.bh_dashboard_layouts
                    (user_id, page_key, widgets, updated_at)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (user_id, page_key) DO NOTHING
                """,
                user_id,
                page_key,
                json.dumps(widgets),
            )

    # Return the generated layouts
    return [
        {"page_key": page_key, "widgets": widgets}
        for page_key, widgets in pages.items()
    ]


# ---- Routes -----------------------------------------------------------------


@router.get("/widgets")
async def list_widgets(user: dict = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Return all active widget types from the registry."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, widget_key, display_name, description, category,
                   data_endpoint, default_config, sort_order, is_active,
                   created_at
              FROM public.bh_dashboard_widgets
             WHERE is_active = true
             ORDER BY sort_order
            """
        )
    return [dict(r) for r in rows]


@router.get("/layouts")
async def get_layouts(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return all layouts for the authenticated user. If none exist, generate
    defaults from the widget registry's default_pages column.
    """
    user_id = user["id"]
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT page_key, widgets, updated_at
              FROM public.bh_dashboard_layouts
             WHERE user_id = $1
             ORDER BY page_key
            """,
            user_id,
        )

    if rows:
        pages = [
            {
                "page_key": row["page_key"],
                "widgets": row["widgets"],
                "updated_at": row["updated_at"].isoformat()
                if row["updated_at"]
                else None,
            }
            for row in rows
        ]
        return {"pages": pages}

    # No layouts found — generate defaults
    logger.info(f"No layouts found for user {user_id}, generating defaults")
    pages = await _generate_default_layouts(user_id)
    return {"pages": pages}


@router.put("/layouts")
async def save_layouts(
    body: LayoutUpdate,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Upsert the user's layout configuration. Accepts a full set of page layouts
    and replaces any existing layouts for those pages.
    """
    user_id = user["id"]
    pool = get_pool()

    async with pool.acquire() as conn:
        for page in body.pages:
            widgets_json = json.dumps(
                [w.model_dump() for w in page.widgets]
            )
            await conn.execute(
                """
                INSERT INTO public.bh_dashboard_layouts
                    (user_id, page_key, widgets, updated_at)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (user_id, page_key)
                DO UPDATE SET widgets = $3, updated_at = now()
                """,
                user_id,
                page.page_key,
                widgets_json,
            )

    # Return the saved layouts
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT page_key, widgets, updated_at
              FROM public.bh_dashboard_layouts
             WHERE user_id = $1
             ORDER BY page_key
            """,
            user_id,
        )

    pages = [
        {
            "page_key": row["page_key"],
            "widgets": row["widgets"],
            "updated_at": row["updated_at"].isoformat()
            if row["updated_at"]
            else None,
        }
        for row in rows
    ]
    return {"pages": pages}


@router.get("/containers")
async def containers(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return a list of Docker containers with name, status, image, ports, and uptime.

    Connects to the Docker daemon via /var/run/docker.sock. If the daemon is
    unreachable, returns an empty list with an error message (HTTP 200, not 500).

    Requirements: 7.2, 7.3, 10.1
    """
    return await get_containers()


@router.get("/system-health")
async def system_health(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return current system health metrics: CPU, memory, disk, uptime.

    Delegates to the system_health service which reads from /proc filesystem.
    Response target: < 2 seconds (CPU measurement takes ~100ms).

    Requirements: 7.1, 7.3, 7.4
    """
    return await get_system_health()



# ---- Finance Endpoints -------------------------------------------------------


def _finance_error_response(error: Exception) -> dict[str, Any]:
    """
    Build a structured error response for finance endpoints.
    Returns HTTP 200 with error details so the widget can display
    the error gracefully rather than crashing.

    Requirements: 8.4
    """
    return {"error": True, "message": str(error), "data": None}


@router.get("/finance/summary")
async def finance_summary(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return month-to-date total spending, top 5 categories by spend,
    and net change from previous month.

    Requirements: 8.1, 8.4, 8.5
    """
    await _validate_finance_columns()
    pool = get_pool()

    try:
        async with pool.acquire() as conn:
            # MTD total spending (negative amounts = spending, exclude transfers)
            mtd_row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(ABS(amount)), 0) AS mtd_spending
                FROM finance.transactions
                WHERE posted_date >= date_trunc('month', CURRENT_DATE)
                  AND amount < 0
                  AND is_transfer = false
                  AND is_investment = false
                """
            )
            mtd_spending = float(mtd_row["mtd_spending"])

            # MTD income (positive amounts, exclude transfers and investments)
            mtd_income_row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(amount), 0) AS mtd_income
                FROM finance.transactions
                WHERE posted_date >= date_trunc('month', CURRENT_DATE)
                  AND amount > 0
                  AND is_transfer = false
                  AND is_investment = false
                """
            )
            mtd_income = float(mtd_income_row["mtd_income"])

            # Top 5 categories by spend this month
            top_categories_rows = await conn.fetch(
                """
                SELECT c.name as category, COALESCE(SUM(ABS(t.amount)), 0) AS total
                FROM finance.transactions t
                JOIN finance.categories c ON c.id = t.category_id
                WHERE t.posted_date >= date_trunc('month', CURRENT_DATE)
                  AND t.amount < 0
                  AND t.is_transfer = false
                GROUP BY c.name
                ORDER BY total DESC
                LIMIT 5
                """
            )
            top_categories = [
                {"category": row["category"], "total": float(row["total"])}
                for row in top_categories_rows
            ]

            # Previous month spending + income
            prev_row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(ABS(amount)) FILTER (WHERE amount < 0 AND is_transfer = false AND is_investment = false), 0) AS prev_month_spending,
                  COALESCE(SUM(amount) FILTER (WHERE amount > 0 AND is_transfer = false AND is_investment = false), 0) AS prev_month_income
                FROM finance.transactions
                WHERE posted_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                  AND posted_date < date_trunc('month', CURRENT_DATE)
                """
            )
            prev_month_spending = float(prev_row["prev_month_spending"])
            prev_month_income = float(prev_row["prev_month_income"])

            # Net change: positive means spending increased, negative means decreased
            net_change = mtd_spending - prev_month_spending

        return {
            "error": False,
            "data": {
                "mtd_spending": mtd_spending,
                "mtd_income": mtd_income,
                "top_categories": top_categories,
                "prev_month_spending": prev_month_spending,
                "prev_month_income": prev_month_income,
                "net_change": net_change,
            },
        }

    except Exception as e:
        logger.error(f"Finance summary query failed: {e}")
        return _finance_error_response(e)


@router.get("/finance/balances")
async def finance_balances(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return all account balances grouped by type (checking, savings, credit,
    investment) with a net worth total.

    Requirements: 8.2, 8.4, 8.5
    """
    await _validate_finance_columns()
    pool = get_pool()

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, org_name, account_name, last_balance
                FROM finance.accounts
                WHERE last_balance IS NOT NULL
                  AND org_name NOT IN ('Email Receipts', 'ADP Redbox', 'Credit Karma')
                ORDER BY org_name, account_name
                """
            )

        # Group accounts by org_name (since there's no 'type' column)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        net_worth = 0.0

        for row in rows:
            balance = float(row["last_balance"]) if row["last_balance"] is not None else 0.0
            org = row["org_name"] or "Other"
            name = row["account_name"] or row["id"]
            grouped[org].append({
                "name": name,
                "balance": balance,
            })
            net_worth += balance

        return {
            "error": False,
            "data": {
                "accounts_by_type": dict(grouped),
                "net_worth": net_worth,
            },
        }

    except Exception as e:
        logger.error(f"Finance balances query failed: {e}")
        return _finance_error_response(e)


@router.get("/finance/recent-transactions")
async def finance_recent_transactions(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the 10 most recent transactions with amount, description,
    category, and posted_date.

    Requirements: 8.3, 8.4, 8.5
    """
    await _validate_finance_columns()
    pool = get_pool()

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.amount, t.description, c.name as category, t.posted_date
                FROM finance.transactions t
                LEFT JOIN finance.categories c ON c.id = t.category_id
                ORDER BY t.posted_date DESC, t.created_at DESC
                LIMIT 10
                """
            )

        transactions = [
            {
                "amount": float(row["amount"]),
                "description": row["description"],
                "category": row["category"],
                "posted_date": row["posted_date"].isoformat()
                if row["posted_date"]
                else None,
            }
            for row in rows
        ]

        return {
            "error": False,
            "data": {
                "transactions": transactions,
            },
        }

    except Exception as e:
        logger.error(f"Finance recent-transactions query failed: {e}")
        return _finance_error_response(e)



# ---- Additional Data Endpoints -----------------------------------------------


from backend.http_client import get_http_session

@router.get("/weather")
async def weather(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return current weather conditions and 3-day forecast.

    Fetches from wttr.in for Clawson, MI and returns structured current
    conditions (temp °F, feels_like, conditions, humidity, wind_speed)
    plus a 3-day forecast array.

    Requirements: 9.1, 9.2, 9.3
    """
    try:
        url = "https://wttr.in/Clawson,MI?format=j1"
        async with get_http_session() as client:
            resp = await client.get(url, headers={"User-Agent": "curl/8.0"}, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current_condition", [{}])[0]
        forecast_days = data.get("weather", [])

        current_conditions = {
            "temp_f": int(current.get("temp_F", 0)),
            "feels_like_f": int(current.get("FeelsLikeF", 0)),
            "conditions": current.get("weatherDesc", [{}])[0].get("value", "Unknown"),
            "humidity": int(current.get("humidity", 0)),
            "wind_speed_mph": int(current.get("windspeedMiles", 0)),
        }

        forecast = []
        for day in forecast_days[:3]:
            hourly = day.get("hourly", [])
            noon = hourly[4] if len(hourly) > 4 else hourly[0] if hourly else {}
            forecast.append({
                "date": day.get("date", ""),
                "max_temp_f": int(day.get("maxtempF", 0)),
                "min_temp_f": int(day.get("mintempF", 0)),
                "conditions": noon.get("weatherDesc", [{}])[0].get("value", ""),
                "chance_of_rain": int(noon.get("chanceofrain", 0)),
            })

        return {
            "error": None,
            "current": current_conditions,
            "forecast": forecast,
        }

    except Exception as e:
        logger.error(f"Weather endpoint failed: {e}")
        return {"error": True, "message": "Weather service unavailable"}


@router.get("/news")
async def news(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return top news stories from AP News RSS feed.
    """
    try:
        url = "https://rss.app/feeds/v1.1/ts8mPzwbNmSGDTJx.json"
        # Fallback: AP Top Headlines RSS
        ap_url = "https://feedx.net/rss/ap.xml"

        async with get_http_session() as client:
            # Try AP News RSS (XML) and parse manually
            resp = await client.get("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", timeout=8.0)
            resp.raise_for_status()
            content = resp.text

        # Simple XML parsing for RSS items
        import re
        items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
        stories = []
        for item in items[:8]:
            title_match = re.search(r'<title>(.*?)</title>', item)
            link_match = re.search(r'<link>(.*?)</link>', item)
            pub_match = re.search(r'<pubDate>(.*?)</pubDate>', item)
            if title_match:
                title = title_match.group(1).replace('<![CDATA[', '').replace(']]>', '').strip()
                link = link_match.group(1).strip() if link_match else ""
                pub_date = pub_match.group(1).strip() if pub_match else ""
                stories.append({"title": title, "url": link, "published": pub_date})

        return {"stories": stories, "error": None}

    except Exception as e:
        logger.error(f"News endpoint failed: {e}")
        return {"stories": [], "error": str(e)}


@router.get("/inventory")
async def inventory(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return item counts per inventory table (tools, router_bits, saw_blades).
    Only counts non-archived items.

    Requirements: 11.1, 11.2
    """
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 'tools' as table_name, COUNT(*) as count
                  FROM inventory.tools WHERE archived_at IS NULL
                UNION ALL
                SELECT 'router_bits', COUNT(*)
                  FROM inventory.router_bits WHERE archived_at IS NULL
                UNION ALL
                SELECT 'saw_blades', COUNT(*)
                  FROM inventory.saw_blades WHERE archived_at IS NULL
                """
            )

        items = [
            {"table": row["table_name"], "count": int(row["count"])}
            for row in rows
        ]

        return {"items": items, "error": None}

    except Exception as e:
        logger.error(f"Inventory endpoint failed: {e}")
        return {"items": [], "error": str(e)}


@router.get("/knowledge")
async def knowledge(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Count markdown files in the /knowledge directory tree recursively.
    Also return last 5 recently modified files.

    Requirements: 11.1, 11.2
    """
    try:
        knowledge_dir = Path("/knowledge")
        if knowledge_dir.exists():
            all_files = list(knowledge_dir.rglob("*.md"))
            count = len(all_files)
            # Get 5 most recently modified files
            recent = sorted(all_files, key=lambda f: f.stat().st_mtime, reverse=True)[:5]
            recent_files = [
                {"name": f.stem, "path": str(f.relative_to(knowledge_dir))}
                for f in recent
            ]
        else:
            count = 0
            recent_files = []

        return {"file_count": count, "recent_files": recent_files, "error": None}

    except Exception as e:
        logger.error(f"Knowledge endpoint failed: {e}")
        return {"file_count": 0, "recent_files": [], "error": str(e)}


@router.get("/emails")
async def emails(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Connect to Gmail IMAP, return unread count + last 5 subjects.
    Uses asyncio.to_thread for the blocking IMAP calls.

    Requirements: 11.1, 11.2
    """
    try:
        result = await asyncio.to_thread(_fetch_emails_sync)
        return result
    except Exception as e:
        logger.error(f"Emails endpoint failed: {e}")
        return {"unread_count": None, "recent_subjects": [], "error": "IMAP unreachable"}


def _fetch_emails_sync() -> dict[str, Any]:
    """Blocking IMAP fetch — runs in a thread via asyncio.to_thread."""
    imap_user = os.environ.get("GMAIL_IMAP_USER", "")
    imap_pass = os.environ.get("GMAIL_IMAP_PASSWORD", "")

    if not imap_user or not imap_pass:
        return {"unread_count": None, "recent_subjects": [], "error": "IMAP credentials not configured"}

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(imap_user, imap_pass)
        mail.select("INBOX", readonly=True)

        # Get unread count
        status, unseen_data = mail.search(None, "UNSEEN")
        unseen_ids = unseen_data[0].split() if unseen_data[0] else []
        unread_count = len(unseen_ids)

        # Get last 5 message subjects (most recent)
        status, all_data = mail.search(None, "ALL")
        all_ids = all_data[0].split() if all_data[0] else []
        recent_ids = all_ids[-5:] if len(all_ids) >= 5 else all_ids
        recent_ids.reverse()  # Most recent first

        recent_subjects = []
        for msg_id in recent_ids:
            status, msg_data = mail.fetch(msg_id, "(BODY[HEADER.FIELDS (SUBJECT)])")
            if msg_data and msg_data[0] and isinstance(msg_data[0], tuple):
                raw_subject = msg_data[0][1].decode("utf-8", errors="replace")
                # Decode RFC 2047 MIME-encoded subject headers
                from email.header import decode_header
                subject_line = raw_subject.replace("Subject: ", "").replace("Subject:", "").strip()
                decoded_parts = decode_header(subject_line)
                subject = ""
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(charset or "utf-8", errors="replace")
                    else:
                        subject += part
                subject = subject.strip().replace("\r", "").replace("\n", "")
                if subject:
                    recent_subjects.append(subject)

        mail.logout()

        return {
            "unread_count": unread_count,
            "recent_subjects": recent_subjects,
            "error": None,
        }

    except (imaplib.IMAP4.error, OSError, TimeoutError) as e:
        logger.warning(f"IMAP connection failed: {e}")
        return {"unread_count": None, "recent_subjects": [], "error": "IMAP unreachable"}


@router.get("/tailscale")
async def tailscale(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Query Tailscale status via the local API socket.
    Requires /var/run/tailscale to be bind-mounted into the container.

    Requirements: 11.1, 11.2
    """
    try:
        transport = httpx.AsyncHTTPTransport(uds="/var/run/tailscale/tailscaled.sock")
        async with httpx.AsyncClient(transport=transport, base_url="http://local-tailscaled.sock", timeout=5.0) as client:
            resp = await client.get("/localapi/v0/status")
            resp.raise_for_status()
            data = resp.json()

        devices = []

        # Parse Self node
        self_node = data.get("Self", {})
        if self_node:
            host_name = self_node.get("HostName", "")
            ts_ips = self_node.get("TailscaleIPs", [])
            ip = ts_ips[0] if ts_ips else ""
            devices.append({
                "name": host_name,
                "online": self_node.get("Online", True),
                "ip": ip,
            })

        # Parse Peer nodes
        peers = data.get("Peer", {})
        for _key, peer in peers.items():
            host_name = peer.get("HostName", "")
            ts_ips = peer.get("TailscaleIPs", [])
            ip = ts_ips[0] if ts_ips else ""
            devices.append({
                "name": host_name,
                "online": peer.get("Online", False),
                "ip": ip,
            })

        return {"devices": devices, "error": None}

    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.warning(f"Tailscale socket not available: {e}")
        return {"devices": [], "error": "tailscale not available"}
    except Exception as e:
        logger.error(f"Tailscale endpoint failed: {e}")
        return {"devices": [], "error": "tailscale not available"}


@router.get("/api-spend")
async def api_spend(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Query public.api_usage_log for 7-day total and per-day breakdown.

    Requirements: 11.1, 11.2
    """
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DATE(called_at) as day, SUM(cost_usd) as daily_cost
                FROM public.api_usage_log
                WHERE called_at >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY DATE(called_at)
                ORDER BY day
                """
            )

        per_day = [
            {
                "date": row["day"].isoformat(),
                "cost": float(row["daily_cost"]) if row["daily_cost"] else 0.0,
            }
            for row in rows
        ]
        total_7d = sum(d["cost"] for d in per_day)

        return {"total_7d": total_7d, "per_day": per_day, "error": None}

    except Exception as e:
        logger.error(f"API spend endpoint failed: {e}")
        return {"total_7d": 0.0, "per_day": [], "error": str(e)}


@router.get("/sports-scores")
async def sports_scores(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return recent sports scores: Michael's tracked teams first,
    then today's games across MLB, NBA, NHL, NFL.

    Requirements: 11.1, 11.2
    """
    try:
        from backend.services.sports_score import get_my_teams_scores, get_sports_score

        # Get my teams first
        my_result = await get_my_teams_scores()
        my_display = my_result.get("_display", "")

        # Get today's games across all major sports
        all_featured_lines = []
        for sport in ["mlb", "nba", "nhl", "nfl", "mls", "epl", "champions league"]:
            try:
                featured = await get_sports_score(team=None, sport=sport)
                featured_games = featured.get("games", [])
                if featured_games:
                    sport_name = {"epl": "Premier League", "champions league": "Champions League"}.get(sport, sport.upper())
                    all_featured_lines.append(f"\n**{sport_name}**")
                    for g in featured_games[:6]:
                        away = g.get("away_team", "?")
                        home = g.get("home_team", "?")
                        status = g.get("status", "")
                        a_score = g.get("away_score", 0)
                        h_score = g.get("home_score", 0)
                        if "final" in status.lower() or a_score or h_score:
                            all_featured_lines.append(f"- {away} {a_score} – {h_score} {home} ({status})")
                        else:
                            all_featured_lines.append(f"- {away} @ {home} — {status}")
            except Exception:
                pass

        if all_featured_lines:
            separator = "\n---\n" if my_display else ""
            my_display += separator + "\n".join(all_featured_lines)

        if not my_display:
            my_display = "No games today."

        return {"scores": my_result.get("games", []), "display": my_display, "error": None}

    except Exception as e:
        logger.error(f"Sports scores endpoint failed: {e}")
        return {"scores": [], "display": "", "error": str(e)}
