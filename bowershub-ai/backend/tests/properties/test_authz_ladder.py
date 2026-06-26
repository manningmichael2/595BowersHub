"""authz core — pure/property tests (no DB).

Covers the canonical ladder, fail-closed rank/capability resolution, the
single-definition invariant, and the _DEFAULT_CAPS == 0039-seed contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.services import authz
from backend.services.authz import (
    ROLE_RANK,
    DENY,
    CapabilityCache,
    _DEFAULT_CAPS,
    rank,
    resolve,
)


def _cache_with(min_role: dict[str, str]) -> CapabilityCache:
    c = CapabilityCache(pool=None)  # reload() not called; inject the map directly
    c._min_role = dict(min_role)
    return c


# --- ladder ordering ---------------------------------------------------------
def test_ladder_strictly_ordered_viewer_member_admin():
    assert ROLE_RANK["viewer"] < ROLE_RANK["member"] < ROLE_RANK["admin"]


def test_deny_outranks_admin():
    # An unknown capability must be unsatisfiable by the highest real role.
    assert DENY > ROLE_RANK["admin"]


# --- rank() fail-closed ------------------------------------------------------
def test_rank_unknown_and_none_below_viewer():
    assert rank(None) == -1
    assert rank("") == -1
    assert rank("superuser") == -1
    assert rank("superuser") < ROLE_RANK["viewer"]


# --- capability resolution fail-closed --------------------------------------
def test_unknown_capability_denies_every_role(monkeypatch):
    monkeypatch.setattr(authz, "_cache", _cache_with({}))
    for role in ("viewer", "member", "admin", None, "superuser"):
        assert resolve({"role": role}, "nonexistent.cap") is False


def test_min_role_rank_unknown_capability_is_deny():
    # Unknown capability with no row AND no code fallback -> DENY (fail-closed).
    assert _cache_with({}).min_role_rank("totally.unknown") == DENY


def test_resolve_rank_threshold(monkeypatch):
    monkeypatch.setattr(authz, "_cache", _cache_with({
        "finance.read": "viewer", "finance.write": "member", "finance.delete": "admin",
    }))
    assert resolve({"role": "viewer"}, "finance.read") is True
    assert resolve({"role": "viewer"}, "finance.write") is False
    assert resolve({"role": "member"}, "finance.write") is True
    assert resolve({"role": "member"}, "finance.delete") is False
    assert resolve({"role": "admin"}, "finance.delete") is True


def test_code_fallback_used_when_row_missing():
    # No rows loaded, but a known capability still resolves via _DEFAULT_CAPS.
    c = _cache_with({})
    assert c.min_role_rank("finance.write") == ROLE_RANK["member"]


# --- single definition invariant --------------------------------------------
def test_skill_executor_reexports_the_one_ladder():
    from backend.services.skill_executor import ROLE_RANK as SE_ROLE_RANK
    assert SE_ROLE_RANK is ROLE_RANK  # same object, not a copy


# --- _DEFAULT_CAPS == 0039 seed ---------------------------------------------
def _parse_seed() -> dict[str, str]:
    sql = (Path(__file__).resolve().parents[2]
           / "migrations" / "0039_capabilities.sql").read_text()
    # Parse only the INSERT ... VALUES block (excludes the CHECK's IN(...) list).
    block = sql.split("VALUES", 1)[1].split("ON CONFLICT", 1)[0]
    rows = re.findall(r"\(\s*'([^']+)'\s*,\s*'(viewer|member|admin)'", block)
    return {cap: role for cap, role in rows}


def test_default_caps_equals_migration_seed():
    assert _parse_seed() == _DEFAULT_CAPS
