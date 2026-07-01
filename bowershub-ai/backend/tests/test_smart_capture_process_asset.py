"""Task 8 — native Process Asset (vision): insert + vision fields, sha256 dedup,
non-image skip, missing-file fallback. Filewriter + model are mocked. (n8n-decommission)
"""

from __future__ import annotations

import json
import uuid

import pytest

from backend.database import close_pool
from backend.models.message import CompletionResult
from backend.services.smart_capture import process_asset as pa
from backend.tests.semantic_helpers import apply_migrations


class FakeProvider:
    def __init__(self, content):
        self._content = content

    async def complete(self, **kwargs):
        # assert an image block was sent
        content = kwargs["messages"][0]["content"]
        assert any(b.get("type") == "image" for b in content)
        return CompletionResult(content=self._content, model="fake", input_tokens=1, output_tokens=1)


def _fw_factory(monkeypatch, *, exists=True, mime="image/jpeg", sha="abc123", b64="Zm9v"):
    async def fake_fw(path, body):
        if path == "/probe":
            return {"ok": True, "exists": exists, "sha256": sha, "mime": mime, "size_bytes": 100}
        if path == "/read-base64":
            return {"ok": True, "base64": b64}
        if path == "/move":
            return {"ok": True}
        raise AssertionError(f"unexpected filewriter path {path}")

    monkeypatch.setattr(pa, "_fw", fake_fw)


@pytest.mark.asyncio
async def test_new_image_inserts_and_runs_vision(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        _fw_factory(monkeypatch, sha="sha-new")
        prov = FakeProvider(json.dumps({"brand": "DeWalt", "type": "drill"}))
        async with pool.acquire() as conn:
            out = await pa.process_asset_native(
                image_path="inbox/x.jpg", domain_hint="tool", model_provider=prov, conn=conn
            )
            assert out["ok"] and out["dedup"] is False
            assert out["ai_summary"] and "DeWalt" in out["ai_summary"]
            assert out["domain"] == "tool"
            row = await conn.fetchrow(
                "SELECT sha256, ai_summary, domain, processed_at FROM files.assets WHERE id=$1::uuid",
                out["asset_id"],
            )
            assert row["sha256"] == "sha-new" and row["processed_at"] is not None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_sha256_dedup_returns_existing(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        _fw_factory(monkeypatch, sha="dup-sha")
        async with pool.acquire() as conn:
            existing = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO files.assets (id, path, original_name, mime, size_bytes, sha256, domain) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                uuid.UUID(existing), "/files/inventory/tools/x.jpg", "x.jpg", "image/jpeg",
                100, "dup-sha", "tool",
            )
            out = await pa.process_asset_native(
                image_path="inbox/x.jpg", domain_hint="tool",
                model_provider=FakeProvider("{}"), conn=conn,
            )
            assert out["dedup"] is True and out["asset_id"] == existing
            # no second row inserted
            n = await conn.fetchval("SELECT count(*) FROM files.assets WHERE sha256='dup-sha'")
            assert n == 1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_non_image_skips_vision_but_inserts(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        _fw_factory(monkeypatch, mime="application/pdf", sha="pdf-sha")

        class BoomProvider:
            async def complete(self, **k):
                raise AssertionError("vision must not run for non-image")

        async with pool.acquire() as conn:
            out = await pa.process_asset_native(
                image_path="inbox/manual.pdf", domain_hint="manual",
                model_provider=BoomProvider(), conn=conn,
            )
            assert out["ok"] and out["ai_summary"] is None
            assert await conn.fetchval("SELECT count(*) FROM files.assets WHERE sha256='pdf-sha'") == 1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_missing_file_returns_none(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        _fw_factory(monkeypatch, exists=False)
        async with pool.acquire() as conn:
            out = await pa.process_asset_native(
                image_path="inbox/ghost.jpg", domain_hint=None,
                model_provider=FakeProvider("{}"), conn=conn,
            )
            assert out is None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_invalid_path_returns_none(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            out = await pa.process_asset_native(
                image_path="../etc/passwd", domain_hint=None,
                model_provider=FakeProvider("{}"), conn=conn,
            )
            assert out is None
    finally:
        await close_pool()
