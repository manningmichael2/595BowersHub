"""
Property test for theme_validator.contrast_decision.

**Property 3: Contrast threshold decision is monotonic and symmetric.**

For any pair of valid hex colors `(text, background)`,
`theme_validator.contrast_decision(text, background)` returns:

  * `'block'` iff the WCAG contrast ratio is below 2.0
  * `'warn'`  iff the ratio is in `[2.0, 4.5)`
  * `'ok'`    iff the ratio is `>= 4.5`

The function is symmetric in its arguments — swapping `text` and `background`
must produce the same decision because contrast ratio itself is symmetric.

Validates: Requirements R1.7, R1.8

Spec reference: design.md → Correctness Properties → Property 3.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from backend.services.theme_validator import (
    contrast_decision,
    contrast_ratio,
)


# ---------------------------------------------------------------------------
# Independent reference implementation of the WCAG contrast ratio.
#
# Mirroring the formula here, rather than calling theme_validator's helper,
# is the whole point of the property test: it cross-checks the production
# decision logic against a freshly-derived computation.
# ---------------------------------------------------------------------------

def _channel(byte: int) -> float:
    c = byte / 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_str: str) -> float:
    s = hex_str.lstrip("#")[:6]
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _ref_ratio(a: str, b: str) -> float:
    la = _luminance(a)
    lb = _luminance(b)
    lighter = max(la, lb)
    darker = min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _ref_decision(a: str, b: str) -> str:
    r = _ref_ratio(a, b)
    if r < 2.0:
        return "block"
    if r < 4.5:
        return "warn"
    return "ok"


# ---------------------------------------------------------------------------
# Smart generator: valid hex tokens that match the published grammar
# `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`.
#
# Constrains to the input space intelligently:
#  - one byte per RGB channel (0..255), drawn uniformly across the full range
#  - optional leading `#` (50/50)
#  - optional trailing alpha byte (50/50) — alpha is ignored by the formula
#    but exercising both shapes catches accidental regressions in parsing
#  - case is randomized so mixed-case hex digits are exercised
# ---------------------------------------------------------------------------

@st.composite
def valid_hex(draw) -> str:
    r = draw(st.integers(min_value=0, max_value=255))
    g = draw(st.integers(min_value=0, max_value=255))
    b = draw(st.integers(min_value=0, max_value=255))
    has_hash = draw(st.booleans())
    has_alpha = draw(st.booleans())
    upper = draw(st.booleans())

    body = f"{r:02x}{g:02x}{b:02x}"
    if has_alpha:
        a = draw(st.integers(min_value=0, max_value=255))
        body += f"{a:02x}"
    if upper:
        body = body.upper()
    return ("#" + body) if has_hash else body


# ---------------------------------------------------------------------------
# The property.
# ---------------------------------------------------------------------------

@settings(max_examples=300, deadline=None)
@given(text_hex=valid_hex(), bg_hex=valid_hex())
def test_contrast_decision_matches_threshold_mapping_and_is_symmetric(
    text_hex: str, bg_hex: str
) -> None:
    """
    Validates: Requirements R1.7, R1.8

    For any pair of valid hex colors:
      1. The decision returned by `contrast_decision` matches the threshold
         mapping applied to an independently-computed WCAG contrast ratio.
      2. The decision is symmetric in its two arguments.
    """
    decision = contrast_decision(text_hex, bg_hex)

    # 1. Decision matches the thresholds applied to the independent reference.
    expected = _ref_decision(text_hex, bg_hex)
    assert decision == expected, (
        f"decision({text_hex!r}, {bg_hex!r}) returned {decision!r}; "
        f"reference computed ratio "
        f"{_ref_ratio(text_hex, bg_hex):.4f} → {expected!r}"
    )

    # 2. Symmetry: swapping arguments yields the same decision.
    swapped = contrast_decision(bg_hex, text_hex)
    assert decision == swapped, (
        f"decision({text_hex!r}, {bg_hex!r}) = {decision!r} but "
        f"decision({bg_hex!r}, {text_hex!r}) = {swapped!r} — "
        f"contrast_decision must be symmetric in its arguments"
    )

    # Sanity tie-back: the production ratio function must also be symmetric,
    # because the decision symmetry above depends on it.
    assert contrast_ratio(text_hex, bg_hex) == contrast_ratio(bg_hex, text_hex)
