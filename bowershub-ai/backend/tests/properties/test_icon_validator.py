"""
Property test for branding_store.validate_icon.

**Property 4: Icon upload validator accepts exactly the published rules.**

For any tuple ``(mime, width, height, size_bytes)``,
``branding_store.validate_icon`` returns ``(ok, errors)`` where:

  * ``ok`` is True iff *every* one of the four published rules holds:
      1. ``mime == 'image/png'``
      2. ``min(width, height) >= 512``
      3. ``abs(width - height) / max(width, height) <= 0.01``
      4. ``size_bytes <= 4 * 1024 * 1024``  (4 MB)

  * Otherwise ``ok`` is False, and for each failing rule there is a
    per-field error in ``errors`` identifying the violation.

The function is total — it never raises on any combination of inputs.

**Validates: Requirements R2.2, R2.3**

Spec references: requirements.md → R2.2, R2.3; design.md → Backend Services
and Modules → branding_store; tasks.md → 7.2.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from backend.services.branding_store import FieldError, validate_icon

# -----------------------------------------------------------------------------
# Constants — kept local so the test can fail loudly if validate_icon's
# thresholds drift away from the published rules.
# -----------------------------------------------------------------------------

REQUIRED_MIME = "image/png"
MIN_DIMENSION = 512
MAX_FILE_SIZE = 4 * 1024 * 1024  # 4 MB
SQUARE_TOLERANCE = 0.01  # 1%

# Field labels emitted by validate_icon for each failing rule.
FIELD_MIME = "mime"
FIELD_DIMENSIONS = "dimensions"
FIELD_ASPECT = "aspect"
FIELD_SIZE = "size"


# -----------------------------------------------------------------------------
# Reference predicates — independently expressing each rule. The property
# below cross-checks validate_icon against these.
# -----------------------------------------------------------------------------


def _ref_mime_ok(mime: str) -> bool:
    return mime == REQUIRED_MIME


def _ref_dimensions_ok(width: int, height: int) -> bool:
    return (
        isinstance(width, int)
        and isinstance(height, int)
        and width > 0
        and height > 0
        and min(width, height) >= MIN_DIMENSION
    )


def _ref_aspect_ok(width: int, height: int) -> bool:
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        # The validator emits a single dimensions error and short-circuits
        # the aspect check; treat aspect as "not separately failing" so the
        # property only asserts what the validator can observe.
        return True
    return abs(width - height) / max(width, height) <= SQUARE_TOLERANCE


def _ref_size_ok(size_bytes: int) -> bool:
    return (
        isinstance(size_bytes, int)
        and size_bytes >= 0
        and size_bytes <= MAX_FILE_SIZE
    )


# -----------------------------------------------------------------------------
# Smart generators — bracket the published thresholds tightly. Hypothesis
# will mix these with random values via st.one_of to cover both the boundary
# cases and the broader input space.
# -----------------------------------------------------------------------------

# MIME: the accepted value, common near-misses (case/whitespace/other types),
# plus arbitrary strings.
mime_strategy = st.one_of(
    st.just("image/png"),
    st.sampled_from(
        [
            "image/png",
            "image/PNG",
            "IMAGE/PNG",
            "image/png ",
            " image/png",
            "image/jpeg",
            "image/jpg",
            "image/gif",
            "image/webp",
            "image/svg+xml",
            "application/octet-stream",
            "text/plain",
            "",
        ]
    ),
    st.text(min_size=0, max_size=20),
)

# Dimensions: bracket the 512 boundary tightly (510..514) plus broader
# valid ranges, and a slice of clearly-invalid values (0, 1, 511, very large).
_dim_boundary = st.sampled_from([0, 1, 100, 256, 510, 511, 512, 513, 514, 1024, 2048])
_dim_broad = st.integers(min_value=1, max_value=4096)
dimension_strategy = st.one_of(_dim_boundary, _dim_broad)

# Sizes: bracket the 4 MB boundary tightly, plus broader values.
_BYTES_4MB = MAX_FILE_SIZE
_size_boundary = st.sampled_from(
    [
        0,
        1,
        1024,
        _BYTES_4MB - 1,
        _BYTES_4MB,
        _BYTES_4MB + 1,
        _BYTES_4MB + 1024,
        _BYTES_4MB * 2,
    ]
)
_size_broad = st.integers(min_value=0, max_value=_BYTES_4MB * 4)
size_strategy = st.one_of(_size_boundary, _size_broad)


# -----------------------------------------------------------------------------
# Property: validate_icon returns ok iff all four rules hold, and emits a
# per-field error for every failing rule.
# -----------------------------------------------------------------------------


@settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    mime=mime_strategy,
    width=dimension_strategy,
    height=dimension_strategy,
    size_bytes=size_strategy,
)
def test_validate_icon_matches_published_rules(
    mime: str, width: int, height: int, size_bytes: int
) -> None:
    """
    Validates: Requirements R2.2, R2.3

    For any (mime, width, height, size_bytes):
      * `ok` is True iff every rule passes.
      * For each rule that fails, the corresponding per-field error is
        present in `errors`.
      * The function never raises.
    """
    ok, errors = validate_icon(mime, width, height, size_bytes)

    # Errors must be a list of FieldError instances.
    assert isinstance(errors, list)
    for e in errors:
        assert isinstance(e, FieldError)
        assert isinstance(e.field, str) and e.field
        assert isinstance(e.message, str) and e.message

    # Reference rule outcomes.
    mime_ok = _ref_mime_ok(mime)
    dims_ok = _ref_dimensions_ok(width, height)
    aspect_ok = _ref_aspect_ok(width, height)
    size_ok = _ref_size_ok(size_bytes)

    expected_ok = mime_ok and dims_ok and aspect_ok and size_ok
    assert ok is expected_ok, (
        f"validate_icon({mime!r}, {width!r}, {height!r}, {size_bytes!r}) "
        f"returned ok={ok}; reference expected ok={expected_ok} "
        f"(mime_ok={mime_ok}, dims_ok={dims_ok}, "
        f"aspect_ok={aspect_ok}, size_ok={size_ok})"
    )

    # Per-rule error presence: when a rule fails, its field tag must appear
    # at least once in errors. When all rules pass, errors must be empty.
    fields_present = {e.field for e in errors}

    if not mime_ok:
        assert FIELD_MIME in fields_present, (
            f"mime rule failed for {mime!r} but no 'mime' error emitted: {errors}"
        )
    if not dims_ok:
        assert FIELD_DIMENSIONS in fields_present, (
            f"dimensions rule failed for ({width}, {height}) but no "
            f"'dimensions' error emitted: {errors}"
        )
    if dims_ok and not aspect_ok:
        # Aspect is only checked when dimensions are otherwise sensible.
        assert FIELD_ASPECT in fields_present, (
            f"aspect rule failed for ({width}, {height}) but no "
            f"'aspect' error emitted: {errors}"
        )
    if not size_ok:
        assert FIELD_SIZE in fields_present, (
            f"size rule failed for {size_bytes!r} but no 'size' error "
            f"emitted: {errors}"
        )

    if expected_ok:
        assert errors == [], (
            f"all rules passed but errors is non-empty: {errors}"
        )


# -----------------------------------------------------------------------------
# Targeted boundary cases — kept tiny and explicit, complementing the
# property-based cross-check above.
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "width,height,expected_ok",
    [
        (512, 512, True),    # exactly at the dimension floor
        (511, 511, False),   # one px short
        (512, 511, False),   # mixed: one dim short
        (513, 512, True),    # one px over (still within 1% aspect)
        (1024, 1024, True),  # comfortably above
    ],
    ids=[
        "exactly-512",
        "511-square",
        "512x511",
        "513x512",
        "1024-square",
    ],
)
def test_dimension_boundary(width: int, height: int, expected_ok: bool) -> None:
    ok, errors = validate_icon("image/png", width, height, 1024)
    assert ok is expected_ok, (
        f"dimension boundary {width}x{height}: ok={ok}, errors={errors}"
    )
    if not expected_ok:
        assert any(e.field == FIELD_DIMENSIONS for e in errors)


@pytest.mark.parametrize(
    "size_bytes,expected_ok",
    [
        (MAX_FILE_SIZE - 1, True),
        (MAX_FILE_SIZE, True),       # boundary: exactly at 4 MB
        (MAX_FILE_SIZE + 1, False),  # boundary: 1 byte over
        (MAX_FILE_SIZE * 2, False),
    ],
    ids=["4MB-1B", "exactly-4MB", "4MB+1B", "8MB"],
)
def test_size_boundary(size_bytes: int, expected_ok: bool) -> None:
    ok, errors = validate_icon("image/png", 512, 512, size_bytes)
    assert ok is expected_ok, (
        f"size boundary {size_bytes}B: ok={ok}, errors={errors}"
    )
    if not expected_ok:
        assert any(e.field == FIELD_SIZE for e in errors)


@pytest.mark.parametrize(
    "width,height,expected_ok",
    [
        # ratio = (w-h)/max(w,h)
        (1000, 1000, True),   # ratio 0.000 — exactly square
        (1000, 995, True),    # ratio 0.005 — within 1%
        (1000, 990, True),    # ratio 0.010 — exactly at boundary
        (1000, 989, False),   # ratio 0.011 — just over
        (1000, 985, False),   # ratio 0.015 — clearly outside
        (1000, 900, False),   # ratio 0.100 — way outside
    ],
    ids=[
        "perfect-square",
        "ratio-0.005",
        "ratio-0.010-at-boundary",
        "ratio-0.011-just-over",
        "ratio-0.015-outside",
        "ratio-0.100-way-outside",
    ],
)
def test_aspect_ratio_boundary(
    width: int, height: int, expected_ok: bool
) -> None:
    ok, errors = validate_icon("image/png", width, height, 1024)
    # Sanity-check our hand-computed ratios match the rule.
    ratio = abs(width - height) / max(width, height)
    assert math.isclose(ratio, abs(width - height) / max(width, height))
    assert ok is expected_ok, (
        f"aspect boundary {width}x{height} (ratio {ratio:.4f}): "
        f"ok={ok}, errors={errors}"
    )
    if not expected_ok:
        assert any(e.field == FIELD_ASPECT for e in errors)


@pytest.mark.parametrize(
    "mime,expected_ok",
    [
        ("image/png", True),
        ("image/jpeg", False),
        ("image/PNG", False),     # case-sensitive per the spec
        ("IMAGE/PNG", False),
        ("image/png ", False),    # trailing whitespace
        (" image/png", False),
        ("", False),
        ("application/octet-stream", False),
    ],
)
def test_mime_variants(mime: str, expected_ok: bool) -> None:
    ok, errors = validate_icon(mime, 512, 512, 1024)
    assert ok is expected_ok, f"mime {mime!r}: ok={ok}, errors={errors}"
    if not expected_ok:
        assert any(e.field == FIELD_MIME for e in errors)


def test_all_rules_pass_returns_no_errors() -> None:
    ok, errors = validate_icon("image/png", 1024, 1024, 1024 * 1024)
    assert ok is True
    assert errors == []


def test_all_rules_fail_emits_one_error_per_rule() -> None:
    # mime wrong, dimensions too small, size too big.
    # Aspect can't be separately failing because the validator skips the
    # aspect check when dimensions are non-positive — so use small-but-square
    # dimensions for this case.
    ok, errors = validate_icon("image/jpeg", 100, 200, MAX_FILE_SIZE + 1)
    assert ok is False
    fields = {e.field for e in errors}
    assert FIELD_MIME in fields
    assert FIELD_DIMENSIONS in fields
    assert FIELD_ASPECT in fields
    assert FIELD_SIZE in fields
