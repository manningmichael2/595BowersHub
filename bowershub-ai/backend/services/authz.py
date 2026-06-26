"""
authz — the single authorization module.

The one place the role ladder, capability resolution, and (later, Task 9) per-user
feature access compose. Holds the canonical role rank; resolves a
(user, capability) -> bool; computes the frontend effective-access payload.

Import direction (design M2): this module imports only `database.get_pool` +
asyncpg — never `middleware.auth` or `skill_executor` — so `skill_executor ->
authz` stays acyclic.

Fail-closed everywhere (R1.1 / R1.3, symmetric):
  - an unknown/None role ranks below viewer (-1), so it satisfies nothing;
  - an unknown capability resolves to DENY (a rank above admin), so no role
    satisfies it.

Cache shape mirrors `model_catalog.Resolver` (warm in lifespan, `reload()` after
an admin edit). NO-HARDCODING: a capability's min_role is a `bh_capabilities`
row; retuning a gate is a DB edit + `reload()`, not a code change.
"""

import json
import logging
from typing import Optional

from backend.database import get_pool  # noqa: F401  (kept for parity; init_authz takes the pool)

logger = logging.getLogger(__name__)

# Canonical role ladder — THE single definition (R1.1). `skill_executor` imports
# this; do not redefine ranks anywhere else. Higher = more privileged.
ROLE_RANK: dict[str, int] = {"viewer": 10, "member": 20, "admin": 100}

# Sentinel rank above admin: an unknown capability resolves here so no real role
# can satisfy it (fail-closed). Distinct from every value in ROLE_RANK.
DENY = 10_000

# Code fallback for capability min-roles, used only when a row is missing from
# bh_capabilities (e.g. read before warm / pre-migration). Asserted == the 0039
# seed by a test. An unseeded *and* unknown capability still resolves to DENY.
_DEFAULT_CAPS: dict[str, str] = {
    "finance.read": "viewer",
    "finance.write": "member",
    "finance.insight.action": "member",
    "finance.delete": "admin",
    "users.manage": "admin",
    "settings.write": "admin",
    "db.query": "admin",
    "db.browser": "admin",
}

# Capabilities referenced by a live `require_capability(...)` gate. The dependency
# factory registers its literal here at import time (FastAPI evaluates the factory
# when routers are imported, before lifespan), so the boot self-check can assert
# every gated capability has a bh_capabilities row.
_REGISTERED_CAPABILITIES: set[str] = set()


def register_capability(cap: str) -> None:
    """Record a capability referenced by a require_capability gate (import-time)."""
    _REGISTERED_CAPABILITIES.add(cap)


def rank(role: Optional[str]) -> int:
    """Rank of a role; unknown/None -> -1 (below viewer, fail-closed)."""
    return ROLE_RANK.get(role or "", -1)


class CapabilityCache:
    """In-process {capability: min_role} cache from bh_capabilities, with reload().

    Mirrors model_catalog.Resolver's cache+reload shape so capability checks take
    no per-request DB round-trip. Rebuilt by reload() on an admin retune (R1.3)."""

    def __init__(self, pool):
        self._pool = pool
        self._min_role: dict[str, str] = {}

    async def reload(self) -> None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT capability, min_role FROM public.bh_capabilities"
            )
        self._min_role = {r["capability"]: r["min_role"] for r in rows}

    def min_role_rank(self, cap: str) -> int:
        """Rank a role must meet for `cap`: configured row, else code fallback,
        else DENY (unknown capability denies everyone — fail-closed)."""
        role = self._min_role.get(cap) or _DEFAULT_CAPS.get(cap)
        if role is None:
            return DENY
        return ROLE_RANK.get(role, DENY)

    def known_capabilities(self) -> set[str]:
        """Capabilities that have an actual bh_capabilities row (not just a fallback)."""
        return set(self._min_role)

    def all_capabilities(self) -> dict[str, str]:
        """Configured rows merged over the code fallback (the full known set)."""
        merged = dict(_DEFAULT_CAPS)
        merged.update(self._min_role)
        return merged


