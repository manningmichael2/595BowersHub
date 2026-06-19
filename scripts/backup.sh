#!/bin/bash
# 595BowersHub Nightly Backup Script
# 
# Backs up:
#   1. Postgres database (pg_dump)
#   2. /home/michael/knowledge/ (markdown knowledge base)
#   3. /home/michael/files/ (photos, receipts, inventory images)
#   4. Docker container configs (compose files, env files)
#
# Run as: crontab -e → 0 3 * * * /home/michael/KiroProject/scripts/backup.sh
# (runs at 3am daily)
#
# Off-site: each run is synced to Google Drive via rclone (step 7), so backups
# survive an SSD failure. Verify the off-site copy with:  rclone lsd gdrive:595BowersHub-Backups/
# Failures (local OR off-site) now send a Pushover alert — a backup that silently
# stops is worse than no backup. Creds are read from bowershub-ai/.env.
#
# RESTORE (bare-metal disaster recovery), in order:
#   1. createuser/roles:  psql -U michael -f globals.sql      (roles + grants; see step 0)
#   2. createdb finance:  createdb -U michael finance
#   3. restore data:      pg_restore -U michael -d finance --no-owner postgres_finance.dump
# Restoring globals first is REQUIRED — the DB dump GRANTs to finance_reader, which
# must exist or pg_restore errors on every grant (found via restore test 2026-06-09).
# The recovery cluster's bootstrap superuser MUST be `michael` (matching prod): the
# globals dump replays role memberships as `GRANTED BY michael`, which silently fail
# under a different superuser (e.g. postgres) — leaving bowershub_app NOT a member of
# finance_reader, which breaks ask-db's SET ROLE. (Verified via restore test 2026-06-19.)

set -euo pipefail

# === Configuration ===
BACKUP_ROOT="/home/michael/backups"
DATE=$(date +%Y-%m-%d_%H%M)
BACKUP_DIR="${BACKUP_ROOT}/${DATE}"
RETENTION_DAYS=7  # Keep local backups for 7 days

# Postgres connection (via Docker network)
PG_CONTAINER="postgres"
PG_DB="finance"
PG_USER="michael"

# === Failure alerting (Pushover) ===
# A silent backup failure defeats the whole point, so any error sends a push.
# Creds live in the app .env (resolved relative to this script, not hardcoded).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../bowershub-ai/.env"
PUSHOVER_USER_KEY="$(grep -E '^PUSHOVER_USER_KEY=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
PUSHOVER_API_TOKEN="$(grep -E '^PUSHOVER_API_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"

notify_failure() {
  local msg="$1"
  echo "[$(date)] ALERT: ${msg}"
  if [ -n "${PUSHOVER_USER_KEY}" ] && [ -n "${PUSHOVER_API_TOKEN}" ]; then
    curl -s --max-time 20 \
      --form-string "token=${PUSHOVER_API_TOKEN}" \
      --form-string "user=${PUSHOVER_USER_KEY}" \
      --form-string "title=595BowersHub backup FAILED" \
      --form-string "priority=1" \
      --form-string "message=${msg}" \
      https://api.pushover.net/1/messages.json > /dev/null \
      || echo "[$(date)] (Pushover notify itself failed)"
  else
    echo "[$(date)] (Pushover creds not found in ${ENV_FILE} — no push sent)"
  fi
}

# set -e aborts on the first failing command; this trap fires before exit so a
# broken pg_dump/tar/etc. pages us instead of failing into the log unseen.
trap 'notify_failure "backup.sh aborted at line ${LINENO} (exit $?) — see ${BACKUP_ROOT}/backup.log"' ERR

# === Create backup directory ===
mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting backup to ${BACKUP_DIR}"

# === 0. Cluster globals (roles + grants) ===
# REQUIRED for a clean restore: the DB dump grants to finance_reader, which must
# exist first. A single-DB pg_dump does NOT capture roles, so dump them here.
# (Contains role password hashes — fine for a private backup, never commit it.)
echo "[$(date)] Dumping cluster globals (roles)..."
docker exec "${PG_CONTAINER}" pg_dumpall -U "${PG_USER}" --globals-only \
  > "${BACKUP_DIR}/globals.sql"
echo "[$(date)] Globals: $(du -sh "${BACKUP_DIR}/globals.sql" | cut -f1)"

# === 1. Postgres dump ===
echo "[$(date)] Dumping Postgres..."
docker exec "${PG_CONTAINER}" pg_dump -U "${PG_USER}" -d "${PG_DB}" \
  --format=custom --compress=6 \
  > "${BACKUP_DIR}/postgres_${PG_DB}.dump"
echo "[$(date)] Postgres dump: $(du -sh "${BACKUP_DIR}/postgres_${PG_DB}.dump" | cut -f1)"

# === 2. Knowledge base ===
echo "[$(date)] Backing up knowledge base..."
tar -czf "${BACKUP_DIR}/knowledge.tar.gz" -C /home/michael knowledge/
echo "[$(date)] Knowledge: $(du -sh "${BACKUP_DIR}/knowledge.tar.gz" | cut -f1)"

# === 3. Files (photos, receipts, inventory) ===
echo "[$(date)] Backing up files..."
tar -czf "${BACKUP_DIR}/files.tar.gz" -C /home/michael files/
echo "[$(date)] Files: $(du -sh "${BACKUP_DIR}/files.tar.gz" | cut -f1)"

# === 4. Config files (compose, env — no secrets in the tarball name) ===
echo "[$(date)] Backing up configs..."
tar -czf "${BACKUP_DIR}/configs.tar.gz" \
  --exclude='*.pyc' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='node_modules' \
  -C /home/michael \
  filewriter/docker-compose.yml \
  caddy/Caddyfile \
  2>/dev/null || true
echo "[$(date)] Configs: $(du -sh "${BACKUP_DIR}/configs.tar.gz" | cut -f1)"

# === 5. Total size ===
TOTAL=$(du -sh "${BACKUP_DIR}" | cut -f1)
echo "[$(date)] Backup complete. Total size: ${TOTAL}"

# === 6. Cleanup old local backups ===
echo "[$(date)] Cleaning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_ROOT}" -maxdepth 1 -type d -mtime +${RETENTION_DAYS} -exec rm -rf {} \;

# === 7. Sync to Google Drive (via rclone) ===
# Off-site failure does NOT abort (the local backup already succeeded and is worth
# keeping) but DOES alert — a silently-broken off-site sync (e.g. expired rclone
# token) is the exact failure mode that leaves you with no net. Tested in an `if`
# so set -e / the ERR trap don't double-fire; we alert explicitly instead.
echo "[$(date)] Syncing to Google Drive..."
if rclone sync "${BACKUP_DIR}/" "gdrive:595BowersHub-Backups/${DATE}/" --quiet; then
  echo "[$(date)] Off-site sync OK."
else
  notify_failure "Off-site rclone sync to Google Drive FAILED (local backup OK at ${BACKUP_DIR}). Check the token: rclone lsd gdrive:"
fi

echo "[$(date)] Done."
