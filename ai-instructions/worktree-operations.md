---
name: worktree-operations
description: Worktree lifecycle for all code changes — create, merge (2-level), Windows-safe cleanup, .git recovery, expand-contract, rerere
when_to_read: before any code change, worktree create/merge/cleanup, or any rename/refactor/schema/signature change
sections:
  - Why worktrees
  - Create a worktree
  - Scratch worktree (quick fixes)
  - Naming convention
  - Work inside the worktree
  - Merge back (two-level hierarchy)
  - Cleanup (Windows-safe)
  - Stale worktree prevention
  - Windows safety
  - Propagating changes (expand-contract)
  - Enable git rerere
---
# Worktree Operations
> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

**ALL code changes — features, bug fixes, refactors, anything — MUST happen in a separate git worktree.** Never modify files directly in the main working tree. This prevents conflicts when multiple agents or conversations work on the same project simultaneously.

## Why worktrees
The main working tree may have uncommitted changes from another agent, another conversation, or the user's own in-progress work. Working directly in it risks overwriting those changes or accidentally committing to the wrong branch. Worktrees provide physical directory isolation while sharing the same `.git` object store — cheap to create, impossible to accidentally cross-contaminate.

## Create a worktree

### Before Starting Work
- **Identify the base branch** — Use `dev` if the project has one, otherwise `main`. Check with: `git branch --list dev main`.
- **Ensure the base branch is up to date** — `git fetch origin && git merge origin/main` (or `origin/dev`). Do this in the main working tree.
- **Check `WORKBOARD.md`** for conflicts with other active work (unchanged from Multi-Agent Coordination).

**CRITICAL: Worktrees MUST be placed OUTSIDE the project directory tree** — never inside it (e.g., never `.worktrees/` inside the project root). This reduces path depth and avoids some symlink scenarios. However, placing worktrees outside the project does NOT fully prevent NTFS junction issues — npm workspace projects create junctions in `node_modules` that point back to the worktree root regardless of where the worktree is located. See the Cleanup and Windows Safety sections for how to handle this safely.

- **Worktree path**: Always use `../.worktrees/<project-name>/<branch-name>/` relative to the project root. For a project at `c:/dev/reply-flow`, worktrees go in `c:/dev/.worktrees/reply-flow/<branch-name>/`.
- **Claude Code main agent**: Use `EnterWorktree` tool or `git worktree add ../. worktrees/<project>/<branch> -b <branch> <base>` to create an isolated worktree with a feature branch off the base branch.
- **Claude Code subagents**: Use `isolation: "worktree"` when launching via the Agent tool. The sub-agent's worktree branches off the **main agent's feature branch**, not off `main`/`dev` directly.
- **Gemini CLI / Codex**: Use `git worktree add ../.worktrees/<project>/<branch-name> -b <branch-name> <base-branch>` to create the worktree manually, then work inside it.
- **Install dependencies immediately after creating a worktree**: Worktrees are bare copies of the source tree — they do NOT share `node_modules` with the main working tree. After `git worktree add`, install dependencies before building or typechecking:
  ```bash
  npm install --prefix <worktree-path>
  ```
  For monorepos or subdirectory-based servers, install in each package directory:
  ```bash
  npm --prefix <worktree-path>/server install
  npm --prefix <worktree-path>/client install
  ```
  **Skipping this step will cause hundreds of "Cannot find module" TypeScript errors.**

## Scratch worktree (quick fixes)
**Default to the scratch worktree for any single-concern task** (not just tiny fixes) — reserve a fresh per-branch worktree for genuinely long-running or parallel multi-agent work. For single-concern work, don't pay the full cost of a fresh worktree — `git worktree add` checks out the whole tree, a fresh `node_modules` install takes minutes, and tearing it down afterward is slow on Windows. Instead reuse the **scratch worktree**: one long-lived worktree per repo at `../.worktrees/<project>/_scratch` whose `node_modules` persists between uses. It is never deleted (`worktree_cleanup.py` skips it), so there is no create / install / teardown overhead for the common case.

