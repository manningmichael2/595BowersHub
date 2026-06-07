"""
Theme Validator: pure functions for validating theme color tokens and computing
WCAG contrast between the text and background tokens.

This module has no I/O. It is reused by:
  - `routers/themes.py` (admin + per-user theme save endpoints)
  - the property tests under `backend/tests/properties/`

References:
  - WCAG 2.x relative luminance:
    https://www.w3.org/WAI/GL/wiki/Relative_luminance
  - WCAG contrast ratio:
    https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

# Acceptable hex grammar: optional leading '#', then exactly 6 hex digits
# (RGB), with an optional 2 trailing hex digits (alpha channel). Mixed case
# allowed.
_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")

# Required color tokens for a theme. Order matches the design doc.
REQUIRED_TOKEN_KEYS: tuple[str, ...] = (
    "background",
    "surface",
    "primary",
    "accent",
    "text",
    "text_muted",
    "border",
    "danger",
    "success",
)

# WCAG thresholds. Below 2.0 contrast is considered unusable; between 2.0
# (inclusive) and 4.5 (exclusive) we warn but allow; 4.5 and above is fine.
_CONTRAST_BLOCK = 2.0
_CONTRAST_OK = 4.5

ContrastDecision = Literal["ok", "warn", "block"]


@dataclass(frozen=True)
class FieldError:
    """A per-field validation error, ready to ship to the client as JSON."""

    field: str
    message: str


def is_valid_hex(s: Any) -> bool:
    """
    Return True iff `s` matches `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`.

    The check is total: non-string inputs (None, int, dict, ...) return False
    rather than raising, so this can sit safely behind a JSON deserializer.
    """
    if not isinstance(s, str):
        return False
    return _HEX_RE.match(s) is not None


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """
    Parse a validated hex string into a (r, g, b) tuple of 0..255 ints.
    The optional leading '#' and optional trailing alpha pair are stripped;
    only the RGB triplet is returned.

    Caller MUST ensure `is_valid_hex(hex_str)` first.
    """
    s = hex_str.lstrip("#")
    # Drop alpha if present — we only compute luminance over RGB.
    s = s[:6]
    return (
        int(s[0:2], 16),
        int(s[2:4], 16),
        int(s[4:6], 16),
    )


def _channel_luminance(channel_byte: int) -> float:
    """Linearize a single 0..255 sRGB channel per the WCAG spec."""
    c = channel_byte / 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_str: str) -> float:
    """
    WCAG relative luminance for an sRGB color. Returns a float in [0.0, 1.0].

    Alpha (if present) is ignored — we compute luminance over the RGB only.

    Raises ValueError if `hex_str` is not a valid hex token.
    """
    if not is_valid_hex(hex_str):
        raise ValueError(f"not a valid hex color: {hex_str!r}")

    r, g, b = _hex_to_rgb(hex_str)
    rl = _channel_luminance(r)
    gl = _channel_luminance(g)
    bl = _channel_luminance(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio(text_hex: str, bg_hex: str) -> float:
    """
    WCAG contrast ratio between two colors. Result is symmetric in its
    arguments — `contrast_ratio(a, b) == contrast_ratio(b, a)`.

    Returns a float in [1.0, 21.0]. Higher is more readable.

    Raises ValueError if either argument is not a valid hex token.
    """
    l1 = relative_luminance(text_hex)
    l2 = relative_luminance(bg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_decision(text_hex: str, bg_hex: str) -> ContrastDecision:
    """
    Map a contrast ratio to a save-time policy:
      - ratio < 2.0     → "block"  (refuse save; unreadable)
      - 2.0 <= r < 4.5  → "warn"   (allow save with warning)
      - ratio >= 4.5    → "ok"     (allow save silently)

    The thresholds match Requirements R1.7 and R1.8.
    """
    ratio = contrast_ratio(text_hex, bg_hex)
    if ratio < _CONTRAST_BLOCK:
        return "block"
    if ratio < _CONTRAST_OK:
        return "warn"
    return "ok"


def validate_tokens(tokens_json: Any) -> list[FieldError]:
    """
    Validate a theme's `tokens_json` payload. Returns one FieldError per
    issue found. An empty list means the payload is valid for save.

    Checks performed:
      1. The payload itself is a dict.
      2. Every required token key is present.
      3. Every required token value is a 6- or 8-digit hex string.

    Note: this function does NOT enforce the contrast policy — that's a
    save-time concern handled by `contrast_decision` because the policy is
    a soft block (warn vs block) and depends on the calling endpoint.
    """
    errors: list[FieldError] = []

    if not isinstance(tokens_json, dict):
        errors.append(
            FieldError(
                field="tokens_json",
                message="tokens_json must be an object with named color fields",
            )
        )
        return errors

    for key in REQUIRED_TOKEN_KEYS:
        if key not in tokens_json:
            errors.append(
                FieldError(field=key, message=f"{key} is required")
            )
            continue

        value = tokens_json[key]
        if not is_valid_hex(value):
            errors.append(
                FieldError(
                    field=key,
                    message=(
                        f"{key} must be a 6- or 8-digit hex color "
                        f"(e.g. '#1a2b3c' or '#1a2b3cff')"
                    ),
                )
            )

    return errors
