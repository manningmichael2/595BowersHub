"""
Text Size Resolver: pure mapping from a user's persisted text_size preference
to a (canonical_label, multiplier) pair.

This module is intentionally trivial and side-effect-free. Any input that is
not one of the four recognized labels — including ``None``, integers, dicts,
lists, and unknown strings — resolves to the default ``('medium', 1.0)``.

Per the bowershub-ai-enhancements spec (R4.1, R4.6):
    - 'small'       -> 0.875x base
    - 'medium'      -> 1.0x base   (default)
    - 'large'       -> 1.125x base
    - 'extra_large' -> 1.25x base

The function never raises.
"""

from typing import Any

# Canonical mapping of text_size labels to their CSS rem multipliers.
# Frozen as a module-level constant so callers can introspect the legal set
# without instantiating anything.
_TEXT_SIZE_MULTIPLIERS: dict[str, float] = {
    "small": 0.875,
    "medium": 1.0,
    "large": 1.125,
    "extra_large": 1.25,
}

_DEFAULT: tuple[str, float] = ("medium", 1.0)


def resolve(value: Any) -> tuple[str, float]:
    """
    Resolve a raw text_size value into a ``(label, multiplier)`` pair.

    Recognizes exactly the four labels ``'small'``, ``'medium'``, ``'large'``,
    and ``'extra_large'``. Every other input — ``None``, integers, floats,
    booleans, dicts, lists, unknown strings, etc. — returns the default
    ``('medium', 1.0)``. This function never raises.
    """
    if isinstance(value, str):
        multiplier = _TEXT_SIZE_MULTIPLIERS.get(value)
        if multiplier is not None:
            return (value, multiplier)
    return _DEFAULT
