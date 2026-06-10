#!/bin/bash
# One-time helper: add the /knowledge bind mount to the filewriter container.
# Run with: sudo bash /home/michael/KiroProject/n8n-workflows/_deploy_knowledge_mount.sh
#
# What it does:
#   1. Backs up the current Portainer-managed compose file
#   2. Inserts "- /home/michael/knowledge:/knowledge" under filewriter volumes
#   3. Recreates the filewriter container so the new mount takes effect
#   4. Verifies the mount is live
set -euo pipefail

COMPOSE=/home/michael/portainer/portainer/data/compose/2/docker-compose.yml
BACKUP="${COMPOSE}.bak.$(date +%s)"

if [ ! -f "$COMPOSE" ]; then
  echo "ERROR: $COMPOSE not found. Adjust path and re-run."
  exit 1
fi

if grep -q "/home/michael/knowledge:/knowledge" "$COMPOSE"; then
  echo "Mount already present in compose file. Skipping edit."
else
  cp -p "$COMPOSE" "$BACKUP"
  echo "Backed up to $BACKUP"
  # Insert the new volume line after the /files mount (which we know exists).
  sed -i '/- \/home\/michael\/files:\/files/a\      - /home/michael/knowledge:/knowledge' "$COMPOSE"
  echo "Edited compose file. New filewriter volume block:"
  awk '/filewriter:/,/working_dir:/' "$COMPOSE"
fi

# Recreate the filewriter container so the bind mount is applied.
# `up -d` will detect the volume change and replace the container.
# Use the same project name Portainer used or you'll get a "container name in use" conflict.
echo
echo "Recreating filewriter container..."
docker compose --project-name filewriter -f "$COMPOSE" up -d filewriter

echo
echo "Verifying mount..."
docker inspect filewriter --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'

echo
echo "Health check:"
sleep 2
curl -s http://localhost:5001/health
echo
