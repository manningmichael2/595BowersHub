# Prowlarr + AudioBookBay Integration Walkthrough (Tor Edition)

## What Was Completed
Your ISP is completely dropping connections to AudioBookBay, so we deployed a **Tor Proxy** to tunnel right through the block. We also kept the FlareSolverr container to handle AudioBookBay's Cloudflare anti-bot checks.

### Changes Made
- **Docker Compose:** Updated `/home/michael/KiroProject/prowlarr/docker-compose.yml` to include `tor-proxy` and configured `flaresolverr` to tunnel its traffic through Tor.
- **Deployment:** Pulled the latest `dockage/tor-privoxy` image and restarted the stack.
- **Handoff:** Updated the shared `context-log.md` to record the new architecture.

## Next Steps for You

Now that the proxy is live, you just need to tell Jackett to use it:

### 1. Enable the Tor Proxy in Jackett
1. Go to **http://100.106.180.101:9117**
2. At the very top right, click the **Wrench Icon** (Settings).
3. Scroll down to the **Proxy** section.
4. Check the box for **Proxy configuration**.
5. Set **Type** to `HTTP`.
6. Set **Proxy URL** to `http://tor-proxy`
7. Set **Port** to `8118`.
8. Check the box for **Proxy configuration applies to FlareSolverr** (very important).
9. Click **Apply server settings** at the bottom.

### 2. Set up AudioBookBay in Jackett
*(If you already added the FlareSolverr URL earlier, you don't need to do it again, but double-check that it is still set to `http://flaresolverr:8191` at the bottom of the page).*

1. Scroll up and click **+ Add indexer**.
2. Search for **AudioBookBay**, click the wrench icon, and enter your login credentials.
3. Once it successfully connects, click the blue **Copy Torznab Feed** button.
4. Note your **API Key** at the top right of the Jackett dashboard.

### 3. Add Jackett to Prowlarr
1. Go to **http://100.106.180.101:9696**
2. Go to **Indexers > Add Indexer** and select **Generic Torznab**.
3. Paste the Jackett URL into the **URL** field.
4. Paste the Jackett API key into the **API Key** field.
5. Click **Test** and **Save**.
