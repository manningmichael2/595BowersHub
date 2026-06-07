"""
Property test for cron firing exactness.

Feature: bowershub-ai-enhancements, Property 11: Scheduled prompt fires
once per matching tick.

Background
----------

When a scheduled-prompt hook is created via
``services.scheduled_prompts.create``, the hook engine's startup path
registers an APScheduler job using a ``CroniterTrigger`` (a custom
trigger that delegates fire-time computation to ``croniter`` so the
dispatch path agrees with the validator on day-of-week conventions).
APScheduler then calls back into ``_execute_scheduled_hook`` exactly
once per fire time.

The full property statement in the design doc is:

    For any valid cron expression ``c`` and any time range
    ``[t0, t1]`` (with ``t0 < t1``), the count of fire times produced
    by the hook engine's trigger over ``[t0, t1]`` equals the count of
    fire times produced by ``croniter(c)`` over the same range. There
    are no duplicate fires and no missed fires.

We can't actually run an APScheduler instance inside a Hypothesis test
loop — the scheduler wakes up on real wall-clock ticks and would block
the test. The pragmatic approach (called out in the task description)
is to drive ``trigger.get_next_fire_time(previous, now)`` manually
in a loop, which is exactly what APScheduler does internally to decide
when to fire each job. Doing it this way keeps the test fast and
deterministic while still proving the dispatch primitive is exactly
equivalent to croniter.

What we test
------------

For every valid cron in a small bag of expressions, and for arbitrary
``[t0, t1]`` windows (timezone-aware UTC):

    next_fire_set_apscheduler(c, t0, t1) == next_fire_set_croniter(c, t0, t1)

Both functions return a sorted list of every fire time strictly greater
than ``t0`` and less than or equal to ``t1``. Equality of the lists
implies:

    - Same count (no duplicates, no misses)
    - Same ordering
    - Same exact tick values

We also exercise ``freezegun`` so the test environment is independent
of wall-clock time and any latent timezone surprises in the host OS.

Validates: Requirements R11.4
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from croniter import croniter
from freezegun import freeze_time
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.services.hook_engine import CroniterTrigger


# ---------------------------------------------------------------------------
# A small bag of known-valid 5-field cron expressions.
#
# Hypothesis-generating arbitrary cron expressions is feasible but mostly
# wasteful: random strings rarely parse as valid crons, and the property
# statement only requires equivalence over *valid* crons. Sticking to a
# curated set keeps each example fast and lets the test cover the cron
# shapes that actually appear in the scheduled-prompts UI:
#
#   - ``* * * * *``       — every minute (densest possible firing)
#   - ``0 7 * * *``       — daily at 07:00 (typical morning briefing)
#   - ``*/5 * * * *``     — every five minutes (typical poll interval)
#   - ``0 0 1 * *``       — first of the month at midnight (sparse)
#   - ``30 14 * * 1-5``   — weekdays at 14:30 (with day-of-week range)
#   - ``0 0 * * 0``       — Sunday midnight (single weekday)
# ---------------------------------------------------------------------------

VALID_CRONS = [
    "* * * * *",
    "0 7 * * *",
    "*/5 * * * *",
    "0 0 1 * *",
    "30 14 * * 1-5",
    "0 0 * * 0",
]


# ---------------------------------------------------------------------------
# Reference oracles.
#
# Both helpers return a sorted list of every fire time strictly greater
# than ``t0`` and less than or equal to ``t1``. Half-open ``(t0, t1]`` is
# the convention used by APScheduler internally — when the scheduler
# wakes up at time ``t`` after having last fired at ``previous``, it asks
# the trigger for the next fire time *after* ``previous`` that is
# ``<= now``. So the property compares apples to apples.
# ---------------------------------------------------------------------------


def croniter_fires(expr: str, t0: datetime, t1: datetime) -> List[datetime]:
    """Return every fire time of ``expr`` in ``(t0, t1]`` per croniter."""
    out: List[datetime] = []
    # ``ret_type=datetime`` makes croniter yield aware datetimes when
    # given an aware start time. Anchor at ``t0`` so the first call to
    # ``get_next`` produces a tick strictly after ``t0``.
    iterator = croniter(expr, t0)
    while True:
        nxt = iterator.get_next(datetime)
        if nxt > t1:
            break
        out.append(nxt)
    return out


def apscheduler_fires(expr: str, t0: datetime, t1: datetime) -> List[datetime]:
    """Return every fire time of ``expr`` in ``(t0, t1]`` per the
    production dispatch trigger (``CroniterTrigger``).

    Drives ``CroniterTrigger.get_next_fire_time(previous, now)`` in a
    loop, which is exactly the primitive APScheduler's ``BaseScheduler``
    uses internally to decide when to invoke a job. Each iteration:

        - ``previous`` is the most recently emitted fire (or ``None``
          for the first iteration; we anchor at ``t0`` so the first
          emitted fire is strictly greater than ``t0``)
        - ``now`` is set to ``t1`` so the trigger considers any fire
          time up to and including ``t1``

    ``CroniterTrigger`` is the trigger ``HookEngine.startup`` registers
    with APScheduler in production (see the trigger's docstring for why
    the built-in ``CronTrigger.from_crontab`` is wrong for this codebase
    — day-of-week conventions disagree with the validator). Driving it
    here means the property test exercises the real dispatch path.
    """
    trigger = CroniterTrigger(expr, tz=timezone.utc)
    out: List[datetime] = []
    # APScheduler's contract for ``previous != None`` is "fire >
    # previous". Set ``previous = t0`` so the first emitted fire is
    # strictly after t0, mirroring croniter's ``get_next`` (fire >
    # start) exactly.
    previous = t0
    while True:
        nxt = trigger.get_next_fire_time(previous, t1)
        if nxt is None or nxt > t1:
            break
        out.append(nxt)
        previous = nxt
        # Safety belt: if a misbehaving trigger ever returned a fire
        # time ``<= previous`` we'd loop forever. Hypothesis runs would
        # silently hang. Detect and abort.
        if len(out) >= 2 and out[-1] <= out[-2]:
            raise AssertionError(
                f"non-monotonic fires from CroniterTrigger for {expr!r}: "
                f"{out[-2]!r} → {out[-1]!r}"
            )
    return out


# ---------------------------------------------------------------------------
# Hypothesis strategies for ``[t0, t1]`` windows.
#
# We constrain to a 5-year band centered on 2026 so cron rules involving
# leap years and DST-ish edge cases (we run UTC throughout, so DST is a
# non-issue, but the year range still matters for ``0 0 29 2 *``-style
# expressions that only fire on leap days) get exercised.
# ---------------------------------------------------------------------------

_MIN_DT = datetime(2024, 1, 1, tzinfo=timezone.utc)
_MAX_DT = datetime(2029, 1, 1, tzinfo=timezone.utc)


@st.composite
def _utc_window(draw) -> tuple[datetime, datetime]:
    """Generate ``(t0, t1)`` with ``t0 < t1`` and a bounded span.

    Limiting ``t1 - t0`` to at most 7 days keeps the test fast even for
    the dense ``* * * * *`` expression (which fires 10080 times per
    week). Without the cap, Hypothesis can pick a span of years and
    each example takes seconds.
    """
    t0 = draw(st.datetimes(min_value=_MIN_DT.replace(tzinfo=None),
                            max_value=_MAX_DT.replace(tzinfo=None),
                            timezones=st.just(timezone.utc)))
    span_seconds = draw(st.integers(min_value=60, max_value=7 * 24 * 60 * 60))
    t1 = t0 + timedelta(seconds=span_seconds)
    return (t0, t1)


# ---------------------------------------------------------------------------
# Property 11
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("expr", VALID_CRONS)
@given(window=_utc_window())
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_apscheduler_and_croniter_agree_over_window(
    expr: str, window: tuple[datetime, datetime]
) -> None:
    """Per Property 11: both engines emit the exact same set of fires.

    For every valid cron expression in ``VALID_CRONS`` and every randomly
    generated window, the lists produced by APScheduler and croniter
    must be identical — same length, same ordering, same exact ticks.

    Same length implies:
        - no duplicate fires from APScheduler (our dispatch primitive
          would not fire twice on the same tick)
        - no missed fires (every cron tick that croniter agrees should
          have fired actually does fire)
    """
    t0, t1 = window

    # ``freeze_time`` here is belt-and-suspenders: neither engine reads
    # wall-clock time when given explicit ``previous`` / ``now`` args,
    # but freezing makes the test independent of any latent default-now
    # behavior either library might add later.
    with freeze_time(t0):
        ap_fires = apscheduler_fires(expr, t0, t1)
        cr_fires = croniter_fires(expr, t0, t1)

    assert ap_fires == cr_fires, (
        f"fire sequences disagree for {expr!r} over [{t0}, {t1}]\n"
        f"  apscheduler: {ap_fires}\n"
        f"  croniter:    {cr_fires}"
    )


# ---------------------------------------------------------------------------
# Concrete worked examples — useful as a sanity check on the oracles.
#
# These are not strictly Property-11 tests, but they cover the
# "no duplicate fires; no missed fires" half of the property in an
# example-based way that's easy to read in CI output if Hypothesis ever
# narrows down to a regression.
# ---------------------------------------------------------------------------


def test_every_minute_one_fire_per_minute() -> None:
    """The densest cron fires exactly once per minute in [t0, t1]."""
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=10)
    fires = apscheduler_fires("* * * * *", t0, t1)
    # 10 minutes after t0, with strictly-greater-than t0 semantics, gives
    # 10 fires at 12:01..12:10 inclusive.
    assert len(fires) == 10
    assert fires[0] == datetime(2026, 6, 1, 12, 1, 0, tzinfo=timezone.utc)
    assert fires[-1] == datetime(2026, 6, 1, 12, 10, 0, tzinfo=timezone.utc)


def test_no_duplicate_fires_when_now_aligns_with_a_tick() -> None:
    """When the window boundary lands exactly on a cron tick, the tick
    is emitted exactly once — never twice."""
    # 12:00 is a fire time for every-5-minutes; 12:05 is too. Build the
    # window so that t0 = 12:00 (fire boundary) and t1 = 12:05 (also a
    # fire boundary). The strictly-greater-than-t0, less-than-or-equal-t1
    # semantics should yield exactly one fire: 12:05.
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 1, 12, 5, 0, tzinfo=timezone.utc)
    fires = apscheduler_fires("*/5 * * * *", t0, t1)
    assert fires == [t1]


def test_sparse_cron_can_have_zero_fires_in_window() -> None:
    """A sparse cron ('first of the month, midnight') can produce zero
    fires in a window that doesn't contain a fire time. The property
    test must accept zero-length sequences as valid (no spurious fires)."""
    # Window entirely within June 2026, away from June 1 00:00.
    t0 = datetime(2026, 6, 2, 0, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
    fires = apscheduler_fires("0 0 1 * *", t0, t1)
    assert fires == []
    # And croniter agrees.
    assert croniter_fires("0 0 1 * *", t0, t1) == []
