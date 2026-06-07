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

BRIEFING_PROMPT = """Generate a concise, friendly morning briefing for a personal AI assistant user. Use the data below to create a natural summary. Be brief — 5-8 bullet points max. Use emoji sparingly for visual scanning.

Today's date: {date}

Available data:
{data_sections}

Format as a clean markdown message. If any data source failed, just skip it — don't mention the failure. Start with a greeting."""


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
        weather = await self._get_weather()
        if weather:
            data_sections.append(f"**Weather:**\n{weather}")

        spending = await self._get_spending_summary(user_id, workspace_id)
        if spending:
            data_sections.append(f"**Yesterday's Spending:**\n{spending}")

        inbox = await self._get_inbox_count()
        if inbox:
            data_sections.append(f"**Inbox:**\n{inbox}")

        cost = await self._get_ai_cost()
        if cost:
            data_sections.append(f"**AI Usage (yesterday):**\n{cost}")

        if not data_sections:
            return "Good morning! I couldn't gather any data for today's briefing. All data sources may be unavailable."

        # Compose via Haiku
        try:
            result = await self.model_provider.complete(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": BRIEFING_PROMPT.format(
                    date=datetime.now().strftime("%A, %B %d, %Y"),
                    data_sections="\n\n".join(data_sections),
                )}],
                max_tokens=500,
            )
            return result.content
        except Exception as e:
            logger.error(f"Briefing generation failed: {e}")
            # Fallback: return raw data
            return f"**Morning Briefing — {datetime.now().strftime('%B %d')}**\n\n" + "\n\n".join(data_sections)

    async def _get_weather(self) -> Optional[str]:
        """Get weather data."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("https://wttr.in/?format=%C+%t+%h+%w")
                if resp.status_code == 200:
                    return resp.text.strip()
        except Exception:
            pass
        return None

    async def _get_spending_summary(self, user_id: int, workspace_id: Optional[int]) -> Optional[str]:
        """Get yesterday's spending via direct DB query."""
        try:
            # Direct DB query for spending (avoids needing workspace context)
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        COALESCE(SUM(ABS(amount)), 0) as total_spent,
                        COUNT(*) as transaction_count
                    FROM public.transactions
                    WHERE date = CURRENT_DATE - 1
                    AND amount < 0
                    AND is_transfer = false
                """)
            if row and row["total_spent"] > 0:
                return f"${float(row['total_spent']):.2f} across {row['transaction_count']} transactions"
        except Exception:
            pass
        return None

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
        """Get yesterday's AI cost."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COALESCE(SUM(cost_usd), 0) as total
                    FROM public.api_usage_log
                    WHERE created_at >= CURRENT_DATE - 1
                    AND created_at < CURRENT_DATE
                """)
            if row:
                return f"${float(row['total']):.4f}"
        except Exception:
            pass
        return None

    async def deliver(self, user_id: int, workspace_id: int):
        """Generate and store briefing as a system message in the target workspace."""
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

            # Insert briefing as system message
            await conn.execute("""
                INSERT INTO public.bh_messages
                    (conversation_id, role, content, routing_layer, metadata)
                VALUES ($1, 'system', $2, 'L1', '{"type": "briefing"}'::jsonb)
            """, conv["id"], content)

            # Update conversation timestamp
            await conn.execute(
                "UPDATE public.bh_conversations SET updated_at = now() WHERE id = $1",
                conv["id"],
            )

        logger.info(f"Daily briefing delivered to user {user_id} in workspace {workspace_id}")
