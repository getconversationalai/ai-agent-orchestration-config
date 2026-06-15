# Global Instructions — Router

This file is your index, loaded every session. It holds (1) **Always-On Rules** that apply to every turn, and (2) a **Rule Index** telling you which detail doc to read before a given kind of task. Everything else lives in `~/.ai-instructions/` — read those docs on demand; never preload them.

## Navigation protocol
Each `~/.ai-instructions/` doc opens with YAML frontmatter listing its `sections`. To use a doc: read ONLY the frontmatter + section list, then `grep` the `##` heading you need and read just that slice (Read with offset/limit). Do NOT read whole docs.

## Multi-tool setup
This user runs Claude Code, Gemini CLI, and Codex. Each reads its own files; keep them in sync.

| Tool | Global instructions | Global settings | Hooks |
|------|--------------------|-----------------|-------|
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/settings.json` | yes |
| Gemini CLI | `~/.gemini/GEMINI.md` | `~/.gemini/settings.json` | yes |
| Codex | `~/.codex/AGENTS.md` | `~/.codex/config.toml` / `hooks.json` | partial |

When you edit any of these global files (this router or a `~/.ai-instructions/` doc), ASK whether to mirror the change to the other tools' files. Never assume.

These local files are the source of truth. They are backed up to the private GitHub repo **`getconversationalai/ai-agent-orchestration-config`**, which can go stale until synced. Sync flow: edit the live files → run `capture.ps1` → commit → push.

## Always-on rules (apply every turn — never skip)
- **Action Gate:** A question (ends in "?", or "how/what/why/can we/should we…") is NOT permission to act. Answer only; wait for an explicit action verb (do it, build, fix, implement, create).
- **Todo discipline:** Any actionable multi-step turn → maintain a live TodoWrite list; exactly one item `in_progress`; mark each item `completed` the instant it's done via its OWN TodoWrite call (never batch) so the full list visibly re-renders with the tick; append new asks rather than dropping current work.
- **Before starting any new work:** `git fetch` the base (`main`) and start from the latest — never branch, plan, or build off a stale base. → `git-safety.md`
- **After writing a spec or plan file:** post its key points in chat (goal, the handful of decisions that matter, what's next) so the user can act without opening the document.
- **Plans are intent, not transcription:** in any implementation plan, file paths / line numbers / code snippets are illustrative *as-of-writing* — at execution, locate targets by content/symbol and re-verify signatures; never edit by absolute line number or paste a plan's snippet unchecked. Before executing a plan, run the **plan-review gate**: review the plan's OWN code for tenant-isolation / hardcoded-URL / swallowed-error / `ON CONFLICT`-on-partial-index defects (full adversarial reviewer subagent when it touches auth, tenant data, URLs, migrations, money, or webhooks); don't start while a Critical/High plan-finding is open. → `planning.md`
- **Think out loud & plan plainly:** Show reasoning. Plans must be understandable to a non-technical stakeholder and must call out file changes, DB/migration changes, and breaking changes.
- **Shell:** Never `cd` into a subdir — use `--prefix`/`--project`/`--dir`/absolute paths. PowerShell syntax on Windows.
- **Code changes happen in a worktree** — never edit code in the main working tree. For a quick single-concern fix, reuse the **scratch worktree** (`py ~/.ai-instructions/tools/scratch_worktree.py fix/<scope>`) instead of spinning up a fresh one — its `node_modules` persists, so no multi-minute install/teardown. → `worktree-operations.md`
- **Propagating changes** (rename/refactor/schema/signature, or moving a data field between JSON `metadata` and a column / renaming an API field) use expand-contract — never one breaking step; for cross-layer data fields, grep every layer (build green ≠ safe — dynamic reads fail silently) and keep dual-writing until zero readers remain on the old location. → `worktree-operations.md`
- **Git:** Never push to main/master without explicit approval; always `git fetch` the base immediately before any merge/update-ref/push to it. → `git-safety.md`
- **Database:** SQL writes require a dedicated standalone confirmation message; the live DB is the source of truth, not migration files. → `supabase-operations.md`
- **Problem-solving:** brainstorm options → try the likeliest → diagnose failures → undo before retrying. Never stack failed attempts. → `code-quality.md`
- **Diagnose & fix out loud:** Before diagnosing anything, state in chat the steps you'll take to reach a diagnosis, and post each finding in chat as you discover it. Before fixing a bug/issue, write in chat what the bug/issue is and your plan for fixing it; after fixing, state in chat what you fixed and how. → `code-quality.md`
- **Browser verification:** after a UI/runtime change, end with ONE short offer to verify (Playwright / Lighthouse / heap-diff / network). → `code-quality.md`
- **Coordination & memory:** read `PROJECT_SCOPE.md` / `MEMORY.md` / `WORKBOARD.md` at start; update `MEMORY.md` + `WORKBOARD.md` after significant work. → `project-setup.md`, `multi-agent-coordination.md`
- **Finishing a phase / plan / feature:** the completing reply MUST be these five sections, in THIS order, with THESE exact headings — (1) **List of What Was Done** (plain-English checklist, every item ✓ — an outcome a non-technical reader can do/see, NOT a copy of your todo list: no commit hashes, file/function names, "Task N" labels, test counts, or build/`tsc` output — those go under Verification); (2) **Summary Of What Was Done** (plain-English paragraph); (3) **Where To Check** (an in-app walkthrough the user can run — nav path + what to click + what they should see, NOT source-file paths; or an explicit "back-end only — here's how to confirm it"); (4) **Verification** (build/typecheck/lint/tests, for code work); (5) **What's Next** (or "Plan complete."). Full format + example → `multi-agent-coordination.md`.

## Rule index — read the doc BEFORE the task
| When you're about to… | Read (`~/.ai-instructions/`) |
|---|---|
| change any code; create/merge/clean a worktree; rename/refactor | `worktree-operations.md` |
| run parallel agents; coordinate via WORKBOARD; track progress; finish a phase/plan | `multi-agent-coordination.md` |
| write, review, or execute an implementation plan | `planning.md` |
| write or fix code (pre/post checklist, bug protocol, tests/regression tests, browser verify) | `code-quality.md` |
| push or merge git | `git-safety.md` |
| do any DB/SQL work | `supabase-operations.md` |
| start, bootstrap, or onboard a project | `project-setup.md` |
| understand or debug hooks | `hooks-reference.md` |
