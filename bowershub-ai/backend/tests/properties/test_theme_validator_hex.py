"""
Property tests for theme_validator.is_valid_hex.

Property 2: Hex token validator accepts exactly the hex grammar.

For any string `s`, `theme_validator.is_valid_hex(s)` returns True iff `s`
matches the published grammar `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$` — that
is, an optional leading `#` followed by exactly 6 hex digits (RGB) or 8 hex
digits (RGB + alpha), in any case. Non-string inputs always return False.

**Validates: Requirements R1.6**

Generators are constrained to bracket the grammar:
  - valid: with/without `#`, mixed case, lengths 6 and 8
  - near-misses: lengths 5 / 7 / 9, non-hex characters, leading whitespace,
    empty string, plus arbitrary text compared against a reference regex.
"""

from __future__ import annotations

import re
import string

import pytest
from hypothesis import given, strategies as st

from backend.services.theme_validator import is_valid_hex

# Reference regex — the authoritative grammar for `is_valid_hex`. The test
# property is that the function agrees with this regex on every input.
_REFERENCE_RE = re.compile(r"^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")

# All hex digits, mixed case, used for valid-string generation.
_HEX_CHARS = string.digits + "abcdefABCDEF"

# Characters that look hex-ish but are not (handy for crafting near-misses).
_NON_HEX_CHARS = "ghijklmnopqrstuvwxyzGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()_+-=[]{}|;:,.<>?/\\\"' \t\n"


def _matches_reference(s: object) -> bool:
    """The published grammar, expressed as a single regex match. Total."""
    if not isinstance(s, str):
        return False
    return _REFERENCE_RE.match(s) is not None


# ---- Smart generators ------------------------------------------------------

# Valid hex bodies: exactly 6 or exactly 8 hex chars, mixed case allowed.
_valid_hex_body = st.one_of(
    st.text(alphabet=_HEX_CHARS, min_size=6, max_size=6),
    st.text(alphabet=_HEX_CHARS, min_size=8, max_size=8),
)

valid_hex = st.builds(
    lambda body, prefix: prefix + body,
    _valid_hex_body,
    st.sampled_from(["", "#"]),
)

# Near-miss: hex chars only, but a length the grammar forbids (5, 7, 9, 10).
near_miss_wrong_length = st.builds(
    lambda body, prefix: prefix + body,
    st.one_of(
        st.text(alphabet=_HEX_CHARS, min_size=5, max_size=5),
        st.text(alphabet=_HEX_CHARS, min_size=7, max_size=7),
        st.text(alphabet=_HEX_CHARS, min_size=9, max_size=9),
        st.text(alphabet=_HEX_CHARS, min_size=10, max_size=10),
    ),
    st.sampled_from(["", "#"]),
)

# Near-miss: right length (6 or 8) but contains at least one non-hex char.
@st.composite
def _near_miss_non_hex(draw: st.DrawFn) -> str:
    length = draw(st.sampled_from([6, 8]))
    base = list(draw(st.text(alphabet=_HEX_CHARS, min_size=length, max_size=length)))
    bad_index = draw(st.integers(min_value=0, max_value=length - 1))
    base[bad_index] = draw(st.sampled_from(list(_NON_HEX_CHARS)))
    prefix = draw(st.sampled_from(["", "#"]))
    return prefix + "".join(base)


near_miss_non_hex_chars = _near_miss_non_hex()

# Near-miss: a leading whitespace character in front of an otherwise valid hex.
near_miss_leading_whitespace = st.builds(
    lambda ws, body, prefix: ws + prefix + body,
    st.sampled_from([" ", "\t", "\n"]),
    _valid_hex_body,
    st.sampled_from(["", "#"]),
)

# Arbitrary text — used to exercise the `is_valid_hex == reference regex`
# equivalence across the whole string space.
arbitrary_text = st.text(min_size=0, max_size=20)

# Non-string inputs.
non_string = st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.booleans(),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
    st.binary(max_size=8),
)


# ---- Properties ------------------------------------------------------------


@given(valid_hex)
def test_valid_hex_strings_are_accepted(s: str) -> None:
    """Every string matching the grammar must be accepted."""
    assert is_valid_hex(s) is True
    assert _matches_reference(s) is True


@given(near_miss_wrong_length)
def test_wrong_length_is_rejected(s: str) -> None:
    """Hex chars but wrong length (5/7/9/10) must be rejected."""
    assert is_valid_hex(s) is False


@given(near_miss_non_hex_chars)
def test_non_hex_characters_are_rejected(s: str) -> None:
    """Right length but containing a non-hex char must be rejected."""
    assert is_valid_hex(s) is False


@given(near_miss_leading_whitespace)
def test_leading_whitespace_is_rejected(s: str) -> None:
    """A leading whitespace character before a valid body must be rejected."""
    assert is_valid_hex(s) is False


@given(arbitrary_text)
def test_agrees_with_reference_grammar(s: str) -> None:
    """Across arbitrary text, the function and the reference regex agree."""
    assert is_valid_hex(s) == _matches_reference(s)


@given(non_string)
def test_non_string_inputs_return_false(value: object) -> None:
    """Non-string inputs are total: the function returns False, never raises."""
    assert is_valid_hex(value) is False


# ---- Targeted edge-case examples (kept tiny, complement the properties) ----


@pytest.mark.parametrize(
    "s",
    [
        "",
        "#",
        "abc",
        "12345",  # 5 hex chars
        "1234567",  # 7 hex chars
        "123456789",  # 9 hex chars
        "ggggggg",  # non-hex letters
        " #ffffff",  # leading space
        "#ffffff ",  # trailing space (also rejected)
        "##ffffff",  # double hash
        None,
        123456,
        ["#ffffff"],
    ],
)
def test_known_invalid_examples(s: object) -> None:
    assert is_valid_hex(s) is False


@pytest.mark.parametrize(
    "s",
    [
        "ffffff",
        "FFFFFF",
        "#ffffff",
        "#FFFFFF",
        "#aBcDeF",
        "abcdef12",  # 8 chars (rgba)
        "#abcdef12",
        "000000",
        "#00000000",
    ],
)
def test_known_valid_examples(s: str) -> None:
    assert is_valid_hex(s) is True
