---
name: code-quality
description: Pre/post-code checklist, bug-fix protocol (incl. regression tests), test discipline, problem-solving approach, browser verification
when_to_read: before AND after writing or fixing any code
sections:
  - Pre-Code Checklist
  - Bug Fix Protocol
  - Problem-Solving Approach
  - Post-Code Verification
  - Browser Verification
---
# Code Quality Checklist

> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

## Pre-Code Checklist

Before writing ANY new code, complete the following checks:

### 1. Read Project Context
- Check `PROJECT_SCOPE.md` (or equivalent) for tech stack, conventions, and structure
- If the project has plans/phases, read the relevant plan first — follow implementation order
- If the plan references a spec file, read those sections for exact field definitions, API contracts, and UX specs

### 2. Check Existing Code
- Search the codebase for existing implementations related to the task (use Grep/Glob)
- Read any files you plan to modify before editing them
- Identify existing patterns, utilities, and conventions already in use — follow them
- Check for existing types, interfaces, and validation schemas that cover your use case

### 3. Check Database Schema (if applicable)
- **Run the project's schema refresh command** (e.g., `py scripts/get_schema.py`) to get the CURRENT schema — do NOT rely on memory or cached knowledge
- Read the refreshed schema file and verify actual column names, types, and constraints for every table you plan to touch
- Confirm the tables, columns, and relationships you need already exist
- If schema changes are needed, create proper migrations — never modify the DB directly
- A global hook will ask for confirmation if schema is stale when executing migrations, but you must ALSO refresh schema **before writing migration code** — the hook only catches execution, not authoring

#### Loud-guard mandate (DB/Supabase reads)
**Never `if (!data) return/throw` on a DB/Supabase call without inspecting `error`.** PostgREST and the Supabase client do NOT throw on a bad query — a wrong/renamed column, a column selected from the wrong table after a refactor, or a broken relationship returns `{ data: null, error }`. If you branch on `!data` alone, the failure is otherwise invisible: no throw, no log, no alert — the code path just silently no-ops. This has caused two platform-wide outages in reply-flow (AI replies silently disabled for 43h the second time). For every DB call: destructure `error`, and when it's present surface it loudly (`console.error` + an alert/throw) BEFORE returning. A bare early-return on missing data is a latent silent outage.
- **Mocked-DB unit tests will NOT catch this** — they return whatever the mock is told to return, never the real PostgREST error shape.
- **The build (tsc) will NOT catch this** — TypeScript cannot see the live DB schema; a moved/renamed column is well-typed but wrong at runtime.

### 4. Check API Contracts (if applicable)
- Review existing API routes and endpoints before creating new ones
- Check existing query hooks — reuse before creating duplicates
- Verify request/response shapes match expectations

---

## Bug Fix Protocol

When fixing a bug, follow this process — do NOT skip straight to writing code:

### Before Fixing
1. **Understand the bug** — Read the error message, stack trace, or reproduction steps. State what is happening vs what should happen.
2. **Find the root cause** — Trace the code path. Don't guess — identify the exact line(s) causing the issue.
3. **Explain the cause** — Before writing any fix, describe the root cause in plain language. If you can't explain it, you don't understand it yet.

### After Fixing
1. **State what changed and why** — Explain the specific code change and how it addresses the root cause.
2. **Lock the fix with a regression test** — Where reasonably possible, add or extend an automated test that **fails before your fix and passes after**, so this exact bug cannot silently return. Confirm it both ways (it should fail on the old code, pass on the new). If a test is genuinely impractical (pure third-party integration, visual-only behavior), say so explicitly rather than skipping in silence.
3. **Describe how to verify** — Tell the user exactly how to confirm the fix works (steps to reproduce, what to check).
4. **Never mark a bug fix done** without stating the root cause, the verification method, and either the regression test you added or why one wasn't feasible.

---

## Problem-Solving Approach

