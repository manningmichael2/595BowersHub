"""
Property test for pushover_payload truncation + workspace deep-link.

**Property 12: Pushover delivery truncates to 1000 chars and includes
workspace link.**

For any string ``s`` (response_text) and any int ``ws_id``,
``hook_engine.pushover_payload(s, ws)`` returns ``{message, url}`` where:

  * ``message`` is a string with ``len(message) <= 1000`` (R11.6).
  * ``url`` is the deep-link to the workspace and includes
    ``/workspace/<ws_id>`` so tapping the Pushover notification opens the
    correct workspace.

The function is total — it never raises and accepts both dict-shaped
workspaces (``{"id": ...}``) and objects with a ``.id`` attribute.

**Validates: Requirements R11.6**

Spec references: requirements.md → R11.6; design.md → Backend Services and
Modules → hook_engine extension; tasks.md → 9.2.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from backend.services.hook_engine import (
    PUSHOVER_MESSAGE_LIMIT,
    WORKSPACE_DEEPLINK_BASE,
    pushover_payload,
)


# Sanity-check the constant the property is written against. If the limit
# ever drifts away from 1000 the assertions need to be revisited.
def test_pushover_message_limit_is_1000() -> None:
    assert PUSHOVER_MESSAGE_LIMIT == 1000


# ---------------------------------------------------------------------------
# Workspace strategies — both shapes pushover_payload accepts.
# ---------------------------------------------------------------------------

# Bound the integer range to plausible workspace ids; hypothesis still
# generates the boundary cases (1, INT_MAX, etc.) inside the range.
_ws_id = st.integers(min_value=1, max_value=10**12)


@st.composite
def workspace_dict(draw) -> dict:
    return {"id": draw(_ws_id)}


@st.composite
def workspace_object(draw):
    return SimpleNamespace(id=draw(_ws_id))


workspace_strategy = st.one_of(workspace_dict(), workspace_object())


def _ws_id_of(ws) -> int:
    """Mirror the helper's own resolution rule for the assertions."""
    if isinstance(ws, dict):
        return ws["id"]
    return getattr(ws, "id")


# ---------------------------------------------------------------------------
# Property 12 — for any string s and any int ws_id, the payload satisfies
# both invariants. We deliberately span "short", "exactly 1000", and "much
# longer" by mixing several text strategies.
# ---------------------------------------------------------------------------

_short_text = st.text(max_size=200)
_boundary_text = st.text(min_size=999, max_size=1001)
_long_text = st.text(min_size=1001, max_size=5000)
_text_strategy = st.one_of(_short_text, _boundary_text, _long_text)


@given(s=_text_strategy, ws=workspace_strategy)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_pushover_payload_truncates_and_links(s: str, ws) -> None:
    """For any (s, ws), message <= 1000 chars and url includes the workspace path."""
    payload = pushover_payload(s, ws)

    # Shape: dict with exactly the two keys expected by the helper's contract.
    assert isinstance(payload, dict)
    assert "message" in payload
    assert "url" in payload

    message = payload["message"]
    url = payload["url"]

    # Property part 1: truncation invariant.
    assert isinstance(message, str)
    assert len(message) <= PUSHOVER_MESSAGE_LIMIT, (
        f"len(message)={len(message)} exceeds limit "
        f"{PUSHOVER_MESSAGE_LIMIT} for input length {len(s)}"
    )

    # Property part 2: workspace deep-link.
    ws_id = _ws_id_of(ws)
    assert isinstance(url, str)
    assert url == f"{WORKSPACE_DEEPLINK_BASE}/{ws_id}", (
        f"url {url!r} does not match the expected workspace deep-link "
        f"for ws_id={ws_id}"
    )
    # Stronger statement of "ends with /workspace/<ws_id>" from the task.
    assert url.endswith(f"/workspace/{ws_id}")


# ---------------------------------------------------------------------------
# Targeted boundary checks — short, exactly 1000, much longer.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n",
    [0, 1, 100, 999, 1000, 1001, 2000, 10_000],
    ids=[
        "empty",
        "one-char",
        "short-100",
        "just-under-limit-999",
        "exactly-limit-1000",
        "just-over-limit-1001",
        "long-2000",
        "much-longer-10000",
    ],
)
def test_pushover_payload_message_length_at_boundaries(n: int) -> None:
    """Exact-length boundary check: any input <=1000 stays as-is in length;
    inputs over the limit are truncated to exactly the limit."""
    s = "x" * n
    payload = pushover_payload(s, {"id": 42})

    assert len(payload["message"]) <= PUSHOVER_MESSAGE_LIMIT
    if n <= PUSHOVER_MESSAGE_LIMIT:
        # Untouched.
        assert payload["message"] == s
    else:
        # Truncated to the limit. No requirement on what marker the helper
        # uses; only that the resulting length is bounded.
        assert len(payload["message"]) == PUSHOVER_MESSAGE_LIMIT


def test_pushover_payload_exactly_1000_chars_unchanged() -> None:
    """A response of exactly 1000 chars is preserved verbatim — no ellipsis."""
    s = "a" * PUSHOVER_MESSAGE_LIMIT
    payload = pushover_payload(s, {"id": 7})
    assert payload["message"] == s
    assert len(payload["message"]) == PUSHOVER_MESSAGE_LIMIT


# ---------------------------------------------------------------------------
# Totality — non-string inputs and odd workspace shapes don't blow up.
# ---------------------------------------------------------------------------


@given(
    junk=st.one_of(
        st.none(),
        st.integers(),
        st.floats(allow_nan=True, allow_infinity=True),
        st.lists(st.integers(), max_size=4),
        st.dictionaries(st.text(max_size=4), st.integers(), max_size=2),
    ),
    ws=workspace_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_pushover_payload_total_on_non_string_response(junk, ws) -> None:
    """Non-string response_text values still produce a valid payload."""
    payload = pushover_payload(junk, ws)

    assert isinstance(payload["message"], str)
    assert len(payload["message"]) <= PUSHOVER_MESSAGE_LIMIT

    ws_id = _ws_id_of(ws)
    assert payload["url"].endswith(f"/workspace/{ws_id}")
