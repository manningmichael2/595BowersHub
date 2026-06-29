# Screenshots

Captured with Playwright at two viewports — **desktop** (1440×900) and **mobile**
(390×844, 2× DPR). The committed `login-*.png` are from the live deployed app
(no personal data). Authenticated views are generated against a **seeded local
test stack** so no real finances are exposed.

## Regenerate

The capture script lives at `bowershub-ai/frontend/scripts/screenshots.mjs`
(Playwright is a devDependency; run `npx playwright install chromium` once).

### Public pages (login) — against the live app

```bash
cd bowershub-ai/frontend
node scripts/screenshots.mjs          # → docs/screenshots/login-{desktop,mobile}.png
```

### Authenticated views — against a seeded test stack

1. Start an isolated backend on a throwaway DB (migrations auto-apply), seed a
   test user + a little demo data (a workspace, a few transactions, a shopping
   list), and have it serve the built frontend on one origin (e.g. `:5099`).
2. Mint a JWT for the test user (the backend's `AuthService.generate_access_token`)
   and pass it in so the app lands logged-in:

```bash
SHOT_BASE=http://localhost:5099 \
SHOT_TOKEN="<test-user-jwt>" \
SHOT_USER='{"id":1,"email":"demo@local","display_name":"Demo","role":"admin"}' \
SHOT_ROUTES="dashboard:/dashboard,chat:/chat,lists:/lists,finance:/finance/transactions,settings:/settings" \
node scripts/screenshots.mjs
```

Env vars: `SHOT_BASE` (target origin), `SHOT_OUT` (output dir), `SHOT_TOKEN` +
`SHOT_USER` (seed `localStorage` auth), `SHOT_ROUTES` (`name:/path,…`).
