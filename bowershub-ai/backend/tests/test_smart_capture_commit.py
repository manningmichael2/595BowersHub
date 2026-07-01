"""Task 4 — native commit: each committer's parameterized write, idempotent
replay, per-intent failure, no-interpolated-SQL, _extra_fields folding,
house_room upsert, asset linking, and service-domain delegation. (n8n-decommission)
"""

from __future__ import annotations

import uuid

import pytest

from backend.database import close_pool
from backend.services.smart_capture import commit as sc_commit
from backend.services.smart_capture import committers as sc_committers
from backend.services.smart_capture import tokens as sc_tokens
from backend.services.smart_capture.config import get_token_secret
from backend.services.smart_capture.intents import intent_hash
from backend.tests.semantic_helpers import apply_migrations

NOW = 1_000_000.0
UID, WID = 7, 3


async def _token(conn, intents, uid=UID, wid=WID, now=NOW):
    """intents: list of (domain, payload, asset_id)."""
    secret = await get_token_secret(conn)
    hashes = [intent_hash(d, p, a) for (d, p, a) in intents]
    return sc_tokens.mint(hashes, uid, wid, secret, now)


async def _commit(conn, domain, payload, asset_id=None, token=None, now=NOW):
    return await sc_commit.commit_native(
        domain=domain, payload=payload, asset_id=asset_id, extract_token=token,
        user_id=UID, workspace_id=WID, conn=conn, now=now,
    )


