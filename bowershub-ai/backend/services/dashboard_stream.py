import asyncio
import json
import logging
from typing import Any, Dict

from backend.routers.dashboard import (
    system_health,
    containers,
    finance_summary,
    finance_balances,
    finance_recent_transactions,
    weather,
    news,
    inventory,
    knowledge,
    emails,
    tailscale,
    api_spend,
    sports_scores
)

logger = logging.getLogger(__name__)

class DashboardStateCache:
    _instance = None

    def __init__(self):
        self.state: Dict[str, Any] = {}
        self.condition = asyncio.Condition()

    @classmethod
    def get_instance(cls) -> "DashboardStateCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def update(self, key: str, value: Any):
        async with self.condition:
            self.state[key] = value
            self.condition.notify_all()

    async def get_all(self) -> Dict[str, Any]:
        async with self.condition:
            return self.state.copy()

# The publisher writes ONE shared cache that the stream serves to every
# connected user. That is correct only because every dashboard data endpoint
# below returns household-global data — none filter by the caller (system stats,
# containers, weather/news, the single household IMAP inbox, and finance over
# the shared `real_activity`). This sentinel context is passed as `user` but is
# intentionally unused by those endpoints.
#
# INVARIANT: do NOT add a per-user endpoint to this global publisher. A widget
# whose data varies by user must be fetched per-connection in the stream
# generator (which has the real authenticated `user`), not cached globally here.
_SYSTEM_CTX = {"id": 0, "email": "system@dashboard", "role": "system"}

async def _poll_endpoint(cache: DashboardStateCache, key: str, func, interval: float):
    """Generic polling wrapper for dashboard endpoints."""
    # Add a slight staggered start based on key to avoid thundering herd on startup
    await asyncio.sleep(hash(key) % 50 / 10.0) 
    
    while True:
        try:
            data = await func(user=_SYSTEM_CTX)
            await cache.update(key, data)
        except Exception as e:
            logger.error(f"Error polling {key} for dashboard stream: {e}")
        await asyncio.sleep(interval)

_polling_tasks = []

def start_dashboard_stream_loop():
    cache = DashboardStateCache.get_instance()
    
    # Define optimal schedules (seconds)
    schedules = [
        ("system_health", system_health, 2.0),
        ("containers", containers, 10.0),
        ("tailscale", tailscale, 30.0),
        
        ("weather", weather, 900.0), # 15 mins
        ("news", news, 900.0),
        
        ("finance_summary", finance_summary, 300.0), # 5 mins
        ("finance_balances", finance_balances, 300.0),
        ("finance_recent_transactions", finance_recent_transactions, 300.0),
        
        ("inventory", inventory, 60.0),
        ("knowledge", knowledge, 60.0),
        
        ("emails", emails, 300.0),
        ("api_spend", api_spend, 3600.0), # 1 hour
        ("sports_scores", sports_scores, 300.0),
    ]
    
    for key, func, interval in schedules:
        _polling_tasks.append(asyncio.create_task(_poll_endpoint(cache, key, func, interval)))
    logger.info("Dashboard SSE publisher loop started")

def stop_dashboard_stream_loop():
    for task in _polling_tasks:
        task.cancel()
    _polling_tasks.clear()
    logger.info("Dashboard SSE publisher loop stopped")
