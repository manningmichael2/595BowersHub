"""Typed capture intent + the single canonical form (R2.2 / R6.1).

``canonical()`` is a stable JSON string over ``{asset_id, domain, payload}`` with
sorted keys and no whitespace, so token mint/verify and the parity corpus agree
byte-for-byte regardless of dict ordering, whitespace, or unicode. It is the ONE
canonical form — mint, verify, and the gate all call it (prevents mint↔verify
drift, the self-DoS risk in the design).

Including ``asset_id`` binds the asset into each intent's hash: commit validates
the committed asset_id against the signed hash set, so an asset can't be swapped
in at commit time (closes the confused-deputy gap — R2.2a).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, List, Optional

# The domain allow-list — the single source of truth shared with prompt.py.
# Mirrors the n8n `Validate Commit` KNOWN set + the `Build Classify Prompt`
# domains, verbatim.
DOMAINS = frozenset(
    {
        "tool",
        "router_bit",
        "saw_blade",
        "wood",
        "album",
        "manual",
        "house_room",
        "recipe",
        "cook_log",
        "shopping_list",
        "knowledge_fact",
        "project",
        "other",
    }
)


def canonical(domain: str, payload: Optional[dict], asset_id: Optional[str]) -> str:
    """Stable canonical JSON for hashing. Sorted keys + tight separators make it
    invariant to dict ordering and whitespace; ensure_ascii=False keeps unicode
    stable (encoded to UTF-8 by the caller when hashing)."""
    return json.dumps(
        {"asset_id": asset_id or None, "domain": domain, "payload": payload or {}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def intent_hash(domain: str, payload: Optional[dict], asset_id: Optional[str]) -> str:
    return hashlib.sha256(canonical(domain, payload, asset_id).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CaptureIntent:
    domain: str
    summary: str = ""
    payload: dict = field(default_factory=dict)
    needs_more_info: List[Any] = field(default_factory=list)
    # The asset (if any) this intent will be committed against — bound into the
    # hash so the token pins it.
    asset_id: Optional[str] = None

    def canonical(self) -> str:
        return canonical(self.domain, self.payload, self.asset_id)

    def hash(self) -> str:
        return intent_hash(self.domain, self.payload, self.asset_id)

    def to_dict(self) -> dict:
        """Wire shape returned by extract (matches the n8n intent shape — no
        asset_id leaked; the asset is returned once at the top level)."""
        return {
            "domain": self.domain,
            "summary": self.summary,
            "payload": self.payload,
            "needs_more_info": list(self.needs_more_info),
        }

    @classmethod
    def from_dict(cls, d: dict, asset_id: Optional[str] = None) -> "CaptureIntent":
        return cls(
            domain=str(d.get("domain") or "other"),
            summary=str(d.get("summary") or ""),
            payload=dict(d.get("payload") or {}),
            needs_more_info=list(d.get("needs_more_info") or []),
            asset_id=asset_id,
        )
