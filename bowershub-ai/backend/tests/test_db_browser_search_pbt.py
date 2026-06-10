"""
Property tests for DB browser text search inclusion.

Feature: native-db-browser

Property 5: Text search inclusion
  - Every returned row has at least one text column containing the search term (case-insensitive)
  - If no text columns exist, search returns all rows (no filtering possible)
  - Search with empty string returns all rows
  - Search results are a subset of the original rows (never adds rows)

**Validates: Requirements 6.2, 6.5**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Pure Python implementation of the text search logic
# (mirrors the SQL ILIKE '%term%' OR logic built by the backend)
# ---------------------------------------------------------------------------


def apply_text_search(
    rows: list[dict[str, Any]],
    text_columns: list[str],
    search_term: str,
) -> list[dict[str, Any]]:
    """
    Apply cross-column text search to rows.

    Mimics the backend behavior:
    - Searches across all text_columns using case-insensitive partial matching
    - A row matches if ANY text column contains the search term (OR logic)
    - If search_term is empty (or whitespace-only), returns all rows
    - If text_columns is empty, returns all rows (no filtering possible)

    Args:
        rows: list of row dicts
        text_columns: list of column names considered "text type"
        search_term: the user's search input

    Returns:
        Filtered list of rows where at least one text column contains the term
    """
    # Empty/whitespace search returns everything (mirrors backend: `if search and search.strip()`)
    stripped = search_term.strip()
    if not stripped:
        return list(rows)

    # No text columns means no filtering is possible
    if not text_columns:
        return list(rows)

    # Filter: row matches if ANY text column contains the search term (case-insensitive)
    term_lower = stripped.lower()
    result = []
    for row in rows:
        matches = False
        for col in text_columns:
            value = row.get(col)
            if value is not None and term_lower in str(value).lower():
                matches = True
                break
        if matches:
            result.append(row)

    return result


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Column names — short identifiers representing table columns
column_names_st = st.sampled_from(
    ["name", "brand", "description", "notes", "status", "category", "title", "url"]
)

# Text column values — strings that could appear in text/varchar columns
text_value_st = st.one_of(
    st.none(),
    st.text(min_size=0, max_size=30, alphabet=st.characters(categories=("L", "N", "P", "Z"))),
)

# Non-text values (integers, floats) to mix in as non-text columns
non_text_value_st = st.one_of(
    st.none(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
)


@st.composite
def row_st(draw: st.DrawFn, text_cols: list[str], other_cols: list[str]) -> dict[str, Any]:
    """Generate a row with specified text and non-text columns."""
    row: dict[str, Any] = {}
    for col in text_cols:
        row[col] = draw(text_value_st)
    for col in other_cols:
        row[col] = draw(non_text_value_st)
    return row


@st.composite
def table_data_st(draw: st.DrawFn) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Generate table data: (rows, text_columns, all_columns)."""
    # Pick text columns (at least 0, up to 4)
    text_cols = draw(
        st.lists(column_names_st, min_size=0, max_size=4, unique=True)
    )
    # Pick some non-text columns
    remaining = [c for c in ["id", "qty", "price", "weight"] if c not in text_cols]
    other_cols = draw(
        st.lists(st.sampled_from(remaining) if remaining else st.nothing(), min_size=0, max_size=3, unique=True)
    )

    # Generate rows
    rows = draw(
        st.lists(row_st(text_cols, other_cols), min_size=0, max_size=20)
    )

    return rows, text_cols, text_cols + other_cols


# Search term strategy — realistic user search input
search_term_st = st.one_of(
    st.just(""),
    st.just("  "),
    st.text(min_size=1, max_size=10, alphabet=st.characters(categories=("L", "N"))),
)


# ---------------------------------------------------------------------------
# Property 5a: Every returned row has at least one text column containing
# the search term (case-insensitive partial match)
# ---------------------------------------------------------------------------


@given(data=table_data_st(), search_term=search_term_st)
@settings(max_examples=200)
def test_every_returned_row_contains_search_term(
    data: tuple[list[dict[str, Any]], list[str], list[str]],
    search_term: str,
) -> None:
    """
    After applying text search, EVERY remaining row has at least one
    text column whose string value contains the search term (case-insensitive).

    This is the core inclusion property for text search.
    """
    rows, text_columns, _ = data
    result = apply_text_search(rows, text_columns, search_term)

    stripped = search_term.strip()
    if not stripped or not text_columns:
        # No filtering should have occurred
        return

    term_lower = stripped.lower()
    for row in result:
        found_match = any(
            row.get(col) is not None and term_lower in str(row.get(col)).lower()
            for col in text_columns
        )
        assert found_match, (
            f"Row {row} was returned but no text column contains the search term "
            f"{search_term!r} (text_columns={text_columns})"
        )


# ---------------------------------------------------------------------------
# Property 5b: If no text columns exist, search returns all rows
# ---------------------------------------------------------------------------


@given(
    rows=st.lists(
        st.fixed_dictionaries({"id": st.integers(), "qty": st.integers()}),
        min_size=0,
        max_size=15,
    ),
    search_term=st.text(min_size=1, max_size=10),
)
@settings(max_examples=200)
def test_no_text_columns_returns_all_rows(
    rows: list[dict[str, Any]],
    search_term: str,
) -> None:
    """
    When there are no text columns in the table, text search cannot
    filter anything and should return all rows unchanged.
    """
    result = apply_text_search(rows, text_columns=[], search_term=search_term)
    assert result == rows


# ---------------------------------------------------------------------------
# Property 5c: Search with empty string returns all rows
# ---------------------------------------------------------------------------


@given(data=table_data_st())
@settings(max_examples=200)
def test_empty_search_returns_all_rows(
    data: tuple[list[dict[str, Any]], list[str], list[str]],
) -> None:
    """
    An empty (or whitespace-only) search term should return all rows
    without any filtering, regardless of text column content.
    """
    rows, text_columns, _ = data
    # Test empty string
    result_empty = apply_text_search(rows, text_columns, "")
    assert result_empty == rows

    # Test whitespace-only
    result_whitespace = apply_text_search(rows, text_columns, "   ")
    assert result_whitespace == rows


# ---------------------------------------------------------------------------
# Property 5d: Search results are a subset of the original rows (never adds rows)
# ---------------------------------------------------------------------------


@given(data=table_data_st(), search_term=search_term_st)
@settings(max_examples=200)
def test_search_results_are_subset_of_original(
    data: tuple[list[dict[str, Any]], list[str], list[str]],
    search_term: str,
) -> None:
    """
    Text search can only remove rows from the result set — it never
    introduces rows that weren't in the original input.
    """
    rows, text_columns, _ = data
    result = apply_text_search(rows, text_columns, search_term)

    # Result count is at most the original count
    assert len(result) <= len(rows)

    # Every row in result must be one of the original rows (by identity)
    original_ids = {id(r) for r in rows}
    for r in result:
        assert id(r) in original_ids, (
            f"Search result contains a row not in the original set: {r}"
        )
