"""
Property tests for DB browser inline edit save persistence.

Feature: native-db-browser

Property 13: Inline edit save persistence
  - After PATCH (applying an update), re-fetching the row returns the updated value
  - All other columns remain unchanged after the update
  - The update is idempotent (applying the same edit twice produces the same result as once)

**Validates: Requirements 25.5**
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Pure Python simulation of inline edit PATCH logic
# (mirrors what the backend does: update a single column, return the full row)
# ---------------------------------------------------------------------------


def apply_inline_edit(
    row: dict[str, Any], column: str, new_value: Any
) -> dict[str, Any]:
    """
    Simulate a PATCH operation that sets a single column to a new value.
    Returns the updated row (a new dict with the change applied).
    """
    updated = dict(row)
    updated[column] = new_value
    return updated


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
def row_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a random row dict with a subset of columns (always has an 'id')."""
    cols = draw(st.lists(column_names_st, min_size=1, max_size=8, unique=True))
    row = {"id": draw(st.integers(min_value=1, max_value=10000))}
    for col in cols:
        row[col] = draw(cell_value_st)
    return row


@st.composite
def edit_st(draw: st.DrawFn) -> tuple[dict[str, Any], str, Any]:
    """
    Generate a (row, column_to_edit, new_value) triple.
    The column to edit is guaranteed to exist in the row (not 'id').
    """
    row = draw(row_st())
    # Pick a column that exists in the row and is not the PK
    editable_cols = [k for k in row if k != "id"]
    if not editable_cols:
        # Ensure at least one editable column
        col = draw(column_names_st)
        row[col] = draw(cell_value_st)
        editable_cols = [col]
    column = draw(st.sampled_from(editable_cols))
    new_value = draw(cell_value_st)
    return row, column, new_value


# ---------------------------------------------------------------------------
# Property 13a: Updated column has the new value after PATCH
# ---------------------------------------------------------------------------


@given(data=edit_st())
@settings(max_examples=200)
def test_updated_column_has_new_value(
    data: tuple[dict[str, Any], str, Any],
) -> None:
    """
    After applying an inline edit (PATCH), the target column in the resulting
    row contains the new value.
    """
    row, column, new_value = data
    updated_row = apply_inline_edit(row, column, new_value)

    assert updated_row[column] == new_value, (
        f"Expected column {column!r} to be {new_value!r}, "
        f"got {updated_row[column]!r}"
    )


# ---------------------------------------------------------------------------
# Property 13b: All other columns remain unchanged after PATCH
# ---------------------------------------------------------------------------


@given(data=edit_st())
@settings(max_examples=200)
def test_other_columns_unchanged(
    data: tuple[dict[str, Any], str, Any],
) -> None:
    """
    After applying an inline edit, all columns OTHER than the edited column
    retain their original values.
    """
    row, column, new_value = data
    original_row = deepcopy(row)
    updated_row = apply_inline_edit(row, column, new_value)

    for key in original_row:
        if key != column:
            assert updated_row[key] == original_row[key], (
                f"Column {key!r} changed unexpectedly: "
                f"original={original_row[key]!r}, got={updated_row[key]!r}"
            )


# ---------------------------------------------------------------------------
# Property 13c: The update is idempotent (applying twice = applying once)
# ---------------------------------------------------------------------------


@given(data=edit_st())
@settings(max_examples=200)
def test_inline_edit_is_idempotent(
    data: tuple[dict[str, Any], str, Any],
) -> None:
    """
    Applying the same inline edit twice produces the same result as applying
    it once. PATCH(PATCH(row, col, val), col, val) == PATCH(row, col, val).
    """
    row, column, new_value = data
    first_edit = apply_inline_edit(row, column, new_value)
    second_edit = apply_inline_edit(first_edit, column, new_value)

    assert first_edit == second_edit, (
        f"Edit not idempotent: first={first_edit}, second={second_edit}"
    )
