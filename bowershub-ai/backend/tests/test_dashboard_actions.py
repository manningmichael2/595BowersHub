"""Dashboard V2 Phase 2 (Task 6) — Action Center trigger logic.

`evaluate_actions` is a pure function over the SSE cache; no DB needed.
"""
from backend.services.dashboard_stream import (
    evaluate_actions, DISK_WARN_PCT, DISK_CRIT_PCT, MEM_WARN_PCT,
)


def _health(disk=None, mem_pct=None):
    return {"system_health": {
        "disk": disk or [],
        "memory": {"percent": mem_pct} if mem_pct is not None else {},
    }}


def test_no_actions_when_healthy():
    assert evaluate_actions(_health(disk=[{"mount": "/", "percent": 40.0}], mem_pct=30.0)) == []


def test_missing_system_health_is_empty():
    assert evaluate_actions({}) == []


def test_disk_warning_and_critical_levels():
    warn = evaluate_actions(_health(disk=[{"mount": "/data", "percent": DISK_WARN_PCT}]))
    assert len(warn) == 1 and warn[0]["level"] == "warning" and warn[0]["id"] == "disk:/data"
    assert "90%" in warn[0]["title"]

    crit = evaluate_actions(_health(disk=[{"mount": "/data", "percent": DISK_CRIT_PCT}]))
    assert crit[0]["level"] == "error"


def test_memory_pressure_alert():
    out = evaluate_actions(_health(mem_pct=MEM_WARN_PCT + 2))
    assert len(out) == 1 and out[0]["id"] == "memory" and out[0]["level"] == "warning"


def test_multiple_and_stable_ids():
    out = evaluate_actions(_health(
        disk=[{"mount": "/", "percent": 96.0}, {"mount": "/boot", "percent": 50.0}],
        mem_pct=91.0,
    ))
    ids = {a["id"] for a in out}
    assert ids == {"disk:/", "memory"}  # healthy /boot excluded


def test_non_numeric_percent_ignored():
    assert evaluate_actions(_health(disk=[{"mount": "/", "percent": None}])) == []
