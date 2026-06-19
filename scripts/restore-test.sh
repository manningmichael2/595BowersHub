#!/bin/bash
# 595BowersHub — Disaster-Recovery RESTORE TEST
#
# Proves a backup is actually *restorable*, not just that it exists. This is the
# repeatable version of the manual drill done 2026-06-09 (see scripts/backup.sh
# RESTORE header). CI proves the schema builds from empty via migrations; this
# proves a real pg_dump + globals round-trips back into a working database.
#
# Three modes (nothing ever writes to prod — the live DB is only read via pg_dump):
#   (default)        dump FRESH from the live container ($PG_CONTAINER), restore
#                    into a throwaway target, compare exact per-table row counts.
#   --from-backup D  restore an existing backup dir's globals.sql + postgres_*.dump
#                    (tests the actual stored artifact; no exact source compare).
#   --selftest       fully self-contained: spin a source container, build the
#                    schema from the migration chain, then dump+restore+compare.
#                    Touches no prod and needs no existing backup — for CI.
#
# Restore order (documented in backup.sh): globals.sql (roles) -> createdb ->
# pg_restore --no-owner. Globals MUST go first — the dump GRANTs to finance_reader
# et al., which must exist or every grant errors (the 2026-06-09 lesson).
#
# Usage:
#   scripts/restore-test.sh
#   scripts/restore-test.sh --from-backup /home/michael/backups/2026-06-19_0300
#   scripts/restore-test.sh --selftest
#
# Env: PG_CONTAINER (default 'postgres'), PG_DB ('finance'), PG_USER ('michael'),
#      IMAGE (pgvector/pgvector:pg16), PYTHON ('python'), APP_DIR (../bowershub-ai).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_CONTAINER="${PG_CONTAINER:-postgres}"
PG_DB="${PG_DB:-finance}"
PG_USER="${PG_USER:-michael}"
IMAGE="${IMAGE:-pgvector/pgvector:pg16}"
PYTHON="${PYTHON:-python}"
APP_DIR="${APP_DIR:-$REPO_ROOT/bowershub-ai}"
# Target bootstrapped with the SAME superuser as the source so the restore mirrors
# real bare-metal DR. pg_dumpall records role-membership grantors ("GRANTED BY
# michael"); replaying them as a different superuser fails the ADMIN-option check.
TARGET_SUPER="$PG_USER"
TARGET_CONTAINER="restore-test-pg-$$"
SELFTEST_SRC="restore-selftest-src-$$"
EXPECTED_ROLES=(finance_reader bowershub_app n8n_app bowershub_migrator)

MODE="live"
FROM_BACKUP=""
case "${1:-}" in
  --from-backup) FROM_BACKUP="${2:?--from-backup needs a directory}"; MODE="backup" ;;
  --selftest)    MODE="selftest" ;;
  "")            ;;
  *)             echo "unknown arg: $1" >&2; exit 2 ;;
esac

WORK="$(mktemp -d)"
log()  { echo "[restore-test] $*"; }
fail() { echo "[restore-test] FAIL: $*" >&2; exit 1; }

cleanup() {
  docker rm -f "$TARGET_CONTAINER" >/dev/null 2>&1 || true
  docker rm -f "$SELFTEST_SRC"     >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# Wait for a freshly-started postgres container's FINAL server. The entrypoint runs
# a temporary init server first, so we wait for the init-complete marker, then poll
# a real query against the restarted server.
wait_pg() {
  local cname="$1" user="$2" i
  for i in $(seq 1 60); do
    docker logs "$cname" 2>&1 | grep -q "PostgreSQL init process complete" && break
    sleep 0.5
  done
  for i in $(seq 1 60); do
    docker exec "$cname" psql -U "$user" -d postgres -At -c 'select 1' >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  return 1
}

# Per-table exact row-count signature for public+finance (base tables only).
COUNT_SQL="SELECT format('%s.%s=%s', schemaname, tablename,
  (xpath('/row/c/text()', query_to_xml(
     format('select count(*) as c from %I.%I', schemaname, tablename),
     false, true, '')))[1]::text)
  FROM pg_tables WHERE schemaname IN ('public','finance')
  ORDER BY schemaname, tablename;"