**Prefer proper solutions over workarounds.** Always use the right tool for the job rather than hacking around limitations. If a proper approach requires installing a safe, standard tool or dependency (e.g., `psql`, a CLI utility, an npm package), install it rather than writing a fragile workaround. Workarounds accumulate tech debt — proper solutions don't.

When unsure how to implement something, follow this process strictly:

1. **Brainstorm options** — Come up with a few possible approaches before writing any code. Briefly list them and evaluate trade-offs.
2. **Pick the most likely** — Choose the approach that seems most likely to work and try it.
3. **If it fails, understand why** — Do NOT blindly try the next option. Diagnose the root cause of the failure first.
4. **Undo before retrying** — Revert all incorrect or partial changes from the failed attempt before trying a different approach. Do not leave broken or dead code behind from failed experiments.
5. **Try the next option** — Only after cleaning up, move on to the next most likely approach. Repeat steps 3-5 as needed.

Never stack failed attempts on top of each other. Each retry should start from a clean state.

---

## Post-Code Verification

After finishing ANY task or feature, verify the work before considering it done:

### 1. Functional Verification
- If UI: describe what to check visually or run the dev server to confirm it renders correctly
- If API: test with a sample request
- If DB changes: verify schema/migrations apply cleanly
- **Re-check the loud-guard mandate** (Pre-Code Checklist): for any DB/Supabase call you added or touched, confirm `error` is inspected and surfaced — never `if (!data) return/throw` alone. Mocked tests and tsc will both pass while it silently fails.
- **Silent failures in a critical always-on pipeline must be *detectable*.** For a path that runs unattended on every event (e.g. inbound→AI-reply, webhook→write, cron→send), don't rely on someone noticing the absence of output — ensure a health probe / canary / synthetic check exists so an outage alerts in **minutes, not days**. If no such monitor exists for the path you're touching, say so and propose adding one.

### 2. Acceptance Criteria
- If the project has plans with acceptance criteria, **re-read EVERY criterion**
- For each criterion, **state whether it is met** and cite the specific code or file that satisfies it
- If a criterion is not met, **do not mark the task done** — either implement it or explain why it was deferred
- If a criterion cannot be verified automatically, explicitly call it out

### 3. Plan Compliance
- If a plan or phase file exists for this work, re-read the task list
- Confirm every task is done
- If you deviated from the plan, explain why and what changed

### 4. Tests & Integration Check
- Verify the new code doesn't break existing functionality
- Check that imports, exports, and cross-module references are correct
- **Run the existing tests** for the affected area — all must pass before the work is done
- **Add a test for new behavior** where reasonably possible, matched to the right *level*: a **unit/integration test** for logic; if the change touches **multi-tenant data, a privileged/`SECURITY DEFINER` function, an access/RLS policy, or a webhook**, also add an **isolation/auth test** asserting another tenant (or an unsigned caller) is *blocked*; reserve slow **end-to-end** tests for a few critical user-facing flows. If a test is genuinely impractical, say why instead of skipping silently.
- **A failing test is an alarm, not a chore.** If a test fails because you *accidentally* broke something, fix the **code** — never edit the test to make it pass. Change a test only when the *intended* behavior deliberately changed, and say so out loud when you do.

### 5. Security Review
Check the code you wrote for these issues:

| Check | Hook-enforced? | Details |
|-------|---------------|---------|
| No hardcoded secrets | **Yes** (Stripe keys, AWS keys) | Hooks catch `sk_live_*`, `sk_test_*`, `AKIA*`. You must also check for other API keys, passwords, and tokens. |
| No `eval()` | **Yes** | Hook blocks eval() in code files |
| No `debugger` statements | **Yes** | Hook blocks debugger in code files |
| No `innerHTML` without sanitization | No | If you must set innerHTML, use DOMPurify or equivalent |
| No SQL string concatenation | No | Use parameterized queries, never string interpolation |
| User input validated at boundaries | No | Validate/sanitize at API boundaries and form inputs |
| No sensitive data in logs/errors | No | Never log passwords, tokens, PII, or full credit card numbers |

