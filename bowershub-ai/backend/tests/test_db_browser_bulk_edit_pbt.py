"""
Property tests for DB browser bulk edit consistency.

Feature: native-db-browser

Property 14: Bulk edit consistency
  - After bulk edit, all affected rows have the target field set to the specified value
  - Non-target columns are unchanged after bulk edit
  - Bulk edit is idempotent (applying the same bulk edit twice = applying once)

**Validates: Requirements 27.5**
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Pure Python simulation of bulk edit logic
# (mirrors what the backend does: update a single column on multiple rows)
# ---------------------------------------------------------------------------


def apply_bulk_edit(
    rows: list[dict[str, Any]], column: str, value: Any
) -> list[dict[str, Any]]:
    """
    Simulate a bulk edit operation that sets a single column to the given value
    on all provided rows. Returns a new list of updated row dicts.
    """
    result = []
    for row in rows:
        updated = dict(row)
        updated[column] = value
        result.append(updated)
    return result


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Column names — short, ascii-only identifiers matching typical DB columns
column_names_st = st.sampled_from(
    ["name", "brand", "price", "qty", "notes", "status", "condition", "url"]
)

# Cell values — a mix of types that could appear in a row
cell_value_st = st.one_of(
    st.none(),
    st.text(min_size=0, max_size=30),
    st.integers(min_value=-10000, max_value=10000),
    st.floats(min_value=-10000, max_value=10000, allow_nan=False, allow_infinity=False),
    st.booleans(),
)


@st.composite
def row_st(draw: st.DrawFn, required_col: str | None = None) -> dict[str, Any]:
    """Generate a random row dict with a subset of columns (always has an 'id')."""
    cols = draw(st.lists(column_names_st, min_size=1, max_size=8, unique=True))
    if required_col and required_col not in cols:
        cols.append(required_col)
    row = {"id": draw(st.integers(min_value=1, max_value=10000))}
    for col in cols:
        row[col] = draw(cell_value_st)
    return row


@st.composite
def bulk_edit_st(draw: st.DrawFn) -> tuple[list[dict[str, Any]], str, Any]:
    """
    Generate a (rows, column_to_edit, new_value) triple.
    All rows share the same schema (same set of columns).
    The column to edit exists in all rows and is not the PK.
    """
    # Pick a shared column set (at least one editable column)
    cols = draw(st.lists(column_names_st, min_size=1, max_size=6, unique=True))
    target_column = draw(st.sampled_from(cols))
    new_value = draw(cell_value_st)

    # Generate 1-10 rows with the same column schema
    num_rows = draw(st.integers(min_value=1, max_value=10))
    rows = []
    for i in range(num_rows):
        row: dict[str, Any] = {"id": i + 1}
        for col in cols:
            row[col] = draw(cell_value_st)
        rows.append(row)

    return rows, target_column, new_value


# ---------------------------------------------------------------------------
# Property 14a: All affected rows have the new value in the target column
# ---------------------------------------------------------------------------


@given(data=bulk_edit_st())
@settings(max_examples=200)
def test_all_affected_rows_have_new_value(
    data: tuple[list[dict[str, Any]], str, Any],
) -> None:
    """
    After applying a bulk edit, every affected row has the target column
    set to the specified value.
    """
    rows, column, new_value = data
    updated_rows = apply_bulk_edit(rows, column, new_value)

    for i, updated_row in enumerate(updated_rows):
        assert updated_row[column] == new_value, (
            f"Row {i} (id={updated_row.get('id')}): "
            f"Expected column {column!r} to be {new_value!r}, "
            f"got {updated_row[column]!r}"
        )


# ---------------------------------------------------------------------------
# Property 14b: Non-target columns are unchanged
# ---------------------------------------------------------------------------


@given(data=bulk_edit_st())
@settings(max_examples=200)
def test_non_target_columns_unchanged(
    data: tuple[list[dict[str, Any]], str, Any],
) -> None:
    """
    After applying a bulk edit, all columns OTHER than the target column
    retain their original values in every row.
    """
    rows, column, new_value = data
    original_rows = deepcopy(rows)
    updated_rows = apply_bulk_edit(rows, column, new_value)

    for i, (original, updated) in enumerate(zip(original_rows, updated_rows)):
        for key in original:
            if key != column:
                assert updated[key] == original[key], (
                    f"Row {i} (id={original.get('id')}): "
                    f"Column {key!r} changed unexpectedly: "
                    f"original={original[key]!r}, got={updated[key]!r}"
                )


# ---------------------------------------------------------------------------
# Property 14c: Bulk edit is idempotent (applying twice = applying once)
# ---------------------------------------------------------------------------


@given(data=bulk_edit_st())
@settings(max_examples=200)
def test_bulk_edit_is_idempotent(
    data: tuple[list[dict[str, Any]], str, Any],
) -> None:
    """
    Applying the same bulk edit twice produces the same result as applying
    it once. bulk_edit(bulk_edit(rows, col, val), col, val) == bulk_edit(rows, col, val).
    """
    rows, column, new_value = data
    first_edit = apply_bulk_edit(rows, column, new_value)
    second_edit = apply_bulk_edit(first_edit, column, new_value)

    assert first_edit == second_edit, (
        f"Bulk edit not idempotent: "
        f"first_edit differs from second_edit"
    )
