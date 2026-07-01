# Screenshots

Captured with Playwright at two viewports — **desktop** (1440×900) and **mobile**
(390×844, 2× DPR). The committed `login-*.png` are from the live deployed app
(no personal data). Authenticated views (`chat`, `lists`, `finance`, `settings`)
are generated against a **seeded local test stack** so no real finances are
exposed.

> The dashboard and admin views are intentionally not captured yet — both are
> slated for a redesign, and the dashboard's widgets pull live host data
> (docker container list, news) that shouldn't land in a public README.

## Regenerate

The capture script lives at `bowershub-ai/frontend/scripts/screenshots.mjs`
(Playwright is a devDependency; run `npx playwright install chromium` once).

### Public pages (login) — against the live app

```bash
cd bowershub-ai/frontend
node scripts/screenshots.mjs          # → docs/screenshots/login-{desktop,mobile}.png
```

### Authenticated views — against a seeded test stack

The app bootstraps a session from `localStorage` `refreshToken` + `user` (it does
**not** read an access token from storage — see `src/stores/auth.ts`), so
`SHOT_TOKEN` is a **refresh** token: on load the app exchanges it at
`/api/auth/refresh` for an access token. Refresh tokens **rotate on use** and
reuse trips theft-detection, so **each browser context needs its own token** —
pass `SHOT_TOKEN` as a comma-separated list, one per viewport (desktop, mobile).

1. **Throwaway Postgres.** Use a pgvector image (a migration hard-requires the
   extension) and enable it:

   ```bash
   docker run -d --name bh-shots -e POSTGRES_USER=me -e POSTGRES_PASSWORD=pw \
     -p 55433:5432 pgvector/pgvector:pg16
   docker exec -e PGPASSWORD=pw bh-shots \
     psql -U me -c 'CREATE DATABASE bh_shots;'
   docker exec -e PGPASSWORD=pw bh-shots \
     psql -U me -d bh_shots -c 'CREATE EXTENSION IF NOT EXISTS vector;'
   ```

2. **Build the frontend and stage it where the backend serves static:**

   ```bash
   cd bowershub-ai/frontend && npm run build
   rm -rf ../static && cp -r dist ../static
   ```

3. **Run an isolated backend** on the throwaway DB (migrations auto-apply). Only
   presence-checked vars need real-ish values; the API key can be a dummy since
   screenshots make no model calls:

   ```bash
   cd bowershub-ai
   ANTHROPIC_API_KEY=dummy DB_HOST=localhost DB_PORT=55433 DB_NAME=bh_shots \
   DB_USER=me DB_PASSWORD=pw JWT_SECRET=dev N8N_BASE=http://localhost:9999 \
   .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 5099
   ```

4. **Seed a demo user + data and mint refresh tokens** (one per viewport).
   Insert a `bh_users` row (bcrypt hash), a workspace, a shopping/to-do list, a
   `finance.accounts` row + a spread of `finance.transactions`, then generate
   refresh tokens (SHA-256 hash into `bh_refresh_tokens`). Capture the raw
   tokens + a `user` object.

5. **Capture:**

   ```bash
   cd bowershub-ai/frontend
   SHOT_BASE=http://localhost:5099 \
   SHOT_TOKEN="<refresh-token-A>,<refresh-token-B>" \
   SHOT_USER='{"id":1,"email":"demo@local","display_name":"Demo","role":"admin","is_active":true}' \
   SHOT_ROUTES="chat:/chat,lists:/lists,finance:/finance/transactions,settings:/settings" \
   node scripts/screenshots.mjs
   ```

Env vars: `SHOT_BASE` (target origin), `SHOT_OUT` (output dir), `SHOT_TOKEN`
(comma-separated refresh tokens, one per viewport) + `SHOT_USER` (seeds
`localStorage` auth), `SHOT_ROUTES` (`name:/path,…`).
