"""In-process registry of active heavy background tasks — powers the Dashboard
V2 Hardware HUD (Task 7). When CPU is pegged, `system_health` names the likely
culprit from this registry instead of leaving the user guessing.

In-process only (single-worker deployment); the dashboard publisher runs in the
same process as the scheduler jobs, so a plain module-level dict is sufficient.
"""
import functools
import time
from contextlib import asynccontextmanager
from typing import Optional

# task name -> wall-clock start time (seconds)
_active: dict[str, float] = {}


@asynccontextmanager
async def track_task(name: str):
    """Mark `name` active for the duration of the block."""
    _active[name] = time.time()
    try:
        yield
    finally:
        _active.pop(name, None)


def tracked(name: str):
    """Decorator form of `track_task` for a whole job entry point."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            async with track_task(name):
                return await fn(*args, **kwargs)
        return wrapper
    return deco


def active_tasks() -> list[dict]:
    """Currently-running tracked tasks, longest-running first."""
    now = time.time()
    return [
        {"name": n, "running_seconds": round(now - t, 1)}
        for n, t in sorted(_active.items(), key=lambda kv: kv[1])
    ]


def strain_culprit() -> Optional[dict]:
    """The longest-running active task, or None if nothing is tracked."""
    tasks = active_tasks()
    return tasks[0] if tasks else None
