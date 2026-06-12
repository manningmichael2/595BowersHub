# Semantic memory — pgvector infra cutover runbook

Bring the `ai-services` Postgres up to a **pgvector-capable** image and install
the `vector` extension **before** deploying the semantic-memory code. The code
deploy applies migration `0010_semantic_memory.sql`, which **fails loudly** if
the `vector` type is absent (R1.5) — so this runbook is mandatory and **ordered
first**.

This mirrors `docs/c7-db-roles-cutover.md`: privileged, one-time, run as the
cluster superuser `michael`; the app role (`bowershub_app`) never installs the
extension.

## Why the ordering is mandatory

Post-C7, forward migrations run as `bowershub_app` (`NOSUPERUSER`), which
**cannot** `CREATE EXTENSION`. `0010` therefore only runs
`CREATE EXTENSION IF NOT EXISTS vector` — a no-op that does **not** trip the
privilege check **when the extension already exists**. If the superuser step
below is skipped, `0010`'s first statement (a `DO`-block guard that does
`PERFORM 'vector'::regtype`) raises and the migration's transaction rolls back
cleanly — no half-applied schema, but the app will not boot until you complete
this runbook. The asyncpg pool's `register_vector()` is likewise guarded: it
logs this remediation and continues if the type is missing.

## Steps (run in order, as superuser `michael`)

### 1. Swap the Postgres image to a pgvector build

The `postgres` service lives in the **Portainer `ai-services` stack**, not the
repo `infrastructure/` (which is diverged and does not deploy it). Edit the
stack's `postgres` service:

```yaml
# was:   image: postgres:16
image: pgvector/pgvector:pg16
```

`pgvector/pgvector:pg16` is the official Postgres 16 image with the pgvector
build artifacts present (same data dir layout — no dump/restore needed). Redeploy
the stack / restart the `postgres` container and confirm it comes back healthy
with the existing volume:

```bash
docker exec -it <postgres-container> psql -U michael -d finance -c 'SELECT version();'
```

### 2. Install the extension as superuser (one-time, per database)

`CREATE EXTENSION` is superuser-only and **per-database** — run it in the app
database (`finance`):

```sql
-- as michael, in -d finance
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname = 'vector';   -- expect a version
```

### 3. Grant the app role what it needs

The `vector`/`halfvec` types are usable by any role once the extension exists
(`USAGE` on the public schema is already in place), so the app role can create
the `kb_chunks` vector columns and HNSW index in `0010` without extra grants.
Confirm as `bowershub_app`:

```sql
-- as bowershub_app (or: SET ROLE bowershub_app)
SELECT 'vector'::regtype, 'halfvec'::regtype;   -- both resolve → no extra GRANT needed
```

If a future hardened cluster restricts type usage, grant explicitly:
`GRANT USAGE ON TYPE vector TO bowershub_app;` (and `halfvec`). Not required on
the default `ai-services` cluster.

### 4. Pull the embedding model into Ollama

The embedding model is **DB-driven** (seeded default `bge-m3`, 1024-d; see
`embedding_config` in `0010`). Pull it into the `ollama_data` volume so the
worker can embed:

```bash
docker exec -it <ollama-container> ollama pull bge-m3
# verify the endpoint returns a 1024-d vector:
curl -s http://<ollama-host>:11434/api/embed \
  -d '{"model":"bge-m3","input":"hello"}' | python3 -c \
  'import sys,json; v=json.load(sys.stdin)["embeddings"][0]; print("dim:", len(v))'
# expect → dim: 1024
```

`nomic-embed-text` (768-d) is the documented CPU-throughput fallback; switching
to it is a deliberate `embedding_config` change (a different dimension is a
destructive re-embed — see R3.4), **not** a hot-swap.

## Then deploy the code

With steps 1–4 done, deploy `bowershub-ai`. On startup `database.py` applies
`0010` as `bowershub_app`; the guard passes (type present), `kb_chunks` +
indexes are created, and the `embed` alias / `embedding_config` rows are seeded.
The `EmbeddingWorker` begins reconciling (backfill = first pass).

## Verification checklist

- [ ] `SELECT 'vector'::regtype;` succeeds as `bowershub_app`.
- [ ] `0010` recorded in `public.bh_migrations`.
- [ ] `\d public.kb_chunks` shows the `halfvec(1024)` `embedding` column + HNSW index.
- [ ] `POST /api/embed` (bge-m3) returns a 1024-element vector.
- [ ] `GET /api/admin/semantic-memory/status` reports a growing `done` count (backfill running).
- [ ] App `current_setting('is_superuser')` is still `off` (no privilege regression).

## Rollback

The image swap is backward-compatible: `pgvector/pgvector:pg16` runs a stock
Postgres 16 unchanged, so reverting the image is safe if needed. `0010` is
forward-only; to abandon the feature, leave the table in place (inert without the
worker) or drop it manually as superuser — there is no down-migration.
