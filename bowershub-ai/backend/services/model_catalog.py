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
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class ModelNotAvailableError(Exception):
    """Raised when no active model can be resolved for a role."""


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
        # invalidate may be sync (no-op) or async (resolver.reload) — Task 5 wires the latter.
        res = self._invalidate()
        if inspect.isawaitable(res):
            await res
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


# ---------------------------------------------------------------------------
# Read cache + resolution (Task 5) — Resolver
# ---------------------------------------------------------------------------
def normalize_key(model_id: str) -> str:
    """Strip provider/version decoration to a bare lookup key (R3.4 fallback only).

    NOT used to collapse providers: exact-match is tried first (so a Bedrock id like
    `us.anthropic.claude-…-v1:0` reads its OWN priced row), and this only runs on an
    exact miss to find a same-base row."""
    s = model_id
    for p in ("us.anthropic.", "anthropic."):
        if s.startswith(p):
            s = s[len(p):]
            break
    s = re.sub(r"-v\d+:\d+$", "", s)   # bedrock '-v1:0'
    s = re.sub(r":\d+$", "", s)        # trailing ':0'
    return s


class Resolver:
    """In-process read cache for the model catalog + role/alias resolution.

    Backs `/api/models` (list_active), cost lookups (row_for_cost — exact-match incl.
    inactive rows so historical usage still prices), and role aliases (resolve_role,
    default_chat_model) — all off the cache, so the router hot path takes NO per-call
    DB round-trip (perf NFR). Rebuilt by `reload()` on refresh/admin-edit."""

    _TIER_KEYWORDS = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus", "local": ""}

    def __init__(self, pool):
        self._pool = pool
        self._by_id: Dict[str, dict] = {}     # ALL rows (active + inactive) for cost lookups
        self._aliases: Dict[str, str] = {}    # role -> model_id

    async def reload(self) -> None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM public.bh_model_rates")
            aliases = await conn.fetch("SELECT role, model_id FROM public.bh_model_aliases")
        self._by_id = {r["model_id"]: dict(r) for r in rows}
        self._aliases = {r["role"]: r["model_id"] for r in aliases}

    async def _ensure_loaded(self) -> None:
        if not self._by_id:           # belt-and-suspenders: warm-on-first-read if lifespan warm was skipped
            await self.reload()

    # --- catalog reads -----------------------------------------------------
    def list_active(self) -> List[dict]:
        return [r for r in self._by_id.values() if r.get("is_active")]

    # Explicit allowlist for the PUBLIC /api/models endpoint — never `dict(row)` minus
    # price, so new bh_model_rates columns can't auto-leak. NO price fields (R5.2).
    # `id` is the model_id STRING the frontend selects (not the integer PK).
    _PUBLIC_FIELDS = (
        "provider", "display_name", "max_input_tokens", "max_output_tokens",
        "supports_vision", "supports_tools",
        "supports_thinking", "supports_effort", "supports_structured_outputs",
    )

    def list_active_public(self) -> List[dict]:
        out = []
        for r in self._by_id.values():
            if not r.get("is_active"):
                continue
            dto = {"id": r["model_id"]}
            for f in self._PUBLIC_FIELDS:
                dto[f] = r.get(f)
            out.append(dto)
        return out

    def get(self, model_id: str) -> Optional[dict]:
        return self._by_id.get(model_id)

    def row_for_cost(self, model_id: str) -> Optional[dict]:
        """Exact-match (incl. inactive) first; same-base normalize fallback (R3.4)."""
        row = self._by_id.get(model_id)
        if row is not None:
            return row
        target = normalize_key(model_id)
        for rid, r in self._by_id.items():
            if normalize_key(rid) == target:
                return r
        return None

    def price_for(self, model_id: str):
        r = self.row_for_cost(model_id)
        if r is None or r.get("input_cost_per_mtok") is None or r.get("output_cost_per_mtok") is None:
            return None
        return (float(r["input_cost_per_mtok"]), float(r["output_cost_per_mtok"]))

    # --- role resolution ---------------------------------------------------
    def resolve_role(self, role: str) -> str:
        """Resolve a logical role ('haiku'/'sonnet'/'opus'/'local') to a concrete,
        active model_id. Fail-closed (R3.4): if the alias is missing/inactive, fall
        back to a known-good active model in the same tier and alert."""
        mid = self._aliases.get(role)
        if mid is not None:
            row = self._by_id.get(mid)
            if row is not None and row.get("is_active"):
                return mid
            logger.error(
                f"model alias '{role}' -> '{mid}' is inactive/missing; failing closed to a same-tier model"
            )
        fallback = self._fallback_for_tier(role)
        if fallback is None:
            raise ModelNotAvailableError(f"no active model resolves for role '{role}'")
        return fallback

    def default_chat_model(self) -> str:
        return self.resolve_role("sonnet")

    def _fallback_for_tier(self, role: str) -> Optional[str]:
        keyword = self._TIER_KEYWORDS.get(role, role)
        want_provider = "ollama" if role == "local" else "anthropic"
        candidates = [
            r["model_id"] for r in self._by_id.values()
            if r.get("is_active") and r.get("provider") == want_provider
            and (keyword == "" or keyword in r["model_id"].lower())
        ]
        if candidates:
            return sorted(candidates)[-1]   # deterministic; later/dated IDs sort last
        # last resort: any active model of the right provider
        any_active = [r["model_id"] for r in self._by_id.values()
                      if r.get("is_active") and r.get("provider") == want_provider]
        return sorted(any_active)[-1] if any_active else None


