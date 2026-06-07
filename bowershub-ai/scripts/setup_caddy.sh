#!/bin/bash
# Sets up a Caddy reverse proxy on 595BowersHub so BowersHub AI is reachable
# at https://595bowershub.tailc4d58a.ts.net (Tailscale-only, real Let's Encrypt cert).
#
# Run this on the server: ssh hub "bash setup_caddy.sh"
# Will prompt for sudo once.
set -euo pipefail

CERT_DIR="$HOME/caddy/certs"
CADDYFILE="$HOME/caddy/Caddyfile"

mkdir -p "$CERT_DIR"

# Move the cert files (already issued via `sudo tailscale cert`).
if [ -f "$HOME/595bowershub.tailc4d58a.ts.net.crt" ]; then
  sudo mv "$HOME/595bowershub.tailc4d58a.ts.net.crt" "$CERT_DIR/cert.crt"
  sudo mv "$HOME/595bowershub.tailc4d58a.ts.net.key" "$CERT_DIR/cert.key"
fi

# Make them readable by the container user.
sudo chown -R michael:michael "$HOME/caddy"
chmod 644 "$CERT_DIR/cert.crt"
chmod 600 "$CERT_DIR/cert.key"

# Write the Caddyfile.
cat > "$CADDYFILE" <<'EOF'
{
    auto_https off
}

595bowershub.tailc4d58a.ts.net:443 {
    tls /certs/cert.crt /certs/cert.key

    # WebSocket-aware reverse proxy to BowersHub AI on the host.
    reverse_proxy localhost:5003 {
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-For {remote}
        header_up X-Forwarded-Proto {scheme}
    }

    encode gzip
}
EOF

# (Re)start the Caddy container with --network host so it can bind 443 on the
# host and reach localhost:5003 (BowersHub AI). No exposed ports needed.
docker stop caddy 2>/dev/null || true
docker rm caddy 2>/dev/null || true
docker run -d --name caddy --restart unless-stopped \
    --network host \
    -v "$CADDYFILE:/etc/caddy/Caddyfile:ro" \
    -v "$CERT_DIR:/certs:ro" \
    caddy:2-alpine

sleep 2
docker logs caddy 2>&1 | tail -10

echo
echo "✓ Caddy reverse proxy live."
echo "  BowersHub AI now reachable at: https://595bowershub.tailc4d58a.ts.net"
