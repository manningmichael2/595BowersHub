"""
Property-based tests for DB Browser pagination invariants.

Feature: native-db-browser

Property 2 — Pagination invariants:
  For any combination of page (1+), page_size (25/50/100), and total_rows (0+):
    - rows returned on any page <= page_size
    - total_pages == ceil(total_rows / page_size)
    - offset == (page - 1) * page_size
    - on the last page: len(rows) == total_rows - (total_pages - 1) * page_size
    - pages beyond total_pages have 0 rows

These are pure math properties — no database connection required.

**Validates: Requirements 3.1, 3.3**
"""

from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Pagination logic under test (mirrors backend/routers/db_browser.py)
# ---------------------------------------------------------------------------


def compute_pagination(
    total_rows: int, page: int, page_size: int
) -> dict[str, int]:
    """
    Pure pagination math matching the server-side implementation.

    Returns:
        total_pages: number of pages needed to cover all rows
        offset: SQL OFFSET value for the requested page
        rows_on_page: how many rows this page would contain
    """
    offset = (page - 1) * page_size

    if total_rows == 0:
        return {"total_pages": 0, "offset": offset, "rows_on_page": 0}

    total_pages = math.ceil(total_rows / page_size)

    if page > total_pages:
        rows_on_page = 0
    elif page == total_pages:
        # Last page gets the remainder
        rows_on_page = total_rows - (total_pages - 1) * page_size
    else:
        rows_on_page = page_size

    return {
        "total_pages": total_pages,
        "offset": offset,
        "rows_on_page": rows_on_page,
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

page_strategy = st.integers(min_value=1, max_value=10_000)
page_size_strategy = st.sampled_from([25, 50, 100])
total_rows_strategy = st.integers(min_value=0, max_value=1_000_000)


# ---------------------------------------------------------------------------
# Property 2a — rows on any page never exceed page_size
# ---------------------------------------------------------------------------


@given(
    page=page_strategy,
    page_size=page_size_strategy,
    total_rows=total_rows_strategy,
)
@settings(max_examples=200)
def test_rows_on_page_never_exceeds_page_size(
    page: int, page_size: int, total_rows: int
) -> None:
    """rows_on_page <= page_size for any valid combination."""
    result = compute_pagination(total_rows, page, page_size)
    assert result["rows_on_page"] <= page_size


# ---------------------------------------------------------------------------
# Property 2b — total_pages == ceil(total_rows / page_size)
# ---------------------------------------------------------------------------


@given(
    page_size=page_size_strategy,
    total_rows=total_rows_strategy,
)
@settings(max_examples=200)
def test_total_pages_equals_ceil_division(
    page_size: int, total_rows: int
) -> None:
    """total_pages matches the mathematical ceiling division."""
    result = compute_pagination(total_rows, 1, page_size)
    if total_rows == 0:
        assert result["total_pages"] == 0
    else:
        expected = math.ceil(total_rows / page_size)
        assert result["total_pages"] == expected


# ---------------------------------------------------------------------------
# Property 2c — offset == (page - 1) * page_size
# ---------------------------------------------------------------------------


@given(
    page=page_strategy,
    page_size=page_size_strategy,
    total_rows=total_rows_strategy,
)
@settings(max_examples=200)
def test_offset_equals_page_minus_one_times_page_size(
    page: int, page_size: int, total_rows: int
) -> None:
    """SQL OFFSET is always (page - 1) * page_size regardless of total_rows."""
    result = compute_pagination(total_rows, page, page_size)
    expected_offset = (page - 1) * page_size
    assert result["offset"] == expected_offset


# ---------------------------------------------------------------------------
# Property 2d — last page has exactly the remaining rows
# ---------------------------------------------------------------------------


@given(
    page_size=page_size_strategy,
    total_rows=st.integers(min_value=1, max_value=1_000_000),
)
@settings(max_examples=200)
def test_last_page_has_remainder_rows(
    page_size: int, total_rows: int
) -> None:
    """On the last page, rows == total_rows - (total_pages - 1) * page_size."""
    total_pages = math.ceil(total_rows / page_size)
    result = compute_pagination(total_rows, total_pages, page_size)
    expected_remainder = total_rows - (total_pages - 1) * page_size
    assert result["rows_on_page"] == expected_remainder
    # The remainder is always between 1 and page_size inclusive
    assert 1 <= result["rows_on_page"] <= page_size


# ---------------------------------------------------------------------------
# Property 2e — pages beyond total_pages yield 0 rows
# ---------------------------------------------------------------------------


@given(
    page_size=page_size_strategy,
    total_rows=total_rows_strategy,
    extra=st.integers(min_value=1, max_value=1000),
)
@settings(max_examples=200)
def test_page_beyond_total_pages_yields_zero_rows(
    page_size: int, total_rows: int, extra: int
) -> None:
    """Any page > total_pages returns 0 rows."""
    result = compute_pagination(total_rows, 1, page_size)
    total_pages = result["total_pages"]
    # Request a page past the end
    beyond_page = total_pages + extra
    result_beyond = compute_pagination(total_rows, beyond_page, page_size)
    assert result_beyond["rows_on_page"] == 0


# ---------------------------------------------------------------------------
# Property 2f — sum of rows across all pages equals total_rows
# ---------------------------------------------------------------------------


@given(
    page_size=page_size_strategy,
    total_rows=st.integers(min_value=0, max_value=5000),
)
@settings(max_examples=200)
def test_sum_of_all_pages_equals_total_rows(
    page_size: int, total_rows: int
) -> None:
    """Summing rows_on_page for pages 1..total_pages recovers total_rows."""
    first = compute_pagination(total_rows, 1, page_size)
    total_pages = first["total_pages"]

    total = 0
    for p in range(1, total_pages + 1):
        result = compute_pagination(total_rows, p, page_size)
        total += result["rows_on_page"]

    assert total == total_rows


# ---------------------------------------------------------------------------
# Property 2g — empty table edge case
# ---------------------------------------------------------------------------


@given(
    page=page_strategy,
    page_size=page_size_strategy,
)
@settings(max_examples=200)
def test_empty_table_always_zero(page: int, page_size: int) -> None:
    """When total_rows == 0, every page has 0 rows and total_pages is 0."""
    result = compute_pagination(0, page, page_size)
    assert result["total_pages"] == 0
    assert result["rows_on_page"] == 0
    # offset still follows the formula
    assert result["offset"] == (page - 1) * page_size
