"""
Model Catalog — DB-driven model discovery, persistence, resolution, and pricing.

This module makes `public.bh_model_rates` the single source of truth for the model
catalog (§9.6 / spec: dynamic-model-discovery). It is built up across the spec's
phased rollout:

  * Task 3 (this section) — the DISCOVERY seam: pluggable `DiscoverySource`s that
    return a `DiscoveryResult{models, complete}` from each provider. No DB writes.
  * Task 4 — `CatalogRefresh`: upsert/deactivate/audit (persistence).
  * Task 5 — `Catalog` read cache + `Resolver` (role aliases, default, cost key).
  * Task 8 — consolidated cost function.

Design constraint: the Anthropic Models API returns identity + capabilities +
context window but NO pricing, so `DiscoveredModel` deliberately has no price field
— pricing stays operator-owned in `bh_model_rates`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# Provisional pricing for brand-new models (R3.2) and the cost miss-path (R3.3).
# Kept BYTE-IDENTICAL to the legacy model_provider._infer_pricing so Task 8's
# cost-parity regression test (old == new on the miss-path) holds. Do not "fix"
# the opus rate here — operator-curated prices live in bh_model_rates; this is the
# flagged-provisional default only.
def _infer_pricing(model_id: str) -> tuple:
    lower = model_id.lower()
    if "haiku" in lower:
        return (0.80, 4.00)
    if "opus" in lower:
        return (15.00, 75.00)
    if "sonnet" in lower:
        return (3.00, 15.00)
    return (3.00, 15.00)


# ---------------------------------------------------------------------------
# Discovery seam (Task 3)
# ---------------------------------------------------------------------------
@dataclass
class DiscoveredModel:
    """A model as seen by a discovery source — identity + API-sourced capabilities.

    No price field by design: the Models API supplies no pricing, so cost stays
    operator-owned in bh_model_rates and is never set from discovery.
    """
    id: str
    provider: str
    display_name: str
    max_input_tokens: Optional[int] = None      # context window; None if the source/API omits it
    max_output_tokens: Optional[int] = None
    supports_vision: bool = False
    supports_tools: bool = False
    supports_thinking: bool = False
    supports_effort: bool = False
    supports_structured_outputs: bool = False


@dataclass
class DiscoveryResult:
    """Output of one discovery run for one source.

    `complete` is the load-bearing primitive for churn-safe deactivation (R1.4):
    only a *complete* (fully fetched, no error) result lets the refresh age-out
    models. A partial/errored fetch returns complete=False and never deactivates.
    """
    models: List[DiscoveredModel] = field(default_factory=list)
    complete: bool = False


@runtime_checkable
class DiscoverySource(Protocol):
    """A pluggable source of models for one provider. Injected into CatalogRefresh
    (Task 4) so tests can substitute a fake without touching the network (R2.6)."""

    provider: str

    async def discover(self) -> DiscoveryResult: ...


def _cap(caps, name: str) -> bool:
    """Read a capability leaf's `.supported` defensively (absent → False, never guess)."""
    if caps is None:
        return False
    leaf = getattr(caps, name, None)
    if leaf is None:
        return False
    return bool(getattr(leaf, "supported", False))


def is_chat_target(model_id: str, caps) -> bool:
    """R1.5 chat-target filter — keep only usable text-conversation models.

    Grounded by T0: the live API returns only `claude-*` chat models, all with
    structured_outputs supported, and no embedding-only entries. Rule: require the
    `claude-` family, and drop a model only if it *explicitly* advertises no
    structured-output/messages capability. Unknown/absent caps → keep (defensive,
    so a capability-schema change never silently drops a real chat model).
    """
    if not model_id.startswith("claude-"):
        return False
    if caps is None:
        return True
    so = getattr(caps, "structured_outputs", None)
    if so is not None and getattr(so, "supported", None) is False:
        return False
    return True


class AnthropicDiscoverySource:
    """Discovers Anthropic models via the official SDK `client.models.list()`.

    Auto-paginates on async iteration (do not use `.data`). Reads REAL
    display_name/context/capabilities (T0 confirmed populated on anthropic>=0.105);
    absent fields fall back to None/False rather than the old fabricated guesses.
    Any exception/partial page → complete=False (refresh deactivates nothing).
    """

    provider = "anthropic"

    def __init__(self, client):
        # client: anthropic.AsyncAnthropic (constructed outside ModelProvider and injected)
        self.client = client

    async def discover(self) -> DiscoveryResult:
        models: List[DiscoveredModel] = []
        try:
            async for m in self.client.models.list(limit=100):
                caps = getattr(m, "capabilities", None)
                if not is_chat_target(m.id, caps):
                    continue
                models.append(DiscoveredModel(
                    id=m.id,
                    provider="anthropic",
                    display_name=getattr(m, "display_name", None) or m.id,
                    max_input_tokens=getattr(m, "max_input_tokens", None),
                    max_output_tokens=getattr(m, "max_tokens", None),
                    supports_vision=_cap(caps, "image_input"),
                    supports_tools=True,  # all current chat models support tools; no negative signal in caps
                    supports_thinking=_cap(caps, "thinking"),
                    supports_effort=_cap(caps, "effort"),
                    supports_structured_outputs=_cap(caps, "structured_outputs"),
                ))
            return DiscoveryResult(models=models, complete=True)
        except Exception as e:
            logger.warning(f"Anthropic model discovery failed (serving last-known): {e}")
            return DiscoveryResult(models=models, complete=False)


