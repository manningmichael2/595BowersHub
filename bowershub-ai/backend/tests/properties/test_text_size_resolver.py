"""
Property test for the text size resolver.

Feature: bowershub-ai-enhancements, Property 5: Text size resolver is total
and falls back to medium.

The module under test is ``backend.services.text_size_resolver``. The pure
function :func:`resolve` must:

  - return ``('small', 0.875)``       iff input is the string ``'small'``
  - return ``('medium', 1.0)``        iff input is the string ``'medium'``
  - return ``('large', 1.125)``       iff input is the string ``'large'``
  - return ``('extra_large', 1.25)``  iff input is the string ``'extra_large'``
  - return ``('medium', 1.0)`` for **every** other input, including ``None``,
    integers, floats, booleans, dicts, lists, unknown strings, etc.
  - never raise

Validates: Requirements R4.1, R4.6
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.services.text_size_resolver import resolve

# The four exact mappings the spec requires (R4.1).
KNOWN_MAPPINGS: dict[str, tuple[str, float]] = {
    "small": ("small", 0.875),
    "medium": ("medium", 1.0),
    "large": ("large", 1.125),
    "extra_large": ("extra_large", 1.25),
}

DEFAULT: tuple[str, float] = ("medium", 1.0)

KNOWN_LABELS: frozenset[str] = frozenset(KNOWN_MAPPINGS.keys())


# ---------------------------------------------------------------------------
# Known-good examples (the four recognized labels)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,expected", list(KNOWN_MAPPINGS.items()))
def test_known_labels_map_to_exact_pairs(label: str, expected: tuple[str, float]) -> None:
    """The four documented labels resolve to their exact (label, multiplier) pair."""
    assert resolve(label) == expected


# ---------------------------------------------------------------------------
# Known-bad examples that must fall back to medium
# ---------------------------------------------------------------------------

OBVIOUS_FALLBACKS: list[object] = [
    None,
    "",
    "Small",          # case-sensitive — uppercase is not recognized
    "MEDIUM",
    "extra-large",    # hyphen instead of underscore
    "extralarge",
    "huge",
    " medium ",       # whitespace not stripped
    0,
    1,
    -1,
    1.0,
    True,
    False,
    {},
    [],
    ("small",),
    {"text_size": "small"},
]


@pytest.mark.parametrize("value", OBVIOUS_FALLBACKS)
def test_obvious_fallbacks_resolve_to_medium(value: object) -> None:
    """Common non-matching inputs all return the default ``('medium', 1.0)``."""
    assert resolve(value) == DEFAULT


# ---------------------------------------------------------------------------
# Property: known labels resolve to their pair; everything else → default;
# resolve() never raises.
# ---------------------------------------------------------------------------

# A strategy that mixes the four known strings with arbitrary other things.
# We deliberately oversample the four labels (via st.sampled_from) so that
# Hypothesis explores both branches of the partition.
_arbitrary_input = st.one_of(
    st.sampled_from(sorted(KNOWN_LABELS)),
    st.none(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.booleans(),
    st.text(max_size=32),
    st.binary(max_size=16),
    st.lists(st.text(max_size=8), max_size=4),
    st.tuples(st.text(max_size=8)),
    st.dictionaries(st.text(max_size=8), st.text(max_size=8), max_size=3),
)


@given(value=_arbitrary_input)
@settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_is_total_and_partitions_correctly(value: object) -> None:
    """
    For every input ``value``:

      - resolve(value) does not raise
      - resolve(value) returns a (str, float) pair
      - if value is exactly one of the four known label strings,
        the result is the matching (label, multiplier) pair
      - otherwise, the result is ('medium', 1.0)
    """
    result = resolve(value)

    # Shape guarantee.
    assert isinstance(result, tuple) and len(result) == 2
    label, multiplier = result
    assert isinstance(label, str)
    assert isinstance(multiplier, float)

    # Partition guarantee.
    if isinstance(value, str) and value in KNOWN_LABELS:
        assert result == KNOWN_MAPPINGS[value]
    else:
        assert result == DEFAULT


# ---------------------------------------------------------------------------
# Defensive: resolve never raises on any input we throw at it.
# ---------------------------------------------------------------------------


@given(
    junk=st.one_of(
        st.none(),
        st.integers(),
        st.floats(allow_nan=True, allow_infinity=True),
        st.text(max_size=64),
        st.binary(max_size=32),
        st.lists(st.integers(), max_size=8),
        st.dictionaries(st.text(max_size=4), st.integers(), max_size=4),
        st.tuples(st.integers(), st.text(max_size=4)),
        st.sets(st.integers(), max_size=4),
        st.frozensets(st.integers(), max_size=4),
    )
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_never_raises(junk: object) -> None:
    """resolve() is total: any input returns a valid (str, float) pair without raising."""
    result = resolve(junk)
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], float)
