# C7 — Scoped DB roles & the migration role (cutover runbook)

This is the runbook that migrations `0002`–`0004` and `0021` reference. It was
missing (the cutover was done ad-hoc), which is the proximate cause of the
**2026-06-19 deploy crash-loop** — see `context-log.md`. Run it once per cluster.

## The model (what runs as what)

| Connection            | Role                 | Privilege                                  | Set via            |
|-----------------------|----------------------|--------------------------------------------|--------------------|
| App request handling  | `bowershub_app`      | DML on app schemas, `SET ROLE finance_reader`; **NOSUPERUSER** | `DB_USER`          |
| Startup migrations    | `bowershub_migrator` | **SUPERUSER** (DDL, `CREATE EXTENSION`, owns legacy objects) | `MIGRATION_DB_USER`|
| ask-db sandbox        | `finance_reader`     | SELECT on domain schemas only              | `SET ROLE`         |
| n8n                   | `n8n_app`            | DML on domain schemas + select public compat | n8n creds        |
| dashboard             | `dashboard_reader`   | SELECT on `public.api_usage_log` only      | dashboard creds    |

Runtime is least-privilege; **only the short-lived migration connection is
privileged**, and `backend/database.py:run_migrations()` closes it immediately
after applying migrations. This is why a compromised request path still can't
drop the world, while deploys can still apply schema changes automatically with
no manual step (the thing that broke on 2026-06-19 was a *manual* step nobody ran).

## Why the migrator is SUPERUSER (and why that's acceptable here)

- `CREATE EXTENSION <non-trusted>` (pgvector, pg_trgm) requires superuser.
- Legacy objects predating the role split are owned by `postgres`/`michael`;
  `ALTER`/`DROP` on them requires ownership or superuser.
- A non-superuser owner role would re-introduce a manual "run this extension as
  superuser" step — the exact failure class we're removing.
- Single-operator homelab, app and DB co-located. This is strictly *better* than
  the pre-C7 state where the **app itself** ran as the cluster superuser for
  every request. The migrator password lives in the app `.env`, used only for the
  startup connection. Rotate it independently of the human `michael` login.

## One-time cutover (run as the cluster superuser `michael`)

> The DB superuser is **`michael`**, not `postgres` (`POSTGRES_USER`). Connect
> with `-U michael`. `psql` runs from the postgres container if not on the host:
> `docker exec -it <postgres-container> psql -U michael -d finance`

```sql
-- 1. Bootstrap the migration role's privileged attributes. The role itself is
--    created (NOLOGIN) by migration 0021; this grants the parts that must not
--    live in VCS. Pick a strong password and store it in Dashlane.
ALTER ROLE bowershub_migrator WITH LOGIN SUPERUSER PASSWORD 'PUT_STRONG_PASSWORD_HERE';

-- 2. (Optional cleanup, not required for correctness.) With a superuser migrator,
--    object ownership no longer blocks DDL. But for tidiness you may transfer the
--    legacy postgres/michael-owned objects to the app role so `\d` ownership is
--    consistent. Safe to skip. REASSIGN moves ALL objects owned by the source
--    role in the CURRENT database, so review first:
--      SELECT n.nspname, c.relname, pg_get_userbyid(c.relowner) AS owner
--      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
--      WHERE pg_get_userbyid(c.relowner) IN ('postgres') AND n.nspname IN
--            ('public','finance','inventory','house','cook','files');
-- REASSIGN OWNED BY postgres TO bowershub_app;
```

If `bowershub_migrator` does not exist yet (first deploy of this change), it is
created by migration `0021` on the next startup — but that startup must connect
as a role that can run `0021`. Bootstrap order for a brand-new cutover:

1. Deploy with `MIGRATION_DB_USER` **blank** once → migrations run as `DB_USER`.
   (Or temporarily set `DB_USER=michael` for a single migrate pass.)
2. Run step 1 SQL above to give `bowershub_migrator` LOGIN/SUPERUSER/password.
3. Set `MIGRATION_DB_USER=bowershub_migrator` + `MIGRATION_DB_PASSWORD=...` and
   `DB_USER=bowershub_app` in `.env`, redeploy. Steady state from here on.

On an already-migrated prod DB where `bowershub_migrator` already exists, just do
steps 2–3.

## Verifying the cutover

```sql
-- migrator is superuser & can log in; app role is neither
SELECT rolname, rolsuper, rolcanlogin FROM pg_roles
 WHERE rolname IN ('bowershub_app','bowershub_migrator');
```

Then confirm a deploy applies cleanly:

```bash
docker compose logs bowershub-ai | grep -i "migration"
# expect: "Applying migrations via dedicated migration role 'bowershub_migrator'"
#         "No pending migrations"  (or "Applied N migration(s)")
curl -sf http://localhost:5003/api/health
```

## Local / CI

Leave `MIGRATION_DB_USER`/`MIGRATION_DB_PASSWORD` unset. Migrations then run as
`DB_USER` (which is `michael`/superuser locally and in the test harness — see
`backend/tests/conftest.py`), so DDL has the privilege it needs and from-scratch
rebuilds work without any cutover. Migration `0021` still creates the (inert)
`bowershub_migrator` role so the schema is reproducible from empty.