**When to use it**
- ✅ Quick single-concern fixes you'll finish and merge in one pass.
- ❌ NOT feature-sized work, anything long-running, or parallel multi-agent work — those still get a dedicated per-branch worktree. The scratch worktree holds one branch at a time, so it is inherently serial.

**Use it (one command, run from anywhere in the repo):**
```bash
py ~/.ai-instructions/tools/scratch_worktree.py fix/<scope>
# branch off dev instead of main:
py ~/.ai-instructions/tools/scratch_worktree.py fix/<scope> --base dev
```
This fetches `origin/<base>`, resets the scratch tree to a fresh `fix/<scope>` branch off the latest `origin/<base>` (discarding the previous fix's leftovers), then runs `npm install` — **skipped automatically when `package-lock.json` is unchanged**, so repeat resets are near-instant. It prints the scratch path to edit in. The first run creates the worktree (one-time full install).

Then: edit in the scratch worktree → build/verify → commit → push to `main` (or open a PR) → walk away. The next quick fix just re-runs the command with a new branch name. **Never delete the scratch worktree** — recycle it by re-running the command.

## Naming convention
- **Main agent branches**: `feat/<scope>`, `fix/<scope>`, `refactor/<scope>`. Name must be specific enough to be globally unique (e.g., `feat/voice-waveform-visualizer` not `feat/ui-update`).
- **Sub-agent branches**: `<parent-branch>/<sub-scope>` — e.g., if the main agent's branch is `feat/voice-notes`, a sub-agent working on the waveform UI would use `feat/voice-notes/waveform-ui`. This makes the hierarchy visible in branch names.
- **Before creating any worktree**, verify the branch name is not taken: `git branch --list <name>` and `git worktree list`. If taken, make the name more specific.

## Work inside the worktree
- All file edits, builds, and tests happen inside the worktree directory.
- **Do NOT touch the main working tree** while inside a worktree — no edits, no checkouts, no stashing.
- **Do NOT modify files outside your feature scope** — especially hub/shared files unless you are certain no other agent is working on them.
- Register your work in `WORKBOARD.md` (in the main working tree / project root) before starting.
- **Push to origin after your first commit** and after each subsequent commit:
  ```bash
  git -C <worktree-path> push -u origin <feature-branch>
  ```
  This creates a remote backup immediately. If `.git` gets corrupted during cleanup or by another agent, all committed work survives on the remote. Feature branch pushes do NOT require user approval. **Unpushed local branches are unrecoverable if `.git` is destroyed — this has happened.**

## Merge back (two-level hierarchy)

There are two distinct merge levels. Do NOT confuse them:

**Level 1: Sub-agent → Main agent's feature branch (automatic, no user permission needed)**
- When a sub-agent finishes its work, its branch merges into the **parent main agent's feature branch** — NOT into `main`/`dev`.
- The main agent performs this merge inside its own worktree:
  1. `git fetch . <sub-agent-branch>` (fetch the sub-agent's branch into the worktree)
  2. `git merge <sub-agent-branch> --no-ff`
  3. If there are conflicts between sub-agents, the main agent resolves them (or asks the user).
  4. Run build/typecheck after each sub-agent merge.
- After merging, clean up: `py ~/.ai-instructions/tools/worktree_cleanup.py <sub-agent-worktree-path>`.

**Level 2: Main agent's feature branch → `main`/`dev` (REQUIRES USER PERMISSION)**
- Only after ALL sub-agents are merged and the feature branch is complete, tested, and passing.
- **Never merge without explicit user approval.** Ask: *"All work on `<feature-branch>` is complete and tested. Can I merge it into `<base-branch>`?"*
- **Merge happens INSIDE the agent's own worktree** — never in the main working tree. This prevents multiple agents from competing for the main working tree during merges.
- Merge strategy:
  1. **Pull the base branch into your worktree**: `git fetch origin <base-branch>`
  2. **Merge the base branch into your feature branch**: `git merge origin/<base-branch>` (inside your worktree)
  3. If there are conflicts, resolve them here in the worktree — this is your code, you understand the intent. For contradictory conflicts, **stop and ask the user**.
  4. **Run a full build/typecheck** in the worktree to verify everything works with the latest base branch changes incorporated.
  5. **Update the base branch ref with `update-ref`**: From inside the worktree, run:
     ```bash
     git update-ref refs/heads/<base-branch> HEAD
     ```
     This atomically moves the base branch pointer to your merged commit. It works even when the base branch is checked out in the main working tree.
     Then sync the main working tree's files to match (both index AND working tree):
     ```bash
     git -C <main-working-tree-path> checkout -f
     ```
  6. If `update-ref` fails or the base branch has moved (another agent merged between steps 1 and 5), go back to step 1 and repeat — pull the new base, merge again, then update-ref.
  7. **NEVER use `git push . HEAD:<base-branch>`** — this fails when the target branch is checked out in another worktree. **NEVER fall back to merging in the main working tree** — always use `update-ref` from the worktree.
- After a successful merge, clean up: `py ~/.ai-instructions/tools/worktree_cleanup.py <worktree-path>`.

**Safety rules for both levels:**
- **Never force-push, rebase over, or reset other branches** — other worktrees/branches may have in-progress work.
- **Sub-agents NEVER merge directly into `main`/`dev`** — they always go through their parent's feature branch.
- **No agent ever needs to `git checkout` in the main working tree to merge** — all merges happen inside worktrees, and the base branch is updated via fast-forward ref update.

## Cleanup (Windows-safe)

**ALWAYS use the cleanup script. NEVER run `git worktree remove` directly.**

```bash
py ~/.ai-instructions/tools/worktree_cleanup.py <worktree-path>

# Or to clean all worktrees whose branches are already merged:
py ~/.ai-instructions/tools/worktree_cleanup.py --all-merged
```

The script handles the entire cleanup sequence safely:
1. Verifies `.git` exists before starting
2. Checks WORKBOARD.md for active entries (refuses to remove active worktrees)
3. Verifies the branch is pushed to remote (refuses if unpushed work could be lost)
4. Scans the entire worktree for ALL NTFS junctions/symlinks
5. Deletes every junction using `cmd /c rd /s /q` (the only junction-safe method on Windows)
6. Re-scans to verify zero junctions remain
7. Runs `git worktree remove` (safe now that all junctions are gone)
8. Verifies `.git` still exists after completion
9. Deletes the merged branch and prunes worktree refs

**Why the script is mandatory:** On Windows, npm workspace projects create NTFS junctions in `node_modules` that point back to the worktree root (e.g., `node_modules/reply-flow` → worktree root). The worktree root contains a `.git` file linking to the main repository's `.git` directory. Almost every deletion tool — `rm -rf`, `Remove-Item`, `shutil.rmtree`, `rimraf`, and `git worktree remove` itself — follows these junctions during recursive deletion and **destroys the main `.git` directory**. The only tool confirmed junction-safe on Windows is `cmd.exe`'s built-in `rd /s /q`. The cleanup script uses this exclusively.

**Scope rule: Only clean up YOUR OWN worktree.** Each agent must only remove the worktree and branch it created. Never touch worktrees belonging to other agents — even if they look stale or finished. If you see a worktree that isn't yours and appears abandoned, mention it to the user but do NOT remove it.

**Hooks enforce this:** `git worktree remove` and `rm -rf` on worktree paths are hard-blocked by hooks in both Claude Code and Gemini CLI. The error message points to the cleanup script.

## Stale worktree prevention
- **Clean up worktrees immediately after merging** using the cleanup script.
- **Before starting new work**, run `git worktree list` and check for leftover worktrees. If any exist and their branches have been merged, clean them up: `py ~/.ai-instructions/tools/worktree_cleanup.py --all-merged`.
- **`--all-merged` misses ancestor-only branches.** The flag uses `git branch --merged`, which only reports branches main has moved *strictly past*. Branches whose tips sit at old commits that already live inside main's history (from prior squash or fast-forward merges that didn't update the local pointer) are invisible to it — they'll look abandoned but won't be swept. To catch those, run this check before assuming the sweep finished the job:
  ```bash
  for b in $(git branch --list "feat/*" "fix/*" "refactor/*" "chore/*" --format="%(refname:short)"); do
    [ "$(git rev-list --count main..$b)" = "0" ] && echo "ancestor-only (safe to clean): $b"
  done
  ```
  For each branch reported, locate its worktree with `git worktree list` and clean it with the individual-worktree form of the script.
- **Maximum active worktrees**: Avoid having more than 3 active worktrees at once.
- **At the end of every conversation that created worktrees**, list active worktrees and remind the user about any that should be cleaned up.

## Windows safety
- **Enable long paths**: Run `git config --global core.longpaths true` once.
- **The cleanup script is the ONLY safe way to remove worktrees.** Never use `rm -rf`, `Remove-Item`, `shutil.rmtree`, `rimraf`, `git clean`, or `git worktree remove` directly on worktree paths. All of these follow NTFS junctions and can destroy `.git`.
- **Worktrees MUST be outside the project tree** — reduces path depth and avoids some symlink scenarios.
- **Always push feature branches to remote before cleanup** — local-only branches can be permanently lost if `.git` is corrupted.
- **Pre-emptively remove the repo-root junction before running the cleanup script.** npm workspace projects create a junction at `<worktree>/node_modules/<package-name>` that points to the project root (the directory containing `.git`). The cleanup script's scanner correctly refuses to touch this one, so you must remove it first yourself:
  ```bash
  MSYS2_ARG_CONV_EXCL="*" cmd /c rmdir "<WORKTREE_WINDOWS_PATH>\\node_modules\\<package-name>"
  ```
  Use double-backslashes and quote the path. **Do not try to do this in a bash `for` loop** — the `MSYS2_ARG_CONV_EXCL` env var + `cmd /c` arg mangling interacts badly in loop bodies and the command silently no-ops. Run each `rmdir` as its own top-level command.
- **If `.git` disappears or is corrupted** — follow this recovery procedure:
  1. **Re-initialize**: `git init && git remote add origin <url>`
  2. **Prune dead worktree refs**: `git worktree prune` — clears refs to worktrees whose `.git` link files are broken.
  3. **Delete corrupt branch refs**: If `git fetch origin` fails with "bad object refs/heads/...", delete the offending branch with `git branch -D <branch>` and retry fetch. Repeat until fetch succeeds.
  4. **Reset to remote**: `git checkout -B main origin/main --force`
  5. **Salvage surviving worktrees**: Worktree directories on disk survive `.git` corruption — the files are still there, only the git tracking is lost. For each worktree directory that still has files:
     - Use `diff -rq` to compare it against the recovered main to identify changed/new files
     - Create a salvage branch: `git checkout -b salvage/<feature-name>`
     - Copy changed files from the worktree directory into the repo and commit
     - Push the salvage branch to origin immediately: `git push -u origin salvage/<feature-name>`
     - **Do NOT merge salvage branches into main** — they may be incomplete work. Push them as backups and let the user decide when to integrate.
  6. **Any branches that were pushed to remote before corruption are fully recoverable** via `git fetch origin`. Unpushed branches are permanently lost — this is why pushing after each commit is mandatory.

## Propagating changes (expand-contract)

**Renames, refactors, schema changes, interface signature changes, and file moves** are "propagating changes" — they ripple across the codebase and silently break other agents' code. These changes often don't even produce git merge conflicts; git merges cleanly but the build breaks because other agents' code references the old names/signatures.

**Rule: ALL propagating changes MUST use the expand-contract pattern (also called "parallel change").** Never make a breaking rename/refactor in a single atomic step.

#### The Three Phases

**Phase 1 — Expand (non-breaking)**
Introduce the new name/interface/schema **alongside** the old one. The old one still works. Nothing breaks for any agent.
- Renaming a function: create `findUser()` that wraps `getUserById()`. Both work.
- Changing an interface: add the new fields as optional, keep old fields present.
- Renaming a file: create the new file, re-export everything from the old file path.
- Schema change: add new columns alongside old ones. Don't drop old columns yet.

**Phase 2 — Migrate**
Move all callers from old to new. This can happen across multiple agents in parallel because each caller migration is independent. If other agents are actively working, they can migrate at their own pace — the old interface still works.

**Phase 3 — Contract (breaking, but safe)**
Remove the old name/interface/column. Only safe when:
- All parallel agents have finished and merged their work.
- All callers have been migrated to the new version.
- A full build confirms nothing references the old version.

#### When to Apply Each Phase

| Situation | What to do |
|-----------|-----------|
| Refactor needed BEFORE launching parallel agents | Complete all 3 phases first, then launch agents against the clean new interface. |
| Refactor needed WHILE other agents are running | Do Phase 1 (expand) only. Merge it into the base branch. Other agents keep working against the old interface. Phases 2-3 happen after all agents finish. |
| Refactor discovered mid-work by one agent | The agent does Phase 1 in its own worktree. At merge time, the expand is merged first. Phases 2-3 are deferred. |

#### Examples

**Function rename** (`getUserById` → `findUser`):
```typescript
// Phase 1 — Expand: add new function, keep old as alias
export function findUser(id: string) { /* new implementation */ }
/** @deprecated Use findUser() instead */
export function getUserById(id: string) { return findUser(id); }

// Phase 2 — Migrate: update all callers to use findUser()
// Phase 3 — Contract: remove getUserById()
```

**Interface change** (`name` → `displayName`):
```typescript
// Phase 1 — Expand: add new field, keep old
interface User {
  name: string;         // deprecated — use displayName
  displayName: string;  // new field
}

// Phase 2 — Migrate: update all consumers to use displayName
// Phase 3 — Contract: remove name field
```

**File move** (`server/routes.ts` → `server/api/routes.ts`):
```typescript
// Phase 1 — Expand: create new file, re-export from old path
// server/api/routes.ts — the new location with actual code
// server/routes.ts — re-exports: export * from './api/routes';

// Phase 2 — Migrate: update all imports to use new path
// Phase 3 — Contract: delete old file
```

#### Cross-layer data fields (the silent-fallback trap)

When the thing you're migrating is a **data value written in one layer and read in another** — a JSON `metadata.<key>`, a DB column, an API response field — the contract phase is **NOT proven safe by "a full build passes."** Dynamic reads (`metadata.html_body`, `row['col']`, `resp.field`) don't reference a removed *symbol*; when the field disappears they silently become `undefined` and the reader falls through to a fallback (often a worse one) with zero compile errors. The build is green; users get garbage.

Rules for data-field / storage migrations (e.g. moving a value from `metadata` JSON to a first-class column, or renaming an API field):
- **Grep every layer, not just the compiler.** Before dropping the old write, search `server/` AND `client/` for the JSON key, the column name, AND any `??`/`||` fallback reading them. `tsc` will not find dynamic key reads for you.
- **Readers use `newSource ?? oldSource`, and the new source must be declared in the consumer's type.** A column returned by `select('*')` is invisible to the client until the row/`Message` type lists it — an undeclared column reads as `undefined`.
- **Keep dual-writing the old location until grep shows zero readers remain.** Dropping the old write "to avoid divergence" while any consumer still reads it converts a loud failure into a silent wrong-value bug. The old location is retired only after every reader is migrated.
- **A regression test asserting the consumer reads the new source (not the fallback) is the durable guard — a build is not.**

Real example (reply-flow, 2026-06-05): email `html_body` was promoted from `metadata.html_body` to a first-class column. The send path dropped the `metadata.html_body` write (Phase 3) while the web client still read `metadata.html_body`, so display silently fell back to the tag-stripped `message_body` and rendered every app-sent email as a garbled `&nbsp;` blob. The build passed the whole time.

**What this replaces:** This rule supersedes the old "create a branch in the main repo" workflow. You no longer work directly in the main working tree for any code changes. The only things you do in the main working tree are:
- Reading project context files (`PROJECT_SCOPE.md`, `WORKBOARD.md`, `MEMORY.md`, plans)
- Updating `WORKBOARD.md` entries
- Running `git fetch` to keep refs current

Merges happen inside worktrees, not in the main working tree.

## Enable git rerere

Enable `git rerere` (Reuse Recorded Resolution) globally so that git remembers how merge conflicts were resolved and auto-applies the same resolution if the same conflict recurs:

```bash
git config --global rerere.enabled true
```

This is especially useful when multiple agents repeatedly modify the same files (e.g., barrel exports, route indexes) — the first manual resolution is recorded and reused automatically for subsequent merges.