@pytest.mark.asyncio
async def test_db_committers_write_expected_rows(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cases = [
                ("tool", {"name": "Table Saw", "brand": "SawStop", "model": "PCS"},
                 "inventory.tools", "name", "Table Saw"),
                ("router_bit", {"brand": "Whiteside", "profile": "Round Over", "shank_size_in": 0.5},
                 "inventory.router_bits", "profile", "Round Over"),
                ("saw_blade", {"brand": "Forrest", "diameter_in": 10, "teeth": 40},
                 "inventory.saw_blades", "brand", "Forrest"),
                ("wood", {"species": "White Oak", "dimensions": "4/4", "quantity": 12},
                 "inventory.wood", "species", "White Oak"),
                ("album", {"title": "Kind of Blue", "artist": "Miles Davis", "year": 1959},
                 "inventory.albums", "title", "Kind of Blue"),
                ("manual", {"brand": "DeWalt", "model": "DW735"},
                 "inventory.manuals", "title", "DeWalt DW735 manual"),
                ("house_room", {"name": "kitchen", "floor": 1},
                 "house.rooms", "name", "kitchen"),
            ]
            for domain, payload, table, col, expected in cases:
                tok = await _token(conn, [(domain, payload, None)])
                res = await _commit(conn, domain, payload, token=tok)
                assert res["ok"] is True, f"{domain}: {res}"
                schema, tbl = table.split(".")
                got = await conn.fetchval(
                    f'SELECT "{col}" FROM {schema}."{tbl}" WHERE id = $1', int(res["record_id"])
                )
                assert got == expected, f"{domain}: expected {expected!r}, got {got!r}"

            # router_bit numeric bound as decimal
            rb = await conn.fetchval("SELECT shank_size_in FROM inventory.router_bits LIMIT 1")
            assert float(rb) == 0.5
            # saw_blade teeth bound as int
            teeth = await conn.fetchval("SELECT teeth FROM inventory.saw_blades LIMIT 1")
            assert teeth == 40
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_recipe_and_cook_log(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            rp = {"title": "Weeknight Chili", "servings": 4,
                  "ingredients": ["beans", "beef"], "method": ["brown", "simmer"]}
            tok = await _token(conn, [("recipe", rp, None)])
            res = await _commit(conn, "recipe", rp, token=tok)
            assert res["ok"]
            notes = await conn.fetchval("SELECT notes FROM cook.recipes WHERE id=$1", int(res["record_id"]))
            assert "INGREDIENTS" in notes and "METHOD" in notes
            slug = await conn.fetchval("SELECT slug FROM cook.recipes WHERE id=$1", int(res["record_id"]))
            assert slug == "weeknight-chili"

            # cook_log resolves the recipe by title fragment
            cl = {"recipe_query": "chili", "rating": 5, "servings_made": 4}
            tok2 = await _token(conn, [("cook_log", cl, None)])
            res2 = await _commit(conn, "cook_log", cl, token=tok2)
            assert res2["ok"]
            rid = await conn.fetchval("SELECT recipe_id FROM cook.cook_log WHERE id=$1", int(res2["record_id"]))
            assert rid == int(res["record_id"])
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_cook_log_no_match_is_per_intent_failure(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cl = {"recipe_query": "nonexistent dish"}
            tok = await _token(conn, [("cook_log", cl, None)])
            res = await _commit(conn, "cook_log", cl, token=tok)
            assert res["ok"] is False and "No recipe matched" in res["error"]
            # No guard row persisted → a corrected retry isn't seen as a replay.
            n = await conn.fetchval("SELECT count(*) FROM public.bh_smart_capture_commits")
            assert n == 0
            assert await conn.fetchval("SELECT count(*) FROM cook.cook_log") == 0
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_replay_writes_one_row(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            payload = {"name": "Cordless Drill", "brand": "Makita"}
            tok = await _token(conn, [("tool", payload, None)])
            r1 = await _commit(conn, "tool", payload, token=tok)
            r2 = await _commit(conn, "tool", payload, token=tok)  # exact replay
            assert r1["ok"] and r2["ok"]
            assert r1["record_id"] == r2["record_id"]  # replay returns original
            n = await conn.fetchval("SELECT count(*) FROM inventory.tools WHERE brand='Makita'")
            assert n == 1  # written once
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_no_interpolated_sql_values_are_data(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            evil = "Robert'); DROP TABLE inventory.tools;--"
            payload = {"name": evil, "brand": "x"}
            tok = await _token(conn, [("tool", payload, None)])
            res = await _commit(conn, "tool", payload, token=tok)
            assert res["ok"]
            # table still exists and stored the literal string
            got = await conn.fetchval("SELECT name FROM inventory.tools WHERE id=$1", int(res["record_id"]))
            assert got == evil
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_extra_fields_folded_into_notes(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            payload = {"name": "Planer", "notes": "used", "_extra_fields": {"motor_amps": 15, "voltage": 120}}
            tok = await _token(conn, [("tool", payload, None)])
            res = await _commit(conn, "tool", payload, token=tok)
            notes = await conn.fetchval("SELECT notes FROM inventory.tools WHERE id=$1", int(res["record_id"]))
            assert "used" in notes and "motor_amps: 15" in notes and "voltage: 120" in notes
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_house_room_recapture_upserts(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            p1 = {"name": "garage", "floor": 0}
            p2 = {"name": "garage", "notes": "added a workbench"}
            r1 = await _commit(conn, "house_room", p1, token=await _token(conn, [("house_room", p1, None)]))
            r2 = await _commit(conn, "house_room", p2, token=await _token(conn, [("house_room", p2, None)]))
            assert r1["record_id"] == r2["record_id"]  # upsert, same row
            n = await conn.fetchval("SELECT count(*) FROM house.rooms WHERE name='garage'")
            assert n == 1
            notes = await conn.fetchval("SELECT notes FROM house.rooms WHERE name='garage'")
            assert notes == "added a workbench"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_asset_link_written(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            aid = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO files.assets (id, path, original_name, mime, size_bytes, sha256) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                uuid.UUID(aid), "/files/inbox/x.jpg", "x.jpg", "image/jpeg", 1024, "deadbeef",
            )
            payload = {"name": "Chisel", "brand": "Narex"}
            tok = await _token(conn, [("tool", payload, aid)])
            res = await _commit(conn, "tool", payload, asset_id=aid, token=tok)
            assert res["ok"]
            linked = await conn.fetchval(
                "SELECT asset_id FROM inventory.tool_files WHERE tool_id=$1", int(res["record_id"])
            )
            assert str(linked) == aid
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_bad_token_rejected_no_write(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            payload = {"name": "Ghost Tool"}
            # token minted for a DIFFERENT payload → membership fails
            tok = await _token(conn, [("tool", {"name": "Other"}, None)])
            res = await _commit(conn, "tool", payload, token=tok)
            assert res["ok"] is False and "invalid" in res["error"]
            assert await conn.fetchval("SELECT count(*) FROM inventory.tools") == 0
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_shopping_list_delegates_to_router(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            calls = {}

            async def fake_route_and_add(items, user_id, *a, **k):
                calls["items"] = items
                calls["user_id"] = user_id
                return {"added": [{"list_id": 1, "added": len(items)}], "needs_disambiguation": []}

            from backend.services import list_router
            monkeypatch.setattr(list_router, "route_and_add", fake_route_and_add)

            payload = {"items": ["milk", "eggs"]}
            tok = await _token(conn, [("shopping_list", payload, None)])
            res = await _commit(conn, "shopping_list", payload, token=tok)
            assert res["ok"] and calls["items"] == ["milk", "eggs"] and calls["user_id"] == UID
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_knowledge_fact_delegates(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            seen = {}

            async def fake_remember(topic, fact):
                seen["topic"] = topic
                seen["fact"] = fact
                return {"saved": True}

            async def fake_remember_entity(**kwargs):
                seen["entity"] = kwargs
                return {"id": 1}

            from backend.services import knowledge, knowledge_graph
            monkeypatch.setattr(knowledge, "remember", fake_remember)
            monkeypatch.setattr(knowledge_graph, "remember_entity", fake_remember_entity)

            payload = {"topic": "woodshop/tools", "fact": "The planer is 15A."}
            tok = await _token(conn, [("knowledge_fact", payload, None)])
            res = await _commit(conn, "knowledge_fact", payload, token=tok)
            assert res["ok"] and seen["topic"] == "woodshop/tools"
            assert seen["fact"] == "The planer is 15A."
            assert seen["entity"]["entity_type"] == "topic"
    finally:
        await close_pool()
