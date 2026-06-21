# Tor Proxy Implementation Plan

## Background Context
Since Hotspot Shield won't give us the OpenVPN configuration files, we cannot use Gluetun. 

Instead, we will use a **Tor Proxy**. The Tor network is completely free, doesn't require any accounts or configuration files, and easily bypasses ISP blocks by bouncing traffic through encrypted nodes. 

## User Review Required

> [!IMPORTANT]
> The Tor network is slightly slower than a traditional VPN, but it is perfect for Jackett because AudioBookBay indexing only involves downloading tiny text pages and magnet links (the actual heavy lifting of downloading the audiobook happens in your torrent client, which won't use Tor). Please review this new approach.

---

## Proposed Changes

We will scrap the Gluetun plan and instead add a lightweight `tor-privoxy` container to our `docker-compose.yml`. We will also configure FlareSolverr to route its Cloudflare-solving traffic through Tor.

### [MODIFY] `/home/michael/KiroProject/prowlarr/docker-compose.yml`
```yaml
services:
  # ... (prowlarr remains the same) ...

  tor-proxy:
    image: dockage/tor-privoxy:latest
    container_name: tor-proxy
    restart: unless-stopped
    ports:
      - "8118:8118" # HTTP Proxy
      - "9050:9050" # SOCKS5 Proxy
    networks:
      - ai-services_ai-network

  jackett:
    image: lscr.io/linuxserver/jackett:latest
    container_name: jackett
    restart: unless-stopped
    ports:
      - "9117:9117"
    volumes:
      - /home/michael/jackett/config:/config
      - /home/michael/jackett/downloads:/downloads
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
    networks:
      - ai-services_ai-network

  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    restart: unless-stopped
    ports:
      - "8191:8191"
    environment:
      - LOG_LEVEL=info
      - TZ=America/New_York
      - PROXY=http://tor-proxy:8118
    networks:
      - ai-services_ai-network

networks:
  ai-services_ai-network:
    external: true
```

### Architecture Changes
- We drop the complicated `network_mode` overrides. Every container gets its own IP and ports back.
- FlareSolverr gets a new `PROXY=http://tor-proxy:8118` environment variable so it solves Cloudflare puzzles over Tor.
- We will manually configure Jackett's UI to use `http://tor-proxy:8118` as a proxy.

## Verification Plan

Once deployed, the manual steps for you will be:
1. In Jackett, go to the wrench icon at the top right for global **Settings**.
2. Scroll down to the **Proxy** section.
3. Check the box to enable the proxy, set type to `HTTP`, URL to `tor-proxy`, and Port to `8118`. Click **Apply server settings**.
4. Configure AudioBookBay exactly as before!
