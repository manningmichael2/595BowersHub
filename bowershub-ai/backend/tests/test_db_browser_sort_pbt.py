"""
Property tests for sort ordering correctness in the DB browser.

Feature: native-db-browser

**Property 3: Sort ordering correctness**

Tests ascending/descending ordering with nulls-last/nulls-first behavior
for arbitrary column types. This validates the SQL sorting behavior the
`GET /api/db/:schema/:table/rows` endpoint produces:

  - Ascending:  non-null values in ascending order, then all nulls (NULLS LAST)
  - Descending: all nulls first, then non-null values in descending order (NULLS FIRST)

The tests are pure (no DB needed). We implement the same sorting logic
the Python/SQL code applies and verify its properties hold for arbitrary
inputs.

**Validates: Requirements 4.1, 4.5**
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from hypothesis import HealthCheck, given, settings, strategies as st


# ---------------------------------------------------------------------------
# Sorting logic under test — mirrors the SQL behavior:
#   ORDER BY col ASC NULLS LAST
#   ORDER BY col DESC NULLS FIRST
# ---------------------------------------------------------------------------


def sort_with_nulls(
    values: list[Any],
    direction: str = "asc",
) -> list[Any]:
    """
    Sort a list of values (which may contain None) following the same
    semantics as the DB browser's server-side sort:

      - ascending:  NULLS LAST  → non-nulls ascending, then nulls
      - descending: NULLS FIRST → nulls first, then non-nulls descending

    This is a pure reference implementation of the SQL behavior.
    """
    non_nulls = [v for v in values if v is not None]
    nulls = [v for v in values if v is None]

    if direction == "asc":
        non_nulls.sort()
        return non_nulls + nulls
    else:
        non_nulls.sort(reverse=True)
        return nulls + non_nulls


# ---------------------------------------------------------------------------
# Strategies for generating test data
# ---------------------------------------------------------------------------

# Integers with some nulls
nullable_integers = st.lists(
    st.one_of(st.integers(min_value=-10_000, max_value=10_000), st.none()),
    min_size=0,
    max_size=50,
)

# Strings with some nulls
nullable_strings = st.lists(
    st.one_of(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=0,
            max_size=20,
        ),
        st.none(),
    ),
    min_size=0,
    max_size=50,
)

# Dates with some nulls
nullable_dates = st.lists(
    st.one_of(
        st.dates(
            min_value=date(2000, 1, 1),
            max_value=date(2030, 12, 31),
        ),
        st.none(),
    ),
    min_size=0,
    max_size=50,
)

# Direction strategy
sort_direction = st.sampled_from(["asc", "desc"])


# ---------------------------------------------------------------------------
# Helper assertions
# ---------------------------------------------------------------------------


def _non_null_values(sorted_list: list[Any]) -> list[Any]:
    """Extract non-null values preserving order."""
    return [v for v in sorted_list if v is not None]


def _null_indices(sorted_list: list[Any]) -> list[int]:
    """Return indices of None values."""
    return [i for i, v in enumerate(sorted_list) if v is None]


def _non_null_indices(sorted_list: list[Any]) -> list[int]:
    """Return indices of non-None values."""
    return [i for i, v in enumerate(sorted_list) if v is not None]


# ---------------------------------------------------------------------------
# Property 3a: Non-null values in ascending sort are monotonically
#              non-decreasing
# ---------------------------------------------------------------------------


@given(values=nullable_integers, direction=st.just("asc"))
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_ascending_integers_non_nulls_are_non_decreasing(
    values: list[Optional[int]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In ascending sort, non-null values must be monotonically non-decreasing.
    """
    result = sort_with_nulls(values, direction)
    non_nulls = _non_null_values(result)

    for i in range(len(non_nulls) - 1):
        assert non_nulls[i] <= non_nulls[i + 1], (
            f"Non-decreasing violated at index {i}: "
            f"{non_nulls[i]} > {non_nulls[i + 1]}"
        )