class OllamaDiscoverySource:
    """Discovers local models via Ollama `/api/tags`. Ollama supplies no capability
    or context metadata, so those are False/None (acceptable for the picker and the
    local-chat tier). Non-200/error → complete=False."""

    provider = "ollama"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def discover(self) -> DiscoveryResult:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
            models = []
            for m in data.get("models", []):
                name = m["name"]
                models.append(DiscoveredModel(
                    id=name,
                    provider="ollama",
                    display_name=name.replace(":", " ").title(),
                    supports_tools=("hermes" in name.lower() or "qwen" in name.lower()),
                ))
            return DiscoveryResult(models=models, complete=True)
        except Exception as e:
            logger.warning(f"Ollama model discovery failed: {e}")
            return DiscoveryResult(models=[], complete=False)


# Cold-start seed (R2.4). The ONLY hardcoded model literals in the catalog code —
# the single residual the acceptance grep allow-lists. IDs MUST match the 0005
# alias seed exactly (canonical, per the T0 decision) so resolve_role works on a
# first boot with an empty catalog and the API unreachable.
_STATIC_SEED: List[DiscoveredModel] = [
    DiscoveredModel("claude-haiku-4-5-20251001", "anthropic", "Claude Haiku 4.5",
                    max_input_tokens=200000, max_output_tokens=64000,
                    supports_vision=True, supports_tools=True, supports_thinking=True,
                    supports_effort=True, supports_structured_outputs=True),
    DiscoveredModel("claude-sonnet-4-6", "anthropic", "Claude Sonnet 4.6",
                    max_input_tokens=1000000, max_output_tokens=64000,
                    supports_vision=True, supports_tools=True, supports_thinking=True,
                    supports_effort=True, supports_structured_outputs=True),
    DiscoveredModel("claude-opus-4-5-20251101", "anthropic", "Claude Opus 4.5",
                    max_input_tokens=200000, max_output_tokens=64000,
                    supports_vision=True, supports_tools=True, supports_thinking=True,
                    supports_effort=True, supports_structured_outputs=True),
    DiscoveredModel("llama3.2:3b", "ollama", "Llama 3.2 3B (Local)"),
]


class StaticDiscoverySource:
    """Cold-start fallback seed (R2.4). Used by CatalogRefresh only to seed an empty
    catalog when live sources are unreachable. Reports complete=False so it can seed
    (upsert) but can NEVER trigger deactivation of real models if ever misused."""

    provider = "static"

    async def discover(self) -> DiscoveryResult:
        return DiscoveryResult(models=list(_STATIC_SEED), complete=False)


# ---------------------------------------------------------------------------
# Persistence / orchestration (Task 4) — CatalogRefresh
# ---------------------------------------------------------------------------
_DEFAULT_STALE_MISSES = 3


@dataclass
class RefreshSummary:
    added: int = 0
    reactivated: int = 0
    deactivated: int = 0
    price_flagged: int = 0
    complete: bool = False
    detail: dict = field(default_factory=dict)


# Capability/identity columns discovery owns (refreshed on every upsert). Price
# columns and needs_price_confirmation are NOT here — they are operator-owned (R3.1)
# and only ever set for genuinely new rows (R3.2).
_UPDATE_COLS = (
    "display_name", "max_input_tokens", "max_output_tokens",
    "supports_vision", "supports_tools",
    "supports_thinking", "supports_effort", "supports_structured_outputs",
)


