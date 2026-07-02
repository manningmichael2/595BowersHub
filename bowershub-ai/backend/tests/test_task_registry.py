"""Dashboard V2 Phase 3 (Task 7) — Hardware HUD: task registry + strain field.

Pure/async, no DB. `get_system_health` reads real host metrics but its CPU probe
is monkeypatched so the strain branch is deterministic.
"""
import pytest

from backend.services import task_registry
from backend.services.task_registry import track_task, tracked, active_tasks, strain_culprit


@pytest.mark.asyncio
async def test_track_task_adds_then_removes():
    assert strain_culprit() is None
    async with track_task("Embedding worker"):
        names = [t["name"] for t in active_tasks()]
        assert names == ["Embedding worker"]
        assert strain_culprit()["name"] == "Embedding worker"
    assert active_tasks() == []  # cleaned up on exit


@pytest.mark.asyncio
async def test_tracked_decorator_registers_during_call():
    seen = {}

    @tracked("Categorizer")
    async def job():
        seen["names"] = [t["name"] for t in active_tasks()]
        return "ok"

    assert await job() == "ok"
    assert seen["names"] == ["Categorizer"]
    assert active_tasks() == []  # gone after return


@pytest.mark.asyncio
async def test_exception_still_unregisters():
    with pytest.raises(ValueError):
        async with track_task("SimpleFin sync"):
            raise ValueError("boom")
    assert active_tasks() == []


@pytest.mark.asyncio
async def test_system_health_reports_strain_when_pegged(monkeypatch):
    from backend.services import system_health

    async def _fake_cpu():
        return 96.0
    monkeypatch.setattr(system_health, "_read_cpu_percent", _fake_cpu)

    async with track_task("Embedding worker"):
        result = await system_health.get_system_health()
    assert result["cpu_percent"] == 96.0
    assert result["strain"]["culprit"] == "Embedding worker"
    assert result["strain"]["active_tasks"][0]["name"] == "Embedding worker"


@pytest.mark.asyncio
async def test_no_strain_field_when_idle(monkeypatch):
    from backend.services import system_health

    async def _fake_cpu():
        return 12.0
    monkeypatch.setattr(system_health, "_read_cpu_percent", _fake_cpu)

    result = await system_health.get_system_health()
    assert "strain" not in result
