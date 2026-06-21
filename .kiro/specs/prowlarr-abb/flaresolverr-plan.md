# FlareSolverr Implementation Plan

## Background Context
I checked the Jackett logs and found exactly why it's spinning:
```text
System.Threading.Tasks.TaskCanceledException: The request was canceled due to the configured HttpClient.Timeout of 100 seconds elapsing.
...
at FlareSolverrSharp.ClearanceHandler.SendAsync(...)
```
AudioBookBay is heavily protected by Cloudflare. When Jackett tries to reach it, Cloudflare throws up an anti-bot challenge. Jackett gets stuck waiting for a tool called **FlareSolverr** to solve the challenge, but since we don't have it installed, Jackett eventually times out after 100 seconds.

## User Review Required

> [!IMPORTANT]
> To bypass the Cloudflare challenge, we need to deploy **FlareSolverr**. It acts as a headless browser proxy that silently solves Cloudflare puzzles on behalf of Jackett. Let me know if you approve adding this container to our stack!

---

## Proposed Changes

We will modify `/home/michael/KiroProject/prowlarr/docker-compose.yml` to include the `flaresolverr` service on the same internal network.

### [MODIFY] `/home/michael/KiroProject/prowlarr/docker-compose.yml`
```yaml
services:
  # ... (prowlarr and jackett remain the same) ...

  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    restart: unless-stopped
    ports:
      - "8191:8191"
    environment:
      - LOG_LEVEL=info
      - TZ=America/New_York
    networks:
      - ai-services_ai-network
```

## Verification Plan
1. Bring down the current stack and bring it back up to deploy FlareSolverr.
2. In Jackett, go to the **FlareSolverr API URL** setting at the bottom of the page and set it to `http://flaresolverr:8191`.
3. Try adding AudioBookBay again. Jackett will route the request through FlareSolverr, solve the Cloudflare puzzle, and authenticate successfully.
