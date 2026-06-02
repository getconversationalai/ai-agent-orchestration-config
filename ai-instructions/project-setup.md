---
name: project-setup
description: Project context discovery, bootstrapping new projects, instruction-files map, memory updates
when_to_read: when starting work on a project, bootstrapping a new one, or after completing significant work
sections:
  - Project knowledge files
  - Plans and status files
  - Coordination and memory files
  - How the system works
  - Project bootstrapping
  - Instruction files map
  - Memory updates
  - Database setup on a new project
---
# Project Setup
> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

## Project knowledge files

When starting work on any project, look for these standard files to understand the project before writing code:

| File | What It Is | When to Read |
|------|-----------|-------------|
| `PROJECT_SCOPE.md` | Tech stack, architecture, conventions, hub files, DB tables | **Always** — read first before any work |
| `README.md` | Project overview, setup instructions | First time working on a project |
| `Product-And-Tech-Spec.md` (or similar) | Requirements, API contracts, UX specs | When you need exact field definitions or API shapes |

## Plans and status files

| File | What It Is | When to Read |
|------|-----------|-------------|
| `plans/INDEX.md` | Master index of all phases — status, scope, dependencies | **Before starting any phase** — check status and dependencies |
| `plans/phase-*.md` | Detailed plan for a specific phase — tasks, acceptance criteria | When working on that specific phase |

**Plans MUST be created in the project's `plans/` directory.** Never save plans to tool-specific directories outside the project (e.g., `~/.cursor/plans/`, `~/.claude/plans/`). If you find existing plans in those locations, migrate them into the project's `plans/` directory.

## Coordination and memory files

| File | What It Is | When to Read/Write |
|------|-----------|-------------------|
| `WORKBOARD.md` | Live coordination board — who is working on what right now | **Read before starting work** (check for conflicts). **Write when you start and finish** work. |
| `MEMORY.md` | Accumulated project knowledge — what's been built, gotchas, architecture notes | **Read at start** of every conversation. **Write after** completing significant work. |

## How the system works
1. **Before coding:** Read `PROJECT_SCOPE.md` → check `plans/INDEX.md` for dependencies → read the relevant `plans/phase-*.md` → check `WORKBOARD.md` for conflicts → read `MEMORY.md` for context
2. **While coding:** Follow `~/.ai-instructions/code-quality.md` checklist. If running parallel agents, follow `~/.ai-instructions/parallel-agents.md`.
3. **After coding:** Update `WORKBOARD.md` (mark done). Update `MEMORY.md` with new knowledge. Re-read acceptance criteria from the phase plan.

## Project bootstrapping

When starting work on any project, check if the project-level files exist. If ANY are missing, create them from the templates in `~/.ai-instructions/templates/`:

| Check for | Template source | Git-tracked? |
|-----------|----------------|-------------|
| `PROJECT_SCOPE.md` | `~/.ai-instructions/templates/PROJECT_SCOPE.md` | Yes |
| `plans/INDEX.md` | `~/.ai-instructions/templates/plans/INDEX.md` | Yes |
| `MEMORY.md` | `~/.ai-instructions/templates/MEMORY.md` | No — add to `.gitignore` |
| `WORKBOARD.md` | `~/.ai-instructions/templates/WORKBOARD.md` | No — add to `.gitignore` |

- Copy the template, replace `[Project Name]` with the actual project name, and fill in what you can from reading the codebase (tech stack, folder structure, etc.).
- If `.gitignore` exists but doesn't include `MEMORY.md` and `WORKBOARD.md`, add them.
- Tell the user what you created so they can review it.
- Do NOT overwrite files that already exist.
- **Project-level hooks**: If no `.claude/settings.json` or `.claude/settings.local.json` exists with hooks, remind the user that build/typecheck and lint will not run automatically. See the Hooks section below for what project-level hooks should be configured.
- **npm workspaces `.npmrc`**: If the project's root `package.json` has a `"workspaces"` field (i.e. it's an npm workspaces monorepo), check whether a root `.npmrc` exists with `workspaces=true` and `include-workspace-root=true`. If missing, propose adding it as part of bootstrapping. These two settings make `npm install` from inside any workspace subdirectory resolve to the workspace root, preventing the sub-lockfile pollution that causes arborist crashes (see "Single Root Lockfile" rules in the project's own CLAUDE.md if it has one). Caveat: `workspaces=true` makes `npm config get` and `npm config list` fail with `ENOWORKSPACES`; users can pass `--no-workspaces` for those one-off invocations. Normal `npm install`, `npm run`, `npm ci`, dev/build/start are unaffected.

## Instruction files map

Read these files BEFORE starting the relevant type of work:

| File | When to Read |
|------|-------------|
| `~/.ai-instructions/code-quality.md` | Before AND after writing any code |
| `~/.ai-instructions/parallel-agents.md` | Before launching parallel sub-agents (additional rules beyond global worktree isolation) |
| `~/.ai-instructions/supabase-operations.md` | Before ANY database/SQL work (from any repo) |

## Memory updates

After completing any phase, plan, or significant task, update the project's `MEMORY.md` (in the project root) with:
- Updated project status (mark the phase/plan as complete)
- New DB tables, API routes, or queues added
- Key file paths and architecture decisions
- Any gotchas or lessons learned

## Database setup on a new project

When bootstrapping a new project, decide its Supabase access method and record it in the project's md files (CLAUDE.md / AGENTS.md / GEMINI.md). See `~/.ai-instructions/supabase-operations.md` for the suggested default (psql + per-project `SUPABASE_DB_URL`). Existing projects keep their own documented method.
