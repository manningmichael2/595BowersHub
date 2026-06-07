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
# Storage options (configure ONE):
#   A) Local directory (default — good for testing, NOT a real backup)
#   B) Hetzner Storage Box via rsync/ssh (~$4/mo for 1TB)
#   C) Backblaze B2 via restic
#
# Current: Option A (local). Switch to B or C once remote storage is set up.

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

# === Create backup directory ===
mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting backup to ${BACKUP_DIR}"

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
echo "[$(date)] Syncing to Google Drive..."
rclone sync "${BACKUP_DIR}/" gdrive:595BowersHub-Backups/${DATE}/ --quiet 2>&1 || echo "[$(date)] WARNING: Google Drive sync failed (will retry next run)"

echo "[$(date)] Done."
