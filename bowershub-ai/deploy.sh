#!/bin/bash
# Deploy BowersHub AI to the server.
# Usage: ./deploy.sh [--no-cache]
#
# This replaces the old scp-based deploy that silently dropped files.
# Uses rsync for reliable, incremental file transfer.

set -e

SERVER="michael@100.106.180.101"
REMOTE_DIR="~/bowershub-ai"
LOCAL_DIR="$(dirname "$0")"

echo "📦 Syncing files to server..."
rsync -av --delete \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*.pyc' \
    --exclude='.env' \
    "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

echo "🔨 Building container..."
BUILD_FLAGS=""
if [[ "$1" == "--no-cache" ]]; then
    BUILD_FLAGS="--no-cache"
fi

ssh "$SERVER" "cd $REMOTE_DIR && \
    docker stop bowershub-ai 2>/dev/null || true && \
    docker rm bowershub-ai 2>/dev/null || true && \
    docker build $BUILD_FLAGS -t bowershub-ai . && \
    docker run -d \
        --name bowershub-ai \
        --restart unless-stopped \
        --network ai-services_ai-network \
        -p 5003:5003 \
        -v /home/michael/files:/files \
        -v /home/michael/knowledge:/knowledge \
        --env-file ~/bowershub-ai/.env \
        bowershub-ai"

echo "⏳ Waiting for startup..."
sleep 5

# Check if it started cleanly
STATUS=$(ssh "$SERVER" "docker logs bowershub-ai 2>&1 | grep -c 'started successfully'" 2>/dev/null || echo "0")

if [[ "$STATUS" -ge 1 ]]; then
    echo "✅ Deploy complete — BowersHub AI is running."
else
    echo "❌ Deploy may have failed. Checking logs..."
    ssh "$SERVER" "docker logs bowershub-ai 2>&1 | tail -10"
    exit 1
fi
