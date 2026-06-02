---
name: supabase-operations
description: How Claude reads/writes Supabase — SUGGESTED global default plus the project-md-authoritative model; execution confirmation; live-DB source of truth
when_to_read: before ANY database or SQL work, from any repo
sections:
  - Authoritative source is the project md
  - Suggested default for new projects
  - Access scope and least-privilege
  - Database execution confirmation
  - Live database is the source of truth
  - Writing migration files
  - Fallback - Management API script (booking_pro_saas)
---
# Supabase Database Operations
> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

## Authoritative source is the project md
The REAL way to read/write a given project's database lives in THAT project's md files (CLAUDE.md / AGENTS.md / GEMINI.md). Always defer to it. This global file is only a *suggested* starting point. Existing projects keep their own method — do not change it:
- **reply-flow** → psql + `SUPABASE_DB_URL` from `server/.env` (the suggested default below).
- **booking_pro_saas** → `execute_sql.py` via the Management API (see the Fallback section — its migration history is drifted and the Techloq filter blocks direct HTTPS).

## Suggested default for new projects
Use direct Postgres via `psql`, with a single per-project connection string read from that project's `server/.env`:
- **Read a query:** `psql "$SUPABASE_DB_URL" -c "select ..."`
- **Full schema dump:** `pg_dump --schema-only --schema=public "$SUPABASE_DB_URL"`
- **Run a migration (WRITE — needs confirmation, see below):** `psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f path/to/migration.sql`

Load `SUPABASE_DB_URL` from `server/.env` (e.g. `source server/.env`). On Windows/PowerShell, read the line from `server/.env` and assign it to the env var before calling psql.

Why this is the default: the Postgres wire protocol is NOT blocked by the Techloq content filter (only HTTPS to api.supabase.com is), so psql works on this machine without `verify=False` hacks. It is standard, supports full read/write, and `pg_dump` gives complete schema.

## Access scope and least-privilege
- A `SUPABASE_DB_URL` is **per-project**: its host (`db.<project-ref>.supabase.co` / pooler) and password are unique to ONE Supabase project. It grants NO access to other projects. (The account-wide credential is the Management API token — which this default deliberately avoids.)
- Within a project, the URL is an elevated, RLS-bypassing connection. To limit employee/contractor access, do it **server-side** (you cannot enforce it from files on their machine):
  - Preferred: give them a **separate dev/staging Supabase project**; keep the prod URL with you/CI.
  - Or: create a **read-only Postgres role** server-side and distribute only its connection string.
- Distribution is the control point: `.env` is gitignored, so cloning the repo grants no credentials. Revoke by rotating the password / dropping the role server-side.

## Database execution confirmation

**NEVER execute SQL against a live database without a dedicated, standalone confirmation from the user.**

This applies to `execute_sql.py`, `psql`, or any command that writes to the database. The confirmation request MUST be its own message containing ONLY the request to run the SQL — no summaries, status updates, or other content bundled with it.

**Why:** When SQL execution is mentioned alongside other content (e.g., "Here's what I did... want me to run the migration?"), a user reply like "continue", "go", or "yes" is ambiguous — it could mean "continue working" not "execute SQL against production."

**Correct flow:**
1. Complete code changes and summarize them (do NOT mention running SQL here)
2. In a **separate, standalone message**, ask ONLY: "Here's the migration to execute: `[filename]`. Can I run it?"
3. Wait for explicit confirmation specifically about the SQL execution

**Each migration is a separate authorization event** — prior approvals in the same conversation do NOT carry forward.

For HOW to execute SQL (which tool, which command, what to avoid), see `~/.ai-instructions/supabase-operations.md`.

## Live database is the source of truth

**Migration files are a historical log, not a source of truth. Always verify against the live database.**

For ANY database-related work — reads, writes, RPC/function definitions, triggers, constraints, RLS policies, column types, defaults, indexes — query the live DB. Never base decisions on what a migration file says.

**Why:** Later migrations may replace function bodies (`CREATE OR REPLACE FUNCTION`), move tables between schemas, rename columns, drop constraints, or otherwise supersede earlier definitions. The original migration file stays unchanged on disk but no longer reflects reality. Reading a migration file and assuming it's current is a fast path to wrong answers and broken code.

**How to apply:**
- Before modifying or renaming any DB object, query the live state:
  - Functions/procedures: `SELECT prosrc FROM pg_proc WHERE proname = '<name>'`
  - Triggers: `SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid = '<schema>.<table>'::regclass`
  - Policies: `SELECT polname, pg_get_expr(polqual, polrelid) FROM pg_policy WHERE polrelid = '<schema>.<table>'::regclass`
  - Constraints: query `pg_constraint` joined with `pg_class`/`pg_namespace`
  - Columns/types/defaults: `information_schema.columns` or a schema-dump script
- When writing a new function that's a modified version of an existing one, copy the body from `pg_proc`, not from a migration file.
- When answering a question about how something works ("what does function X do?", "what columns does table Y have?"), query the live DB — do not quote a migration file as the answer.
- Applies even to "simple" changes and even for read-only questions. No exceptions.

