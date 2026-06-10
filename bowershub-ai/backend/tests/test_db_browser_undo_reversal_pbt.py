"""
Property tests for DB browser undo reversal.

Feature: native-db-browser

Property 15: Undo reversal
  - For any single operation, undo restores exact pre-operation state
  - For UPDATE: undo restores previous_values, redo re-applies new_values
  - For INSERT: undo removes the row (state → "row does not exist"), redo re-creates it
  - For DELETE: undo restores the row to previous_values, redo re-deletes
  - Undo then redo is the identity operation (state matches post-operation)
  - Multiple undos in sequence restore the state step by step

**Validates: Requirements 29.1, 29.2, 29.3, 29.4**
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Pure Python simulation of the undo/redo system
# (mirrors the backend's bh_db_browser_undo_log logic)
# ---------------------------------------------------------------------------

# Sentinel representing "row does not exist"
ROW_ABSENT = object()


def apply_operation(
    row_state: dict[str, Any] | object,
    operation_type: str,
    previous_values: dict[str, Any] | None,
    new_values: dict[str, Any] | None,
) -> dict[str, Any] | object:
    """
    Apply an operation and return the new row state.

    - UPDATE: merges new_values into the existing row
    - INSERT: creates the row from new_values (row was absent)
    - DELETE: removes the row (returns ROW_ABSENT)
    """
    if operation_type == "update":
        # Row must exist; merge new_values into it
        assert row_state is not ROW_ABSENT
        updated = dict(row_state)  # type: ignore[arg-type]
        updated.update(new_values)  # type: ignore[arg-type]
        return updated
    elif operation_type == "insert":
        # Row didn't exist; create it from new_values
        assert row_state is ROW_ABSENT
        return dict(new_values)  # type: ignore[arg-type]
    elif operation_type == "delete":
        # Row existed; remove it
        assert row_state is not ROW_ABSENT
        return ROW_ABSENT
    else:
        raise ValueError(f"Unknown operation_type: {operation_type}")


def undo_operation(
    row_state: dict[str, Any] | object,
    operation_type: str,
    previous_values: dict[str, Any] | None,
    new_values: dict[str, Any] | None,
) -> dict[str, Any] | object:
    """
    Undo an operation, restoring the pre-operation row state.

    - UPDATE: apply previous_values to restore original fields
    - INSERT: delete the row (it didn't exist before)
    - DELETE: re-insert the row with previous_values
    """
    if operation_type == "update":
        # Restore previous field values
        assert row_state is not ROW_ABSENT
        restored = dict(row_state)  # type: ignore[arg-type]
        restored.update(previous_values)  # type: ignore[arg-type]
        return restored
    elif operation_type == "insert":
        # Row was inserted; undo means remove it
        assert row_state is not ROW_ABSENT
        return ROW_ABSENT
    elif operation_type == "delete":
        # Row was deleted; undo means re-insert with previous_values
        assert row_state is ROW_ABSENT
        return dict(previous_values)  # type: ignore[arg-type]
    else:
        raise ValueError(f"Unknown operation_type: {operation_type}")


def redo_operation(
    row_state: dict[str, Any] | object,
    operation_type: str,
    previous_values: dict[str, Any] | None,
    new_values: dict[str, Any] | None,
) -> dict[str, Any] | object:
    """
    Redo a previously undone operation (re-apply the operation).
    Identical to apply_operation.
    """
    return apply_operation(row_state, operation_type, previous_values, new_values)


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
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-10000, max_value=10000),
    st.floats(min_value=-10000, max_value=10000, allow_nan=False, allow_infinity=False),
    st.booleans(),
)


@st.composite
def row_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a random row dict with a subset of columns (always has 'id')."""
    cols = draw(st.lists(column_names_st, min_size=1, max_size=6, unique=True))
    row: dict[str, Any] = {"id": draw(st.integers(min_value=1, max_value=10000))}
    for col in cols:
        row[col] = draw(cell_value_st)
    return row


@st.composite
def update_entry_st(draw: st.DrawFn) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    """
    Generate an (existing_row, "update", previous_values, new_values) tuple.
    previous_values contains the original values of the columns being changed.
    new_values contains the new values for those columns.
    """
    row = draw(row_st())
    # Pick 1-3 columns to update (not 'id')
    editable_cols = [k for k in row if k != "id"]
    if not editable_cols:
        # Ensure at least one editable column
        col = draw(column_names_st)
        row[col] = draw(cell_value_st)
        editable_cols = [col]
    cols_to_update = draw(
        st.lists(
            st.sampled_from(editable_cols),
            min_size=1,
            max_size=min(3, len(editable_cols)),
            unique=True,
        )
    )
    previous_values = {col: row[col] for col in cols_to_update}
    new_values = {col: draw(cell_value_st) for col in cols_to_update}
    return row, "update", previous_values, new_values


@st.composite
def insert_entry_st(draw: st.DrawFn) -> tuple[object, str, None, dict[str, Any]]:
    """
    Generate a (ROW_ABSENT, "insert", None, new_values) tuple.
    The row doesn't exist yet; insert creates it.
    """
    new_row = draw(row_st())
    return ROW_ABSENT, "insert", None, new_row


@st.composite
def delete_entry_st(draw: st.DrawFn) -> tuple[dict[str, Any], str, dict[str, Any], None]:
    """
    Generate an (existing_row, "delete", previous_values, None) tuple.
    previous_values is the full row state before deletion.
    """
    row = draw(row_st())
    return row, "delete", dict(row), None


# Combined strategy for any single operation
any_operation_st = st.one_of(update_entry_st(), insert_entry_st(), delete_entry_st())


# ---------------------------------------------------------------------------
# Property 15a: For UPDATE, undo restores previous_values
# ---------------------------------------------------------------------------


@given(data=update_entry_st())
@settings(max_examples=200)
def test_update_undo_restores_previous_state(
    data: tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]],
) -> None:
    """
    After an UPDATE operation, undoing it restores the exact original row state.

    **Validates: Requirements 29.1**
    """
    original_row, op_type, previous_values, new_values = data
    original_snapshot = deepcopy(original_row)

    # Apply the update
    post_op_state = apply_operation(original_row, op_type, previous_values, new_values)
    assert post_op_state is not ROW_ABSENT

    # Undo the update
    restored_state = undo_operation(post_op_state, op_type, previous_values, new_values)
    assert restored_state is not ROW_ABSENT

    # The restored state must match the original row exactly
    assert restored_state == original_snapshot, (
        f"Undo did not restore original state.\n"
        f"  Original: {original_snapshot}\n"
        f"  After undo: {restored_state}"
    )


