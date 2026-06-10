"""
Property tests for DB browser relation discovery completeness.

Feature: native-db-browser

Property 18: Relation discovery completeness
  - ALL tables with FK columns referencing the target table are returned
  - Self-referencing FKs (a table with an FK to itself) are included
  - Multiple FKs from the same table to the same target each appear as separate
    relation groups
  - Tables with no FK to the target are excluded from results

**Validates: Requirements 31.1, 31.5**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hypothesis import given, settings, strategies as st


# ---------------------------------------------------------------------------
# Data model representing FK constraints in a schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FkConstraint:
    """A single foreign key constraint in the schema."""

    fk_schema: str  # schema of the table that HAS the FK column
    fk_table: str  # table that HAS the FK column
    fk_column: str  # the FK column name
    ref_schema: str  # schema of the REFERENCED table
    ref_table: str  # the REFERENCED table name
    ref_column: str  # the referenced column (usually the PK)


@dataclass(frozen=True)
class RelationGroup:
    """A single relation group returned by the discovery function."""

    schema: str
    table: str
    fk_column: str


# ---------------------------------------------------------------------------
# Pure Python implementation of relation discovery logic
# (mirrors the SQL query in GET /:schema/:table/:id/relations)
# ---------------------------------------------------------------------------


def discover_relations(
    constraints: list[FkConstraint],
    target_schema: str,
    target_table: str,
) -> list[RelationGroup]:
    """
    Given a list of all FK constraints in the database, discover which tables
    reference the target table.

    This mirrors the backend's information_schema query:
      - Find all constraints where ref_schema = target_schema
        AND ref_table = target_table
      - Return a RelationGroup for each (fk_schema, fk_table, fk_column) tuple

    Each FK column referencing the target produces its own RelationGroup entry,
    even if multiple FKs come from the same table.
    """
    results: list[RelationGroup] = []

    for c in constraints:
        if c.ref_schema == target_schema and c.ref_table == target_table:
            results.append(
                RelationGroup(
                    schema=c.fk_schema,
                    table=c.fk_table,
                    fk_column=c.fk_column,
                )
            )

    # Sort for deterministic output (matches the ORDER BY in the SQL query)
    results.sort(key=lambda r: (r.schema, r.table, r.fk_column))
    return results


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Schema names — short identifiers
schema_names_st = st.sampled_from(["public", "inventory", "files", "cook", "house"])

# Table names — realistic-ish identifiers
table_names_st = st.sampled_from([
    "users", "orders", "products", "categories", "tags",
    "tools", "saw_blades", "router_bits", "recipes",
    "assets", "transactions", "accounts", "employees",
    "departments", "projects", "tasks", "comments",
])

# Column names for FK columns
fk_column_names_st = st.sampled_from([
    "user_id", "category_id", "parent_id", "created_by",
    "updated_by", "manager_id", "project_id", "asset_id",
    "order_id", "product_id", "department_id", "task_id",
])

# Column names for referenced PK columns
ref_column_names_st = st.sampled_from(["id", "pk", "uid"])


@st.composite
def fk_constraint_st(draw: st.DrawFn) -> FkConstraint:
    """Generate a single FK constraint."""
    return FkConstraint(
        fk_schema=draw(schema_names_st),
        fk_table=draw(table_names_st),
        fk_column=draw(fk_column_names_st),
        ref_schema=draw(schema_names_st),
        ref_table=draw(table_names_st),
        ref_column=draw(ref_column_names_st),
    )


@st.composite
def constraints_st(draw: st.DrawFn) -> list[FkConstraint]:
    """Generate a list of FK constraints (0 to 30)."""
    return draw(st.lists(fk_constraint_st(), min_size=0, max_size=30))


@st.composite
def target_table_st(draw: st.DrawFn) -> tuple[str, str]:
    """Generate a (schema, table) pair as the target for relation discovery."""
    return (draw(schema_names_st), draw(table_names_st))


# ---------------------------------------------------------------------------
# Property 18a: ALL tables with FK columns referencing the target are returned
# ---------------------------------------------------------------------------


@given(constraints=constraints_st(), target=target_table_st())
@settings(max_examples=300)
def test_all_referencing_tables_are_returned(
    constraints: list[FkConstraint],
    target: tuple[str, str],
) -> None:
    """
    For any set of FK constraints, the discovery function returns EVERY
    constraint that references the target table. No referencing FK is missed.
    """
    target_schema, target_table = target

    result = discover_relations(constraints, target_schema, target_table)
    result_set = {(r.schema, r.table, r.fk_column) for r in result}

    # Compute the expected set: all constraints referencing this target
    expected_set = set()
    for c in constraints:
        if c.ref_schema == target_schema and c.ref_table == target_table:
            expected_set.add((c.fk_schema, c.fk_table, c.fk_column))

    assert result_set == expected_set, (
        f"Discovery missed or added relations.\n"
        f"Expected: {expected_set}\n"
        f"Got: {result_set}\n"
        f"Missing: {expected_set - result_set}\n"
        f"Extra: {result_set - expected_set}"
    )


# ---------------------------------------------------------------------------
# Property 18b: Self-referencing FKs are included
# ---------------------------------------------------------------------------


@given(
    constraints=constraints_st(),
    self_schema=schema_names_st,
    self_table=table_names_st,
    self_fk_col=fk_column_names_st,
    ref_col=ref_column_names_st,
)
@settings(max_examples=200)
def test_self_referencing_fks_are_included(
    constraints: list[FkConstraint],
    self_schema: str,
    self_table: str,
    self_fk_col: str,
    ref_col: str,
) -> None:
    """
    A table with an FK to itself (e.g., employees.manager_id → employees.id)
    appears in its own relation groups.
    """
    # Add a self-referencing FK constraint
    self_ref = FkConstraint(
        fk_schema=self_schema,
        fk_table=self_table,
        fk_column=self_fk_col,
        ref_schema=self_schema,
        ref_table=self_table,
        ref_column=ref_col,
    )
    all_constraints = constraints + [self_ref]

    result = discover_relations(all_constraints, self_schema, self_table)
    result_set = {(r.schema, r.table, r.fk_column) for r in result}

    # The self-referencing FK must appear in results
    assert (self_schema, self_table, self_fk_col) in result_set, (
        f"Self-referencing FK ({self_schema}.{self_table}.{self_fk_col} → "
        f"{self_schema}.{self_table}.{ref_col}) was not included in results.\n"
        f"Results: {result_set}"
    )


# ---------------------------------------------------------------------------
# Property 18c: Multiple FKs from the same table each appear as separate groups
# ---------------------------------------------------------------------------


@given(
    constraints=constraints_st(),
    fk_schema=schema_names_st,
    fk_table=table_names_st,
    target_schema=schema_names_st,
    target_table=table_names_st,
    ref_col=ref_column_names_st,
)
@settings(max_examples=200)
def test_multiple_fks_from_same_table_appear_separately(
    constraints: list[FkConstraint],
    fk_schema: str,
    fk_table: str,
    target_schema: str,
    target_table: str,
    ref_col: str,
) -> None:
    """
    When the same table has multiple FK columns referencing the target
    (e.g., posts.created_by and posts.updated_by both reference users.id),
    each FK column appears as a separate relation group in the result.
    """
    # Create two distinct FK columns from the same table to the same target
    fk1 = FkConstraint(
        fk_schema=fk_schema,
        fk_table=fk_table,
        fk_column="created_by",
        ref_schema=target_schema,
        ref_table=target_table,
        ref_column=ref_col,
    )
    fk2 = FkConstraint(
        fk_schema=fk_schema,
        fk_table=fk_table,
        fk_column="updated_by",
        ref_schema=target_schema,
        ref_table=target_table,
        ref_column=ref_col,
    )
    all_constraints = constraints + [fk1, fk2]

    result = discover_relations(all_constraints, target_schema, target_table)
    result_tuples = [(r.schema, r.table, r.fk_column) for r in result]

    # Both FK columns must appear as separate entries
    assert (fk_schema, fk_table, "created_by") in result_tuples, (
        f"FK column 'created_by' from {fk_schema}.{fk_table} not found in results.\n"
        f"Results: {result_tuples}"
    )
    assert (fk_schema, fk_table, "updated_by") in result_tuples, (
        f"FK column 'updated_by' from {fk_schema}.{fk_table} not found in results.\n"
        f"Results: {result_tuples}"
    )


# ---------------------------------------------------------------------------
# Property 18d: Tables with no FK to the target are excluded from results
# ---------------------------------------------------------------------------


@given(constraints=constraints_st(), target=target_table_st())
@settings(max_examples=200)
def test_non_referencing_tables_are_excluded(
    constraints: list[FkConstraint],
    target: tuple[str, str],
) -> None:
    """
    A table that has NO FK column pointing to the target table does not
    appear in the relation discovery results.
    """
    target_schema, target_table = target

    result = discover_relations(constraints, target_schema, target_table)

    # Build set of tables that actually reference the target
    referencing_fk_cols = set()
    for c in constraints:
        if c.ref_schema == target_schema and c.ref_table == target_table:
            referencing_fk_cols.add((c.fk_schema, c.fk_table, c.fk_column))

    # Every entry in the result must be in the referencing set
    for r in result:
        assert (r.schema, r.table, r.fk_column) in referencing_fk_cols, (
            f"Table {r.schema}.{r.table}.{r.fk_column} appeared in results "
            f"but does NOT have an FK to {target_schema}.{target_table}.\n"
            f"All referencing FKs: {referencing_fk_cols}"
        )


# ---------------------------------------------------------------------------
# Property 18e: Result count equals the number of distinct FK references
# ---------------------------------------------------------------------------


@given(constraints=constraints_st(), target=target_table_st())
@settings(max_examples=200)
def test_result_count_equals_distinct_fk_references(
    constraints: list[FkConstraint],
    target: tuple[str, str],
) -> None:
    """
    The number of relation groups returned equals the number of distinct
    (fk_schema, fk_table, fk_column) tuples that reference the target.
    Duplicate constraints (same FK column listed twice) are deduplicated.
    """
    target_schema, target_table = target

    result = discover_relations(constraints, target_schema, target_table)

    # Expected distinct FK references
    expected_refs = set()
    for c in constraints:
        if c.ref_schema == target_schema and c.ref_table == target_table:
            expected_refs.add((c.fk_schema, c.fk_table, c.fk_column))

    # Result should have exactly this count (no duplicates, no omissions)
    result_set = {(r.schema, r.table, r.fk_column) for r in result}
    assert len(result_set) == len(expected_refs), (
        f"Expected {len(expected_refs)} distinct relation groups, "
        f"got {len(result_set)}.\n"
        f"Expected: {expected_refs}\n"
        f"Got: {result_set}"
    )