## Writing migration files
- Location: the project's own `supabase/migrations/` (or as the project md specifies).
- Naming: `YYYYMMDD_HHMMSS_<description>.sql` (timestamp-based, collision-free across parallel agents).
- After execution: refresh schema cache / regenerate types per the project's documented commands.

## Fallback - Management API script (booking_pro_saas)
This method is for booking_pro_saas specifically, or as a fallback when a project's direct Postgres port is unreachable. It is NOT the default for new projects.

### How to Execute SQL

One command. Works from any repo, any directory:

```bash
py c:/dev/booking_pro_saas/scripts/execute_sql.py <absolute-path-to-sql-file>
```

- Takes an absolute path to any `.sql` file (doesn't matter which repo it lives in)
- Uses Supabase Management API with `SUPABASE_ACCESS_TOKEN` from `c:/dev/booking_pro_saas/.env.local`
- Uses Python `requests` with `verify=False` — this is specifically how it bypasses the Techloq content filter on this machine
- Project ref `oaajdbqadvtcdxlgcxig` is read from `.env.local` automatically

### What NOT To Do (And Why)

These all fail on this machine. Do not attempt them.

| Don't do this | Why it fails |
|---|---|
| `supabase db push` | Migration history is permanently drifted. CLI lists hundreds of already-applied migrations and refuses, or tries to re-apply all of them. |
| `supabase db execute` | This command does not exist in the Supabase CLI. |
| Python `urllib` to `api.supabase.com` | Techloq content filter intercepts HTTPS and blocks the request (HTTP 403, Cloudflare error 1010). |
| `curl` to `api.supabase.com` | Same Techloq block (TLS handshake failure, exit code 35). |
| Supabase REST API RPC (`/rpc/exec_sql`) | No such RPC function exists in this project's database. |
| `supabase migration repair` to force `db push` | Marks legitimate migrations as "reverted," damaging history for other tools and future pushes. |
| Raw `requests.post()` to Management API | You're reinventing `execute_sql.py`. Use the script — it already handles auth, UTF-8, and `verify=False`. |
| Hunting for CLI access tokens or DB passwords | Unnecessary. `execute_sql.py` has everything it needs in `.env.local`. |

### Permission Model

- **SQL READS** (SELECT, information_schema, pg_proc lookups): No permission needed. Run freely via `execute_sql.py`.
- **SQL WRITES** (CREATE, ALTER, INSERT, UPDATE, DELETE, DROP): Dedicated standalone confirmation required. See global CLAUDE.md "Database Execution Confirmation" section.

### Writing Migration Files

- **Location:** Always `c:/dev/booking_pro_saas/supabase/migrations/` — even when working from a different repo.
- **Naming:** `YYYYMMDD_HHMMSS_<description>.sql` (timestamp-based). Never sequential numbering.
- **After execution:** Refresh schema cache: `py c:/dev/booking_pro_saas/scripts/get_schema.py`
- **TypeScript types:** If the migration changes tables used by TypeScript code: `pnpm --dir c:/dev/booking_pro_saas gen-types`

### Migration History Drift

The remote `schema_migrations` table is out of sync with local migration files. This is a **known permanent state** — many migrations were applied directly via SQL Editor or other tools and were never tracked by `supabase db push`.

- `supabase db push` will always complain: "Remote migration versions not found in local migrations directory." This is expected.
- Do NOT try to fix this with `migration repair`, `db pull`, or `--include-all`. Use `execute_sql.py`.
- Migration files in `supabase/migrations/` are a historical log for humans. The live database is the source of truth (see global CLAUDE.md "Database Source of Truth" section).

### Querying Live Database State

- **Full schema dump:** `py c:/dev/booking_pro_saas/scripts/get_schema.py` → outputs `supabase_full_schema.json`
- **Specific objects:** Write a SELECT query in a `.sql` file, run via `execute_sql.py`
- **Introspection queries:** See global CLAUDE.md "Database Source of Truth" section for pg_proc, pg_trigger, pg_policy, pg_constraint, information_schema.columns queries

### Anti-Spiral Rule

**If your first approach to executing SQL fails, STOP.** Do not try alternative approaches. Re-read this file. The answer is always `execute_sql.py`.

If `execute_sql.py` itself fails, check these three things in order:
1. Does `c:/dev/booking_pro_saas/.env.local` contain `SUPABASE_ACCESS_TOKEN`? (If not, the token may be in `.env.master` — copy it to `.env.local`)
2. Is the `requests` Python package installed? (`py -m pip install requests`)
3. Is the SQL file valid? (Check for syntax errors, encoding issues)

If all three are fine and it still fails, **tell the user and stop**. Do not improvise alternative execution methods.

### Supabase CLI — What It's Good For

The Supabase CLI is authenticated and working. It's useful for:
- `supabase projects list --workdir c:/dev/booking_pro_saas` — verify connectivity
- `supabase migration list --workdir c:/dev/booking_pro_saas` — see migration history (read-only)
- `supabase gen types --workdir c:/dev/booking_pro_saas` — generate TypeScript types

It is NOT useful for executing SQL against the database. Use `execute_sql.py`.

### Path Note

All paths in this file assume `booking_pro_saas` is at `c:/dev/booking_pro_saas`. If the repo moves, update the paths here.
