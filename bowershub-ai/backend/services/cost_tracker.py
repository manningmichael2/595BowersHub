"""
Cost tracking: logs AI API calls to api_usage_log, calculates costs from model rates.
"""

import logging
from typing import Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)


class CostTracker:
    """Tracks and logs AI API costs."""

    async def log_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        routing_layer: str,
        workspace_id: Optional[int] = None,
        user_id: Optional[int] = None,
        message_id: Optional[int] = None,
        provider: str = "anthropic",
    ):
        """Log an AI API call to the api_usage_log table."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO public.api_usage_log
                        (model, input_tokens, output_tokens, cost_usd,
                         cache_read_tokens, cache_write_tokens, workflow_name, node_name)
                    VALUES ($1, $2, $3, $4, 0, 0, $5, $6)
                """, model, input_tokens, output_tokens, cost_usd,
                    f"bowershub-ai/{routing_layer}", provider)
        except Exception as e:
            # Never block the response for logging failures
            logger.warning(f"Failed to log API usage: {e}")

    async def get_daily_summary(self) -> dict:
        """Get today's cost summary."""
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COALESCE(SUM(cost_usd), 0) as total_cost,
                    COALESCE(SUM(input_tokens), 0) as total_input,
                    COALESCE(SUM(output_tokens), 0) as total_output,
                    COUNT(*) as total_calls
                FROM public.api_usage_log
                WHERE called_at >= CURRENT_DATE
                AND workflow_name LIKE 'bowershub-ai/%'
            """)

            # Breakdown by layer
            layers = await conn.fetch("""
                SELECT
                    workflow_name,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COUNT(*) as calls
                FROM public.api_usage_log
                WHERE called_at >= CURRENT_DATE
                AND workflow_name LIKE 'bowershub-ai/%'
                GROUP BY workflow_name
            """)

        layer_breakdown = {}
        for l in layers:
            layer_name = l["workflow_name"].replace("bowershub-ai/", "")
            layer_breakdown[layer_name] = {
                "cost": float(l["cost"]),
                "calls": l["calls"],
            }

        return {
            "total_cost": float(row["total_cost"]),
            "total_input_tokens": row["total_input"],
            "total_output_tokens": row["total_output"],
            "total_calls": row["total_calls"],
            "by_layer": layer_breakdown,
        }

    async def get_weekly_breakdown(self) -> dict:
        """Get 7-day cost breakdown by layer."""
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    DATE(called_at) as day,
                    workflow_name,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COUNT(*) as calls
                FROM public.api_usage_log
                WHERE called_at >= CURRENT_DATE - INTERVAL '7 days'
                AND workflow_name LIKE 'bowershub-ai/%'
                GROUP BY DATE(called_at), workflow_name
                ORDER BY day DESC
            """)

        days = {}
        for r in rows:
            day_str = r["day"].isoformat()
            if day_str not in days:
                days[day_str] = {"total": 0.0, "layers": {}}
            layer = r["workflow_name"].replace("bowershub-ai/", "")
            days[day_str]["layers"][layer] = {"cost": float(r["cost"]), "calls": r["calls"]}
            days[day_str]["total"] += float(r["cost"])

        return days

    async def check_daily_alert(self, user_id: int, threshold: float = 2.0) -> Optional[str]:
        """Check if daily spend exceeds threshold. Returns warning message or None."""
        summary = await self.get_daily_summary()
        if summary["total_cost"] >= threshold:
            return (
                f"⚠️ Daily AI spend has reached ${summary['total_cost']:.2f} "
                f"(threshold: ${threshold:.2f}). "
                f"Consider using /commands for common lookups to save costs."
            )
        return None

    @staticmethod
    def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD. Uses hardcoded rates as fallback."""
        rates = {
            "claude-haiku-4-5-20251001": (0.80, 4.00),
            "claude-sonnet-4-5": (3.00, 15.00),
            "claude-sonnet-4": (3.00, 15.00),
            "claude-opus-4-5": (15.00, 75.00),
        }
        input_rate, output_rate = rates.get(model, (3.00, 15.00))
        cost = (input_tokens * input_rate / 1_000_000) + (output_tokens * output_rate / 1_000_000)
        return round(cost, 6)
