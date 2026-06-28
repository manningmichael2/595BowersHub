"""Context-capture attribution: a persisted fact records *from whom* it was
captured (household feature), and stays clean when no user is associated."""
import json
from types import SimpleNamespace

import pytest

from backend.services.context_capture import ContextCapture


class _StubProvider:
    """Returns a fixed extraction so the test is deterministic (no model call)."""
    def __init__(self, facts):
        self._payload = json.dumps({"facts": facts})

    async def complete(self, **kwargs):
        return SimpleNamespace(content=self._payload)


def _capture(tmp_path, facts):
    cfg = SimpleNamespace(KNOWLEDGE_ROOT=str(tmp_path))
    return ContextCapture(_StubProvider(facts), cfg)


@pytest.mark.asyncio
async def test_persisted_fact_records_capturing_user(tmp_path):
    cap = _capture(tmp_path, [{"topic": "people", "statement": "Manon likes oat milk"}])

    await cap.evaluate(
        "Please remember that Manon likes oat milk in her coffee.",
        "Got it — noted.",
        workspace_name="General",
        captured_by="Michael",
    )

    note = (tmp_path / "general" / "people.md").read_text()
    assert "(Michael)" in note
    assert "Manon likes oat milk" in note


@pytest.mark.asyncio
async def test_no_author_stamp_when_user_unknown(tmp_path):
    cap = _capture(tmp_path, [{"topic": "people", "statement": "Manon likes oat milk"}])

    await cap.evaluate(
        "Please remember that Manon likes oat milk in her coffee.",
        "Got it — noted.",
        workspace_name="General",
        captured_by=None,
    )

    note = (tmp_path / "general" / "people.md").read_text()
    assert "(" not in note.split("] ", 1)[1]  # nothing between the date and statement
    assert "Manon likes oat milk" in note
