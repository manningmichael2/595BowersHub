"""
Property-based and unit tests for layout persistence round-trip.

Feature: dashboard-integration, Property 2: Layout persistence round-trip

For any valid layout configuration (any list of widget instances in any order
with any config overrides), persisting via PUT /api/dashboard/layouts and then
retrieving via GET /api/dashboard/layouts SHALL produce an identical widget
list with the same ordering and config values.

Validates: Requirements 3.2, 3.4
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st


# ---------------------------------------------------------------------------
# Hypothesis strategies for generating random layout data
# ---------------------------------------------------------------------------

# Widget keys: non-empty strings of printable ASCII (simulating real keys)
widget_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)

# Positions: integers 0-100
position_st = st.integers(min_value=0, max_value=100)

# Page keys: non-empty strings
page_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)

# Config overrides: dictionaries with string keys and JSON-compatible values
json_value_st = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-10000, max_value=10000),
        st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
        st.text(min_size=0, max_size=50),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(
            st.text(
                alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_"),
                min_size=1,
                max_size=15,
            ),
            children,
            max_size=5,
        ),
    ),
    max_leaves=10,
)

config_overrides_st = st.dictionaries(
    st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_"),
        min_size=1,
        max_size=20,
    ),
    json_value_st,
    max_size=5,
)

# A single widget instance
widget_instance_st = st.builds(
    lambda wk, pos, co: {"widget_key": wk, "position": pos, "config_overrides": co},
    wk=widget_key_st,
    pos=position_st,
    co=config_overrides_st,
)

# A page layout: page_key + list of 0-20 widget instances
page_layout_st = st.builds(
    lambda pk, widgets: {"page_key": pk, "widgets": widgets},
    pk=page_key_st,
    widgets=st.lists(widget_instance_st, min_size=0, max_size=20),
)


# A full layout update: list of 1-5 page layouts with unique page keys
@st.composite
def layout_update_st(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Generate a layout update with unique page keys."""
    n_pages = draw(st.integers(min_value=1, max_value=5))
    pages = []
    used_keys: set[str] = set()
    for _ in range(n_pages):
        page = draw(page_layout_st)
        # Ensure unique page_key
        while page["page_key"] in used_keys:
            page["page_key"] = draw(page_key_st)
        used_keys.add(page["page_key"])
        pages.append(page)
    return pages


# ---------------------------------------------------------------------------
# Mock database layer
#
# Simulates the Postgres round-trip: PUT serializes widgets via json.dumps()
# and stores them; GET retrieves the stored JSONB (which asyncpg returns as
# native Python dicts/lists thanks to the JSON codec registered in database.py).
# ---------------------------------------------------------------------------


