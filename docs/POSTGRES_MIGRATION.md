# Render PostgreSQL schema migration

The app applies its versioned schema migration in FastAPI's startup lifespan,
before it accepts requests. It uses a PostgreSQL transaction and an advisory
lock so multiple Render workers do not run the migration concurrently. It only
adds columns, indexes, a foreign key, missing model tables, and a migration
version row; it does not drop tables, delete records, or reset accounts.

## Before deploying

1. In the Render Dashboard, open the CTR PostgreSQL database and create a
   manual backup/snapshot. Confirm it appears in the database's backups before
   continuing. If manual backups are unavailable for the database plan, export
   a database dump using Render's documented connection procedure and retain it
   securely.
2. Do not copy the database URL into source files, command history, tickets, or
   logs. Keep the existing Render `DATABASE_URL` setting unchanged.
3. Deploy the application commit containing `app/migrations.py`.

The application startup runs the migration before `/admin` or other routes can
serve a request. To run it explicitly from a Render Shell after the new code is
available, use:

```sh
python -m app.migrations
```

The command is repeatable and uses the same configured `DATABASE_URL` as the
service. It does not print that URL or any database credential. Restart or
redeploy the web service after an explicit Shell run so the application starts
with the migrated schema.

## Verify the deployment

1. Check Render service logs for `Applied database migration
   20261126_01_add_server_integration_schema` on the first successful run, or
   `Database migration ... is already applied` on later startups. Migration
   errors are surfaced and prevent startup rather than allowing `/admin` to
   fail on missing columns.
2. Using the Render database query interface, confirm the expected columns:

   ```sql
   SELECT column_name, data_type, is_nullable, column_default
   FROM information_schema.columns
   WHERE table_schema = 'public'
     AND table_name = 'game_servers'
   ORDER BY ordinal_position;
   ```

3. Open the public CTR home page and log into `/admin`. Confirm existing
   servers, reports, and admin login are still present.
4. If startup fails, review the error (without sharing connection strings),
   keep the backup, and correct the reported schema/data issue before retrying.
   PostgreSQL rolls back the migration transaction on failure.

## Schema details

The migration adds `verification_status VARCHAR(32) NOT NULL DEFAULT
'pending_verification'`, `pairing_token_hash VARCHAR(64) NOT NULL DEFAULT ''`,
`registration_id VARCHAR(80) NOT NULL DEFAULT ''`, nullable `owner_id INTEGER`
referencing `users.id`, `can_issue_global_bans BOOLEAN NOT NULL DEFAULT FALSE`,
nullable `last_heartbeat TIMESTAMP WITH TIME ZONE`, integer player counts
defaulting to zero, and `gmod_version VARCHAR(100) NOT NULL DEFAULT ''`.

Existing server registration IDs are assigned deterministic `legacy-<id>`
values (with a suffix only if needed) when blank or duplicated, so existing
server rows can satisfy the unique registration index without removing data.
When `verification_status` is new, its initial value is mapped from the existing
`verified` and `active` fields so approved servers remain verified and inactive
servers remain suspended.
The ORM's missing tables, including `global_bans`, are created if absent.
