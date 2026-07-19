---
name: renames-and-schema-changes
description: The standard end-to-end process for ANY identifier rename or DB schema change, in ANY project — classify, inventory, plan, execute with checkpoints, verify with real evidence, contract
when_to_read: BEFORE planning any rename (symbol, column, table, API field) or any DB schema change (table/column/type/constraint/index/trigger/function/enum), in any repository
sections:
  - When this applies
  - Non-negotiables
  - Step 0 — Classify the change (decision matrix)
  - Step 1 — Discovery and inventory
  - Step 2 — Plan in shippable phases + review gate
  - Step 3 — Execute with checkpoints
  - Step 4 — Verify with real evidence
  - Step 5 — Contract and close
  - Reference incident
---

# Renames & Schema Changes — Standard Process

## When this applies

Read this BEFORE planning, in ANY repository:
- any identifier rename that crosses a file boundary or a system boundary (code symbol, DB column/table, API field, config key, queue/job payload key);
- any DB schema change: add/drop/rename/retype a table or column, constraint, index, trigger, function/procedure, enum, policy, view;
- any bulk mechanical sweep (regex/perl/sed across many files), whatever it renames.

The unit of safety is the **boundary**: a rename is trivial inside one compiler-checked unit and dangerous across every boundary the compiler cannot see (DB catalog, separately-deployed clients, stored data, external consumers, humans' mental models). This process exists to enumerate the boundaries first and cross each one deliberately.

## Non-negotiables

1. **Never a one-step breaking change where live traffic exists.** Every change is expand → migrate → contract; every intermediate state is fully working and can be paused at indefinitely.
2. **A code-side rename renames ZERO DB objects.** Every index, constraint, trigger, function signature, and function body still carries the old name until a migration you wrote and ran says otherwise. The converse also holds: a DB rename changes zero code.
3. **Nothing destructive without a way back.** Before any step that overwrites or drops data — including indirect overwrites via trigger side-effects — either snapshot the affected column/table (`CREATE TABLE _snap_x AS SELECT …`) or confirm a restorable backup/PITR covers it. State which, in chat, before running.
4. **Separately-deployed units never assume each other's version.** Client/server/workers deploy at different times and old clients live on in cached tabs. API-visible renames are dual-field: the server accepts AND returns both names first; consumers migrate; only then is the old name dropped.
5. **Verification means real evidence** (see code-quality.md → Evidence Hierarchy): live calls through the real framework and the real DB, compat paths exercised with OLD inputs, catalog re-checked with catalog queries. Mocked suites and happy-path smoke tests are not evidence for boundary behavior.
6. **This class of change always gets the full adversarial plan review** (planning.md → Plan-Review Gate) — it counts as touching migrations even when no migration file exists yet.

## Step 0 — Classify the change (decision matrix)

| Change | Required pattern |
|---|---|
| **Rename table** | Single `ALTER TABLE … RENAME` — FKs, indexes, RLS policies, triggers, sequences follow automatically (they bind by OID). BUT anything storing the name as TEXT does not: function bodies (`prosrc`), raw-SQL strings in code, views' textual defs elsewhere, external tools. Add a backward-compat updatable VIEW under the old name (`security_invoker = true` when the table has RLS, or the view bypasses it — tenant leak); migrate code; drop the view only after all deploy units soak. |
| **Rename column** | No view escape hatch exists. Dual-column expand-contract: ADD new column → backfill (batched, idempotent, trigger-aware) → BEFORE INSERT/UPDATE sync trigger keeping both equal → migrate code in batches → after soak, drop old column + trigger, then add NOT NULL/unique constraints on the new column to match the old. |
| **Add column** | Additive and safe. NOT NULL arrives in two steps: add nullable (+ default) → backfill → `SET NOT NULL`. |
| **Drop column/table** | Contract-only step: allowed only after a reference census returns zero readers AND all deploy units have soaked on code that no longer touches it. Snapshot first. |
| **Change column type** | New column of the new type + dual-write + backfill + migrate readers + contract. In-place `ALTER TYPE` only when provably lossless AND non-rewriting (or during accepted downtime). |
| **Enum / value-set change** | Expand (accept old + new values) → migrate stored data → contract validation. Grep for the values as string literals in code AND stored JSON. |
| **Rename API/payload field** | Dual-field: server accepts both on input and returns both on output (deploy FIRST, verify live) → consumers switch → drop old name. Compat shims are verified through the real framework with old-name requests — framework semantics bite here (e.g. Express 5 `req.query` is a lazy getter: mutating it is a silent no-op; multipart bodies parse after global middleware). |
| **Rename code-only symbol** (no DB/API/stored-data coupling) | Sweep is acceptable — after Step 1 proves the "only" and with Step 3's sweep hygiene + post-checks. |
| **Constraint / index / trigger / function changes** | Same expand-contract thinking: create the new alongside, migrate dependents, drop the old. `CREATE OR REPLACE FUNCTION` preserves grants; DROP+CREATE resets them to defaults (PUBLIC EXECUTE — re-assert REVOKEs and re-verify with `has_function_privilege`). |

## Step 1 — Discovery and inventory

Post the full inventory in chat BEFORE any plan or sweep. Grep/query every boundary for the OLD name — and check the NEW name for collisions in each of the same places:

**Code** (count per layer: server / client / shared / tests — tests counted separately on purpose):
- quoted occurrences (`'name'`, `"name"`) and unquoted (object keys, property access, camelCase variants);
- look-alike names that must be PROTECTED from a sweep (e.g. `stripe_account_id` vs `account_id`) — write the exclusion (word-boundary + lookbehind) before the sweep.

**DB catalog** (live DB, not migration files — migration history ≠ current state):
```sql
-- unique/partial indexes the name participates in (upsert conflict targets live here)
SELECT indexname, indexdef FROM pg_indexes WHERE indexdef ILIKE '%<name>%';
-- constraints + FKs
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE pg_get_constraintdef(oid) ILIKE '%<name>%';
-- triggers on affected tables + their side effects (updated_at stampers!)
SELECT tgrelid::regclass, tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = '<table>'::regclass;
-- functions whose BODY or PARAMETER NAMES reference it (both matter: prosrc text AND arg names)
SELECT proname, pg_get_function_arguments(oid) FROM pg_proc WHERE prosrc ILIKE '%<name>%' OR pg_get_function_arguments(oid) ILIKE '%<name>%';
-- RLS policies, views, publications
SELECT * FROM pg_policies WHERE qual ILIKE '%<name>%' OR with_check ILIKE '%<name>%';
SELECT viewname FROM pg_views WHERE definition ILIKE '%<name>%';
SELECT * FROM pg_publication_tables WHERE tablename = '<table>';
```

**Stored data**: JSON/JSONB blobs (config columns, job/queue payloads, metadata) that carry the name as a KEY — code migrated to the new key silently misses old stored rows.

**External contracts**: API request/response fields (incl. query params and multipart form fields — enumerate every `req.query`/`req.body` read of the name), webhook payloads delivered to customers, exports/CSVs, third-party integrations, public docs.

**Ops**: env vars, cron/scripts, dashboards, alert rules.

**Sizing**: row counts + table sizes for anything to be backfilled → decides batched vs single-shot.

## Step 2 — Plan in shippable phases + review gate

- Phase the work so that after EVERY phase the system is fully working with mixed old/new code — and can sit there indefinitely. If a phase can't be paused at, it's two phases.
- State the deploy ORDER across units explicitly (server-superset before client for API fields) and what verifies each phase before the next starts.
- For each backfill: trigger handling (suppress via `SET LOCAL session_replication_role='replica'` — session-local, no table locks — or per-table `DISABLE TRIGGER`) and the snapshot decision (Non-negotiable 3).
- Migration files: always NEW files (never edit applied history); check the timestamp slot is free; migrations that lock down or recreate functions preserve SECURITY DEFINER + grants.
- Run the full adversarial plan review; do not start with a Critical/High finding open.

## Step 3 — Execute with checkpoints

- **One phase at a time.** Verify each phase live before the next. Record every applied SQL statement in chat.
- **Dry-run every migration first**: run it with `COMMIT` swapped for `ROLLBACK` against the live DB (`psql -f`, `ON_ERROR_STOP=1`). Prefer self-gating scripts: compute verify counts inside the transaction and `\gset`/`\if` to COMMIT only when clean.
- **Backfills**: batched (bounded chunks, own transactions), idempotent (`WHERE new IS NULL`), resumable, with a final 0-unsynced verification query.
- **Sweep hygiene** (when a sweep is justified per Step 0):
  - sweep quoted and unquoted forms as separate, separately-reviewed passes;
  - protect look-alikes with the exclusions written in Step 1;
  - EXCLUDE test directories — migrate test fixtures/assertions by hand (a swept assertion can no longer detect the sweep's own breakage);
  - afterwards, run the degenerate-fallback grep `\b(\w+)\s*(\?\?|\|\|)\s*\1\b` (an `old ?? new` fallback collapses to `x ?? x`, silently deleting the fallback) and re-run the Step 1 catalog queries to confirm every swept DB-coupled string matches the live catalog.

## Step 4 — Verify with real evidence

- One LIVE invocation per DB-contract call site the change touched: upserts (conflict targets fail per-call, not at boot), RPC/procedure calls (param-name mismatches fail per-call), and at least one write per synced/dual column pair in each direction.
- Exercise every compat path with OLD inputs against the running server (old field names in query, JSON body, and multipart form) — the whole point of the shim is traffic you no longer generate yourself.
- Gates per deploy unit: the real typecheck (not a transpiler that skips types), the real client build, and the targeted test suites — plus a full-suite baseline diff against the exact pre-change commit when assertions were untouched.
- After deploy: soak, then re-verify the same live calls against production before any contract step.

## Step 5 — Contract and close

- Contract (drop old columns/views/shims/dual-fields) ONLY after: reference census returns zero, all deploy units are on migrated code, and the soak produced no old-name traffic errors.
- Finish the catalog: rename stale index/constraint/trigger names to match, or explicitly record the deferral.
- Record in the project's memory/docs: what changed, the pattern used, anything deferred, and any gotchas discovered — the next session must not rediscover them.

## Reference incident

reply-flow 2026-07-19 (`account_id → channel_id`, ~2000 refs): the table rename went cleanly via the view pattern; the column rename's sweeps broke 7 upserts (conflict targets vs un-renamed unique indexes), 5 procedure calls (param names vs un-renamed signatures), collapsed two legacy fallbacks into `x ?? x` (a customer could not reconnect WhatsApp), shipped a compat shim that was a silent no-op on the real framework (validated only by plain-object mocks), and a backfill's `set_updated_at` trigger irreversibly stamped 89k rows (recovered only by heuristic reconstruction). Every failure traces to a skipped step above; the process is the postmortem.
