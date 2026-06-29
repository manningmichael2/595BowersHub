"""
Proactive alerts service — runs on schedule via apscheduler.

- Budget threshold alerts (80% / 100%)
- Inbox file count alerts
- Timed reminders delivery
"""
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Set

from backend.database import get_pool
from backend.services import authz

logger = logging.getLogger(__name__)

# Constructed lazily from env on first use (env is fixed for the process'
# lifetime, so one instance is fine). Routes through NotificationService so
# alerts honor each household member's per-user prefs + quiet hours, instead of
# the old single-shared-account `pushover.send_notification`.
_notifier = None


def _get_notifier():
    global _notifier
    if _notifier is None:
        from backend.config import load_config
        from backend.services.notifications import NotificationService

        _notifier = NotificationService(load_config())
    return _notifier


async def _all_active_user_ids(conn) -> list[int]:
    """Every active household member."""
    rows = await conn.fetch("SELECT id FROM public.bh_users WHERE is_active = true")
    return [r["id"] for r in rows]


async def _finance_user_ids(conn) -> list[int]:
    """Active members who can read finance (budgets are shared household-wide,
    so everyone with finance access gets budget alerts)."""
    rows = await conn.fetch(
        "SELECT id, role, settings_json FROM public.bh_users WHERE is_active = true"
    )
    out: list[int] = []
    for r in rows:
        user = {"id": r["id"], "role": r["role"], "settings_json": r["settings_json"]}
        if authz.resolve(user, "finance.read"):
            out.append(r["id"])
    return out

# In-memory debounce: track which budget alerts have fired today
_budget_alerts_fired_today: Set[str] = set()
_budget_alerts_date: date = date.today()

# Inbox alert debounce
_last_inbox_alert: datetime = datetime.min.replace(tzinfo=timezone.utc)


async def check_budgets():
    """Check MTD spending against budget thresholds. Notify on 80% and 100%."""
    global _budget_alerts_fired_today, _budget_alerts_date

    # Reset daily debounce
    today = date.today()
    if _budget_alerts_date != today:
        _budget_alerts_fired_today = set()
        _budget_alerts_date = today

    pool = get_pool()
    async with pool.acquire() as conn:
        finance_users = await _finance_user_ids(conn)
        from backend.services.budgets import alert_thresholds
        warn_ratio, over_ratio = await alert_thresholds(conn)  # DB-driven (R3.5)
        # Allocation-aware MTD spend via public.real_activity (split children
        # counted, transfers + investments excluded) — R2.1/R3.5.
        rows = await conn.fetch("""
            SELECT
                b.id,
                c.name as category,
                b.limit_amount as budget_amount,
                COALESCE(SUM(ABS(ra.amount)), 0) as mtd_spend
            FROM finance.budgets b
            JOIN finance.categories c ON c.id = b.category_id
            LEFT JOIN public.real_activity ra ON ra.category_id = b.category_id
                AND ra.posted_date >= date_trunc('month', CURRENT_DATE)
                AND ra.amount < 0
            WHERE b.month = date_trunc('month', CURRENT_DATE)::date
            GROUP BY b.id, c.name, b.limit_amount
            HAVING b.limit_amount > 0
        """)

    warn_pct, over_pct = warn_ratio * 100, over_ratio * 100
    for row in rows:
        category = row["category"]
        budget = float(row["budget_amount"])
        spent = float(row["mtd_spend"])
        pct = (spent / budget) * 100 if budget > 0 else 0

        # over-budget alert
        if pct >= over_pct:
            key = f"{category}:100"
            if key not in _budget_alerts_fired_today:
                _budget_alerts_fired_today.add(key)
                await _get_notifier().notify_users(
                    finance_users,
                    event_type="budget",
                    title=f"🚨 Budget exceeded: {category}",
                    message=f"You've spent <b>${spent:,.0f}</b> of your <b>${budget:,.0f}</b> {category} budget ({pct:.0f}%).",
                    priority=1,
                )
                logger.info(f"Budget alert fired: {category} at {pct:.0f}%")

        # warn alert (only if over hasn't already fired)
        elif pct >= warn_pct:
            key = f"{category}:80"
            if key not in _budget_alerts_fired_today:
                _budget_alerts_fired_today.add(key)
                await _get_notifier().notify_users(
                    finance_users,
                    event_type="budget",
                    title=f"⚠️ Budget warning: {category}",
                    message=f"You've spent <b>${spent:,.0f}</b> of your <b>${budget:,.0f}</b> {category} budget ({pct:.0f}%).",
                    priority=0,
                )
                logger.info(f"Budget warning fired: {category} at {pct:.0f}%")


async def check_inbox():
    """Notify if inbox has accumulated files."""
    global _last_inbox_alert

    inbox_path = Path("/files/inbox")
    if not inbox_path.exists():
        return

    files = [f for f in inbox_path.iterdir() if f.is_file()]
    count = len(files)

    if count < 5:
        return

    # Debounce: once per hour
    now = datetime.now(timezone.utc)
    if (now - _last_inbox_alert).total_seconds() < 3600:
        return

    _last_inbox_alert = now
    pool = get_pool()
    async with pool.acquire() as conn:
        recipients = await _all_active_user_ids(conn)  # shared household inbox
    await _get_notifier().notify_users(
        recipients,
        event_type="inbox",
        title=f"📥 {count} files in inbox",
        message=f"You have <b>{count}</b> unprocessed files waiting in your inbox.",
        priority=0,
    )
    logger.info(f"Inbox alert: {count} files")


async def check_reminders():
    """Deliver any reminders whose time has come."""
    pool = get_pool()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        # Find due reminders
        reminders = await conn.fetch("""
            SELECT id, user_id, message, deliver_at
            FROM public.bh_reminders
            WHERE deliver_at <= $1
              AND delivered_at IS NULL
            ORDER BY deliver_at
            LIMIT 10
        """, now)

        for r in reminders:
            # Reminders are per-user — deliver to the owner's own channels.
            result = await _get_notifier().notify_users(
                [r["user_id"]],
                event_type="reminder",
                title="⏰ Reminder",
                message=r["message"],
                priority=1,
                url="https://595bowershub.tailc4d58a.ts.net",
                url_title="Open BowersHub AI",
            )

            # Mark delivered once we've actually attempted for an awake user
            # (i.e. not suppressed by quiet hours) — otherwise it re-fires next
            # tick and delivers when quiet hours end, rather than looping forever
            # for a user with no working channel.
            if result["attempted"] > 0:
                await conn.execute(
                    "UPDATE public.bh_reminders SET delivered_at = $1 WHERE id = $2",
                    now, r["id"],
                )
                logger.info(
                    f"Reminder delivered: id={r['id']}, "
                    f"web_push={result['web_push_count']}, pushover={result['pushover_sent']}, "
                    f"message={r['message'][:50]}"
                )
            else:
                logger.info(f"Reminder held (quiet hours): id={r['id']}")
