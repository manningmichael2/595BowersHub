"""Task 9 — deterministic parity gate (R6.1).

The LLM is identical across engines (same prompt, same model); the only thing
that can diverge is the *parse/coerce/fallback* layer (n8n `Parse Classification`
JS vs native Python). This gate feeds a golden corpus of recorded model outputs
through native extract and asserts, with NO live network:

  - every produced intent is schema-valid (domain ∈ DOMAINS, summary str,
    payload dict, needs_more_info list) — **0 schema violations**, and
  - the intent domains match the golden structure — **≥95% field agreement**
    (100% here since the parse layer is deterministic).

Covers: grocery text, multi-intent, ambiguous, empty, fenced, bogus-domain,
non-JSON, and oversized (rejected). Inbox response-shape parity is covered in
test_smart_capture_inbox.py.
"""

from __future__ import annotations

import json

import pytest

from backend.database import close_pool
from backend.models.message import CompletionResult
from backend.services.smart_capture.extract import MAX_INPUT_CHARS, extract_native
from backend.services.smart_capture.intents import DOMAINS
from backend.tests.semantic_helpers import apply_migrations

NOW = 1_000_000.0


class Canned:
    def __init__(self, content):
        self._c = content

    async def complete(self, **k):
        return CompletionResult(content=self._c, model="fake", input_tokens=1, output_tokens=1)


def _intents(items):
    return json.dumps({"intents": items})


# (label, raw_model_output, expected_domains)
CORPUS = [
    ("grocery_text",
     _intents([{"domain": "shopping_list", "summary": "add milk + eggs",
                "payload": {"items": ["milk", "eggs"]}, "needs_more_info": []}]),
     ["shopping_list"]),
    ("multi_intent",
     _intents([
         {"domain": "recipe", "summary": "chili", "payload": {"title": "Chili"}},
         {"domain": "shopping_list", "summary": "beans", "payload": {"items": ["beans"]}},
     ]),
     ["recipe", "shopping_list"]),
    ("ambiguous_single",
     _intents([{"domain": "other", "summary": "a note", "payload": {"suggested_title": "note", "content": "hmm"}}]),
     ["other"]),
    ("fenced_output",
     "```json\n" + _intents([{"domain": "tool", "summary": "drill", "payload": {"name": "drill"}}]) + "\n```",
     ["tool"]),
    ("bogus_domain_coerced",
     _intents([{"domain": "crypto", "summary": "x", "payload": {"coin": "BTC"}}]),
     ["other"]),
    ("empty_output", "", ["other"]),        # other-fallback
    ("garbage_output", "not json {{{", ["other"]),  # other-fallback
]


def _schema_violations(intents: list[dict]) -> int:
    bad = 0
    for it in intents:
        if it.get("domain") not in DOMAINS:
            bad += 1
        if not isinstance(it.get("summary"), str):
            bad += 1
        if not isinstance(it.get("payload"), dict):
            bad += 1
        if not isinstance(it.get("needs_more_info"), list):
            bad += 1
    return bad


@pytest.mark.asyncio
async def test_corpus_parity_and_schema(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        total_fields = 0
        matched_fields = 0
        total_violations = 0
        async with pool.acquire() as conn:
            for label, raw, expected_domains in CORPUS:
                out = await extract_native(
                    text="corpus input", domain_hint=None, user_id=7, workspace_id=3,
                    model_provider=Canned(raw), conn=conn, now=NOW,
                )
                assert out["ok"], f"{label}: extract not ok"
                intents = out["intents"]
                total_violations += _schema_violations(intents)
                got_domains = [i["domain"] for i in intents]
                # field-agreement accounting (domain is the compared field)
                total_fields += len(expected_domains)
                matched_fields += sum(
                    1 for a, b in zip(sorted(got_domains), sorted(expected_domains)) if a == b
                )
                assert sorted(got_domains) == sorted(expected_domains), (
                    f"{label}: domains {got_domains} != {expected_domains}"
                )

        assert total_violations == 0, f"{total_violations} schema violations across corpus"
        agreement = matched_fields / total_fields
        assert agreement >= 0.95, f"field agreement {agreement:.2%} < 95%"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_corpus_oversized_rejected(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            out = await extract_native(
                text="x" * (MAX_INPUT_CHARS + 1), domain_hint=None, user_id=7, workspace_id=3,
                model_provider=Canned("{}"), conn=conn, now=NOW,
            )
            assert out["ok"] is False and "too large" in out["error"]
    finally:
        await close_pool()
