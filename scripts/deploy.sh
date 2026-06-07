#!/bin/bash
# Quick deploy script for 595BowersHub services
# Usage: ./deploy.sh <service> [--no-cache]
#
# Examples:
#   ./deploy.sh bowershub-ai
#   ./deploy.sh bowershub-ai --no-cache
#   ./deploy.sh db-admin
#   ./deploy.sh dashboard
#   ./deploy.sh filewriter
#   ./deploy.sh infra

set -euo pipefail

SERVICE="${1:-}"
NO_CACHE="${2:-}"

REPO="/home/michael/KiroProject"

case "$SERVICE" in
  bowershub-ai|bh)
    DIR="$REPO/bowershub-ai"
    ;;
  db-admin|db)
    DIR="$REPO/db-admin"
    ;;
  dashboard|dash)
    DIR="$REPO/dashboard"
    ;;
  filewriter|fw)
    DIR="$REPO/filewriter"
    ;;
  infra|infrastructure)
    DIR="$REPO/infrastructure"
    ;;
  *)
    echo "Usage: $0 <service> [--no-cache]"
    echo ""
    echo "Services:"
    echo "  bowershub-ai (bh)   — Chat app"
    echo "  db-admin (db)       — Database browser"
    echo "  dashboard (dash)    — Hub dashboard"
    echo "  filewriter (fw)     — File/IMAP microservice"
    echo "  infra               — Postgres + n8n + Caddy"
    exit 1
    ;;
esac

echo "=== Deploying $SERVICE from $DIR ==="

cd "$DIR"

if [ "$NO_CACHE" = "--no-cache" ]; then
  echo "Building with --no-cache..."
  docker compose build --no-cache
fi

docker compose up -d --build

echo "=== Done. Checking health... ==="
sleep 3

# Quick health check for services with HTTP endpoints
case "$SERVICE" in
  bowershub-ai|bh)
    curl -sf http://localhost:5003/api/health && echo "" || echo "⚠️  Health check failed"
    ;;
  db-admin|db)
    curl -sf http://localhost:5002/ > /dev/null && echo "✅ db-admin responding" || echo "⚠️  Health check failed"
    ;;
  filewriter|fw)
    curl -sf http://localhost:5001/health && echo "" || echo "⚠️  Health check failed"
    ;;
  *)
    echo "✅ Containers up"
    ;;
esac
