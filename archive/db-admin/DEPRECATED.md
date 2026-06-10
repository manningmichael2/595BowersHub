# db-admin — RETIRED (C7 / C3)

This standalone Flask service was an **unauthenticated**, SQL-injectable
reimplementation of the DB browser that connected to Postgres as the
**superuser** and exposed arbitrary DDL (CREATE/ALTER/DROP/RENAME) and
row delete/insert to anyone who could reach port 5002. See project-review.md
C3/C7.

**Status:** retired. Its unique features (inbox processing, AI extract,
field hints, image serving) now live in the authenticated `bowershub-ai`
backend (`backend/routers/db_browser.py`, ~33 inbox/AI-extract routes).

**To fully decommission on the server:**
```bash
docker stop db-admin && docker rm db-admin
# remove any reverse-proxy route to :5002
```

Kept in git history for reference only. Do not redeploy.
