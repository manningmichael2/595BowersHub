# C7 — Scoped DB roles cutover runbook

Stop services connecting to Postgres as the cluster **superuser `michael`**.
Migration `0003_scoped_db_roles.sql` creates the scoped roles (NOLOGIN, so it's
**inert** until you run this cutover). Every step below has been validated
against a Postgres 16 built from the migration chain.

## Roles

| Role | For | Privileges |
|---|---|---|
| `bowershub_app` | the main `bowershub-ai` app | owns all app objects (full DDL within the DB), `CREATEROLE`, member of `finance_reader`; **not** superuser (no `pg_read_file`, `COPY PROGRAM`, other DBs) |
| `finance_reader` | ask-db (via `SET LOCAL ROLE`) | read-only on finance/inventory/house/cook/files only (migration `0002`) |
| `dashboard_reader` | the `dashboard` service | `SELECT` on `public.api_usage_log` only |

## Pre-req

Deploy the code first so the app (still connecting as `michael`) applies
migrations `0002` + `0003`. Confirm the roles exist:

```sql
SELECT rolname, rolcanlogin, rolsuper FROM pg_roles
WHERE rolname IN ('bowershub_app','dashboard_reader','finance_reader');
```

## Cutover (run as superuser `michael`)

1. **Set passwords + enable login** (choose strong passwords; put them in the
   services' `.env` in step 3):

   ```sql
   ALTER ROLE bowershub_app    LOGIN PASSWORD '<app-pw>';
   ALTER ROLE dashboard_reader LOGIN PASSWORD '<dash-pw>';
   ```

2. **Transfer ownership of app objects** to `bowershub_app` (NOT the database —
   that stays with `michael`/superuser). Run in `psql -d finance`:

   ```sql
   DO $$
   DECLARE r record;
   BEGIN
     FOR r IN SELECT nspname FROM pg_namespace
              WHERE nspname IN ('finance','inventory','house','cook','files') LOOP
       EXECUTE format('ALTER SCHEMA %I OWNER TO bowershub_app', r.nspname);
     END LOOP;
     FOR r IN SELECT schemaname, tablename FROM pg_tables
              WHERE schemaname IN ('public','finance','inventory','house','cook','files') LOOP
       EXECUTE format('ALTER TABLE %I.%I OWNER TO bowershub_app', r.schemaname, r.tablename);
     END LOOP;
     FOR r IN SELECT sequence_schema, sequence_name FROM information_schema.sequences
              WHERE sequence_schema IN ('public','finance','inventory','house','cook','files') LOOP
       EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO bowershub_app', r.sequence_schema, r.sequence_name);
     END LOOP;
     FOR r IN SELECT schemaname, viewname FROM pg_views
              WHERE schemaname IN ('public','finance','inventory','house','cook','files') LOOP
       EXECUTE format('ALTER VIEW %I.%I OWNER TO bowershub_app', r.schemaname, r.viewname);
     END LOOP;
     FOR r IN SELECT p.oid::regprocedure AS func FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname IN ('finance','inventory','house','cook','files')
                 OR (n.nspname='public' AND p.proname='update_updated_at') LOOP
       EXECUTE format('ALTER FUNCTION %s OWNER TO bowershub_app', r.func);
     END LOOP;
   END $$;
   ```

   Verify `SELECT count(*) FROM pg_tables WHERE schemaname IN
   ('public','finance','inventory','house','cook','files') AND tableowner='michael';`
   returns **0**.

3. **Switch each service's credentials** (in their `.env`, not committed):
   - `bowershub-ai/.env`: `DB_USER=bowershub_app`, `DB_PASSWORD=<app-pw>`
   - `dashboard/.env`: `DB_USER=dashboard_reader`, `DB_PASSWORD=<dash-pw>`

4. **Restart** the services (`bowershub-ai`, `dashboard`).

5. **Verify**: app boots, chat works, ask-db works; dashboard renders API spend.
   Confirm the app is no longer superuser:
   ```sql
   -- as the app: should be 'off'
   SELECT current_setting('is_superuser');
   ```

## Rollback

Set the two `.env` files back to `DB_USER=michael` + its password and restart.
(Ownership stays with `bowershub_app`, which is harmless — `michael` is still
superuser and can do anything.)

## Notes

- **Fresh deploys**: provision the DB and run the app **once as `michael`**
  (superuser) so the baseline `CREATE EXTENSION pgcrypto` + role creation run,
  then perform this cutover. `pgcrypto` must be pre-installed for a non-superuser
  runtime.
- **Future forward migrations** run as `bowershub_app` after cutover, so they
  must avoid superuser-only ops (no `CREATE EXTENSION`). Role ops are fine —
  `bowershub_app` has `CREATEROLE`.
- **db-admin** was retired (see `archive/db-admin/DEPRECATED.md`); **n8n**'s
  Postgres credential (configured in the n8n UI) should also be moved off
  `michael` to a scoped role when convenient — a follow-up.
