# T0 — Anthropic SDK / Models API field verification (Task 1)

Precondition for Task 3 (discovery). Verified against the pinned SDK and one live `models.list()` call on 2026-06-10.

## SDK version
`anthropic==0.105.0` (pinned in `bowershub-ai/requirements.txt`, installed in `.venv`).

## `models.list()` — shape & pagination
- Returns `SyncPage[ModelInfo]`; **auto-paginates on iteration** (`list(c.models.list(limit=100))` returns the full set — do not rely on `.data`). Confirmed: 9 models in one iteration.
- `Models.list(*, after_id, before_id, limit, ...)` — cursor pagination params available if ever needed.

## `ModelInfo` fields (all design-assumed fields are REAL on 0.105.0, `extra="allow"`)
| field | type | populated live? |
|---|---|---|
| `id` | str | ✓ |
| `display_name` | str | ✓ |
| `max_input_tokens` | int \| None | ✓ (e.g. 1000000 / 200000) |
| `max_tokens` | int \| None | ✓ (e.g. 128000 / 64000) |
| `capabilities` | `ModelCapabilities \| None` | ✓ |
| `created_at` | datetime | ✓ |
| `type` | Literal['model'] | ✓ |

`ModelCapabilities` (`extra="allow"`) leaves, each a `CapabilitySupport{supported: bool}` (or a richer sub-type): `batch`, `citations`, `code_execution`, `context_management`, `effort`, `image_input`, `pdf_input`, `structured_outputs`, `thinking`.

**Conclusion:** no NULL-field fallback is needed for Anthropic discovery on the pinned version — `max_input_tokens`/`max_tokens`/`capabilities.{image_input,structured_outputs,thinking,effort}` are all populated. Keep the defensive "absent → NULL/false, never fabricate" guard (Task 3) for forward-compat, but it is not the live path today.

## Live result (9 models, 2026-06-10)
```
id                            ctx_in   max_out  vision struct think
claude-fable-5               1000000   128000   T      T      T
claude-opus-4-8              1000000   128000   T      T      T
claude-opus-4-7              1000000   128000   T      T      T
claude-sonnet-4-6            1000000   128000   T      T      T
claude-opus-4-6              1000000   128000   T      T      T
claude-opus-4-5-20251101      200000    64000   T      T      T
claude-haiku-4-5-20251001     200000    64000   T      T      T
claude-sonnet-4-5-20250929   1000000    64000   T      T      T
claude-opus-4-1-20250805      200000    32000   T      T      T
```

## R1.5 chat-target filter — concrete rule (now grounded)
All 9 returned models are `claude-*` chat targets with `structured_outputs.supported = true`; the API returns **no** embedding-only entries today. Filter: keep if `id` starts with `claude-` **and** (`capabilities is None` or `structured_outputs.supported` is not explicitly false). The id-prefix fallback is sufficient and safe.

## ⚠️ FINDING that gates Task 2 (migration) + Task 4 (deactivation) — alias/canonical-ID mismatch
`models.list()` returns **canonical dated IDs**, not the bare alias forms the DB seed / planned alias seed use:

| role alias seed (planned) | returned by `models.list()`? | canonical the API returns |
|---|---|---|
| `claude-haiku-4-5-20251001` | **yes** ✓ | `claude-haiku-4-5-20251001` |
| `claude-sonnet-4-5` | **no** ✗ | `claude-sonnet-4-5-20250929` |
| `claude-opus-4-5` | **no** ✗ | `claude-opus-4-5-20251101` |
| `llama3.2:3b` (Ollama) | n/a (Ollama source) | — |

Consequence under the current design: the bare `claude-sonnet-4-5` / `claude-opus-4-5` rows are **never seen by discovery**, so `missed_fetch_count` climbs and they get **deactivated** after N complete Anthropic fetches → the `sonnet`/`opus` role aliases then point at an **inactive** model → `resolve_role` fails closed. Only the `haiku` alias is safe (its ID is canonical).

This is a real latent bug the live data reveals; it must be resolved before Task 2's migration alias seed and Task 4's deactivation rule are built.

## Decision (approved 2026-06-10)
**Reseed aliases to canonical discoverable IDs + protect alias-targeted models from deactivation.** Migration `0005` inserts the canonical rows `models.list()` returns but `0001` lacks (`claude-sonnet-4-6`, `claude-opus-4-5-20251101`) and seeds aliases to canonical IDs: haiku→`claude-haiku-4-5-20251001`, **sonnet→`claude-sonnet-4-6`** (chosen: current best Sonnet, a deliberate bump from the 4-5 tier), opus→`claude-opus-4-5-20251101`, local→`llama3.2:3b`. `CatalogRefresh` additionally never auto-deactivates any model that is an alias target (belt-and-suspenders for future operator repoints). Folded into `design.md` (migration + deactivation rule) and `tasks.md` (Task 2/3/4).
