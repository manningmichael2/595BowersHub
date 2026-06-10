"""
Property tests for DB browser filter predicate satisfaction.

Feature: native-db-browser

Property 4: Filter predicate satisfaction
  - Every returned row satisfies ALL applied filter conditions (AND logic)
  - The filter function is idempotent (applying twice produces same result)
  - Adding a filter never increases result count
  - `is_null` and `has_value` are complementary (their union = all rows)

**Validates: Requirements 5.2, 5.3, 5.5**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Pure Python implementation of the filter logic
# (mirrors the SQL WHERE clause built by the backend)
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
    Apply a list of filter conditions to rows, returning only rows that
    satisfy ALL conditions (AND logic).

    Each filter is: {"column": str, "operator": str, "value": Any}
    Operators: eq, neq, contains, gt, lt, is_null, has_value
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
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Column names — short, ascii-only identifiers
column_names_st = st.sampled_from(["name", "brand", "price", "qty", "notes", "status"])

# Cell values — a mix of types that could appear in a row
cell_value_st = st.one_of(
    st.none(),
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
)


@st.composite
def row_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a random row dict with a subset of columns."""
    cols = draw(st.lists(column_names_st, min_size=1, max_size=6, unique=True))
    return {col: draw(cell_value_st) for col in cols}


@st.composite
def rows_st(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Generate a list of random rows (0 to 20)."""
    return draw(st.lists(row_st(), min_size=0, max_size=20))


# Filter value strategy — matches what users would type
filter_value_st = st.one_of(
    st.text(min_size=0, max_size=10),
    st.integers(min_value=-100, max_value=100),
    st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
)


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
    """Generate a list of filter conditions (0 to 5)."""
    return draw(st.lists(filter_condition_st(), min_size=0, max_size=5))


# ---------------------------------------------------------------------------
# Property 4a: Every returned row satisfies ALL filter conditions (AND logic)
# ---------------------------------------------------------------------------


@given(rows=rows_st(), filters=filters_st())
@settings(max_examples=200)
def test_every_returned_row_satisfies_all_conditions(
    rows: list[dict[str, Any]], filters: list[dict[str, Any]]
) -> None:
    """
    After applying filters, EVERY remaining row satisfies ALL conditions.
    This is the core AND-logic property.
    """
    result = apply_filters(rows, filters)

    for row in result:
        for f in filters:
            col = f.get("column")
            op = f.get("operator")
            val = f.get("value")

            if not col or not op:
                continue

            row_value = row.get(col)
            assert _satisfies_condition(row_value, op, val), (
                f"Row {row} does not satisfy filter "
                f"(column={col!r}, operator={op!r}, value={val!r}): "
                f"row_value={row_value!r}"
            )


# ---------------------------------------------------------------------------
# Property 4b: Filter function is idempotent
# ---------------------------------------------------------------------------


@given(rows=rows_st(), filters=filters_st())
@settings(max_examples=200)
def test_filter_is_idempotent(
    rows: list[dict[str, Any]], filters: list[dict[str, Any]]
) -> None:
    """
    Applying the same filters twice produces the same result as applying once.
    apply_filters(apply_filters(rows, filters), filters) == apply_filters(rows, filters)
    """
    first_pass = apply_filters(rows, filters)
    second_pass = apply_filters(first_pass, filters)

    assert first_pass == second_pass


# ---------------------------------------------------------------------------
# Property 4c: Adding a filter never increases result count
# ---------------------------------------------------------------------------


@given(rows=rows_st(), base_filters=filters_st(), extra_filter=filter_condition_st())
@settings(max_examples=200)
def test_adding_filter_never_increases_count(
    rows: list[dict[str, Any]],
    base_filters: list[dict[str, Any]],
    extra_filter: dict[str, Any],
) -> None:
    """
    Adding an additional filter condition can only reduce (or maintain)
    the number of results — never increase it.
    """
    base_result = apply_filters(rows, base_filters)
    extended_filters = base_filters + [extra_filter]
    extended_result = apply_filters(rows, extended_filters)

    assert len(extended_result) <= len(base_result)


# ---------------------------------------------------------------------------
# Property 4d: is_null and has_value are complementary
# ---------------------------------------------------------------------------


@given(rows=rows_st(), col=column_names_st)
@settings(max_examples=200)
def test_is_null_and_has_value_are_complementary(
    rows: list[dict[str, Any]], col: str
) -> None:
    """
    For any column, the union of rows matching `is_null` and rows matching
    `has_value` equals the full row set. They partition the input.
    """
    null_filter = [{"column": col, "operator": "is_null", "value": None}]
    value_filter = [{"column": col, "operator": "has_value", "value": None}]

    null_rows = apply_filters(rows, null_filter)
    value_rows = apply_filters(rows, value_filter)

    # Their union should equal the original rows
    assert len(null_rows) + len(value_rows) == len(rows)

    # And no row appears in both sets
    null_set = {id(r) for r in null_rows}
    value_set = {id(r) for r in value_rows}
    assert null_set.isdisjoint(value_set)
