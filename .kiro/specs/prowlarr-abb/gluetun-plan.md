# Gluetun VPN Implementation Plan

## Background Context
Since your ISP drops connections to AudioBookBay, we will route Jackett and FlareSolverr's traffic through a Hotspot Shield VPN connection. We will use `gluetun`, a lightweight Docker VPN client designed specifically for routing other containers' traffic.

## User Review Required

> [!IMPORTANT]
> This requires a major shift in how the containers talk to each other. Jackett and FlareSolverr will no longer have their own IP addresses; they will live "inside" the Gluetun network namespace. Please review the architecture changes and the manual steps you must take to provide the Hotspot Shield credentials.

---

## Proposed Changes

We will modify `/home/michael/KiroProject/prowlarr/docker-compose.yml` heavily.

### [MODIFY] `/home/michael/KiroProject/prowlarr/docker-compose.yml`
```yaml
services:
  gluetun:
    image: qmcgaw/gluetun:latest
    container_name: gluetun
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    ports:
      - "9117:9117" # Jackett UI
      - "8191:8191" # FlareSolverr API
      - "9696:9696" # Prowlarr UI (if we route Prowlarr through it too, see Open Questions)
    volumes:
      - /home/michael/prowlarr/gluetun:/gluetun
    environment:
      - VPN_SERVICE_PROVIDER=custom
      - OPENVPN_CUSTOM_CONFIG=/gluetun/custom.conf
      # We will use an auth.txt file for credentials to avoid putting them in docker-compose.
    networks:
      - ai-services_ai-network
    restart: unless-stopped

  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    restart: unless-stopped
    volumes:
      - /home/michael/prowlarr/config:/config
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
    network_mode: "service:gluetun"

  jackett:
    image: lscr.io/linuxserver/jackett:latest
    container_name: jackett
    restart: unless-stopped
    volumes:
      - /home/michael/jackett/config:/config
      - /home/michael/jackett/downloads:/downloads
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
    network_mode: "service:gluetun"

  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    restart: unless-stopped
    environment:
      - LOG_LEVEL=info
      - TZ=America/New_York
    network_mode: "service:gluetun"

networks:
  ai-services_ai-network:
    external: true
```

### Architecture Changes
- `prowlarr`, `jackett`, and `flaresolverr` are all routed through `gluetun`. 
- **Because they share the same network namespace**, they must communicate over `localhost`. 
- For example, in Jackett, the FlareSolverr URL will change from `http://flaresolverr:8191` to `http://localhost:8191`.
- In Prowlarr, the Jackett URL will change to `http://localhost:9117`.

## Open Questions

> [!WARNING]
> Do you want **Prowlarr** routed through the VPN as well? The design above routes all three containers through the VPN. This is safer for Prowlarr anyway since it talks to torrent indexers.

## Verification Plan

Before I can deploy this, **you must complete these manual steps**:
1. Log into your Hotspot Shield dashboard and download an `.ovpn` configuration file for the server you want to use.
2. Note your specific Router Username and Password.
3. Save the `.ovpn` file onto the server at `/home/michael/prowlarr/gluetun/custom.conf`.
4. Create a file at `/home/michael/prowlarr/gluetun/auth.txt` containing just your Username on the first line and your Password on the second line.
5. In `custom.conf`, find the line that says `auth-user-pass` and change it to `auth-user-pass /gluetun/auth.txt`.

Once you tell me those files are in place and answer the Open Question, I will pull the trigger on the deployment!
