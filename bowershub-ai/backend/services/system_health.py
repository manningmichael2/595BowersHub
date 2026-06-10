"""
System health metrics service.

Reads CPU, memory, disk, and uptime from Linux /proc filesystem and os.statvfs.
Each sub-section is gathered independently — a failure in one doesn't crash the others.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Mount points to check for disk usage
DISK_MOUNT_POINTS = ["/", "/files", "/knowledge"]


async def _read_cpu_percent() -> float:
    """
    Calculate CPU usage percentage by reading /proc/stat twice with a short delay.
    Returns the overall CPU usage as a percentage (0-100).
    """
    def _parse_cpu_line(line: str) -> tuple[int, int]:
        """Parse the first 'cpu' line from /proc/stat. Returns (idle, total)."""
        parts = line.split()
        # cpu user nice system idle iowait irq softirq steal guest guest_nice
        values = [int(v) for v in parts[1:]]
        idle = values[3] + values[4]  # idle + iowait
        total = sum(values)
        return idle, total

    proc_stat = Path("/proc/stat")
    content1 = proc_stat.read_text()
    await asyncio.sleep(0.1)
    content2 = proc_stat.read_text()

    line1 = content1.splitlines()[0]
    line2 = content2.splitlines()[0]

    idle1, total1 = _parse_cpu_line(line1)
    idle2, total2 = _parse_cpu_line(line2)

    idle_delta = idle2 - idle1
    total_delta = total2 - total1

    if total_delta == 0:
        return 0.0

    cpu_percent = (1.0 - idle_delta / total_delta) * 100.0
    return round(cpu_percent, 1)


def _read_memory() -> dict[str, Any]:
    """
    Read memory info from /proc/meminfo.
    Returns dict with used_bytes, total_bytes, percent.
    """
    meminfo = Path("/proc/meminfo").read_text()
    info: dict[str, int] = {}

    for line in meminfo.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            # Values in /proc/meminfo are in kB
            value_kb = int(parts[1])
            info[key] = value_kb

    total_kb = info.get("MemTotal", 0)
    available_kb = info.get("MemAvailable", 0)
    used_kb = total_kb - available_kb

    total_bytes = total_kb * 1024
    used_bytes = used_kb * 1024
    percent = round((used_kb / total_kb) * 100, 1) if total_kb > 0 else 0.0

    return {
        "used_bytes": used_bytes,
        "total_bytes": total_bytes,
        "percent": percent,
    }


def _read_disk() -> list[dict[str, Any]]:
    """
    Read disk usage for configured mount points using os.statvfs.
    Skips mount points that don't exist gracefully.
    """
    disks = []
    for mount in DISK_MOUNT_POINTS:
        if not os.path.exists(mount):
            continue
        try:
            stat = os.statvfs(mount)
            total_bytes = stat.f_blocks * stat.f_frsize
            free_bytes = stat.f_bavail * stat.f_frsize
            used_bytes = total_bytes - free_bytes
            percent = round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0.0
            disks.append({
                "mount": mount,
                "used_bytes": used_bytes,
                "total_bytes": total_bytes,
                "percent": percent,
            })
        except OSError as e:
            logger.warning(f"Failed to read disk stats for {mount}: {e}")
            continue
    return disks


def _read_uptime() -> float:
    """Read system uptime in seconds from /proc/uptime."""
    content = Path("/proc/uptime").read_text()
    # First value is uptime in seconds (float)
    return float(content.split()[0])


async def get_system_health() -> dict[str, Any]:
    """
    Gather all system health metrics.

    Each sub-section is independently try/excepted so a failure in one
    doesn't crash the whole response. Errors are flagged per-section.

    Returns structured JSON matching the design spec:
    {
        "cpu_percent": float,
        "memory": {"used_bytes": int, "total_bytes": int, "percent": float},
        "disk": [{"mount": str, "used_bytes": int, "total_bytes": int, "percent": float}],
        "uptime_seconds": float,
        "errors": {}  # per-section error flags
    }
    """
    result: dict[str, Any] = {
        "cpu_percent": 0.0,
        "memory": {"used_bytes": 0, "total_bytes": 0, "percent": 0.0},
        "disk": [],
        "uptime_seconds": 0.0,
        "errors": {},
    }

    # CPU (async — needs sleep for delta calculation)
    try:
        result["cpu_percent"] = await _read_cpu_percent()
    except Exception as e:
        logger.error(f"Failed to read CPU stats: {e}")
        result["errors"]["cpu"] = str(e)

    # Memory
    try:
        result["memory"] = _read_memory()
    except Exception as e:
        logger.error(f"Failed to read memory stats: {e}")
        result["errors"]["memory"] = str(e)

    # Disk
    try:
        result["disk"] = _read_disk()
    except Exception as e:
        logger.error(f"Failed to read disk stats: {e}")
        result["errors"]["disk"] = str(e)

    # Uptime
    try:
        result["uptime_seconds"] = _read_uptime()
    except Exception as e:
        logger.error(f"Failed to read uptime: {e}")
        result["errors"]["uptime"] = str(e)

    return result
