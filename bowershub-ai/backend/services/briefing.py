"""
Daily Briefing Service: generates a morning summary from multiple data sources.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.config import Config
from backend.database import get_pool
from backend.services.model_provider import ModelProvider
from backend.services.skill_executor import SkillExecutor

logger = logging.getLogger(__name__)


BRIEFING_PROMPT = """Generate a concise morning briefing. Use ONLY the data provided below — do NOT invent, assume, or add any information not explicitly listed (no calendar events, no to-do items, no schedule assumptions, no lifestyle suggestions).

Today: {date}

{data_sections}

Rules:
- Start with a short greeting (one line)
- Present each data section with a bold heading
- For weather, include the temperature and forecast summary (keep it to 2-3 lines)
- For emails, list sender and subject on separate lines
- For sports, show team/score on one line each
- For spending and budget, show the numbers clearly
- For upcoming bills, list them briefly
- Do NOT add filler text, suggestions, or commentary beyond the data
- Do NOT mention calendars, to-do lists, schedules, or activities unless that data is explicitly provided above
- Do NOT add "enjoy your day" or similar sign-offs"""


class BriefingService:
    """Generates daily briefing summaries from multiple data sources."""

    def __init__(self, model_provider: ModelProvider, skill_executor: SkillExecutor, config: Config):
        self.model_provider = model_provider
        self.skill_executor = skill_executor
        self.config = config

    async def generate(self, user_id: int, workspace_id: Optional[int] = None) -> str:
        """
        Generate a daily briefing by calling relevant skills and composing a summary.
        Returns the briefing content as markdown.
        """
        data_sections = []

        # Gather data from various sources (fail gracefully)
        weather = await self._get_weather(user_id)
        if weather:
            data_sections.append(f"**☀️ Weather**\n\n{weather}")
        else:
            data_sections.append("**☀️ Weather**\n\n_Weather data unavailable._")

        calendar = await self._get_calendar_events()
        data_sections.append(f"**📅 Today's Schedule**\n\n{calendar or '_No calendar events today (or calendar not configured)._'}")

        emails = await self._get_recent_emails()
        data_sections.append(f"**📬 Unread Emails**\n\n{emails or '_No unread emails._'}")

        scores = await self._get_sports_scores()
        data_sections.append(f"**⚾ Sports**\n\n{scores or '_No games today or recent scores for tracked teams._'}")

        finance = await self._get_finance_summary()
        data_sections.append(f"**💰 Finance**\n\n{finance}")

        recent_txns = await self._get_recent_notable_transactions()
        data_sections.append(f"**🧾 Recent Transactions**\n\n{recent_txns or '_No notable transactions in the last 7 days._'}")

        reminders = await self._get_upcoming_bills()
        data_sections.append(f"**🔔 Pending Reminders**\n\n{reminders or '_No reminders set. Use `/remind` to add one._'}")

        cost = await self._get_ai_cost()
        data_sections.append(f"**🤖 AI Cost**\n\n{cost or '_No AI usage recorded recently._'}")

        inbox = await self._get_inbox_count()
        data_sections.append(f"**📁 File Inbox**\n\n{inbox or '_No files waiting in inbox._'}")

        # Build directly as markdown — no LLM needed, data is already structured
        date_str = datetime.now().strftime("%A, %B %d, %Y")
        header = f"**Good morning — {date_str}**\n\n---\n"
        return header + "\n\n---\n\n".join(data_sections)

    async def generate_short(self, user_id: int) -> str:
        """Generate a short briefing — just weather + important emails."""
        sections = []

        weather = await self._get_weather(user_id)
        sections.append(f"**☀️ Weather**\n\n{weather or '_Weather data unavailable._'}")

        emails = await self._get_recent_emails()
        sections.append(f"**📬 Unread Emails**\n\n{emails or '_No unread emails._'}")

        if not sections:
            return "📭 Nothing notable right now — no weather data or unread emails."

        date_str = datetime.now().strftime("%A, %B %d")
        header = f"**Quick update — {date_str}**\n\n---\n"
        return header + "\n\n---\n\n".join(sections)

    async def _get_weather(self, user_id: Optional[int] = None) -> Optional[str]:
        """Get weather data via the native weather skill."""
        try:
            from backend.services.weather import get_weather
            result = await get_weather(location=None, user_id=user_id)
            if isinstance(result, dict) and "_display" in result:
                return result["_display"]
            if isinstance(result, dict) and "error" in result:
                return None
            return str(result)
        except Exception as e:
            logger.warning(f"Briefing weather fetch failed: {e}")
        return None

    async def _get_recent_emails(self) -> Optional[str]:
        """Fetch unread emails from Gmail INBOX via filewriter's IMAP endpoint."""
        try:
            import httpx
            from backend.http_client import get_http_client
            client = get_http_client()
            resp = await client.post(
                "http://filewriter:5001/imap/fetch-recent",
                json={"folder": "INBOX", "since_minutes": 720, "limit": 10},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data.get("ok") or not data.get("emails"):
                return None
            emails = data["emails"]
            lines = []
            for em in emails[:8]:  # Cap at 8 most recent
                sender = em.get("from_name") or em.get("from_address") or "Unknown"
                subject = em.get("subject", "(no subject)")
                lines.append(f"- **{sender}**: {subject}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Briefing email fetch failed: {e}")
        return None

    async def _get_spending_summary(self, user_id: int, workspace_id: Optional[int]) -> Optional[str]:
        """Get last week's spending via direct DB query (since sync may be stale)."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        COALESCE(SUM(ABS(amount)), 0) as total_spent,
                        COUNT(*) as transaction_count,
                        MAX(posted_date) as latest_date
                    FROM finance.transactions
                    WHERE posted_date >= CURRENT_DATE - 7
                    AND amount < 0
                    AND is_transfer = false
                """)
            if row and row["total_spent"] > 0:
                latest = row["latest_date"]
                latest_str = latest.strftime("%b %d") if latest else "?"
                return f"${float(row['total_spent']):.2f} across {row['transaction_count']} transactions (last 7 days, latest: {latest_str})"
        except Exception:
            pass
        return None

    async def _get_finance_summary(self) -> str:
        """Get spend, income, and investment activity for current and previous month.
        
        Excludes transfers (already filtered) and investments (flagged separately).
        """
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        -- Current month: real spend/income (excluding transfers AND investments)
                        COALESCE(SUM(CASE WHEN amount < 0 AND date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE) AND NOT is_investment THEN ABS(amount) ELSE 0 END), 0) as cur_spend,
                        COALESCE(SUM(CASE WHEN amount > 0 AND date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE) AND NOT is_investment THEN amount ELSE 0 END), 0) as cur_income,
                        -- Current month: investment activity
                        COALESCE(SUM(CASE WHEN date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE) AND is_investment AND amount < 0 THEN ABS(amount) ELSE 0 END), 0) as cur_inv_out,
                        COALESCE(SUM(CASE WHEN date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE) AND is_investment AND amount > 0 THEN amount ELSE 0 END), 0) as cur_inv_in,
                        -- Previous month
                        COALESCE(SUM(CASE WHEN amount < 0 AND date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE - interval '1 month') AND NOT is_investment THEN ABS(amount) ELSE 0 END), 0) as prev_spend,
                        COALESCE(SUM(CASE WHEN amount > 0 AND date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE - interval '1 month') AND NOT is_investment THEN amount ELSE 0 END), 0) as prev_income,
                        COALESCE(SUM(CASE WHEN date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE - interval '1 month') AND is_investment AND amount < 0 THEN ABS(amount) ELSE 0 END), 0) as prev_inv_out,
                        COALESCE(SUM(CASE WHEN date_trunc('month', posted_date) = date_trunc('month', CURRENT_DATE - interval '1 month') AND is_investment AND amount > 0 THEN amount ELSE 0 END), 0) as prev_inv_in,
                        MAX(posted_date) as latest_date
                    FROM finance.transactions
                    WHERE is_transfer = false
                    AND posted_date >= date_trunc('month', CURRENT_DATE - interval '1 month')
                """)
            
            if not row:
                return "_No transaction data available._"
            
            cur_spend = float(row["cur_spend"] or 0)
            cur_income = float(row["cur_income"] or 0)
            cur_inv_out = float(row["cur_inv_out"] or 0)
            cur_inv_in = float(row["cur_inv_in"] or 0)
            prev_spend = float(row["prev_spend"] or 0)
            prev_income = float(row["prev_income"] or 0)
            prev_inv_out = float(row["prev_inv_out"] or 0)
            prev_inv_in = float(row["prev_inv_in"] or 0)
            latest = row["latest_date"]
            
            now = datetime.now()
            cur_month_name = now.strftime("%B")
            from datetime import timedelta
            prev_month = (now.replace(day=1) - timedelta(days=1))
            prev_month_name = prev_month.strftime("%B")
            
            lines = []
            
            # Current month
            cur_net = cur_income - cur_spend
            cur_inv_net = cur_inv_in - cur_inv_out
            if cur_spend == 0 and cur_income == 0 and cur_inv_out == 0:
                lines.append(f"**{cur_month_name}:** _No transactions yet._")
            else:
                net_emoji = "📈" if cur_net >= 0 else "📉"
                lines.append(f"**{cur_month_name}:** {net_emoji} Cash flow **${cur_net:+,.2f}**")
                lines.append(f"  - 💚 Income: ${cur_income:,.2f}")
                lines.append(f"  - 💸 Spend: ${cur_spend:,.2f}")
                if cur_inv_out > 0 or cur_inv_in > 0:
                    if cur_inv_net < 0:
                        lines.append(f"  - 📊 Invested: ${cur_inv_out:,.2f}" + (f" (net ${cur_inv_net:+,.2f})" if cur_inv_in > 0 else ""))
                    else:
                        lines.append(f"  - 📊 From investments: ${cur_inv_in:,.2f}")
            
            lines.append("")
            
            # Previous month
            prev_net = prev_income - prev_spend
            prev_inv_net = prev_inv_in - prev_inv_out
            if prev_spend == 0 and prev_income == 0 and prev_inv_out == 0:
                lines.append(f"**{prev_month_name}:** _No data._")
            else:
                net_emoji = "📈" if prev_net >= 0 else "📉"
                lines.append(f"**{prev_month_name}:** {net_emoji} Cash flow **${prev_net:+,.2f}**")
                lines.append(f"  - 💚 Income: ${prev_income:,.2f}")
                lines.append(f"  - 💸 Spend: ${prev_spend:,.2f}")
                if prev_inv_out > 0 or prev_inv_in > 0:
                    if prev_inv_net < 0:
                        lines.append(f"  - 📊 Invested: ${prev_inv_out:,.2f}" + (f" (net ${prev_inv_net:+,.2f})" if prev_inv_in > 0 else ""))
                    else:
                        lines.append(f"  - 📊 From investments: ${prev_inv_in:,.2f}")
            
            # Note if data is stale
            if latest:
                days_stale = (datetime.now().date() - latest).days
                if days_stale > 1:
                    lines.append(f"\n_Latest transaction: {latest.strftime('%b %d')} ({days_stale} days ago) — sync may be stale._")
            
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Briefing finance summary failed: {e}")
            return "_Finance data unavailable._"

    async def _get_today_spending(self) -> Optional[str]:
        """Get today's spending so far."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        COALESCE(SUM(ABS(amount)), 0) as total_spent,
                        COUNT(*) as transaction_count
                    FROM finance.transactions
                    WHERE posted_date = CURRENT_DATE
                    AND amount < 0
                    AND is_transfer = false
                """)
            if row and row["total_spent"] > 0:
                return f"${float(row['total_spent']):.2f} across {row['transaction_count']} transactions so far today"
        except Exception:
            pass
        return None

    async def _get_weekly_budget_status(self) -> Optional[str]:
        """Get this month's spending vs budget for top categories."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT 
                        c.name as category,
                        b.limit_amount as budget,
                        COALESCE(SUM(ABS(t.amount)), 0) as spent
                    FROM finance.budgets b
                    JOIN finance.categories c ON c.id = b.category_id
                    LEFT JOIN finance.transactions t 
                        ON t.category_id = c.id
                        AND t.posted_date >= date_trunc('month', CURRENT_DATE)::date
                        AND t.posted_date <= CURRENT_DATE
                        AND t.amount < 0
                        AND t.is_transfer = false
                    WHERE b.limit_amount > 0
                    GROUP BY c.name, b.limit_amount
                    ORDER BY (COALESCE(SUM(ABS(t.amount)), 0) / b.limit_amount) DESC
                    LIMIT 5
                """)
            if rows:
                lines = []
                for r in rows:
                    spent = float(r["spent"])
                    budget = float(r["budget"])
                    if spent > 0:
                        pct = int((spent / budget) * 100)
                        flag = "⚠️" if pct >= 80 else ""
                        lines.append(f"- {r['category']}: ${spent:.0f} / ${budget:.0f} ({pct}%) {flag}")
                if lines:
                    return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Briefing budget status failed: {e}")
        return None

    async def _get_upcoming_bills(self) -> Optional[str]:
        """Get pending reminders for today."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT message, deliver_at FROM public.bh_reminders
                    WHERE delivered_at IS NULL
                    AND deliver_at <= CURRENT_DATE + interval '1 day'
                    ORDER BY deliver_at ASC
                    LIMIT 5
                """)
            if rows:
                lines = []
                for r in rows:
                    time_str = r["deliver_at"].strftime("%I:%M %p").lstrip("0")
                    lines.append(f"- {time_str} — {r['message']}")
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Briefing reminders failed: {e}")
        return None

    async def _get_sports_scores(self) -> Optional[str]:
        """Get scores and upcoming games for tracked teams.
        
        Fetches each team's most recent and upcoming game from ESPN with full
        details: opponent, time, venue, score.
        """
        from datetime import date as date_cls, timedelta
        import httpx
        from backend.http_client import get_http_client
        
        # Tracked teams: (display name, ESPN sport, ESPN league, team search string)
        tracked = [
            ("Tigers", "baseball", "mlb", "tigers"),
            ("Lions", "football", "nfl", "lions"),
            ("Pistons", "basketball", "nba", "pistons"),
            ("Red Wings", "hockey", "nhl", "red wings"),
            ("Michigan", "football", "college-football", "michigan"),
        ]
        
        finished = []  # Yesterday/today's completed games
        live = []      # In-progress
        upcoming = []  # Today's scheduled or future
        
        today = date_cls.today()
        yesterday = today - timedelta(days=1)
        
        client = get_http_client()
        for display_name, sport, league, search in tracked:
            try:
                # Check today and yesterday
                for try_date in [today, yesterday]:
                    date_str = try_date.strftime("%Y%m%d")
                    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date_str}"
                    resp = await client.get(url, timeout=8.0)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    events = data.get("events", [])
                        
                    # Find a game involving this team
                    match = None
                    for event in events:
                        competitors = event.get("competitions", [{}])[0].get("competitors", [])
                        for c in competitors:
                            team = c.get("team", {})
                            names = [
                                team.get("displayName", "").lower(),
                                team.get("name", "").lower(),
                                team.get("shortDisplayName", "").lower(),
                            ]
                            if any(search in n for n in names):
                                match = event
                                break
                        if match:
                            break
                        
                    if not match:
                        continue
                        
                    # Extract game details
                    comp = match.get("competitions", [{}])[0]
                    competitors = comp.get("competitors", [])
                    if len(competitors) < 2:
                        continue
                        
                    # ESPN puts home team first usually; sort by homeAway
                    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                        
                    home_name = home.get("team", {}).get("shortDisplayName") or home.get("team", {}).get("name", "?")
                    away_name = away.get("team", {}).get("shortDisplayName") or away.get("team", {}).get("name", "?")
                    home_score = home.get("score", "0")
                    away_score = away.get("score", "0")
                        
                    status = match.get("status", {}).get("type", {})
                    state = status.get("state", "")  # "pre", "in", "post"
                    detail = status.get("detail", "")
                    completed = status.get("completed", False)
                        
                    # Venue
                    venue = comp.get("venue", {}).get("fullName", "")
                        
                    # Time/date
                    date_iso = match.get("date", "")
                        
                    if state == "post" or completed:
                        # Final score
                        home_s = int(home_score) if str(home_score).isdigit() else home_score
                        away_s = int(away_score) if str(away_score).isdigit() else away_score
                        # Bold the winner
                        if isinstance(home_s, int) and isinstance(away_s, int):
                            if home_s > away_s:
                                line = f"- **{display_name}**: {away_name} {away_s} @ **{home_name} {home_s}** _(Final)_"
                            else:
                                line = f"- **{display_name}**: **{away_name} {away_s}** @ {home_name} {home_s} _(Final)_"
                        else:
                            line = f"- **{display_name}**: {away_name} {away_score} @ {home_name} {home_score} _(Final)_"
                        finished.append(line)
                        break  # Got a result, move to next team
                    elif state == "in":
                        # Live game
                        line = f"- 🔴 **{display_name}**: {away_name} {away_score} @ {home_name} {home_score} _({detail})_"
                        live.append(line)
                        break
                    else:
                        # Scheduled
                        time_str = ""
                        if date_iso:
                            try:
                                # Parse ISO and convert to local time (assume Detroit/EST)
                                from datetime import datetime as dt
                                game_dt = dt.fromisoformat(date_iso.replace("Z", "+00:00"))
                                # Convert to Detroit time (EDT = UTC-4 in summer)
                                local_dt = game_dt - timedelta(hours=4)
                                time_str = local_dt.strftime("%I:%M %p ET").lstrip("0")
                            except Exception:
                                time_str = detail or "TBD"
                            
                        venue_str = f" at {venue}" if venue else ""
                        line = f"- **{display_name}**: {away_name} @ {home_name} — {time_str}{venue_str}"
                        upcoming.append(line)
                        break
                            
            except Exception as e:
                logger.debug(f"Sports fetch failed for {display_name}: {e}")
                continue
        
        parts = []
        if live:
            parts.append("**🔴 Live:**\n" + "\n".join(live))
        if finished:
            parts.append("**Recent Results:**\n" + "\n".join(finished))
        if upcoming:
            parts.append("**Today's Games:**\n" + "\n".join(upcoming))
        
        return "\n\n".join(parts) if parts else None

    async def _get_inbox_count(self) -> Optional[str]:
        """Count files in the inbox directory."""
        try:
            from pathlib import Path
            inbox = Path(self.config.FILES_ROOT) / "inbox"
            if inbox.exists():
                files = list(inbox.iterdir())
                if files:
                    images = [f for f in files if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
                    return f"{len(files)} files ({len(images)} images)"
        except Exception:
            pass
        return None

    async def _get_ai_cost(self) -> Optional[str]:
        """Get last 7 days AI cost."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT 
                        COALESCE(SUM(cost_usd), 0) as total,
                        COUNT(*) as call_count
                    FROM public.api_usage_log
                    WHERE called_at >= CURRENT_DATE - 7
                """)
            if row and float(row["total"]) > 0:
                return f"${float(row['total']):.4f} ({row['call_count']} calls, last 7 days)"
        except Exception:
            pass
        return None

    async def _get_recent_notable_transactions(self) -> Optional[str]:
        """Get the last few notable transactions (>$20, last 7 days, real spending only)."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT t.posted_date, t.description, t.amount, c.name as category
                    FROM finance.transactions t
                    LEFT JOIN finance.categories c ON c.id = t.category_id
                    WHERE t.posted_date >= CURRENT_DATE - 7
                    AND t.amount < 0
                    AND ABS(t.amount) >= 20
                    AND t.is_transfer = false
                    AND t.is_investment = false
                    ORDER BY t.posted_date DESC, ABS(t.amount) DESC
                    LIMIT 8
                """)
            if rows:
                lines = []
                for r in rows:
                    desc = str(r["description"] or "—")[:35]
                    amount = abs(float(r["amount"]))
                    cat = str(r["category"] or "").replace("_", " ")
                    day = r["posted_date"].strftime("%a %b %d")
                    lines.append(f"- {day} · **${amount:,.2f}** — {desc}" + (f" _{cat}_" if cat else ""))
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Briefing recent transactions failed: {e}")
        return None

    async def _get_calendar_events(self) -> Optional[str]:
        """Get today's calendar events via the calendar service (CalDAV + App Password)."""
        try:
            from backend.services.calendar import get_today_events
            events = await get_today_events()
            if not events:
                return None
            lines = []
            for ev in events:
                time_str = ev.get("display_time", "All day")
                summary = ev.get("summary", "Untitled")
                loc = f" _(at {ev['location']})_" if ev.get("location") else ""
                lines.append(f"- **{time_str}** — {summary}{loc}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Briefing calendar fetch failed: {e}")
            return None

    async def deliver(self, user_id: int, workspace_id: int):
        """Generate and store briefing as a system message in the target workspace, then push to phone."""
        content = await self.generate(user_id, workspace_id)

        pool = get_pool()
        async with pool.acquire() as conn:
            # Find or create a "Daily Briefing" conversation
            conv = await conn.fetchrow("""
                SELECT id FROM public.bh_conversations
                WHERE workspace_id = $1 AND user_id = $2 AND title = 'Daily Briefing'
                AND is_archived = false
                ORDER BY created_at DESC LIMIT 1
            """, workspace_id, user_id)

            if not conv:
                conv = await conn.fetchrow("""
                    INSERT INTO public.bh_conversations (workspace_id, user_id, title)
                    VALUES ($1, $2, 'Daily Briefing') RETURNING id
                """, workspace_id, user_id)

            # Insert briefing as assistant message (not system — so it shows in chat naturally)
            await conn.execute("""
                INSERT INTO public.bh_messages
                    (conversation_id, role, content, routing_layer, metadata)
                VALUES ($1, 'assistant', $2, 'L1', '{"type": "briefing"}'::jsonb)
            """, conv["id"], content)

            # Update conversation timestamp
            await conn.execute(
                "UPDATE public.bh_conversations SET updated_at = now() WHERE id = $1",
                conv["id"],
            )

        # Send push notification with condensed summary
        from backend.services.pushover import send_notification
        # Build a short plain-text summary for the push notification
        lines = content.split("\n")
        # Take first 4 non-empty, non-heading lines as the push body
        summary_lines = [l.strip("*#- ") for l in lines if l.strip() and not l.startswith("**Morning")][:4]
        push_body = "\n".join(summary_lines)[:400]
        
        await send_notification(
            title="☀️ Morning Briefing",
            message=push_body or "Your daily summary is ready.",
            priority=0,
            url="https://595bowershub.tailc4d58a.ts.net",
            url_title="Open BowersHub AI",
        )

        logger.info(f"Daily briefing delivered to user {user_id} in workspace {workspace_id}")
