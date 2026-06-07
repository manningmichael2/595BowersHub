#!/bin/bash
# Tailscale HTTPS cert renewal for BowersHub AI PWA
#
# Tailscale-issued Let's Encrypt certs expire in 90 days.
# Cert was first issued ~May 27, 2026 → expires ~August 25, 2026.
#
# Run as: crontab -e → 0 4 1,15 * * /home/michael/KiroProject/scripts/renew-cert.sh
# (runs on 1st and 15th of each month at 4am)
#
# Requires: sudo access (tailscale cert needs root)

set -euo pipefail

DOMAIN="595bowershub.tailc4d58a.ts.net"
CERT_DIR="/home/michael/caddy/certs"

echo "[$(date)] Renewing Tailscale cert for ${DOMAIN}..."

# Issue new cert (overwrites existing files if they exist)
sudo tailscale cert \
  --cert-file "${CERT_DIR}/cert.crt" \
  --key-file "${CERT_DIR}/cert.key" \
  "${DOMAIN}"

# Fix permissions so Caddy can read them
sudo chown michael:michael "${CERT_DIR}/cert.crt" "${CERT_DIR}/cert.key"
chmod 644 "${CERT_DIR}/cert.crt"
chmod 600 "${CERT_DIR}/cert.key"

# Reload Caddy to pick up new cert
docker restart caddy

echo "[$(date)] Cert renewed and Caddy restarted."