# Module-level singleton (mirrors database.py _pool / get_pool / init_pool).
_resolver: Optional["Resolver"] = None


async def init_resolver(pool) -> "Resolver":
    """Construct + warm the resolver cache. Call in lifespan AFTER run_migrations
    and BEFORE the scheduler (T1), so the first request never races an empty cache."""
    global _resolver
    _resolver = Resolver(pool)
    await _resolver.reload()
    logger.info(f"model resolver warmed: {len(_resolver._by_id)} models, {len(_resolver._aliases)} roles")
    return _resolver


def get_resolver() -> "Resolver":
    if _resolver is None:
        raise RuntimeError("model resolver not initialized — call init_resolver(pool) in lifespan")
    return _resolver


# Cold-start fallback for role resolution when the resolver cache isn't warmed
# (tests / very early startup). Same canonical IDs as the 0005 alias seed and the
# StaticDiscoverySource — model_catalog.py is the single documented home for these
# residual literals (R2.4); every other service resolves roles, never literals.
_FALLBACK_ROLE_MODEL = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-5-20251101",
    "local": "llama3.2:3b",
}


def resolve_role(role: str) -> str:
    """Module-level role resolver (R4.2/R4.3) — the seam every service uses instead of
    a hardcoded model id. Uses the warmed resolver cache (DB-driven, no per-call DB hit)
    when available; otherwise the documented cold-start canonical default. Never raises,
    so it's safe at call sites that may run before lifespan warms the cache."""
    if _resolver is not None:
        try:
            return _resolver.resolve_role(role)
        except ModelNotAvailableError:
            pass
    return _FALLBACK_ROLE_MODEL.get(role, _FALLBACK_ROLE_MODEL["sonnet"])


def default_chat_model() -> str:
    """Default chat model, resolved from the DB (R4.4)."""
    return resolve_role("sonnet")


# ---------------------------------------------------------------------------
# Cost (Task 8) — the single cost home
# ---------------------------------------------------------------------------
def cost_for(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """The ONE cost function (R3.3). Prices from the catalog by exact key (incl.
    inactive rows, so historical usage of a deactivated model still prices) with a
    same-provider normalize fallback (R3.4). On a miss/NULL price, falls back to the
    provisional name heuristic and WARNs — it must NEVER return 0 for an unknown model
    (that would be a silent under-billing regression). Resolver-optional: if the cache
    isn't warmed it goes straight to the heuristic, so it never raises and is safe in
    tests/early-startup.

    The miss-path is byte-identical to the legacy RouterEngine._calculate_cost heuristic
    (same rates, same round(6)) so the cost-parity gate holds."""
    in_rate = out_rate = None
    if _resolver is not None:
        row = _resolver.row_for_cost(model_id)
        if row is not None and row.get("input_cost_per_mtok") is not None \
                and row.get("output_cost_per_mtok") is not None:
            in_rate = float(row["input_cost_per_mtok"])
            out_rate = float(row["output_cost_per_mtok"])
    if in_rate is None:
        logger.warning(f"no catalog price for model {model_id!r}; using provisional heuristic")
        in_rate, out_rate = _infer_pricing(model_id)
    cost = (input_tokens * in_rate / 1_000_000) + (output_tokens * out_rate / 1_000_000)
    return round(cost, 6)


# ---------------------------------------------------------------------------
# Wiring helpers (Task 6) — sources factory + discovery config
# ---------------------------------------------------------------------------
MIN_DISCOVERY_INTERVAL_HOURS = 6   # floor so we never hammer the rate-limited /v1/models


def build_default_sources(config) -> List[DiscoverySource]:
    """Construct the live discovery sources OUTSIDE ModelProvider (so they're
    injectable). Anthropic always; Ollama when configured."""
    import anthropic
    sources: List[DiscoverySource] = [
        AnthropicDiscoverySource(anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY))
    ]
    ollama_url = getattr(config, "OLLAMA_URL", None)
    if ollama_url:
        sources.append(OllamaDiscoverySource(ollama_url))
    return sources


async def get_discovery_config(pool) -> tuple:
    """Read DB-driven discovery config (R2.2): returns (interval_hours, enabled).
    Interval is clamped to the floor; both fall back to sane defaults if unset."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value_json FROM public.bh_platform_settings WHERE key LIKE 'model_discovery_%'"
        )
    cfg = {}
    for r in rows:
        v = r["value_json"]
        cfg[r["key"]] = json.loads(v) if isinstance(v, str) else v
    interval = int(cfg.get("model_discovery_interval_hours", {}).get("hours", 24))
    enabled = bool(cfg.get("model_discovery_enabled", {}).get("enabled", True))
    return max(MIN_DISCOVERY_INTERVAL_HOURS, interval), enabled
