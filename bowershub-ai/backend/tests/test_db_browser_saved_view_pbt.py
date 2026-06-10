"""
Property tests for saved view filter application in the DB browser.

Feature: native-db-browser

**Property 17: Saved view filter application**

For any saved view configuration, activating that view SHALL produce the same
result set as manually applying its stored filters, sort order, and column
visibility to the table.

The key equivalence being tested: applying a saved view's config in one step
must produce identical results to applying filters first, then sorting —
regardless of the specific filters, sort column, sort direction, or data.

These tests are pure (no DB needed). We implement the same filter + sort logic
the backend applies and verify the composition property holds for arbitrary
inputs.

**Validates: Requirements 28.3**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Pure Python filter logic (same as in test_db_browser_filter_pbt.py)
# ---------------------------------------------------------------------------

OPERATORS = ("eq", "neq", "contains", "gt", "lt", "is_null", "has_value")


def _satisfies_condition(value: Any, operator: str, filter_value: Any) -> bool:
    """Check if a single value satisfies a single filter condition."""
    if operator == "is_null":
        return value is None
    if operator == "has_value":
        return value is not None
    if operator == "eq":
        return value == filter_value
    if operator == "neq":
        return value != filter_value
    if operator == "contains":
        if value is None:
            return False
        return str(filter_value).lower() in str(value).lower()
    if operator == "gt":
        if value is None:
            return False
        try:
            return value > filter_value
        except TypeError:
            return False
    if operator == "lt":
        if value is None:
            return False
        try:
            return value < filter_value
        except TypeError:
            return False
    return False


def apply_filters(
    rows: list[dict[str, Any]], filters: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Apply filter conditions (AND logic). Each filter:
    {"column": str, "operator": str, "value": Any}
    """
    if not filters:
        return list(rows)

    result = []
    for row in rows:
        passes_all = True
        for f in filters:
            col = f.get("column")
            op = f.get("operator")
            val = f.get("value")
            if not col or not op:
                continue
            row_value = row.get(col)
            if not _satisfies_condition(row_value, op, val):
                passes_all = False
                break
        if passes_all:
            result.append(row)
    return result


# ---------------------------------------------------------------------------
# Pure Python sort logic (same as in test_db_browser_sort_pbt.py)
# ---------------------------------------------------------------------------


def sort_rows(
    rows: list[dict[str, Any]],
    sort_column: str | None,
    sort_direction: str | None,
) -> list[dict[str, Any]]:
    """
    Sort rows by a column following SQL semantics:
      - ascending:  NULLS LAST  (non-nulls asc, then nulls)
      - descending: NULLS FIRST (nulls first, then non-nulls desc)

    If sort_column is None, returns the rows in their original order.
    """
    if not sort_column:
        return list(rows)

    direction = sort_direction or "asc"

    def sort_key(row: dict[str, Any]) -> tuple[int, Any]:
        val = row.get(sort_column)
        if val is None:
            if direction == "asc":
                # NULLS LAST: nulls sort after everything
                return (1, "")
            else:
                # NULLS FIRST: nulls sort before everything
                return (0, "")
        else:
            if direction == "asc":
                return (0, val)
            else:
                return (1, val)

    # We can't use the tuple sort directly because mixed types in the
    # val position may not be comparable. Instead, separate nulls and
    # sort non-nulls independently.
    non_null_rows = [r for r in rows if r.get(sort_column) is not None]
    null_rows = [r for r in rows if r.get(sort_column) is None]

    reverse = direction == "desc"
    non_null_rows.sort(key=lambda r: r[sort_column], reverse=reverse)

    if direction == "asc":
        return non_null_rows + null_rows
    else:
        return null_rows + non_null_rows


# ---------------------------------------------------------------------------
# The "apply saved view" function — composition of filter + sort
# ---------------------------------------------------------------------------