# === 0. (--selftest) build an isolated source from the migration chain ===
if [[ "$MODE" == selftest ]]; then
  log "Self-test: starting isolated source container ..."
  docker run -d --name "$SELFTEST_SRC" -p 127.0.0.1::5432 \
    -e POSTGRES_USER="$PG_USER" -e POSTGRES_PASSWORD=postgres "$IMAGE" >/dev/null
  wait_pg "$SELFTEST_SRC" "$PG_USER" || fail "source container never became ready"
  SRC_PORT=$(docker port "$SELFTEST_SRC" 5432/tcp | head -1 | sed 's/.*://')
  docker exec "$SELFTEST_SRC" createdb -U "$PG_USER" "$PG_DB"
  docker exec "$SELFTEST_SRC" psql -U "$PG_USER" -d "$PG_DB" -q \
    -c "CREATE EXTENSION IF NOT EXISTS vector"
  log "Building schema from the migration chain (run_migrations) ..."
  ( cd "$APP_DIR" && PYTHONPATH=. \
    DB_HOST=127.0.0.1 DB_PORT="$SRC_PORT" DB_NAME="$PG_DB" \
    DB_USER="$PG_USER" DB_PASSWORD=postgres "$PYTHON" - <<'PY'
import asyncio, os
from backend.config import Config
from backend.database import init_pool, run_migrations, close_pool
async def main():
    cfg = Config(DB_HOST=os.environ["DB_HOST"], DB_PORT=int(os.environ["DB_PORT"]),
                 DB_NAME=os.environ["DB_NAME"], DB_USER=os.environ["DB_USER"],
                 DB_PASSWORD=os.environ["DB_PASSWORD"])
    pool = await init_pool(cfg)
    await run_migrations(pool, cfg)
    await close_pool()
asyncio.run(main())
PY
  ) || fail "schema build (run_migrations) failed"
  PG_CONTAINER="$SELFTEST_SRC"   # dump from the source we just built
fi

# === 1. Obtain artifacts ===
if [[ "$MODE" == backup ]]; then
  log "Using stored backup: $FROM_BACKUP"
  [[ -f "$FROM_BACKUP/globals.sql" ]] || fail "no globals.sql in $FROM_BACKUP"
  DUMP=$(ls "$FROM_BACKUP"/postgres_*.dump 2>/dev/null | head -1) \
    || fail "no postgres_*.dump in $FROM_BACKUP"
  cp "$FROM_BACKUP/globals.sql" "$WORK/globals.sql"
  cp "$DUMP" "$WORK/data.dump"
  SRC_SIG=""   # stored artifact predates current state — can't compare exact counts
else
  log "Dumping from container '$PG_CONTAINER' (read-only) ..."
  docker exec "$PG_CONTAINER" pg_dumpall -U "$PG_USER" --globals-only > "$WORK/globals.sql"
  docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    --format=custom --compress=6 > "$WORK/data.dump"
  log "Capturing source row-count signature ..."
  SRC_SIG=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -c "$COUNT_SQL")
fi
log "globals.sql $(wc -c < "$WORK/globals.sql") bytes, dump $(wc -c < "$WORK/data.dump") bytes"

# === 2. Throwaway target ===
log "Starting throwaway target container ($IMAGE) ..."
docker run -d --name "$TARGET_CONTAINER" \
  -e POSTGRES_USER="$TARGET_SUPER" -e POSTGRES_PASSWORD=restore "$IMAGE" >/dev/null
wait_pg "$TARGET_CONTAINER" "$TARGET_SUPER" || fail "target Postgres never became ready"
log "Target ready."

