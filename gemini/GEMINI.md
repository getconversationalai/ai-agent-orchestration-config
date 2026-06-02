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

## Always-on rules (apply every turn — never skip)
- **Action Gate:** A question (ends in "?", or "how/what/why/can we/should we…") is NOT permission to act. Answer only; wait for an explicit action verb (do it, build, fix, implement, create).
- **Todo discipline:** Any actionable multi-step turn → maintain a live TodoWrite list; exactly one item `in_progress`; mark done immediately; append new asks rather than dropping current work.
- **Think out loud & plan plainly:** Show reasoning. Plans must be understandable to a non-technical stakeholder and must call out file changes, DB/migration changes, and breaking changes.
- **Shell:** Never `cd` into a subdir — use `--prefix`/`--project`/`--dir`/absolute paths. PowerShell syntax on Windows.
- **Code changes happen in a worktree** — never edit code in the main working tree. → `worktree-operations.md`
- **Propagating changes** (rename/refactor/schema/signature) use expand-contract — never one breaking step. → `worktree-operations.md`
- **Git:** Never push to main/master without explicit approval; always `git fetch` the base immediately before any merge/update-ref/push to it. → `git-safety.md`
- **Database:** SQL writes require a dedicated standalone confirmation message; the live DB is the source of truth, not migration files. → `supabase-operations.md`
- **Problem-solving:** brainstorm options → try the likeliest → diagnose failures → undo before retrying. Never stack failed attempts. → `code-quality.md`
- **Browser verification:** after a UI/runtime change, end with ONE short offer to verify (Playwright / Lighthouse / heap-diff / network). → `code-quality.md`
- **Coordination & memory:** read `PROJECT_SCOPE.md` / `MEMORY.md` / `WORKBOARD.md` at start; update `MEMORY.md` + `WORKBOARD.md` after significant work. → `project-setup.md`, `multi-agent-coordination.md`

## Rule index — read the doc BEFORE the task
| When you're about to… | Read (`~/.ai-instructions/`) |
|---|---|
| change any code; create/merge/clean a worktree; rename/refactor | `worktree-operations.md` |
| run parallel agents; coordinate via WORKBOARD; track progress; finish a phase/plan | `multi-agent-coordination.md` |
| write or fix code (pre/post checklist, bug protocol, browser verify) | `code-quality.md` |
| push or merge git | `git-safety.md` |
| do any DB/SQL work | `supabase-operations.md` |
| start, bootstrap, or onboard a project | `project-setup.md` |
| understand or debug hooks | `hooks-reference.md` |