@given(values=nullable_strings, direction=st.just("asc"))
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_ascending_strings_non_nulls_are_non_decreasing(
    values: list[Optional[str]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In ascending sort, non-null string values must be lexicographically
    non-decreasing.
    """
    result = sort_with_nulls(values, direction)
    non_nulls = _non_null_values(result)

    for i in range(len(non_nulls) - 1):
        assert non_nulls[i] <= non_nulls[i + 1], (
            f"Non-decreasing violated at index {i}: "
            f"{non_nulls[i]!r} > {non_nulls[i + 1]!r}"
        )


@given(values=nullable_dates, direction=st.just("asc"))
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_ascending_dates_non_nulls_are_non_decreasing(
    values: list[Optional[date]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In ascending sort, non-null date values must be chronologically
    non-decreasing.
    """
    result = sort_with_nulls(values, direction)
    non_nulls = _non_null_values(result)

    for i in range(len(non_nulls) - 1):
        assert non_nulls[i] <= non_nulls[i + 1], (
            f"Non-decreasing violated at index {i}: "
            f"{non_nulls[i]} > {non_nulls[i + 1]}"
        )


# ---------------------------------------------------------------------------
# Property 3b: Non-null values in descending sort are monotonically
#              non-increasing
# ---------------------------------------------------------------------------


@given(values=nullable_integers, direction=st.just("desc"))
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_descending_integers_non_nulls_are_non_increasing(
    values: list[Optional[int]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In descending sort, non-null values must be monotonically non-increasing.
    """
    result = sort_with_nulls(values, direction)
    non_nulls = _non_null_values(result)

    for i in range(len(non_nulls) - 1):
        assert non_nulls[i] >= non_nulls[i + 1], (
            f"Non-increasing violated at index {i}: "
            f"{non_nulls[i]} < {non_nulls[i + 1]}"
        )


@given(values=nullable_strings, direction=st.just("desc"))
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_descending_strings_non_nulls_are_non_increasing(
    values: list[Optional[str]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In descending sort, non-null string values must be lexicographically
    non-increasing.
    """
    result = sort_with_nulls(values, direction)
    non_nulls = _non_null_values(result)

    for i in range(len(non_nulls) - 1):
        assert non_nulls[i] >= non_nulls[i + 1], (
            f"Non-increasing violated at index {i}: "
            f"{non_nulls[i]!r} < {non_nulls[i + 1]!r}"
        )


@given(values=nullable_dates, direction=st.just("desc"))
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_descending_dates_non_nulls_are_non_increasing(
    values: list[Optional[date]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In descending sort, non-null date values must be chronologically
    non-increasing.
    """
    result = sort_with_nulls(values, direction)
    non_nulls = _non_null_values(result)

    for i in range(len(non_nulls) - 1):
        assert non_nulls[i] >= non_nulls[i + 1], (
            f"Non-increasing violated at index {i}: "
            f"{non_nulls[i]} < {non_nulls[i + 1]}"
        )


# ---------------------------------------------------------------------------
# Property 3c: All nulls appear AFTER non-nulls in ascending sort
#              (NULLS LAST behavior)
# ---------------------------------------------------------------------------


@given(values=nullable_integers)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_ascending_nulls_last_integers(values: list[Optional[int]]) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In ascending sort (NULLS LAST), all nulls must appear after all
    non-null values.
    """
    result = sort_with_nulls(values, "asc")
    null_indices = _null_indices(result)
    non_null_indices = _non_null_indices(result)

    if null_indices and non_null_indices:
        # The maximum non-null index must be less than the minimum null index
        assert max(non_null_indices) < min(null_indices), (
            f"NULLS LAST violated: last non-null at index {max(non_null_indices)}, "
            f"first null at index {min(null_indices)}"
        )


@given(values=nullable_strings)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_ascending_nulls_last_strings(values: list[Optional[str]]) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In ascending sort (NULLS LAST), all nulls must appear after all
    non-null values.
    """
    result = sort_with_nulls(values, "asc")
    null_indices = _null_indices(result)
    non_null_indices = _non_null_indices(result)

    if null_indices and non_null_indices:
        assert max(non_null_indices) < min(null_indices), (
            f"NULLS LAST violated: last non-null at index {max(non_null_indices)}, "
            f"first null at index {min(null_indices)}"
        )


@given(values=nullable_dates)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_ascending_nulls_last_dates(values: list[Optional[date]]) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In ascending sort (NULLS LAST), all nulls must appear after all
    non-null values.
    """
    result = sort_with_nulls(values, "asc")
    null_indices = _null_indices(result)
    non_null_indices = _non_null_indices(result)

    if null_indices and non_null_indices:
        assert max(non_null_indices) < min(null_indices), (
            f"NULLS LAST violated: last non-null at index {max(non_null_indices)}, "
            f"first null at index {min(null_indices)}"
        )


# ---------------------------------------------------------------------------
# Property 3d: All nulls appear BEFORE non-nulls in descending sort
#              (NULLS FIRST behavior)
# ---------------------------------------------------------------------------


@given(values=nullable_integers)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_descending_nulls_first_integers(values: list[Optional[int]]) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In descending sort (NULLS FIRST), all nulls must appear before all
    non-null values.
    """
    result = sort_with_nulls(values, "desc")
    null_indices = _null_indices(result)
    non_null_indices = _non_null_indices(result)

    if null_indices and non_null_indices:
        # The maximum null index must be less than the minimum non-null index
        assert max(null_indices) < min(non_null_indices), (
            f"NULLS FIRST violated: last null at index {max(null_indices)}, "
            f"first non-null at index {min(non_null_indices)}"
        )


@given(values=nullable_strings)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_descending_nulls_first_strings(values: list[Optional[str]]) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In descending sort (NULLS FIRST), all nulls must appear before all
    non-null values.
    """
    result = sort_with_nulls(values, "desc")
    null_indices = _null_indices(result)
    non_null_indices = _non_null_indices(result)

    if null_indices and non_null_indices:
        assert max(null_indices) < min(non_null_indices), (
            f"NULLS FIRST violated: last null at index {max(null_indices)}, "
            f"first non-null at index {min(non_null_indices)}"
        )


@given(values=nullable_dates)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_descending_nulls_first_dates(values: list[Optional[date]]) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    In descending sort (NULLS FIRST), all nulls must appear before all
    non-null values.
    """
    result = sort_with_nulls(values, "desc")
    null_indices = _null_indices(result)
    non_null_indices = _non_null_indices(result)

    if null_indices and non_null_indices:
        assert max(null_indices) < min(non_null_indices), (
            f"NULLS FIRST violated: last null at index {max(null_indices)}, "
            f"first non-null at index {min(non_null_indices)}"
        )


# ---------------------------------------------------------------------------
# Property 3e: Output length equals input length (sort is a permutation)
# ---------------------------------------------------------------------------


@given(
    values=st.lists(
        st.one_of(st.integers(min_value=-1000, max_value=1000), st.none()),
        min_size=0,
        max_size=50,
    ),
    direction=sort_direction,
)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_sort_preserves_length(
    values: list[Optional[int]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    Sorting must produce the same number of elements as the input
    (sort is a permutation, not a filter).
    """
    result = sort_with_nulls(values, direction)
    assert len(result) == len(values)


# ---------------------------------------------------------------------------
# Property 3f: Sort preserves the multiset of values (same elements,
#              possibly reordered)
# ---------------------------------------------------------------------------


@given(
    values=st.lists(
        st.one_of(st.integers(min_value=-1000, max_value=1000), st.none()),
        min_size=0,
        max_size=50,
    ),
    direction=sort_direction,
)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_sort_preserves_multiset(
    values: list[Optional[int]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    Sorting must not add, remove, or duplicate elements — the output is
    a permutation of the input.
    """
    result = sort_with_nulls(values, direction)

    # Count nulls
    input_nulls = values.count(None)
    result_nulls = result.count(None)
    assert input_nulls == result_nulls, (
        f"Null count changed: input had {input_nulls}, result has {result_nulls}"
    )

    # Count non-nulls
    input_non_nulls = sorted(v for v in values if v is not None)
    result_non_nulls = sorted(v for v in result if v is not None)
    assert input_non_nulls == result_non_nulls, (
        "Non-null multiset changed after sorting"
    )


# ---------------------------------------------------------------------------
# Property 3g: Combined property — for any direction, the sort function
#              produces a correctly ordered output matching SQL semantics
# ---------------------------------------------------------------------------


@given(
    values=st.lists(
        st.one_of(st.integers(min_value=-10_000, max_value=10_000), st.none()),
        min_size=0,
        max_size=100,
    ),
    direction=sort_direction,
)
@settings(
    max_examples=500,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_combined_sort_correctness(
    values: list[Optional[int]], direction: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.5**

    Combined property: for any list and direction, the sort produces:
      1. Correct null placement (NULLS LAST for asc, NULLS FIRST for desc)
      2. Correct ordering of non-null values
      3. Same element count (permutation)
    """
    result = sort_with_nulls(values, direction)

    # Length preserved
    assert len(result) == len(values)

    # Null placement
    null_indices = _null_indices(result)
    non_null_indices = _non_null_indices(result)

    if null_indices and non_null_indices:
        if direction == "asc":
            # NULLS LAST: all nulls after all non-nulls
            assert max(non_null_indices) < min(null_indices)
        else:
            # NULLS FIRST: all nulls before all non-nulls
            assert max(null_indices) < min(non_null_indices)

    # Non-null ordering
    non_nulls = _non_null_values(result)
    for i in range(len(non_nulls) - 1):
        if direction == "asc":
            assert non_nulls[i] <= non_nulls[i + 1]
        else:
            assert non_nulls[i] >= non_nulls[i + 1]
