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
from backend.services.pushover import send_notification

logger = logging.getLogger(__name__)

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
        # Get budgets with their MTD spend
        rows = await conn.fetch("""
            SELECT 
                b.id,
                c.name as category,
                b.amount as budget_amount,
                COALESCE(SUM(ABS(t.amount)), 0) as mtd_spend
            FROM finance.budgets b
            JOIN finance.categories c ON c.id = b.category_id
            LEFT JOIN finance.transactions t ON t.category_id = b.category_id
                AND t.posted_date >= date_trunc('month', CURRENT_DATE)
                AND t.amount < 0
                AND t.is_transfer = false
            GROUP BY b.id, c.name, b.amount
            HAVING b.amount > 0
        """)

    for row in rows:
        category = row["category"]
        budget = float(row["budget_amount"])
        spent = float(row["mtd_spend"])
        pct = (spent / budget) * 100 if budget > 0 else 0

        # 100% alert
        if pct >= 100:
            key = f"{category}:100"
            if key not in _budget_alerts_fired_today:
                _budget_alerts_fired_today.add(key)
                await send_notification(
                    title=f"🚨 Budget exceeded: {category}",
                    message=f"You've spent <b>${spent:,.0f}</b> of your <b>${budget:,.0f}</b> {category} budget ({pct:.0f}%).",
                    priority=1,
                )
                logger.info(f"Budget alert fired: {category} at {pct:.0f}%")

        # 80% alert (only if 100% hasn't already fired)
        elif pct >= 80:
            key = f"{category}:80"
            if key not in _budget_alerts_fired_today:
                _budget_alerts_fired_today.add(key)
                await send_notification(
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
    await send_notification(
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
            # Deliver via Pushover
            success = await send_notification(
                title="⏰ Reminder",
                message=r["message"],
                priority=1,
                url="https://595bowershub.tailc4d58a.ts.net",
                url_title="Open BowersHub AI",
            )

            # Mark as delivered
            if success:
                await conn.execute(
                    "UPDATE public.bh_reminders SET delivered_at = $1 WHERE id = $2",
                    now, r["id"],
                )
                logger.info(f"Reminder delivered: id={r['id']}, message={r['message'][:50]}")
            else:
                logger.warning(f"Failed to deliver reminder id={r['id']}")
