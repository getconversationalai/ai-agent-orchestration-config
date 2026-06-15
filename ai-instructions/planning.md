---
name: planning
description: How to write implementation plans (precision tiers — intent is authoritative, locations/code are illustrative) and the plan-review gate run before execution
when_to_read: before writing an implementation plan, AND before executing one
sections:
  - Precision Tiers
  - Authoring Rules
  - Plan-Review Gate
  - Reviewer Checklist
---
# Implementation Planning

> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

> This doc OVERRIDES the superpowers `writing-plans` / `subagent-driven-development` skills where they conflict (user instructions win). The skills' "no vague placeholders, show real code, frequent commits, TDD" discipline still holds — this only changes how *authoritative* exact paths/line-numbers/code are, and adds a mandatory review of the plan itself.

## Precision Tiers

A plan has two kinds of content. Be exact about the first; treat the second as disposable.

**Authoritative — state precisely, the executor must honor:**
- The goal and the behavioral contract (what's true when done).
- Interfaces / function signatures / data shapes / API contracts.
- Invariants — especially tenant isolation (`company_id` scoping), security, and error-surfacing.
- The test assertions and the verification gates (build/typecheck/test commands + expected results).

**Illustrative — "as of writing," MUST be re-verified at execution:**
- Exact file paths, line numbers, and line ranges. **Code drifts; line numbers rot.** Plans say *what to find* and *how to find it* (by symbol/content), never "edit line 412."
- Code snippets. A snippet is a **reference implementation, not a transcription target.** The executor re-derives it against the live code: confirm the real symbol names, signatures, imports, and that it compiles — adapt anything that has drifted. Never paste a plan's snippet unchecked, and never assume the plan's code is correct (see the Reviewer Checklist — bugs get authored *into* plans).

Rule of thumb: if a detail would silently break when someone renames a file or refactors a function next week, it's illustrative — mark it so and tell the executor to re-locate/re-verify.

## Authoring Rules

- Lead each task with the **authoritative** part (contract + invariants + test), then provide illustrative code/paths under a "locate by content; re-verify" instruction.
- For every file a task touches, instruct: *find it by content/symbol (grep/Glob), read it, confirm the snippet still matches the current API, then edit.* Do not embed absolute line numbers as edit anchors.
- Keep the skills' bans on genuinely vague placeholders ("add error handling", "TBD"): illustrative ≠ vague. Show the intended code — just don't treat it as gospel.
- Do not over-specify the unknowable: enum values, column names, and signatures that the executor will read from the live schema/code should be stated as "confirm against live" rather than hard-asserted from memory.

## Plan-Review Gate

**Before executing ANY implementation plan, run a plan-review pass.** A plan is reviewed like code — because bugs get written *into* plans and then faithfully copied (real cases: a hardcoded production host and a missing `company_id` filter both shipped verbatim from plan snippets).

- **Lightweight (every plan):** the plan's author re-reads it against the Reviewer Checklist below and fixes findings inline.
- **Full adversarial (mandatory when the plan touches auth, tenant data, outbound URLs, DB migrations, money, or webhooks):** dispatch a **fresh reviewer subagent** whose only job is to find defects in the plan's own snippets and assumptions. It does not rubber-stamp.
- **Gate:** do not start execution while any Critical/High plan-finding is unresolved. Fixing the plan before coding is far cheaper than fixing shipped code.

This is in addition to (not a replacement for) reviewing the resulting code after execution.

## Reviewer Checklist

Run each item against the plan's OWN snippets and assumptions:

- **Tenant isolation:** does every DB read/write snippet scope `.eq('company_id', req.companyId)` (or scope through a verified parent for `company_id`-less tables)? Is any company/user id read from `req.body`/`query`/`params` instead of `requireAuth`?
- **Outbound URLs:** any hardcoded host literal? URLs must be built from validated env (frontend host vs API host), never a baked-in domain.
- **Error surfacing:** any DB/client call whose `.error` is ignored — i.e. a path that could fail silently (HTTP 200 with 0 rows, swallowed exception)? Errors must be checked and surfaced.
- **DB constraints:** any `ON CONFLICT`/upsert that could target a *partial* unique index (illegal — use pre-filter + plain insert)? Any `DROP+ADD CHECK`/constraint migration that could clobber values, or a schema change with readers not re-grepped (expand-contract)?
- **Route/middleware:** public/unauthenticated routes mounted before blanket auth? CORS allows the expected origins?
- **Stale references:** are file paths/line numbers/code marked illustrative, with a "locate by content + re-verify signatures" instruction — not absolute-line edits?
- **Build/verify gates:** does the plan name the *real* gates (the typechecking build, the live/integration check), not just a bundler that skips type errors? Is there a live/runtime verification step for anything mocked-only tests can't see (route mounting, CORS, real DB constraint semantics, deployed host resolution)?
- **Missing call sites:** if the plan adds a helper, does it enumerate EVERY place that must call it (a unit test of a helper can't catch an un-wired call site)?