class FeatureCache:
    """In-process feature registry (bh_features) + per-user overrides
    (bh_user_feature_access) (R5.1/R5.2/R5.3).

    A capability belongs to a feature by NAMESPACE — the prefix of the feature's
    baseline_capability (finance.read -> 'finance', db.browser -> 'db'). So
    finance.write/delete/insight.action all map to the finance feature, and
    db.query maps to the database feature, with no separate hardcoded table.
    users.manage / settings.write have no feature → never feature-gated."""

    def __init__(self, pool):
        self._pool = pool
        self._features: dict[str, dict] = {}       # feature_key -> row dict
        self._by_namespace: dict[str, str] = {}    # cap-namespace -> feature_key
        self._disabled: dict[int, set[str]] = {}   # user_id -> {feature_key} (enabled=false)

    async def reload(self) -> None:
        async with self._pool.acquire() as conn:
            frows = await conn.fetch(
                "SELECT feature_key, label, nav_routes, baseline_capability, "
                "admin_only_floor FROM public.bh_features")
            orows = await conn.fetch(
                "SELECT user_id, feature_key, enabled FROM public.bh_user_feature_access")
        features, by_ns = {}, {}
        for r in frows:
            row = dict(r)
            routes = row.get("nav_routes")
            if isinstance(routes, str):       # asyncpg returns jsonb as text
                row["nav_routes"] = json.loads(routes)
            features[row["feature_key"]] = row
            bc = row.get("baseline_capability")
            if bc:
                by_ns[bc.split(".", 1)[0]] = row["feature_key"]
        disabled: dict[int, set[str]] = {}
        for r in orows:
            if not r["enabled"]:              # restrict-only: enabled=true is a no-op
                disabled.setdefault(r["user_id"], set()).add(r["feature_key"])
        self._features, self._by_namespace, self._disabled = features, by_ns, disabled

    def all_features(self) -> list[dict]:
        return list(self._features.values())

    def get(self, feature_key: str) -> Optional[dict]:
        return self._features.get(feature_key)

    def feature_of_capability(self, capability: str) -> Optional[str]:
        return self._by_namespace.get(capability.split(".", 1)[0])

    def is_disabled_for_user(self, user_id: Optional[int], feature_key: str) -> bool:
        return user_id is not None and feature_key in self._disabled.get(user_id, set())

    def has_floor(self, feature_key: str) -> bool:
        f = self._features.get(feature_key)
        return bool(f and f.get("admin_only_floor"))


# --- module singletons (mirror model_catalog.init_resolver) ------------------
_cache: Optional[CapabilityCache] = None
_features: Optional[FeatureCache] = None


async def init_authz(pool) -> CapabilityCache:
    """Warm the capability + feature caches in lifespan (after migrations)."""
    global _cache, _features
    _cache = CapabilityCache(pool)
    await _cache.reload()
    _features = FeatureCache(pool)
    await _features.reload()
    logger.info(f"authz warmed: {len(_cache._min_role)} capabilities, "
                f"{len(_features._features)} features")
    return _cache


def get_cache() -> CapabilityCache:
    if _cache is None:
        raise RuntimeError("authz not initialized — call init_authz(pool) in lifespan")
    return _cache


def get_features() -> FeatureCache:
    if _features is None:
        raise RuntimeError("authz not initialized — call init_authz(pool) in lifespan")
    return _features


async def reload() -> None:
    """Rebuild the capability + feature caches after an admin edit (R1.3)."""
    if _cache is not None:
        await _cache.reload()
    if _features is not None:
        await _features.reload()


# --- the single resolver (R5.3 precedence lives only here) -------------------
def resolve(user: dict, capability: str) -> bool:
    """True if `user` may exercise `capability` — the ONLY place the R5.3
    precedence lives:

        rank(role) >= min_role(cap)                       [DB, fail-closed]
        AND NOT feature-disabled-for-user(feature_of cap) [restrict-only]
        AND NOT (admin_only_floor(feature) AND role<admin)[unconditional]
    """
    role = user.get("role")
    if rank(role) < get_cache().min_role_rank(capability):
        return False
    feat = get_features().feature_of_capability(capability)
    if feat is not None:
        if get_features().is_disabled_for_user(user.get("id"), feat):
            return False
        if get_features().has_floor(feat) and rank(role) < ROLE_RANK["admin"]:
            return False
    return True


def effective_access(user: dict) -> dict:
    """Frontend effective-access payload for GET /me/features (R5.5) — the source
    of truth the frontend consumes (it never infers permission from role)."""
    role = user.get("role")
    caps = sorted(c for c in get_cache().all_capabilities() if resolve(user, c))
    features = []
    for f in get_features().all_features():
        bc = f.get("baseline_capability")
        features.append({
            "key": f["feature_key"],
            "label": f["label"],
            "routes": f.get("nav_routes") or [],
            "permitted": resolve(user, bc) if bc else False,
        })
    return {"role": role, "capabilities": caps, "features": features}


async def verify_registered_capabilities() -> None:
    """Boot self-check: fail startup if any live require_capability(...) gate
    references a capability with no bh_capabilities row (risk-first safety rail).

    Routers are imported before lifespan, so every gate has registered by now."""
    known = get_cache().known_capabilities()
    missing = sorted(_REGISTERED_CAPABILITIES - known)
    if missing:
        raise SystemExit(
            "authz boot self-check failed — require_capability gates reference "
            f"capabilities with no bh_capabilities row: {missing}"
        )

    # Every feature's baseline_capability must resolve to a real capability —
    # catches a typo'd seed the 0040 FK wouldn't (the FK allows NULL, and a
    # capability could be dropped later). Features warmed alongside caps.
    bad_features = sorted(
        f["feature_key"] for f in get_features().all_features()
        if f.get("baseline_capability") and f["baseline_capability"] not in known
    )
    if bad_features:
        raise SystemExit(
            "authz boot self-check failed — bh_features.baseline_capability does not "
            f"resolve to a bh_capabilities row for: {bad_features}"
        )