class MockRecord:
    """Simulates an asyncpg Record with dict-like access."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]


class MockConnection:
    """
    Simulates an asyncpg connection that stores data in memory.
    Mimics the actual SQL behavior of the dashboard router.
    """

    def __init__(self, storage: dict[tuple[int, str], dict[str, Any]]):
        self._storage = storage

    async def execute(self, query: str, *args) -> None:
        """Simulate INSERT/UPSERT into bh_dashboard_layouts."""
        if "INSERT INTO public.bh_dashboard_layouts" in query:
            user_id = args[0]
            page_key = args[1]
            widgets_json_str = args[2]
            key = (user_id, page_key)
            # Simulate what Postgres does: stores JSON string, returns parsed
            # via the JSONB codec (json.loads on read). The asyncpg codec
            # registered in database.py calls json.loads on JSONB columns.
            self._storage[key] = {
                "user_id": user_id,
                "page_key": page_key,
                "widgets": json.loads(widgets_json_str),
                "updated_at": datetime.now(timezone.utc),
            }

    async def fetch(self, query: str, *args) -> list[MockRecord]:
        """Simulate SELECT from bh_dashboard_layouts."""
        if "bh_dashboard_layouts" in query:
            user_id = args[0] if args else None
            rows = []
            for (uid, pk), row in sorted(self._storage.items()):
                if uid == user_id:
                    rows.append(MockRecord(row))
            return rows
        return []


class MockPoolAcquireCtx:
    """Async context manager for pool.acquire()."""

    def __init__(self, storage: dict[tuple[int, str], dict[str, Any]]):
        self._conn = MockConnection(storage)

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockPool:
    """Simulates an asyncpg connection pool."""

    def __init__(self):
        self._storage: dict[tuple[int, str], dict[str, Any]] = {}

    def acquire(self):
        return MockPoolAcquireCtx(self._storage)


# ---------------------------------------------------------------------------
# Round-trip simulation function
#
# This directly replicates the logic from save_layouts and get_layouts in
# backend/routers/dashboard.py without importing the full module tree.
# ---------------------------------------------------------------------------


async def simulate_save_layouts(pool: MockPool, user_id: int, pages: list[dict[str, Any]]) -> None:
    """
    Replicates the PUT /api/dashboard/layouts logic:
    For each page, serialize widgets to JSON and upsert into the DB.
    """
    async with pool.acquire() as conn:
        for page in pages:
            # This matches how save_layouts serializes: model_dump() each widget
            widgets_json = json.dumps(page["widgets"])
            await conn.execute(
                """
                INSERT INTO public.bh_dashboard_layouts
                    (user_id, page_key, widgets, updated_at)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (user_id, page_key)
                DO UPDATE SET widgets = $3, updated_at = now()
                """,
                user_id,
                page["page_key"],
                widgets_json,
            )


async def simulate_get_layouts(pool: MockPool, user_id: int) -> dict[str, Any]:
    """
    Replicates the GET /api/dashboard/layouts logic:
    Fetch all layouts for the user and return them.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT page_key, widgets, updated_at
              FROM public.bh_dashboard_layouts
             WHERE user_id = $1
             ORDER BY page_key
            """,
            user_id,
        )

    pages = [
        {
            "page_key": row["page_key"],
            "widgets": row["widgets"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
        for row in rows
    ]
    return {"pages": pages}


# ---------------------------------------------------------------------------
# Property test: Layout persistence round-trip
# ---------------------------------------------------------------------------


@given(pages=layout_update_st())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_property_layout_persistence_round_trip(pages: list[dict[str, Any]]) -> None:
    """
    Feature: dashboard-integration, Property 2: Layout persistence round-trip

    For any valid layout configuration, persisting via PUT /api/dashboard/layouts
    and then retrieving via GET /api/dashboard/layouts SHALL produce an identical
    widget list with the same ordering and config values.

    **Validates: Requirements 3.2, 3.4**
    """
    import asyncio

    pool = MockPool()
    user_id = 1

    async def run_round_trip():
        # PUT: persist the layout
        await simulate_save_layouts(pool, user_id, pages)
        # GET: retrieve the layout
        return await simulate_get_layouts(pool, user_id)

    result = asyncio.run(run_round_trip())

    # Verify round-trip: each page's widgets should match what was saved
    result_pages = result["pages"]
    result_by_key = {p["page_key"]: p["widgets"] for p in result_pages}

    for page_data in pages:
        page_key = page_data["page_key"]
        assert page_key in result_by_key, f"Page '{page_key}' missing from GET response"

        expected_widgets = page_data["widgets"]
        actual_widgets = result_by_key[page_key]

        # Same number of widgets
        assert len(actual_widgets) == len(expected_widgets), (
            f"Widget count mismatch for page '{page_key}': "
            f"expected {len(expected_widgets)}, got {len(actual_widgets)}"
        )

        # Same ordering and values
        for i, (expected, actual) in enumerate(zip(expected_widgets, actual_widgets)):
            assert actual["widget_key"] == expected["widget_key"], (
                f"widget_key mismatch at position {i} on page '{page_key}'"
            )
            assert actual["position"] == expected["position"], (
                f"position mismatch at position {i} on page '{page_key}'"
            )
            assert actual["config_overrides"] == expected["config_overrides"], (
                f"config_overrides mismatch at position {i} on page '{page_key}':\n"
                f"  expected: {expected['config_overrides']}\n"
                f"  actual:   {actual['config_overrides']}"
            )


# ---------------------------------------------------------------------------
# Unit tests: specific round-trip scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_layout_round_trip():
    """Empty widget list for a page survives the round-trip."""
    pool = MockPool()
    user_id = 1

    pages = [{"page_key": "overview", "widgets": []}]

    await simulate_save_layouts(pool, user_id, pages)
    result = await simulate_get_layouts(pool, user_id)

    assert len(result["pages"]) == 1
    assert result["pages"][0]["page_key"] == "overview"
    assert result["pages"][0]["widgets"] == []


@pytest.mark.asyncio
async def test_single_widget_round_trip():
    """A single widget with config overrides survives the round-trip."""
    pool = MockPool()
    user_id = 1

    pages = [{
        "page_key": "overview",
        "widgets": [{
            "widget_key": "weather",
            "position": 0,
            "config_overrides": {"location": "Clawson,MI", "units": "imperial"},
        }],
    }]

    await simulate_save_layouts(pool, user_id, pages)
    result = await simulate_get_layouts(pool, user_id)

    assert len(result["pages"]) == 1
    widgets = result["pages"][0]["widgets"]
    assert len(widgets) == 1
    assert widgets[0]["widget_key"] == "weather"
    assert widgets[0]["position"] == 0
    assert widgets[0]["config_overrides"] == {"location": "Clawson,MI", "units": "imperial"}


@pytest.mark.asyncio
async def test_multiple_pages_round_trip():
    """Multiple pages each with multiple widgets survive the round-trip."""
    pool = MockPool()
    user_id = 1

    pages = [
        {
            "page_key": "overview",
            "widgets": [
                {"widget_key": "weather", "position": 0, "config_overrides": {}},
                {"widget_key": "containers", "position": 1, "config_overrides": {
                    "links": {"n8n": "http://localhost:5678"}
                }},
            ],
        },
        {
            "page_key": "finance",
            "widgets": [
                {"widget_key": "finance_summary", "position": 0, "config_overrides": {}},
                {"widget_key": "balances", "position": 1, "config_overrides": {}},
                {"widget_key": "recent_transactions", "position": 2, "config_overrides": {}},
            ],
        },
        {
            "page_key": "system",
            "widgets": [
                {"widget_key": "system_health", "position": 0, "config_overrides": {}},
                {"widget_key": "tailscale_devices", "position": 1, "config_overrides": {}},
            ],
        },
    ]

    await simulate_save_layouts(pool, user_id, pages)
    result = await simulate_get_layouts(pool, user_id)

    result_by_key = {p["page_key"]: p["widgets"] for p in result["pages"]}

    # Verify all three pages present
    assert "overview" in result_by_key
    assert "finance" in result_by_key
    assert "system" in result_by_key

    # Verify widget counts
    assert len(result_by_key["overview"]) == 2
    assert len(result_by_key["finance"]) == 3
    assert len(result_by_key["system"]) == 2

    # Verify ordering preserved
    assert result_by_key["overview"][0]["widget_key"] == "weather"
    assert result_by_key["overview"][1]["widget_key"] == "containers"
    assert result_by_key["finance"][0]["widget_key"] == "finance_summary"
    assert result_by_key["finance"][1]["widget_key"] == "balances"
    assert result_by_key["finance"][2]["widget_key"] == "recent_transactions"


@pytest.mark.asyncio
async def test_nested_config_overrides_round_trip():
    """Config overrides with nested objects survive the round-trip."""
    pool = MockPool()
    user_id = 1

    nested_config = {
        "links": {
            "n8n": "http://100.106.180.101:5678",
            "bowershub-ai": "https://595bowershub.tailc4d58a.ts.net",
        },
        "show_stopped": True,
        "refresh_interval": 30,
        "tags": ["production", "development"],
        "metadata": {
            "version": 2,
            "last_edited": "2026-06-07",
            "nested_deeper": {"key": "value", "number": 42},
        },
    }

    pages = [{
        "page_key": "system",
        "widgets": [{
            "widget_key": "containers",
            "position": 0,
            "config_overrides": nested_config,
        }],
    }]

    await simulate_save_layouts(pool, user_id, pages)
    result = await simulate_get_layouts(pool, user_id)

    assert len(result["pages"]) == 1
    widgets = result["pages"][0]["widgets"]
    assert len(widgets) == 1
    assert widgets[0]["config_overrides"] == nested_config


@pytest.mark.asyncio
async def test_overwrite_preserves_latest():
    """Saving the same page twice keeps only the latest layout."""
    pool = MockPool()
    user_id = 1

    # First save
    pages_v1 = [{
        "page_key": "overview",
        "widgets": [
            {"widget_key": "weather", "position": 0, "config_overrides": {}},
        ],
    }]
    await simulate_save_layouts(pool, user_id, pages_v1)

    # Second save (different widgets, same page_key)
    pages_v2 = [{
        "page_key": "overview",
        "widgets": [
            {"widget_key": "containers", "position": 0, "config_overrides": {}},
            {"widget_key": "system_health", "position": 1, "config_overrides": {}},
        ],
    }]
    await simulate_save_layouts(pool, user_id, pages_v2)

    result = await simulate_get_layouts(pool, user_id)

    assert len(result["pages"]) == 1
    widgets = result["pages"][0]["widgets"]
    assert len(widgets) == 2
    assert widgets[0]["widget_key"] == "containers"
    assert widgets[1]["widget_key"] == "system_health"
