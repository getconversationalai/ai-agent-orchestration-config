---
name: hooks-reference
description: Descriptive reference of global and project-level hooks (what blocks/warns/reminds)
when_to_read: when asked about hooks, when a hook fires unexpectedly, or when configuring project hooks
sections:
  - Global hooks
  - Project-level hooks
---
# Hooks Reference
> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

## Global hooks

### Global Hooks (apply to ALL projects via `~/.claude/settings.json`)

**PreToolUse — Blocks and confirmations:**

| Hook | Matcher | What it does |
|------|---------|-------------|
| `pretooluse_bash.py` | Bash | **Blocks:** `python`/`python3` (use `py`), `git push` to main/master, `git add` on sensitive files, ALL `git worktree remove` (must use cleanup script), ALL `rm -rf` on worktree paths including node_modules (must use cleanup script), merges in main working tree, ANY mutating `git stash` (bare/push/pop/apply/drop/clear) in a repo with linked worktrees — shared stash stack; `stash list`/`show` still allowed. **Asks:** `cd` without `&&`, `git push` to main, `git merge`, `git update-ref` to main, `git branch -d` on unpushed branches, `git stash drop`/`clear` in single-worktree repos, SQL execution. Also checks WORKBOARD.md for active agents before merges to main. |
| `pretooluse_bash_confirm.py` | Bash | Double-check confirmation for high-risk shared-state operations only: SQL execution, git push to main, merge to main/dev, update-ref to main, rebase, cherry-pick, stash drop, tag delete, remote changes. Feature branch operations (push, merge within worktrees) are single-confirm only. |
| `pretooluse_code.py` | Edit, Write | Blocks hardcoded Stripe secret keys, AWS access keys (`AKIA...`), `eval()`, `debugger` statements. |
| `pretooluse_main_worktree_guard.py` | Edit, Write | **Denies** edits to code files in the main working tree (all code changes must happen in worktrees), returning a worktree-migration playbook as the deny reason. Allows non-code files (WORKBOARD.md, MEMORY.md, plans), files under the OS temp dir (session scratchpads), the HOME dotfiles repo (global config), and any target outside the CWD's repo. |

**PostToolUse — Reminders (printed after tool completes):**
| Hook | What it does |
|------|-------------|
| `posttooluse_write.py` | After writing a SQL migration file, reminds to refresh schema cache |
| `posttooluse_bash.py` | After `git worktree add`, reminds to install dependencies (`npm install`) |

**Stop — Warnings (printed after every response):**
- **Branch guard** — Warns if you have uncommitted code changes directly on main/master. Create a feature branch.
- **WORKBOARD check** — Warns if code files changed but no `WORKBOARD.md` exists. Reminds to create one for multi-agent coordination.
- **Debug code scan** — Scans `git diff` for `console.log` and `debugger` left in changed lines. Warns if found.

**SubagentStop — Warnings (printed after each subagent completes):**
- **Worktree check** — Detects worktrees not referenced as active/waiting in `WORKBOARD.md` and suggests cleanup. Skips worktrees that have active entries in WORKBOARD.md.
- **WORKBOARD reminder** — Reminds to move completed subagent work to the Completed section.

## Project-level hooks

### Project-Level Hooks (set per-project in `.claude/settings.json` or `.claude/settings.local.json`)

These vary by project and must be configured separately:
- **Build/typecheck** — Should run on Stop. Command depends on the project (e.g., `npx tsc --noEmit`, `npm run build`).
- **Lint** — Should run on Stop. Command depends on the project (e.g., `npm run lint`).
- **Hub file guard** — Optional SubagentStop hook that checks if a subagent modified hub files listed in `PROJECT_SCOPE.md`.

If a project has no project-level hooks configured, you MUST run build and lint checks manually after writing code (see `~/.ai-instructions/code-quality.md`).
