"""Cost-path tests (spec: dynamic-model-discovery, Task 8). Covers R3.3 (single cost
function, non-zero miss-path floor) and R3.4 (exact-match incl. Bedrock + inactive).

The miss-path must be BYTE-IDENTICAL to the legacy RouterEngine._calculate_cost
heuristic — that's the permanent cost-parity regression gate before the P3 cutover."""

from __future__ import annotations

import asyncpg
import pytest

from backend.config import Config
from backend.database import init_pool, run_migrations
from backend.services import model_catalog as mc
from backend.services.model_catalog import Resolver, cost_for

pytestmark = pytest.mark.asyncio


def _legacy_calc(model: str, i: int, o: int) -> float:
    """A verbatim copy of the pre-refactor RouterEngine._calculate_cost heuristic.
    The new miss-path must equal this exactly so historical cost attribution is unchanged."""
    lower = model.lower()
    if "haiku" in lower:
        ir, orr = 0.80, 4.00
    elif "opus" in lower:
        ir, orr = 15.00, 75.00
    elif "sonnet" in lower:
        ir, orr = 3.00, 15.00
    else:
        ir, orr = 3.00, 15.00
    return round((i * ir / 1_000_000) + (o * orr / 1_000_000), 6)


async def _apply_migrations(db_name, db_settings) -> asyncpg.Pool:
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test", N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    await run_migrations(pool)
    return pool


async def test_misspath_is_byte_identical_to_legacy_and_never_zero():
    """No resolver / unknown model → exact legacy heuristic, never 0 (R3.3)."""
    saved = mc._resolver
    mc._resolver = None        # force the miss-path
    try:
        grid_models = ["claude-haiku-x", "claude-opus-x", "claude-sonnet-x",
                       "us.anthropic.claude-sonnet-4-5-v1:0", "totally-unknown-model"]
        grid_tokens = [(0, 0), (1000, 500), (1_500_000, 800_000), (37, 991)]
        for model in grid_models:
            for i, o in grid_tokens:
                assert cost_for(model, i, o) == _legacy_calc(model, i, o), (model, i, o)
        assert cost_for("totally-unknown-model", 1, 1) > 0.0   # never silently 0
    finally:
        mc._resolver = saved


async def test_db_price_authoritative_bedrock_and_inactive(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    saved = mc._resolver
    try:
        async with pool.acquire() as c:
            # sentinel prices that DIFFER from the name heuristic, so we can prove the
            # DB row (not the heuristic) was read
            await c.execute("UPDATE public.bh_model_rates SET input_cost_per_mtok=9.99, output_cost_per_mtok=99.99 WHERE model_id='claude-sonnet-4-6'")
            await c.execute("UPDATE public.bh_model_rates SET input_cost_per_mtok=1.11, output_cost_per_mtok=2.22 WHERE model_id='us.anthropic.claude-sonnet-4-5-v1:0'")
            await c.execute("UPDATE public.bh_model_rates SET input_cost_per_mtok=7.77, output_cost_per_mtok=8.88, is_active=false WHERE model_id='claude-opus-4-5'")
        r = Resolver(pool)
        await r.reload()
        mc._resolver = r
        M = 1_000_000
        # DB price wins over heuristic (heuristic sonnet would be 18.0)
        assert cost_for("claude-sonnet-4-6", M, M) == round(9.99 + 99.99, 6)
        # Bedrock id reads its OWN row (B1), not the bare claude-* row nor the sonnet heuristic
        assert cost_for("us.anthropic.claude-sonnet-4-5-v1:0", M, M) == round(1.11 + 2.22, 6)
        # an INACTIVE model still prices from its retained row, not the heuristic (opus heuristic would be 90.0)
        assert cost_for("claude-opus-4-5", M, M) == round(7.77 + 8.88, 6)
    finally:
        mc._resolver = saved
        await pool.close()