# ---------------------------------------------------------------------------
# Property 15b: For INSERT, undo removes the row
# ---------------------------------------------------------------------------


@given(data=insert_entry_st())
@settings(max_examples=200)
def test_insert_undo_removes_row(
    data: tuple[object, str, None, dict[str, Any]],
) -> None:
    """
    After an INSERT operation, undoing it returns the row to "does not exist".

    **Validates: Requirements 29.2**
    """
    original_state, op_type, previous_values, new_values = data
    assert original_state is ROW_ABSENT

    # Apply the insert
    post_op_state = apply_operation(original_state, op_type, previous_values, new_values)
    assert post_op_state is not ROW_ABSENT

    # Undo the insert
    restored_state = undo_operation(post_op_state, op_type, previous_values, new_values)

    # Row should no longer exist
    assert restored_state is ROW_ABSENT, (
        f"Undo of INSERT did not remove the row. Got: {restored_state}"
    )


# ---------------------------------------------------------------------------
# Property 15c: For DELETE, undo restores the row with previous_values
# ---------------------------------------------------------------------------


@given(data=delete_entry_st())
@settings(max_examples=200)
def test_delete_undo_restores_row(
    data: tuple[dict[str, Any], str, dict[str, Any], None],
) -> None:
    """
    After a DELETE operation, undoing it restores the row to its previous_values.

    **Validates: Requirements 29.3**
    """
    original_row, op_type, previous_values, new_values = data
    original_snapshot = deepcopy(original_row)

    # Apply the delete
    post_op_state = apply_operation(original_row, op_type, previous_values, new_values)
    assert post_op_state is ROW_ABSENT

    # Undo the delete
    restored_state = undo_operation(post_op_state, op_type, previous_values, new_values)
    assert restored_state is not ROW_ABSENT

    # The restored state must match the original row exactly
    assert restored_state == original_snapshot, (
        f"Undo of DELETE did not restore original state.\n"
        f"  Original: {original_snapshot}\n"
        f"  After undo: {restored_state}"
    )


