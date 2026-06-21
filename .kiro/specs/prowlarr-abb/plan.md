# Prowlarr + AudioBookBay Installation Plan

This plan covers deploying Prowlarr with AudioBookBay (ABB) support on your home server.

## Background Context
AudioBookBay officially requested the Prowlarr team to remove their site from the supported indexers, which Prowlarr honored. As a result, standard Prowlarr images do not include ABB out of the box, and attempting to add custom YAML definitions often fails because ABB actively blocks standard scrapers.

There are two viable paths to get ABB working alongside your *Arr stack.

## User Review Required

> [!IMPORTANT]
> Please review the two approaches below and let me know which path you prefer. Path B is strongly recommended for long-term stability, but Path A is available if you prefer a single-container setup.

### Path A: The Community Fork (What you found)
We can deploy the community-maintained Docker fork (e.g., `BitlessByte0/docker-prowlarr-abb`). 
- **Pros:** It's a single container and acts exactly like standard Prowlarr but with the ABB indexer manually patched back in.
- **Cons:** It relies on a third-party maintainer to keep the base Prowlarr image up to date. If the maintainer abandons the fork, you'll be stuck on an old version of Prowlarr or it will break when ABB changes its site structure.

### Path B: Official Prowlarr + Jackett (Recommended)
We deploy the official `linuxserver/prowlarr` container alongside an official `linuxserver/jackett` container. Jackett is an older indexer manager that **still natively supports AudioBookBay**. We then add Jackett as a "Generic Torznab" indexer inside Prowlarr.
- **Pros:** You get the official, secure, and always-updated Prowlarr image. Jackett handles the messy ABB scraping, and Prowlarr seamlessly passes the results to your *Arr apps.
- **Cons:** Requires running two lightweight containers instead of one.

---

## Proposed Changes

We will create a new directory on the server at `/home/michael/prowlarr/` containing a `docker-compose.yml` file.

### If you choose Path A (Community Fork)

#### [NEW] `/home/michael/prowlarr/docker-compose.yml`
```yaml
services:
  prowlarr:
    image: bitlessbyte0/docker-prowlarr-abb:latest
    container_name: prowlarr
    restart: unless-stopped
    ports:
      - "9696:9696"
    volumes:
      - /home/michael/prowlarr/config:/config
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
    networks:
      - ai-services_ai-network

networks:
  ai-services_ai-network:
    external: true
```

### If you choose Path B (Official Prowlarr + Jackett)

#### [NEW] `/home/michael/prowlarr/docker-compose.yml`
```yaml
services:
  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    restart: unless-stopped
    ports:
      - "9696:9696"
    volumes:
      - /home/michael/prowlarr/config:/config
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
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

networks:
  ai-services_ai-network:
    external: true
```

## Verification Plan

### Automated Tests
- Bring the container(s) up using `docker compose up -d`.
- Verify the containers report a `running` and `healthy` status via `docker ps`.

### Manual Verification
- You will navigate to the Prowlarr web UI (`http://100.106.180.101:9696`).
- **If Path A:** You will search for AudioBookBay in the indexers list and test the connection.
- **If Path B:** You will navigate to Jackett (`http://100.106.180.101:9117`), add AudioBookBay, copy the Torznab feed URL and API key, and paste it into Prowlarr as a new Generic Torznab indexer.