### 6. Summarize Work
See the canonical completion-summary format in `multi-agent-coordination.md` → "Summary on phase or plan completion" (completed checklist → What was done → Where to check → Verification done → What's next). For a SQL migration, include a clickable link and remind the user to run it.

### 7. Build Check
- Run the relevant build/typecheck command to confirm there are no compile or type errors
- Fix any errors before moving on

### 8. Lint & Format
- Run linting to catch code quality issues
- Ensure no new warnings or errors are introduced

> **Note:** If your tool has hooks configured (e.g., Claude Code):
> - Steps 7-8 (build/lint) are handled automatically by Stop hooks.
> - A Stop hook also scans `git diff` for debug code (console.log, debugger). If it warns, remove the debug code before finishing.
> - Security items marked "Hook-enforced" in step 5 are blocked automatically — but items marked "No" are YOUR responsibility.
> - If any hook reports errors, fix them before considering the task done.

---

## Browser Verification

After completing any UI, front-end, or runtime-affecting change (component edits, page changes, styling, layout, copy that affects rendering, marketing/landing files, anything visible in the browser or measurable in DevTools), end the turn with **one short question** offering the most relevant verification for what changed. Keep it to a single sentence.

**Route the offer by what changed:**

| Change touched | Offer |
|---|---|
| Landing / marketing pages | *"Want me to run Lighthouse on it?"* (mobile profile) |
| Inbox, realtime subscriptions, long-lived state surfaces | *"Want me to heap-diff it?"* (snapshot → drive → snapshot, look for retained DOM/listeners) |
| Webhook handler or fetch-heavy code path | *"Want me to capture the network trace?"* (source-mapped initiators) |
| Anything else with visible UI | *"Want me to verify it in Playwright?"* |

If the change spans categories, offer the higher-leverage one (perf/memory > visual snapshot). Do not stack multiple offers in one turn.

If the user says **yes**, run the chosen verification end-to-end without asking again — full tool sequence, console + network checks where applicable, resize for mobile if relevant, then report what you saw. **Do not stop mid-flow to re-confirm individual tool calls.** The user has auto-approved Playwright and Chrome DevTools tools in `~/.claude/settings.json` (via the `mcp__*` wildcard).

If the user says **no** (or doesn't reply), don't bring it up again for that change.

**Skip the offer when** the change is purely backend/server-only, scripts, configs, docs, plans, tests, or anything with no visual or runtime-behavior effect.

A new visible/runtime change resets the offer — each one gets its own one-time ask.

### Tool boundary

- **Playwright** — *"does it look right / does the flow work?"* Use for visual snapshots, scripted user flows, layout regression checks.
- **Chrome DevTools MCP** — *"why is it slow / why is it leaking / why did that request fail?"* Use for Lighthouse, performance traces, heap snapshots, network panel with source-mapped initiators, source-mapped console errors.

When in doubt: visual question → Playwright, *why* question → Chrome DevTools.

### Browser Artifact Folder (MANDATORY)

All screenshots, traces, snapshots, and other browser artifacts MUST be written to `.playwright-mcp/` at the current project root (kept under that name for historical reasons; the convention covers Chrome DevTools artifacts too).

```
browser_take_screenshot({ filename: ".playwright-mcp/landing-hero.png" })
```

Equivalent Chrome DevTools tools accept similar path arguments — write all outputs under `.playwright-mcp/`. Without an explicit path, MCP servers fall back to writing files to whatever the agent's CWD is — typically the project root, which clutters the repo. `.playwright-mcp/` is gitignored on a per-project basis. Old PNGs in that folder are auto-purged by the `stop_cleanup_playwright_screenshots.py` hook (older than 10 minutes get removed each Stop event). Note: that hook is currently PNG-only — `.json` perf traces and `.heapsnapshot` files won't be auto-cleaned yet, so prune those manually if they accumulate.

If the project's `.gitignore` doesn't yet include `.playwright-mcp/`, add it.