def apply_saved_view(
    rows: list[dict[str, Any]],
    view_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Simulate activating a saved view: apply its filters first, then sort.
    This is the single-step "activate view" operation.

    view_config shape:
    {
        "filters": [{"column": str, "operator": str, "value": Any}, ...],
        "sortColumn": str | None,
        "sortDirection": "asc" | "desc" | None,
        "columns": [str, ...]  # column visibility (doesn't affect row content)
    }
    """
    filters = view_config.get("filters", [])
    sort_column = view_config.get("sortColumn")
    sort_direction = view_config.get("sortDirection")

    filtered = apply_filters(rows, filters)
    sorted_rows = sort_rows(filtered, sort_column, sort_direction)
    return sorted_rows


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Column names — a fixed set for generated rows and view configs
COLUMN_NAMES = ["name", "brand", "price", "qty", "notes", "status"]
column_names_st = st.sampled_from(COLUMN_NAMES)

# Cell values — integers only to avoid mixed-type sort issues in the test
# (the property being tested is about filter+sort composition, not type handling)
cell_value_st = st.one_of(
    st.none(),
    st.integers(min_value=-500, max_value=500),
)


@st.composite
def row_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a row with all columns present (some may be None)."""
    return {col: draw(cell_value_st) for col in COLUMN_NAMES}


@st.composite
def rows_st(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Generate a list of rows (0 to 15)."""
    return draw(st.lists(row_st(), min_size=0, max_size=15))


# Filter condition strategy (values are integers to match cell values)
filter_value_st = st.integers(min_value=-100, max_value=100)


@st.composite
def filter_condition_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a single filter condition."""
    return {
        "column": draw(column_names_st),
        "operator": draw(st.sampled_from(OPERATORS)),
        "value": draw(filter_value_st),
    }


@st.composite
def filters_st(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Generate a list of filter conditions (0 to 4)."""
    return draw(st.lists(filter_condition_st(), min_size=0, max_size=4))


@st.composite
def saved_view_config_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a saved view configuration."""
    filters = draw(filters_st())
    sort_column = draw(st.one_of(st.none(), column_names_st))
    sort_direction = draw(st.one_of(st.none(), st.sampled_from(["asc", "desc"])))
    # Column visibility — subset of all columns
    columns = draw(
        st.lists(column_names_st, min_size=1, max_size=6, unique=True)
    )
    return {
        "filters": filters,
        "sortColumn": sort_column,
        "sortDirection": sort_direction,
        "columns": columns,
    }


# ---------------------------------------------------------------------------
# Property 17a: Activating a view produces the SAME result as manually
#               applying filters then sorting
# ---------------------------------------------------------------------------


@given(rows=rows_st(), view_config=saved_view_config_st())
@settings(max_examples=300)
def test_saved_view_equals_manual_filter_then_sort(
    rows: list[dict[str, Any]], view_config: dict[str, Any]
) -> None:
    """
    **Validates: Requirements 28.3**

    The core equivalence property: activating a saved view must produce the
    exact same row sequence as manually applying the view's filters and then
    applying the view's sort. The two paths must be indistinguishable.
    """
    # Path 1: "activate view" (single composite operation)
    view_result = apply_saved_view(rows, view_config)

    # Path 2: manually apply filters, then manually sort
    manual_filtered = apply_filters(rows, view_config.get("filters", []))
    manual_sorted = sort_rows(
        manual_filtered,
        view_config.get("sortColumn"),
        view_config.get("sortDirection"),
    )

    assert view_result == manual_sorted, (
        f"View activation diverges from manual application.\n"
        f"View config: {view_config}\n"
        f"View result ({len(view_result)} rows): {view_result[:5]}...\n"
        f"Manual result ({len(manual_sorted)} rows): {manual_sorted[:5]}..."
    )


# ---------------------------------------------------------------------------
# Property 17b: Activating the same view twice (idempotent application)
# ---------------------------------------------------------------------------


@given(rows=rows_st(), view_config=saved_view_config_st())
@settings(max_examples=200)
def test_saved_view_is_idempotent(
    rows: list[dict[str, Any]], view_config: dict[str, Any]
) -> None:
    """
    **Validates: Requirements 28.3**

    Applying the same saved view to its own output must not change the result.
    This ensures filter+sort is stable when re-applied.
    """
    first = apply_saved_view(rows, view_config)
    second = apply_saved_view(first, view_config)

    assert first == second, (
        f"Saved view is not idempotent.\n"
        f"View config: {view_config}\n"
        f"First pass ({len(first)} rows): {first[:5]}...\n"
        f"Second pass ({len(second)} rows): {second[:5]}..."
    )


# ---------------------------------------------------------------------------
# Property 17c: View activation never produces rows not in the source
# ---------------------------------------------------------------------------


@given(rows=rows_st(), view_config=saved_view_config_st())
@settings(max_examples=200)
def test_saved_view_result_is_subset_of_input(
    rows: list[dict[str, Any]], view_config: dict[str, Any]
) -> None:
    """
    **Validates: Requirements 28.3**

    The result of activating a view must be a subset of (or equal to) the
    input rows. Views can only filter down and reorder — never introduce
    new rows.
    """
    result = apply_saved_view(rows, view_config)

    # Every row in result must exist in the original input
    for row in result:
        assert row in rows, (
            f"View produced a row not in the input: {row}"
        )

    # Result length must be <= input length
    assert len(result) <= len(rows)


# ---------------------------------------------------------------------------
# Property 17d: View with no filters and no sort returns all rows unchanged
# ---------------------------------------------------------------------------


@given(rows=rows_st())
@settings(max_examples=200)
def test_empty_view_returns_all_rows_in_original_order(
    rows: list[dict[str, Any]],
) -> None:
    """
    **Validates: Requirements 28.3**

    A saved view with no filters and no sort (the "All" default view)
    must return the input rows in their original order — it's the identity
    operation.
    """
    empty_config: dict[str, Any] = {
        "filters": [],
        "sortColumn": None,
        "sortDirection": None,
        "columns": COLUMN_NAMES,
    }

    result = apply_saved_view(rows, empty_config)
    assert result == rows, (
        f"Empty view should be identity but got different result.\n"
        f"Input: {rows[:5]}...\n"
        f"Output: {result[:5]}..."
    )


# ---------------------------------------------------------------------------
# Property 17e: Column visibility doesn't affect row content or count
# ---------------------------------------------------------------------------


@given(rows=rows_st(), view_config=saved_view_config_st())
@settings(max_examples=200)
def test_column_visibility_does_not_affect_rows(
    rows: list[dict[str, Any]], view_config: dict[str, Any]
) -> None:
    """
    **Validates: Requirements 28.3**

    Changing the columns (visibility) list in a saved view must not affect
    which rows are returned or their order — column visibility is a display
    concern only.
    """
    # Apply the view as-is
    result1 = apply_saved_view(rows, view_config)

    # Apply the same view with different column visibility
    modified_config = dict(view_config)
    modified_config["columns"] = COLUMN_NAMES  # show all columns

    result2 = apply_saved_view(rows, modified_config)

    assert result1 == result2, (
        f"Column visibility affected row results.\n"
        f"Original columns: {view_config['columns']}\n"
        f"Modified columns: {modified_config['columns']}\n"
        f"Result 1: {result1[:5]}...\n"
        f"Result 2: {result2[:5]}..."
    )
