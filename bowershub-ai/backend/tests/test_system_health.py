"""
Unit tests for the system health service.

Tests the CPU, memory, disk, and uptime parsing logic, plus the
partial-failure resilience (each sub-section fails independently).

Validates: Requirements 7.1, 7.3, 7.4
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from backend.services.system_health import (
    _read_cpu_percent,
    _read_memory,
    _read_disk,
    _read_uptime,
    get_system_health,
)


# ---------------------------------------------------------------------------
# CPU parsing
# ---------------------------------------------------------------------------

PROC_STAT_SAMPLE_1 = """\
cpu  10000 200 3000 50000 1000 100 50 0 0 0
cpu0 5000 100 1500 25000 500 50 25 0 0 0
cpu1 5000 100 1500 25000 500 50 25 0 0 0
"""

PROC_STAT_SAMPLE_2 = """\
cpu  10100 210 3050 50200 1010 105 55 0 0 0
cpu0 5050 105 1525 25100 505 52 27 0 0 0
cpu1 5050 105 1525 25100 505 53 28 0 0 0
"""


@pytest.mark.asyncio
async def test_read_cpu_percent_calculates_delta():
    """CPU usage is calculated from the difference between two /proc/stat reads."""
    call_count = [0]

    def mock_read_text(self=None):
        nonlocal call_count
        call_count[0] += 1
        if call_count[0] == 1:
            return PROC_STAT_SAMPLE_1
        return PROC_STAT_SAMPLE_2

    with patch("backend.services.system_health.Path.read_text", mock_read_text):
        with patch("asyncio.sleep", return_value=None):
            result = await _read_cpu_percent()

    # idle1 = 50000 + 1000 = 51000, total1 = 10000+200+3000+50000+1000+100+50 = 64350
    # idle2 = 50200 + 1010 = 51210, total2 = 10100+210+3050+50200+1010+105+55 = 64730
    # idle_delta = 210, total_delta = 380
    # cpu% = (1 - 210/380) * 100 = 44.7...
    assert isinstance(result, float)
    assert 44.0 <= result <= 45.0


@pytest.mark.asyncio
async def test_read_cpu_percent_zero_delta():
    """When total_delta is 0 (unlikely but possible), returns 0.0."""
    def mock_read_text(self=None):
        return PROC_STAT_SAMPLE_1

    with patch("backend.services.system_health.Path.read_text", mock_read_text):
        with patch("asyncio.sleep", return_value=None):
            result = await _read_cpu_percent()

    assert result == 0.0


# ---------------------------------------------------------------------------
# Memory parsing
# ---------------------------------------------------------------------------

PROC_MEMINFO_SAMPLE = """\
MemTotal:       16384000 kB
MemFree:         2000000 kB
MemAvailable:    8000000 kB
Buffers:          500000 kB
Cached:          4000000 kB
SwapTotal:       4000000 kB
SwapFree:        4000000 kB
"""


def test_read_memory_parses_meminfo():
    """Memory parsing extracts total, used (total - available), and percent."""
    with patch("backend.services.system_health.Path.read_text", return_value=PROC_MEMINFO_SAMPLE):
        result = _read_memory()

    total_bytes = 16384000 * 1024
    available_bytes = 8000000 * 1024
    used_bytes = total_bytes - available_bytes

    assert result["total_bytes"] == total_bytes
    assert result["used_bytes"] == used_bytes
    assert 50.0 <= result["percent"] <= 52.0  # ~51.2%


def test_read_memory_zero_total():
    """If MemTotal is 0 (weird but defensive), percent should be 0.0."""
    meminfo = "MemTotal:        0 kB\nMemAvailable:    0 kB\n"
    with patch("backend.services.system_health.Path.read_text", return_value=meminfo):
        result = _read_memory()

    assert result["percent"] == 0.0
    assert result["total_bytes"] == 0
    assert result["used_bytes"] == 0


# ---------------------------------------------------------------------------
# Disk parsing
# ---------------------------------------------------------------------------

def test_read_disk_returns_entries_for_existing_mounts():
    """Disk info is returned for each mount point that exists."""
    mock_stat = MagicMock()
    mock_stat.f_blocks = 1000000
    mock_stat.f_frsize = 4096
    mock_stat.f_bavail = 600000

    with patch("os.path.exists", return_value=True):
        with patch("os.statvfs", return_value=mock_stat):
            result = _read_disk()

    # Should check all 3 mount points (/, /files, /knowledge)
    assert len(result) == 3
    for entry in result:
        assert "mount" in entry
        assert "used_bytes" in entry
        assert "total_bytes" in entry
        assert "percent" in entry

    # Verify calculation: total = 1000000 * 4096, free = 600000 * 4096
    total = 1000000 * 4096
    free = 600000 * 4096
    used = total - free
    assert result[0]["total_bytes"] == total
    assert result[0]["used_bytes"] == used
    assert 39.0 <= result[0]["percent"] <= 41.0  # 40%


def test_read_disk_skips_nonexistent_mounts():
    """Mount points that don't exist are silently skipped."""
    def mock_exists(path):
        return path == "/"

    mock_stat = MagicMock()
    mock_stat.f_blocks = 500000
    mock_stat.f_frsize = 4096
    mock_stat.f_bavail = 250000

    with patch("os.path.exists", side_effect=mock_exists):
        with patch("os.statvfs", return_value=mock_stat):
            result = _read_disk()

    assert len(result) == 1
    assert result[0]["mount"] == "/"