texec() { docker exec -i "$TARGET_CONTAINER" "$@"; }

# === 3. Restore in documented order ===
log "Step 1/3 — restoring globals (roles + grants) ..."
# The bootstrap superuser already exists in the target; drop only its own
# CREATE ROLE line (the lone collision). Its ALTER ROLE and every app-role
# create/grant stay and must apply cleanly under ON_ERROR_STOP=1.
grep -vE "^CREATE ROLE ${TARGET_SUPER};\$" "$WORK/globals.sql" > "$WORK/globals.filtered.sql"
docker cp "$WORK/globals.filtered.sql" "$TARGET_CONTAINER:/tmp/globals.sql"
docker cp "$WORK/data.dump"            "$TARGET_CONTAINER:/tmp/data.dump"
texec psql -U "$TARGET_SUPER" -d postgres -v ON_ERROR_STOP=1 -q -f /tmp/globals.sql \
  || fail "globals.sql failed to apply (role/ordering regression?)"

log "Step 2/3 — createdb $PG_DB ..."
texec createdb -U "$TARGET_SUPER" "$PG_DB" || fail "createdb failed"

log "Step 3/3 — pg_restore --no-owner ..."
# pg_restore prints non-fatal warnings to stderr and still exits 0; the exact
# row-count compare below is the real correctness gate. Surface fatal errors.
if ! texec pg_restore -U "$TARGET_SUPER" -d "$PG_DB" --no-owner /tmp/data.dump \
       2> "$WORK/restore.err"; then
  cat "$WORK/restore.err" >&2
  fail "pg_restore returned non-zero"
fi
if grep -qi '^pg_restore: error:' "$WORK/restore.err"; then
  cat "$WORK/restore.err" >&2
  fail "pg_restore reported errors"
fi
[[ -s "$WORK/restore.err" ]] && { log "pg_restore warnings (non-fatal):"; sed 's/^/    /' "$WORK/restore.err"; }

# === 4. Assertions ===
log "Asserting roles ..."
for role in "${EXPECTED_ROLES[@]}"; do
  ok=$(texec psql -U "$TARGET_SUPER" -d "$PG_DB" -At \
        -c "SELECT 1 FROM pg_roles WHERE rolname='$role'")
  [[ "$ok" == "1" ]] || fail "expected role '$role' missing after restore"
done
log "  roles OK: ${EXPECTED_ROLES[*]}"

log "Asserting schemas ..."
for sch in public finance; do
  ok=$(texec psql -U "$TARGET_SUPER" -d "$PG_DB" -At \
        -c "SELECT 1 FROM information_schema.schemata WHERE schema_name='$sch'")
  [[ "$ok" == "1" ]] || fail "expected schema '$sch' missing after restore"
done
log "  schemas OK: public, finance"

DST_SIG=$(texec psql -U "$TARGET_SUPER" -d "$PG_DB" -At -c "$COUNT_SQL")
TBL_COUNT=$(printf '%s\n' "$DST_SIG" | grep -c . || true)
[[ "$TBL_COUNT" -gt 0 ]] || fail "no tables found in restored DB"

if [[ -n "$SRC_SIG" ]]; then
  if [[ "$SRC_SIG" == "$DST_SIG" ]]; then
    log "  row counts MATCH source across $TBL_COUNT tables ✓"
  else
    echo "[restore-test] row-count diff (source < vs > restored):" >&2
    diff <(printf '%s\n' "$SRC_SIG") <(printf '%s\n' "$DST_SIG") >&2 || true
    fail "restored row counts differ from source"
  fi
else
  log "  restored $TBL_COUNT tables (stored-artifact mode: no exact source compare)"
fi

TX=$(printf '%s\n' "$DST_SIG" | sed -n 's/^finance\.transactions=//p')
[[ -n "$TX" ]] && log "  finance.transactions rows restored: $TX"

log "RESTORE TEST PASSED — backup is restorable."