# ---------------------------------------------------------------------------
# Property 15d: Undo then redo is the identity (state matches post-operation)
# ---------------------------------------------------------------------------


@given(data=any_operation_st)
@settings(max_examples=300)
def test_undo_then_redo_is_identity(
    data: tuple,
) -> None:
    """
    For any operation: apply → undo → redo produces the same state as
    just applying the operation. Undo+Redo is the identity operation.

    **Validates: Requirements 29.1, 29.2, 29.3, 29.4**
    """
    original_state, op_type, previous_values, new_values = data

    # Apply the operation
    post_op_state = apply_operation(
        original_state, op_type, previous_values, new_values
    )

    # Save post-op snapshot for comparison
    if post_op_state is ROW_ABSENT:
        post_op_snapshot = ROW_ABSENT
    else:
        post_op_snapshot = deepcopy(post_op_state)

    # Undo
    after_undo = undo_operation(post_op_state, op_type, previous_values, new_values)

    # Redo
    after_redo = redo_operation(after_undo, op_type, previous_values, new_values)

    # After redo, state should match post-operation state exactly
    assert after_redo == post_op_snapshot, (
        f"Undo+Redo did not restore post-op state.\n"
        f"  Operation: {op_type}\n"
        f"  Post-op: {post_op_snapshot}\n"
        f"  After undo+redo: {after_redo}"
    )


# ---------------------------------------------------------------------------
# Property 15e: Multiple undos in sequence restore state step by step
# ---------------------------------------------------------------------------


@st.composite
def sequential_updates_st(draw: st.DrawFn) -> tuple[dict[str, Any], list[tuple[dict, dict]]]:
    """
    Generate a row and a sequence of 2-5 update operations on it.
    Returns (initial_row, [(previous_values, new_values), ...]).
    """
    row = draw(row_st())
    # Ensure at least one editable column
    editable_cols = [k for k in row if k != "id"]
    if not editable_cols:
        col = draw(column_names_st)
        row[col] = draw(cell_value_st)
        editable_cols = [col]

    num_ops = draw(st.integers(min_value=2, max_value=5))
    operations: list[tuple[dict, dict]] = []
    current_row = dict(row)

    for _ in range(num_ops):
        cols_to_update = draw(
            st.lists(
                st.sampled_from(editable_cols),
                min_size=1,
                max_size=min(2, len(editable_cols)),
                unique=True,
            )
        )
        prev = {col: current_row[col] for col in cols_to_update}
        new = {col: draw(cell_value_st) for col in cols_to_update}
        operations.append((prev, new))
        # Apply the operation to track state for next iteration
        current_row.update(new)

    return row, operations


@given(data=sequential_updates_st())
@settings(max_examples=200)
def test_sequential_undos_restore_state_step_by_step(
    data: tuple[dict[str, Any], list[tuple[dict, dict]]],
) -> None:
    """
    When multiple update operations are applied in sequence, undoing them
    one at a time in reverse order restores each intermediate state correctly,
    and after all undos the original state is restored.

    **Validates: Requirements 29.1, 29.4**
    """
    initial_row, operations = data
    initial_snapshot = deepcopy(initial_row)

    # Apply all operations and record intermediate states
    states: list[dict[str, Any]] = [deepcopy(initial_row)]
    current = dict(initial_row)

    for prev_vals, new_vals in operations:
        current = dict(apply_operation(current, "update", prev_vals, new_vals))  # type: ignore[arg-type]
        states.append(deepcopy(current))

    # Now undo each operation in reverse order
    for i in range(len(operations) - 1, -1, -1):
        prev_vals, new_vals = operations[i]
        current = dict(undo_operation(current, "update", prev_vals, new_vals))  # type: ignore[arg-type]

        expected_state = states[i]
        assert current == expected_state, (
            f"After undo #{len(operations) - i}, state doesn't match.\n"
            f"  Expected: {expected_state}\n"
            f"  Got: {current}"
        )

    # After all undos, we should be back at the initial state
    assert current == initial_snapshot, (
        f"After all undos, state doesn't match initial.\n"
        f"  Expected: {initial_snapshot}\n"
        f"  Got: {current}"
    )
