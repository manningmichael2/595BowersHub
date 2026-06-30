"""Context-capture attribution: a persisted fact records *from whom* it was
captured (household feature), and stays clean when no user is associated."""
import json
from types import SimpleNamespace

import pytest

from backend.services.context_capture import ContextCapture


def _capture(tmp_path, facts):
    """A ContextCapture whose LLM extraction is stubbed to a fixed result, so the
    test is deterministic and makes no Ollama call."""
    cfg = SimpleNamespace(KNOWLEDGE_ROOT=str(tmp_path), OLLAMA_URL="http://x")
    cap = ContextCapture(None, cfg)
    payload = json.dumps({"facts": facts})

    async def _stub_extraction(prompt):
        return payload

    cap._run_extraction = _stub_extraction
    return cap


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


@pytest.mark.asyncio
async def test_captured_fact_mirrored_into_knowledge_graph(tmp_path, monkeypatch):
    """A captured fact is ALSO written to the pgvector knowledge graph (bh_entities
    via remember_entity), so it becomes hybrid-retrievable — not just a markdown file."""
    calls = []

    async def _fake_remember_entity(**kwargs):
        calls.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr("backend.services.knowledge_graph.remember_entity",
                        _fake_remember_entity)

    cap = _capture(tmp_path, [{"topic": "preferences",
                               "statement": "Michael is allergic to walnuts"}])
    await cap.evaluate(
        "By the way, I'm allergic to walnuts so keep that in mind.",
        "Noted — I'll remember you're allergic to walnuts.",
        workspace_name="General", captured_by="Michael", user_id=7,
    )

    assert len(calls) == 1, "the captured fact should be mirrored to exactly one entity"
    c = calls[0]
    assert c["summary"] == "Michael is allergic to walnuts"
    assert c["entity_type"] == "preference"          # mapped from the 'preferences' topic
    assert c["source"] == "context_capture"          # distinguishable from manual /remember
    assert c["user_id"] == 7                          # created_by attribution threaded through
    assert c["attributes"]["auto_captured"] is True


@pytest.mark.asyncio
async def test_captured_fact_defaults_to_private(tmp_path, monkeypatch):
    """With no visibility passed (the default), the mirrored entity is 'private' —
    auto-capture never silently shares a fact across the household (0057)."""
    calls = []

    async def _fake_remember_entity(**kwargs):
        calls.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr("backend.services.knowledge_graph.remember_entity",
                        _fake_remember_entity)

    cap = _capture(tmp_path, [{"topic": "preferences",
                               "statement": "Michael is allergic to walnuts"}])
    await cap.evaluate(
        "I'm allergic to walnuts.", "Noted.",
        workspace_name="General", captured_by="Michael", user_id=7,
    )
    assert calls and calls[0]["visibility"] == "private"


@pytest.mark.asyncio
async def test_captured_fact_shared_when_toggled(tmp_path, monkeypatch):
    """When the chat-bar toggle says Shared, the mirrored entity is 'shared'."""
    calls = []

    async def _fake_remember_entity(**kwargs):
        calls.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr("backend.services.knowledge_graph.remember_entity",
                        _fake_remember_entity)

    cap = _capture(tmp_path, [{"topic": "household",
                               "statement": "We are going to Italy in July"}])
    await cap.evaluate(
        "We're going to Italy in July.", "Sounds great.",
        workspace_name="General", captured_by="Michael", user_id=7,
        visibility="shared",
    )
    assert calls and calls[0]["visibility"] == "shared"


@pytest.mark.asyncio
async def test_graph_mirror_failure_does_not_lose_markdown(tmp_path, monkeypatch):
    """If the graph write throws, the markdown capture must still succeed (graph is
    best-effort; the file is the source of truth)."""
    async def _boom(**kwargs):
        raise RuntimeError("pool down")

    monkeypatch.setattr("backend.services.knowledge_graph.remember_entity", _boom)

    cap = _capture(tmp_path, [{"topic": "people", "statement": "Manon likes oat milk"}])
    persisted = await cap.evaluate(
        "Remember Manon likes oat milk.", "Got it.",
        workspace_name="General", captured_by="Michael", user_id=1,
    )

    assert len(persisted) == 1
    assert "Manon likes oat milk" in (tmp_path / "general" / "people.md").read_text()
