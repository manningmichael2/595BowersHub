"""
Property tests for DB browser CSV export/import round-trip.

Feature: native-db-browser

Property 16: CSV export/import round-trip
  - Exporting a value via _serialize_value (then writing to CSV) and
    re-importing it via _cast_value with an identity column mapping
    preserves the original value (or an equivalent representation).

**Validates: Requirements 30.1, 30.4**
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from hypothesis import given, settings, strategies as st

from backend.routers.db_browser import _cast_value, _serialize_value


# ---------------------------------------------------------------------------
# CSV serialization helper (mirrors the export loop in export-csv endpoint)
# ---------------------------------------------------------------------------


def serialize_for_csv(value: Any) -> str:
    """
    Simulate what the CSV export does: _serialize_value → then convert to
    the string that csv.writer would write.

    Rules from the export code:
      - None → ""
      - dict/list → json.dumps(value)
      - everything else → str(value)
    """
    serialized = _serialize_value(value)
    if serialized is None:
        return ""
    if isinstance(serialized, (dict, list)):
        return json.dumps(serialized)
    return str(serialized)


# ---------------------------------------------------------------------------
# Hypothesis strategies for supported types
# ---------------------------------------------------------------------------

# Text values: any printable string (avoid control chars that break CSV)
text_values_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=0,
    max_size=50,
)

# Integer values
integer_values_st = st.integers(min_value=-2_147_483_648, max_value=2_147_483_647)

# Numeric/Decimal values — finite decimals with reasonable precision
numeric_values_st = st.decimals(
    min_value=Decimal("-999999999.999999"),
    max_value=Decimal("999999999.999999"),
    allow_nan=False,
    allow_infinity=False,
    places=6,
)

# Boolean values
boolean_values_st = st.booleans()

# Date values — reasonable range
date_values_st = st.dates(
    min_value=date(1900, 1, 1),
    max_value=date(2099, 12, 31),
)

# None (represents NULL)
none_st = st.none()


# ---------------------------------------------------------------------------
# Property 16a: Text round-trip
# ---------------------------------------------------------------------------


@given(value=text_values_st)
@settings(max_examples=200)
def test_text_roundtrip(value: str) -> None:
    """
    Text values survive CSV export → import round-trip.
    Empty strings become None (as per _cast_value treating "" as NULL).
    Non-empty strings pass through unchanged.
    """
    csv_str = serialize_for_csv(value)
    result = _cast_value(csv_str, "text")

    if value.strip() == "":
        # Empty or whitespace-only strings become None on re-import
        # (because _cast_value returns None for empty/whitespace strings)
        assert result is None, (
            f"Expected None for whitespace-only text {value!r}, got {result!r}"
        )
    else:
        assert result == value, (
            f"Text round-trip failed: original={value!r}, csv={csv_str!r}, "
            f"result={result!r}"
        )


# ---------------------------------------------------------------------------
# Property 16b: Integer round-trip
# ---------------------------------------------------------------------------


@given(value=integer_values_st)
@settings(max_examples=200)
def test_integer_roundtrip(value: int) -> None:
    """
    Integer values survive CSV export → import round-trip exactly.
    """
    csv_str = serialize_for_csv(value)
    result = _cast_value(csv_str, "integer")

    assert result == value, (
        f"Integer round-trip failed: original={value!r}, csv={csv_str!r}, "
        f"result={result!r}"
    )


# ---------------------------------------------------------------------------
# Property 16c: Numeric/Decimal round-trip
# ---------------------------------------------------------------------------


@given(value=numeric_values_st)
@settings(max_examples=200)
def test_numeric_roundtrip(value: Decimal) -> None:
    """
    Decimal values survive CSV export → import round-trip.

    Note: _serialize_value converts Decimal → float for JSON serialization,
    so the round-trip is: Decimal → float → str → Decimal.
    This may introduce floating-point representation differences.
    We verify the result is close to the original within expected precision.
    """
    csv_str = serialize_for_csv(value)
    result = _cast_value(csv_str, "numeric")

    assert result is not None, (
        f"Numeric round-trip returned None: original={value!r}, csv={csv_str!r}"
    )
    # Compare as Decimal; the float→str→Decimal path may differ in trailing
    # digits, so we compare with a tolerance
    assert abs(result - value) < Decimal("0.000001"), (
        f"Numeric round-trip drift too large: original={value!r}, "
        f"csv={csv_str!r}, result={result!r}, diff={abs(result - value)}"
    )


# ---------------------------------------------------------------------------
# Property 16d: Boolean round-trip
# ---------------------------------------------------------------------------


@given(value=boolean_values_st)
@settings(max_examples=200)
def test_boolean_roundtrip(value: bool) -> None:
    """
    Boolean values survive CSV export → import round-trip.
    True → "True" → True (since "true" is in the truthy set)
    False → "False" → False (since "false" is not in the truthy set)
    """
    csv_str = serialize_for_csv(value)
    result = _cast_value(csv_str, "boolean")

    assert result == value, (
        f"Boolean round-trip failed: original={value!r}, csv={csv_str!r}, "
        f"result={result!r}"
    )


# ---------------------------------------------------------------------------
# Property 16e: Date round-trip
# ---------------------------------------------------------------------------


@given(value=date_values_st)
@settings(max_examples=200)
def test_date_roundtrip(value: date) -> None:
    """
    Date values survive CSV export → import round-trip exactly.
    date → isoformat string → date.fromisoformat.
    """
    csv_str = serialize_for_csv(value)
    result = _cast_value(csv_str, "date")

    assert result == value, (
        f"Date round-trip failed: original={value!r}, csv={csv_str!r}, "
        f"result={result!r}"
    )


# ---------------------------------------------------------------------------
# Property 16f: None round-trip (all types)
# ---------------------------------------------------------------------------


@given(
    data_type=st.sampled_from(
        ["text", "integer", "numeric", "boolean", "date"]
    )
)
@settings(max_examples=50)
def test_none_roundtrip(data_type: str) -> None:
    """
    None values round-trip perfectly for all supported data types.
    None → _serialize_value → None → CSV "" → _cast_value → None.
    """
    csv_str = serialize_for_csv(None)
    assert csv_str == "", f"Serialized None should be empty string, got {csv_str!r}"

    result = _cast_value(csv_str, data_type)
    assert result is None, (
        f"None round-trip failed for {data_type}: expected None, got {result!r}"
    )
