"""HMAC-SHA256 extract tokens (R2.2 / R2.2a).

Replaces n8n's decorative djb2 hash (``build-smart-capture.py`` `Parse
Classification`) with a real, keyed signature. A token binds the acting user +
workspace + the exact set of extracted intent hashes (each hash includes its
asset_id). ``commit`` verifies by:

  1. recomputing the HMAC over the token body → rejects **tampering** / wrong secret
  2. checking the 30-min expiry → rejects **expired** tokens
  3. checking uid/wid == the auth-resolved acting user/workspace → rejects **wrong-workspace**
  4. checking the committed intent's hash is a **member** of the signed set
     (NOT equality — a multi-intent extract is committed one intent at a time)

The token is ``b64url(body) + "." + b64url(sig)`` where body is canonical JSON
``{ih, ts, uid, v, wid}``. The body is self-describing but tamper-evident: any
change invalidates the signature.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Iterable, List, Tuple

TOKEN_VERSION = 1
TOKEN_TTL_SECONDS = 30 * 60
# Small allowance for clock skew between mint and verify (both are this host in
# practice, but keep it robust): a token stamped slightly in the future is ok.
_FUTURE_SKEW_SECONDS = 60


def _body_bytes(ts: int, uid: int, wid: int, intent_hashes: Iterable[str]) -> bytes:
    return json.dumps(
        {"v": TOKEN_VERSION, "ts": ts, "uid": uid, "wid": wid, "ih": sorted(intent_hashes)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode("ascii"))


def mint(
    intent_hashes: Iterable[str],
    user_id: int,
    workspace_id: int,
    secret: bytes,
    now: float,
) -> str:
    """Sign the set of intent hashes for (user_id, workspace_id) at time `now`."""
    body = _body_bytes(int(now), int(user_id), int(workspace_id), list(intent_hashes))
    sig = hmac.new(secret, body, hashlib.sha256).digest()
    return f"{_b64e(body)}.{_b64e(sig)}"


def verify(
    token: str,
    committed_intent_hash: str,
    user_id: int,
    workspace_id: int,
    secret: bytes,
    now: float,
) -> Tuple[bool, str]:
    """Return (ok, reason). ok=False carries a short, safe reason for logging/UX.

    Checks, in order: well-formedness → HMAC (tamper) → version → expiry →
    uid/wid match → membership of the committed intent's hash."""
    if not token or not isinstance(token, str) or "." not in token:
        return False, "missing or malformed extract_token"
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64d(body_b64)
        sig = _b64d(sig_b64)
    except (ValueError, binascii.Error):
        return False, "malformed extract_token encoding"

    expected = hmac.new(secret, body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return False, "extract_token signature mismatch (tampered or wrong secret)"

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False, "malformed extract_token body"

    if data.get("v") != TOKEN_VERSION:
        return False, "unsupported extract_token version"

    ts = data.get("ts")
    if not isinstance(ts, (int, float)):
        return False, "malformed extract_token timestamp"
    age = now - ts
    if age > TOKEN_TTL_SECONDS:
        return False, "extract_token has expired (valid for 30 minutes)"
    if age < -_FUTURE_SKEW_SECONDS:
        return False, "extract_token timestamp is in the future"

    if data.get("uid") != int(user_id) or data.get("wid") != int(workspace_id):
        return False, "extract_token was issued for a different user/workspace"

    ih: List[str] = data.get("ih") or []
    if committed_intent_hash not in ih:
        return False, "committed intent is not part of the signed extract (membership)"

    return True, "ok"