class CatalogRefresh:
    """Discovers models and reconciles them into bh_model_rates — the single source
    of truth (R1.1). Single-flight (R2.5), upsert preserves operator prices (R3.1),
    churn-safe + alias-protected deactivation (R1.4), audited (R2.5), degrades to the
    last-known catalog on incomplete fetches (R2.4).

    `sources` are the live DiscoverySources (injected — R2.6). `invalidate` is called
    after a successful refresh so the Task 5 read caches rebuild (no-op until wired).
    """

    def __init__(
        self,
        pool,
        sources: List[DiscoverySource],
        *,
        static_source: Optional[DiscoverySource] = None,
        invalidate: Optional[Callable[[], None]] = None,
    ):
        self.pool = pool
        self.sources = sources
        self.static = static_source or StaticDiscoverySource()
        self._invalidate = invalidate or (lambda: None)
        self._lock = asyncio.Lock()

    async def refresh(self, *, trigger: str = "scheduled") -> RefreshSummary:
        # Single-flight: scheduled vs admin refreshes never interleave the
        # upsert + deactivate + invalidate critical section (R2.5).
        async with self._lock:
            return await self._refresh(trigger)

    async def _refresh(self, trigger: str) -> RefreshSummary:
        results = []
        for src in self.sources:
            try:
                results.append((src.provider, await src.discover()))
            except Exception as e:  # defensive — a source should already catch its own errors
                logger.warning(f"discovery source {src.provider!r} raised: {e}")
                results.append((src.provider, DiscoveryResult(models=[], complete=False)))

        discovered: List[DiscoveredModel] = [m for _, r in results for m in r.models]
        complete_providers = sorted({p for p, r in results if r.complete})
        all_complete = bool(results) and all(r.complete for _, r in results)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Cold-start (R2.4): empty catalog + nothing live → seed from static.
                existing_count = await conn.fetchval("SELECT count(*) FROM public.bh_model_rates")
                if existing_count == 0 and not discovered:
                    seed = await self.static.discover()
                    discovered = seed.models
                    logger.info("model catalog empty + no live models — seeding from static cold-start source")

                before = {
                    r["model_id"]: r["is_active"]
                    for r in await conn.fetch("SELECT model_id, is_active FROM public.bh_model_rates")
                }

                summary = RefreshSummary(complete=all_complete)
                for m in discovered:
                    if m.id in before:
                        await self._update_existing(conn, m)
                        if before[m.id] is False:
                            summary.reactivated += 1
                    else:
                        await self._insert_new(conn, m)
                        summary.added += 1
                        summary.price_flagged += 1  # new rows get a flagged provisional price

                seen_ids = [m.id for m in discovered]
                if complete_providers:
                    deactivated_rows = await conn.fetch(
                        """
                        UPDATE public.bh_model_rates
                           SET missed_fetch_count = missed_fetch_count + 1,
                               is_active = (missed_fetch_count + 1 < $1),
                               updated_at = now()
                         WHERE provider = ANY($2::text[])
                           AND model_id <> ALL($3::text[])
                           AND model_id NOT IN (SELECT model_id FROM public.bh_model_aliases)
                        RETURNING model_id, is_active
                        """,
                        await self._stale_misses(conn), complete_providers, seen_ids,
                    )
                    summary.deactivated = sum(
                        1 for r in deactivated_rows
                        if r["is_active"] is False and before.get(r["model_id"]) is True
                    )

                summary.detail = {
                    "trigger": trigger,
                    "complete_providers": complete_providers,
                    "discovered": len(discovered),
                    "by_provider": {p: {"complete": r.complete, "models": len(r.models)} for p, r in results},
                }
                await conn.execute(
                    """
                    INSERT INTO public.bh_model_refresh_log
                        (trigger, complete, added, deactivated, reactivated, price_flagged, summary)
                    VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
                    """,
                    trigger, all_complete, summary.added, summary.deactivated,
                    summary.reactivated, summary.price_flagged, json.dumps(summary.detail),
                )

        if summary.added or summary.reactivated or summary.deactivated:
            logger.info(
                f"model catalog refresh ({trigger}): +{summary.added} new, "
                f"{summary.reactivated} reactivated, {summary.deactivated} deactivated, "
                f"{summary.price_flagged} price-flagged"
            )
        else:
            logger.info(f"model catalog refresh ({trigger}): no changes (no-op)")
        self._invalidate()
        return summary

    async def _stale_misses(self, conn) -> int:
        row = await conn.fetchval(
            "SELECT value_json FROM public.bh_platform_settings WHERE key = 'model_discovery_stale_misses'"
        )
        try:
            return int(json.loads(row)["count"]) if isinstance(row, str) else int(row["count"])
        except Exception:
            return _DEFAULT_STALE_MISSES

    async def _update_existing(self, conn, m: DiscoveredModel) -> None:
        # Refresh identity/caps + lifecycle; NEVER touch price or needs_price_confirmation (R3.1).
        await conn.execute(
            """
            UPDATE public.bh_model_rates SET
                display_name = $2, max_input_tokens = $3, max_output_tokens = $4,
                supports_vision = $5, supports_tools = $6, supports_thinking = $7,
                supports_effort = $8, supports_structured_outputs = $9,
                is_active = true, last_seen_at = now(), missed_fetch_count = 0, updated_at = now()
            WHERE model_id = $1
            """,
            m.id, m.display_name, m.max_input_tokens, m.max_output_tokens,
            m.supports_vision, m.supports_tools, m.supports_thinking,
            m.supports_effort, m.supports_structured_outputs,
        )

    async def _insert_new(self, conn, m: DiscoveredModel) -> None:
        in_cost, out_cost = _infer_pricing(m.id)  # provisional, flagged (R3.2)
        await conn.execute(
            """
            INSERT INTO public.bh_model_rates
                (provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok,
                 supports_vision, supports_tools, max_output_tokens, max_input_tokens,
                 supports_thinking, supports_effort, supports_structured_outputs,
                 is_active, last_seen_at, missed_fetch_count, needs_price_confirmation)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, true, now(), 0, true)
            ON CONFLICT (model_id) DO NOTHING
            """,
            m.provider, m.id, m.display_name, in_cost, out_cost,
            m.supports_vision, m.supports_tools, m.max_output_tokens, m.max_input_tokens,
            m.supports_thinking, m.supports_effort, m.supports_structured_outputs,
        )
