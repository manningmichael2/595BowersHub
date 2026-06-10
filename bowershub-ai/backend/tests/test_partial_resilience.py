"""
Property test for partial response resilience of the system-health endpoint.

**Property 5: Partial response resilience**

For any dashboard data endpoint that aggregates multiple sub-sections
(e.g., system-health aggregates CPU + memory + disk + uptime), if one
sub-section's data source is unreachable, the endpoint SHALL still return
the successful sub-sections with an error flag indicating which sub-section
failed — never a complete endpoint failure.

**Validates: Requirements 7.3, 11.2**

Feature: dashboard-integration, Property 5: Partial response resilience
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from backend.services.system_health import get_system_health


# ---------------------------------------------------------------------------
# Sub-section definitions
# ---------------------------------------------------------------------------

SUBSECTIONS = ["cpu", "memory", "disk", "uptime"]

# Maps sub-section name → the internal function path to mock
SUBSECTION_PATCHES = {
    "cpu": "backend.services.system_health._read_cpu_percent",
    "memory": "backend.services.system_health._read_memory",
    "disk": "backend.services.system_health._read_disk",
    "uptime": "backend.services.system_health._read_uptime",
}

# Maps sub-section name → a valid return value when the section succeeds
SUBSECTION_SUCCESS_VALUES = {
    "cpu": 42.5,
    "memory": {"used_bytes": 8 * 1024**3, "total_bytes": 16 * 1024**3, "percent": 50.0},
    "disk": [{"mount": "/", "used_bytes": 200 * 1024**3, "total_bytes": 500 * 1024**3, "percent": 40.0}],
    "uptime": 86400.0,
}

# Maps sub-section name → the result key in the response
SUBSECTION_RESULT_KEYS = {
    "cpu": "cpu_percent",
    "memory": "memory",
    "disk": "disk",
    "uptime": "uptime_seconds",
}


# ---------------------------------------------------------------------------
# Strategy: generate random subsets of failures (0 to all 4)
# ---------------------------------------------------------------------------

failure_set_strategy = st.lists(
    st.sampled_from(SUBSECTIONS),
    unique=True,
    min_size=0,
    max_size=4,
)


# ---------------------------------------------------------------------------
# Property test: partial response resilience
# ---------------------------------------------------------------------------

@given(failure_set=failure_set_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@pytest.mark.asyncio
async def test_partial_response_resilience(failure_set: list[str]) -> None:
    """
    For any subset of sub-section failures (0 to all 4), the system-health
    endpoint returns a valid response with error flags only for failed sections.
    Non-failed sections return valid data. The function never raises.

    Feature: dashboard-integration, Property 5: Partial response resilience
    """
    patches = {}
    for section in SUBSECTIONS:
        if section in failure_set:
            # This section should fail
            patches[section] = patch(
                SUBSECTION_PATCHES[section],
                side_effect=Exception(f"simulated failure: {section}"),
            )
        else:
            # This section should succeed
            if section == "cpu":
                # _read_cpu_percent is async
                async def _mock_cpu():
                    return SUBSECTION_SUCCESS_VALUES["cpu"]
                patches[section] = patch(
                    SUBSECTION_PATCHES[section],
                    side_effect=_mock_cpu,
                )
            else:
                patches[section] = patch(
                    SUBSECTION_PATCHES[section],
                    return_value=SUBSECTION_SUCCESS_VALUES[section],
                )

    # Apply all patches
    for p in patches.values():
        p.start()

    try:
        # The function should NEVER raise, regardless of failure combination
        result = await get_system_health()
    finally:
        for p in patches.values():
            p.stop()

    # --- Assertions ---

    # 1. Response always has all expected keys
    assert "cpu_percent" in result, "Response missing cpu_percent key"
    assert "memory" in result, "Response missing memory key"
    assert "disk" in result, "Response missing disk key"
    assert "uptime_seconds" in result, "Response missing uptime_seconds key"
    assert "errors" in result, "Response missing errors key"

    # 2. errors dict contains exactly the sections that were set to fail
    assert set(result["errors"].keys()) == set(failure_set), (
        f"Expected errors for {failure_set}, got errors for {list(result['errors'].keys())}"
    )

    # 3. Non-failed sections have valid data
    for section in SUBSECTIONS:
        if section not in failure_set:
            result_key = SUBSECTION_RESULT_KEYS[section]
            if section == "cpu":
                assert isinstance(result[result_key], float), (
                    f"cpu_percent should be float, got {type(result[result_key])}"
                )
                assert result[result_key] == SUBSECTION_SUCCESS_VALUES["cpu"]
            elif section == "memory":
                mem = result[result_key]
                assert isinstance(mem, dict), "memory should be a dict"
                assert "used_bytes" in mem
                assert "total_bytes" in mem
                assert "percent" in mem
                assert mem == SUBSECTION_SUCCESS_VALUES["memory"]
            elif section == "disk":
                assert isinstance(result[result_key], list), "disk should be a list"
                assert result[result_key] == SUBSECTION_SUCCESS_VALUES["disk"]
            elif section == "uptime":
                assert isinstance(result[result_key], float), (
                    f"uptime_seconds should be float, got {type(result[result_key])}"
                )
                assert result[result_key] == SUBSECTION_SUCCESS_VALUES["uptime"]

    # 4. Failed sections have error messages (non-empty strings)
    for section in failure_set:
        assert isinstance(result["errors"][section], str), (
            f"Error for {section} should be a string"
        )
        assert len(result["errors"][section]) > 0, (
            f"Error message for {section} should not be empty"
        )


# ---------------------------------------------------------------------------
# Parametrized tests for specific failure combinations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_failures_returns_clean_response():
    """When all sections succeed, errors dict is empty and all data is present."""
    async def _mock_cpu():
        return 33.3

    with patch(SUBSECTION_PATCHES["cpu"], side_effect=_mock_cpu):
        with patch(SUBSECTION_PATCHES["memory"], return_value=SUBSECTION_SUCCESS_VALUES["memory"]):
            with patch(SUBSECTION_PATCHES["disk"], return_value=SUBSECTION_SUCCESS_VALUES["disk"]):
                with patch(SUBSECTION_PATCHES["uptime"], return_value=SUBSECTION_SUCCESS_VALUES["uptime"]):
                    result = await get_system_health()

    assert result["errors"] == {}
    assert result["cpu_percent"] == 33.3
    assert result["memory"]["percent"] == 50.0
    assert len(result["disk"]) == 1
    assert result["uptime_seconds"] == 86400.0


@pytest.mark.asyncio
async def test_all_failures_still_returns_valid_response():
    """When all 4 sections fail, response is still well-formed with all error flags."""
    with patch(SUBSECTION_PATCHES["cpu"], side_effect=Exception("cpu down")):
        with patch(SUBSECTION_PATCHES["memory"], side_effect=Exception("mem down")):
            with patch(SUBSECTION_PATCHES["disk"], side_effect=Exception("disk down")):
                with patch(SUBSECTION_PATCHES["uptime"], side_effect=Exception("uptime down")):
                    result = await get_system_health()

    # All keys present
    assert "cpu_percent" in result
    assert "memory" in result
    assert "disk" in result
    assert "uptime_seconds" in result
    assert "errors" in result

    # All sections flagged as errors
    assert set(result["errors"].keys()) == {"cpu", "memory", "disk", "uptime"}

    # Default/fallback values are set
    assert result["cpu_percent"] == 0.0
    assert result["memory"] == {"used_bytes": 0, "total_bytes": 0, "percent": 0.0}
    assert result["disk"] == []
    assert result["uptime_seconds"] == 0.0


@pytest.mark.parametrize("failed_section", SUBSECTIONS)
@pytest.mark.asyncio
async def test_single_section_failure(failed_section: str):
    """Each individual section can fail without affecting the others."""
    patches_ctx = {}

    for section in SUBSECTIONS:
        if section == failed_section:
            patches_ctx[section] = patch(
                SUBSECTION_PATCHES[section],
                side_effect=Exception(f"{section} unavailable"),
            )
        else:
            if section == "cpu":
                async def _mock_cpu():
                    return SUBSECTION_SUCCESS_VALUES["cpu"]
                patches_ctx[section] = patch(
                    SUBSECTION_PATCHES[section],
                    side_effect=_mock_cpu,
                )
            else:
                patches_ctx[section] = patch(
                    SUBSECTION_PATCHES[section],
                    return_value=SUBSECTION_SUCCESS_VALUES[section],
                )

    for p in patches_ctx.values():
        p.start()

    try:
        result = await get_system_health()
    finally:
        for p in patches_ctx.values():
            p.stop()

    # Only the failed section should be in errors
    assert list(result["errors"].keys()) == [failed_section]

    # Other sections should have valid data
    for section in SUBSECTIONS:
        if section != failed_section:
            result_key = SUBSECTION_RESULT_KEYS[section]
            assert result[result_key] == SUBSECTION_SUCCESS_VALUES[section], (
                f"Section {section} should have valid data when {failed_section} fails"
            )