def test_read_disk_handles_statvfs_error():
    """If statvfs raises OSError for a mount, that mount is skipped."""
    def mock_exists(path):
        return True

    def mock_statvfs(path):
        if path == "/files":
            raise OSError("Permission denied")
        stat = MagicMock()
        stat.f_blocks = 100000
        stat.f_frsize = 4096
        stat.f_bavail = 50000
        return stat

    with patch("os.path.exists", side_effect=mock_exists):
        with patch("os.statvfs", side_effect=mock_statvfs):
            result = _read_disk()

    # Only / and /knowledge should be returned (not /files)
    assert len(result) == 2
    mounts = [d["mount"] for d in result]
    assert "/" in mounts
    assert "/knowledge" in mounts
    assert "/files" not in mounts


# ---------------------------------------------------------------------------
# Uptime parsing
# ---------------------------------------------------------------------------

def test_read_uptime_parses_proc_uptime():
    """Uptime is the first float from /proc/uptime."""
    with patch("backend.services.system_health.Path.read_text", return_value="86400.50 172000.00\n"):
        result = _read_uptime()

    assert result == 86400.50


# ---------------------------------------------------------------------------
# get_system_health — partial failure resilience
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_system_health_returns_complete_response():
    """Full response has all sections populated and empty errors dict."""
    with patch("backend.services.system_health._read_cpu_percent", return_value=25.5):
        with patch("backend.services.system_health._read_memory", return_value={
            "used_bytes": 4 * 1024**3, "total_bytes": 16 * 1024**3, "percent": 25.0
        }):
            with patch("backend.services.system_health._read_disk", return_value=[
                {"mount": "/", "used_bytes": 100 * 1024**3, "total_bytes": 500 * 1024**3, "percent": 20.0}
            ]):
                with patch("backend.services.system_health._read_uptime", return_value=86400.0):
                    result = await get_system_health()

    assert result["cpu_percent"] == 25.5
    assert result["memory"]["percent"] == 25.0
    assert len(result["disk"]) == 1
    assert result["uptime_seconds"] == 86400.0
    assert result["errors"] == {}


@pytest.mark.asyncio
async def test_get_system_health_cpu_failure_doesnt_crash_others():
    """If CPU reading fails, the rest still returns with an error flag for cpu."""
    with patch("backend.services.system_health._read_cpu_percent", side_effect=FileNotFoundError("/proc/stat")):
        with patch("backend.services.system_health._read_memory", return_value={
            "used_bytes": 8 * 1024**3, "total_bytes": 16 * 1024**3, "percent": 50.0
        }):
            with patch("backend.services.system_health._read_disk", return_value=[]):
                with patch("backend.services.system_health._read_uptime", return_value=1000.0):
                    result = await get_system_health()

    assert result["cpu_percent"] == 0.0  # default fallback
    assert "cpu" in result["errors"]
    assert result["memory"]["percent"] == 50.0
    assert result["uptime_seconds"] == 1000.0


@pytest.mark.asyncio
async def test_get_system_health_memory_failure_doesnt_crash_others():
    """If memory reading fails, the rest still returns with an error flag for memory."""
    with patch("backend.services.system_health._read_cpu_percent", return_value=10.0):
        with patch("backend.services.system_health._read_memory", side_effect=ValueError("bad parse")):
            with patch("backend.services.system_health._read_disk", return_value=[]):
                with patch("backend.services.system_health._read_uptime", return_value=5000.0):
                    result = await get_system_health()

    assert result["cpu_percent"] == 10.0
    assert "memory" in result["errors"]
    assert result["memory"] == {"used_bytes": 0, "total_bytes": 0, "percent": 0.0}
    assert result["uptime_seconds"] == 5000.0


@pytest.mark.asyncio
async def test_get_system_health_all_failures_returns_error_flags():
    """If all sub-sections fail, response is still valid JSON with all error flags."""
    with patch("backend.services.system_health._read_cpu_percent", side_effect=Exception("cpu fail")):
        with patch("backend.services.system_health._read_memory", side_effect=Exception("mem fail")):
            with patch("backend.services.system_health._read_disk", side_effect=Exception("disk fail")):
                with patch("backend.services.system_health._read_uptime", side_effect=Exception("uptime fail")):
                    result = await get_system_health()

    assert "cpu" in result["errors"]
    assert "memory" in result["errors"]
    assert "disk" in result["errors"]
    assert "uptime" in result["errors"]
    # Response is still well-formed
    assert "cpu_percent" in result
    assert "memory" in result
    assert "disk" in result
    assert "uptime_seconds" in result
