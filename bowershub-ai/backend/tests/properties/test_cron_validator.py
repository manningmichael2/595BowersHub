"""
Property test for the cron expression validator.

Feature: bowershub-ai-enhancements, Property 10: Cron expression validator
agrees with croniter.

The module under test is ``backend.services.scheduled_prompts``. The thin
wrapper :func:`validate_cron` catches every exception raised by
:func:`croniter.croniter.is_valid` and reports those inputs as invalid
(returns ``False``). The property documented in the design doc is:

  for any string ``s``,
    if ``croniter.is_valid(s)`` returns a bool without raising, then
      ``validate_cron(s) == croniter.is_valid(s)``
    else
      ``validate_cron(s) == False``

  ``validate_cron(s)`` never raises.

In short: ``validate_cron`` is a total function that agrees with
``croniter.is_valid`` whenever the latter is itself total.

Validates: Requirements R11.11
"""

from __future__ import annotations

import pytest
from croniter import croniter
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.services.scheduled_prompts import validate_cron


# ---------------------------------------------------------------------------
# Known-good and known-bad examples from the task spec
# ---------------------------------------------------------------------------

KNOWN_VALID = [
    "* * * * *",
    "0 7 * * *",
    "*/5 * * * *",
]

KNOWN_INVALID = [
    "bogus",
    "",
    "60 24 32 13 8",  # all five fields out of range
    "* * * *",        # only four fields
]


@pytest.mark.parametrize("expr", KNOWN_VALID)
def test_known_valid_examples(expr: str) -> None:
    """The documented valid examples are accepted and agree with croniter."""
    assert validate_cron(expr) is True
    assert validate_cron(expr) == croniter.is_valid(expr)


@pytest.mark.parametrize("expr", KNOWN_INVALID)
def test_known_invalid_examples(expr: str) -> None:
    """The documented invalid examples are rejected and agree with croniter."""
    assert validate_cron(expr) is False
    assert validate_cron(expr) == croniter.is_valid(expr)


# ---------------------------------------------------------------------------
# Property strategies
# ---------------------------------------------------------------------------

# A "field-like" token: digits, ranges, lists, steps, named days/months,
# wildcards. Most of these random combinations will be invalid, which is
# fine — the property checks the wrapper agrees with croniter, not that any
# particular fraction of inputs is valid.
_field_token = st.one_of(
    st.sampled_from(
        [
            "*",
            "0",
            "7",
            "15",
            "30",
            "59",
            "60",  # out of range
            "*/5",
            "*/15",
            "0,15,30,45",
            "1-5",
            "MON",
            "MON-FRI",
            "JAN",
            "?",
            "L",
        ]
    ),
    st.from_regex(r"\A[0-9*/,\-?LW]{1,8}\Z", fullmatch=True),
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=0,
        max_size=8,
    ),
)


@st.composite
def cron_like_strings(draw) -> str:
    """Whitespace-joined small bag of field tokens (1–7 fields).

    croniter accepts the standard 5-field form and the optional 6/7-field
    forms (with seconds and/or year). Anything outside that span is
    rejected. We deliberately produce the full 1–7 range so the wrapper
    has to handle both the valid neighborhood and the invalid one.
    """
    n = draw(st.integers(min_value=1, max_value=7))
    fields = [draw(_field_token) for _ in range(n)]
    return " ".join(fields)


def _croniter_truth(s: str):
    """Reference oracle.

    Returns the bool that croniter.is_valid produces, OR the sentinel
    ``"raised"`` if croniter raises any exception. The wrapper is required
    to agree with the bool case and to return ``False`` for the "raised"
    case.
    """
    try:
        result = croniter.is_valid(s)
    except Exception:
        return "raised"
    # Defensive: croniter is documented to return a bool, but if a future
    # version returns something truthy/falsy we still compare meaningfully.
    return bool(result)


# ---------------------------------------------------------------------------
# Property 10: validate_cron agrees with croniter, never raises
# ---------------------------------------------------------------------------


@given(s=st.one_of(cron_like_strings(), st.text(max_size=64)))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_validate_cron_agrees_with_croniter(s: str) -> None:
    """For any string s, validate_cron(s) agrees with croniter.is_valid(s).

    When croniter.is_valid raises (it does for some malformed strings on
    older croniter versions), the wrapper must return False rather than
    propagating the exception.
    """
    truth = _croniter_truth(s)

    # The wrapper must never raise — that's half of the property.
    result = validate_cron(s)

    # The wrapper must always return a bool.
    assert isinstance(result, bool)

    if truth == "raised":
        assert result is False, (
            "croniter raised on this input; validate_cron must report False, "
            f"got {result!r} for {s!r}"
        )
    else:
        assert result == truth, (
            f"validate_cron disagrees with croniter.is_valid for {s!r}: "
            f"wrapper={result!r} truth={truth!r}"
        )


# ---------------------------------------------------------------------------
# Defensive: non-string inputs must not raise either.
# ---------------------------------------------------------------------------

@given(
    junk=st.one_of(
        st.none(),
        st.integers(),
        st.floats(allow_nan=True, allow_infinity=True),
        st.binary(max_size=16),
        st.lists(st.integers(), max_size=4),
        st.dictionaries(st.text(max_size=4), st.integers(), max_size=2),
    )
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_validate_cron_never_raises_on_arbitrary_inputs(junk) -> None:
    """validate_cron is total: arbitrary non-string inputs return False, never raise."""
    result = validate_cron(junk)
    assert isinstance(result, bool)
    assert result is False
