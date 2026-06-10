# C7 — n8n scoped DB role cutover runbook

Closes the **last** service connecting to Postgres as the cluster superuser
`michael`: n8n's `Finance Postgres` credential. n8n runs automation workflows,
several with dynamic (`{{ $json.sql }}`) Postgres nodes, so a superuser
credential there meant any workflow — or a compromise of n8n — could read
password hashes (`public.bh_users`) or run server-side programs.

Migration `0004_n8n_scoped_role.sql` creates the scoped role **`n8n_app`**
(NOLOGIN, so it's **inert** until this cutover). Validated end-to-end against the
live DB before the credential swap.

## Role

| Role | For | Privileges |
|---|---|---|
| `n8n_app` | n8n's `Finance Postgres` credential (all 17 PG workflows) | `SELECT/INSERT/UPDATE/DELETE` on the data schemas (`finance`, `inventory`, `house`, `cook`, `files`) + the `public.*` compat views (`transactions`, `accounts`, `email_labels`, …) + `public.api_usage_log` (and its sequence). **No** `bh_*`/auth tables, **no** DDL, **not** superuser, **no** `CREATEROLE`. |

Why these grants: the 021 schema move left auto-updatable compat **views** in
`public` (`public.transactions` → `finance.transactions`, …) owned by
`bowershub_app`; workflows write through them, so view-mediated writes are
checked against the owner. Direct-access workflows (`files.assets`) and the
dynamic-SQL nodes get DML on the base data schemas. `api_usage_log` is a real
public table, so its sequence is granted explicitly. Everything `bh_*` (auth,
secrets, app state) is deliberately excluded.

## Pre-req

Deploy the code so the app applies migration `0004` (creates `n8n_app` NOLOGIN).
Confirm:

```sql
SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname = 'n8n_app';
-- n8n_app | f | f
```

## Cutover

1. **Set a password + enable login** (run as `bowershub_app` — it has
   `CREATEROLE` — or as superuser):

   ```sql
   ALTER ROLE n8n_app LOGIN PASSWORD '<n8n-pw>';
   ```

2. **Point the n8n credential at `n8n_app`.** The credential lives encrypted in
   n8n's store, so edit it through the n8n CLI (re-encrypts on import) — no UI
   needed:

   ```sh
   # in the n8n container; credential id from: n8n export:credentials --all
   n8n export:credentials --id=JvthRCvWKXaGGbBI --decrypted --output=/tmp/c.json
   # set data.user = "n8n_app", data.password = "<n8n-pw>" (preserve host/db/port)
   n8n import:credentials --input=/tmp/c.json     # update in place (same id)
   rm -f /tmp/c.json                              # contains the plaintext password
   ```

   (Or in the UI: Credentials → *Finance Postgres* → set User `n8n_app` +
   password → Save.)

3. **Restart n8n** to drop any pooled connections under the old credential:
   `docker restart n8n`.

4. **Verify** — no `permission denied` / `password authentication failed` in
   `docker logs n8n`, and live connections arrive as `n8n_app`:

   ```sql
   SELECT usename, count(*) FROM pg_stat_activity
   WHERE datname='finance' GROUP BY 1;   -- expect n8n_app when a workflow runs
   ```

## Where the password lives

- In **n8n's credential store** (encrypted, in the `ai-services_n8n_data`
  volume) — this is what n8n uses at runtime.
- The **role's hash** is captured by `pg_dumpall --globals-only` (step 0 of
  `scripts/backup.sh`), so a bare-metal restore brings `n8n_app` back with the
  same password. **Never** in the repo.

## Rollback

Set the credential's user/password back to `michael` (export/edit/import as
above) and restart n8n. `n8n_app` can be left in place (inert once unused).

## Result

After cutover, **no** app service connects to Postgres as superuser `michael`.
Remaining `michael` logins are interactive/admin + the backup job only.
