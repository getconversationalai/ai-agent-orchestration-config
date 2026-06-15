---
name: multi-agent-coordination
description: Coordinate parallel agents via WORKBOARD; dependency analysis; progress tracking; subagents; merge ordering; migration naming; phase/plan completion summary
when_to_read: before launching parallel agents, registering work, tracking progress, merging multiple agents, or finishing a phase/plan
sections:
  - Before starting any work
  - Dependency analysis
  - While working
  - When finished
  - Merging multiple completed agents
  - Migration naming convention
  - WORKBOARD format and write safety
  - Progress tracking (PROGRESS.json lifecycle)
  - Subagents
  - Summary on phase or plan completion
  - Parallel-agent specifics
---
# Multi-Agent Coordination
> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

Multiple agents (Claude, Gemini, Codex, or multiple instances of the same tool) may be working on the same project simultaneously. Agents coordinate through the shared `WORKBOARD.md` file in the project root.

## Before starting any work
1. **Read `WORKBOARD.md`** in the project root. If it doesn't exist, create it.
2. **Theme-based overlap scan (MANDATORY).** The workboard's *Active* list is not sufficient — parallel agents complete features and archive their entries long before you start, and a completed-but-unmerged branch using different wording (e.g. `feat/access-ux-clarity` vs your `feat/access-sharing-ux-clarity`) is invisible to an active-only scan. For every feature you are about to start, extract 1–2 theme keywords (e.g. "access", "sharing", "inbox-filter", "email-parity") and grep across:
   - **Local + remote branches:** `git branch -a --list "*<keyword>*"`
   - **Completed workboard entries:** `py ~/.ai-instructions/tools/workboard.py show` and scan the `Completed` section too, not just `Active Work`
   - **Recent main commits:** `git log --oneline --all --grep='<keyword>' -i -30`

   If anything matches, read its diff against main before writing your plan. Your plan may need to shrink (many tasks already shipped) or pivot (the user already tried an approach and reverted it, like the "Just for me" collapsed-picker revert in commit `84e26de`).
3. **If there are other active agents**, run the overlap check to see what they have actually changed:
   ```bash
   py ~/.ai-instructions/tools/overlap_check.py --detailed
   ```
   This compares actual `git diff` across all active branches — not just declared file lists. Also read their plan file (linked in their WORKBOARD.md entry) to understand what they still intend to do.
4. **Use the real diffs + their plan** to perform a **Dependency Analysis** (see below) to decide whether to proceed or wait. This happens BEFORE you make your own plan — the other agents' actual changes inform your planning.
5. **Register your work** using the workboard script:
   ```bash
   py ~/.ai-instructions/tools/workboard.py register --feature "<name>" --tool <tool> \
       --plan <plan-path> --files "<file1,file2>" --branch <branch> --worktree <worktree-path>
   ```

## Dependency analysis

When your work overlaps with another active agent's files, **do NOT automatically stop or ask the user**. Use two sources of truth to analyze the overlap:
- **`git diff --name-only <base>...<their-branch>`** — what they have ALREADY changed (always accurate)
- **Their plan file** — what they INTEND to change next (may not be complete, but shows direction)

Then analyze the nature of the overlap:

### Proceed in Parallel (most common case)
Overlap is safe to proceed when the changes are **independent additions to the same file**:
- Both agents add different routes to a routes index file
- Both agents add different components to a barrel export
- Both agents add different columns/tables in separate migrations
- Both agents import from the same utility but don't modify it
- Both agents add different items to a shared config/array

In these cases: **proceed with your work**. The merge conflicts will be trivial — both sides are adding lines, and the resolution is to keep both additions. Note in your WORKBOARD.md entry: `Overlaps with: [other feature] on [files] — independent additions, will merge.`

### Wait for the Other Agent (less common)
You MUST wait when your feature **structurally depends** on the other agent's output:
- The other agent is building an auth/permission system that your feature needs to use
- The other agent is refactoring a database schema that your feature queries against
- The other agent is creating an API that your feature will consume
- The other agent is changing the signature/behavior of a function your feature calls
- Building your feature without the other's changes would result in code that needs to be **rewritten** (not just merge-resolved) once the other agent finishes

In these cases: set your WORKBOARD.md status to `waiting` with reason, and tell the user: *"My work on [feature] depends on [other agent's feature] because [reason]. I'll start once that's merged."*

### Gray Area — Ask the User
If you genuinely can't determine whether the dependency is structural or just additive overlap, ask the user. But this should be rare — most overlaps are clearly one or the other.

## While working
- Keep your WORKBOARD.md entry updated via the workboard script if your scope or file list changes:
  ```bash
  py ~/.ai-instructions/tools/workboard.py update-files --feature "<name>" --files "<updated,file,list>"
  ```
- **If you need to modify a file not in your original plan**, do NOT just silently expand scope. Spawn a sub-agent to update your plan file with the new files and rationale, and update your WORKBOARD.md entry. This keeps your plan the source of truth for other agents reading it.
- If a dependency on another agent emerges mid-work that wasn't apparent at the start, update your status and tell the user:
  ```bash
  py ~/.ai-instructions/tools/workboard.py update-status --feature "<name>" --status waiting \
      --reason "Needs X from <other feature>"
  ```

## When finished
1. **Move your entry** from `Active Work` to `Completed` using the workboard script:
   ```bash
   py ~/.ai-instructions/tools/workboard.py complete --feature "<name>" --files "<final,file,list>"
   ```
2. If another agent's entry in `Active Work` looks stale (timestamp is very old with no updates), note it but do NOT remove it — let the user decide.

## Merging multiple completed agents

When multiple main agents have completed work and need to merge into `main`/`dev`, follow this protocol to preserve ALL changes from ALL agents:

### Step 0: Run the Merge Order Tool
```bash
py ~/.ai-instructions/tools/merge_order.py --detailed
```
This analyzes actual `git diff` across all completed branches, computes file and hunk-level overlaps, and outputs the recommended merge order. Follow it.

### Step 1: Establish Merge Order
The merge order tool sorts branches by overlap risk:
- **Agents with no file overlap** merge first — zero conflict risk.
- **Agents with the fewest overlapping files** merge next.
- **Agents with the most overlapping files** merge last (they'll have the most conflicts to resolve, but by then all other changes are in the base branch and visible).

### Step 2: Merge One at a Time
Each agent merges from inside its own worktree (see Level 2 merge in Worktree Isolation):
1. Inside the agent's worktree: `git fetch origin <base-branch> && git merge origin/<base-branch>`
2. **If no conflicts** → run build/typecheck → update the base branch ref: `git update-ref refs/heads/<base-branch> HEAD` → sync main working tree: `git -C <main-working-tree-path> reset HEAD` → done.
3. **If conflicts** → proceed to conflict resolution (Step 3).
4. The next agent then repeats from step 1 — its `git fetch` will pick up the previous agent's merged changes.

### Step 3: Conflict Resolution (MANDATORY RULES)
- **NEVER silently drop changes from either side.** Both agents' changes must be preserved.
- **For additive conflicts** (both sides added different lines to the same location): keep BOTH additions. This is the most common case — e.g., both added routes, both added imports, both added config entries.
- **For contradictory conflicts** (both sides changed the SAME lines differently): stop and show the user both versions. Explain what each agent was trying to do. Let the user decide.
- **After resolving each conflict**: verify that the intent of BOTH agents' changes is preserved. Read the resolved file and confirm it includes the functionality from both feature branches.

### Step 4: Post-Merge Verification
After ALL agents are merged:
1. Run full build and typecheck.
2. Run tests if available.
3. **Audit check**: for each merged agent, verify its key changes are present in the final codebase. Spot-check at least the main files each agent modified to confirm nothing was silently dropped or reverted.

## Migration naming convention

When multiple agents create database migrations in parallel, sequential numbering (e.g., `065_`, `066_`) will collide. Use **timestamp-based migration names** instead:

```
YYYYMMDD_HHMMSS_<description>.sql
```

Example: `20260317_143000_classification_suggestions.sql`

Timestamps are inherently collision-free across parallel agents (different agents create migrations at different times). If the project already uses sequential numbering, check the highest existing number AND check WORKBOARD.md for numbers claimed by other agents before picking a number.

## WORKBOARD format and write safety

### WORKBOARD.md Format
```markdown
# Workboard

## Active Work
- **[feature]** — [tool] — Started [time]. Status: active/waiting/blocked.
  Plan: [path to plan file, e.g., plans/phase-3.md]
  Files: [file1, file2, ...] (ALL files you will modify, update as scope changes)
  Migrations: [migration numbers or timestamps claimed, e.g., 065, 066]
  Branch: [branch]. Worktree: [worktree path].
  Overlaps with: [other feature] on [files] — [independent additions / waiting for dependency].
  Waiting reason: [if status is waiting, explain what you're waiting for and why].

## Completed
- **[feature]** — [tool] — Completed [time]. Branch: [branch]. Merged: yes/no.
  Files modified: [final list of all files that were actually modified].
```

### WORKBOARD.md Write Safety

`WORKBOARD.md` is a shared file that multiple agents may read/write concurrently. **All writes MUST go through the workboard helper script** to prevent race conditions:

```bash
py ~/.ai-instructions/tools/workboard.py register --feature "Voice Notes" --tool claude \
    --plan plans/phase-3.md --files "server/routes.ts,client/VoiceRecorder.tsx" \
    --branch feat/voice-notes --worktree ../.worktrees/feat/voice-notes

py ~/.ai-instructions/tools/workboard.py update-status --feature "Voice Notes" --status waiting \
    --reason "Needs auth middleware"

py ~/.ai-instructions/tools/workboard.py update-files --feature "Voice Notes" \
    --files "server/routes.ts,client/VoiceRecorder.tsx,server/middleware.ts"

py ~/.ai-instructions/tools/workboard.py set-overlap --feature "Voice Notes" \
    --overlap "Affiliate Portal on [server/routes.ts] — independent additions"

py ~/.ai-instructions/tools/workboard.py complete --feature "Voice Notes" \
    --files "server/routes.ts,client/VoiceRecorder.tsx"

py ~/.ai-instructions/tools/workboard.py show
```

The script acquires a file lock, reads current state, applies the change, writes atomically, and releases the lock. This prevents one agent from overwriting another's entry.

**Reading WORKBOARD.md directly is fine** — only writes need the script.

## Progress tracking (PROGRESS.json lifecycle)

Agents declare their plan structure (plan/phase/wave/task **titles only**) and tick items off as they complete them. This gives every other agent a live, fine-grained view of what's done, what's in progress, and what's still pending — without dumping plan content into the coordination files.

### Two files, both managed by the same script
- **`WORKBOARD.json`** — the evolved workboard (who is working on what, branches, worktrees, files, **current position in their progress tree**, and any sub-agents they've dispatched).
- **`PROGRESS.json`** — per-plan hierarchical trees containing ONLY the titles of phases/waves/tasks and a status for each (`pending`/`active`/`done`).
- **`WORKBOARD.md`** and **`PROGRESS.md`** — auto-generated read-only mirrors for easy grepping/eyeballing. **Never edit these by hand** — every call to `workboard.py` regenerates them.

All writes must go through `py ~/.ai-instructions/tools/workboard.py`, which acquires a file lock and updates both JSON files atomically. Reading the JSON or markdown mirrors directly is always fine.

### Required lifecycle — main-thread agents

When you start a new feature/work item, after `register` (see Multi-Agent Coordination), **you must also build the progress tree** using titles from your plan. If your plan has phases and tasks but no waves, skip the wave layer. All four levels are optional — register what's actually in your plan.

```bash
# 1. Register the plan tree (titles only — no plan content is duplicated)
py ~/.ai-instructions/tools/workboard.py register-plan \
    --feature "Voice Notes" --plan-title "Voice Notes v1" \
    --plan-path plans/phase-3-voice-notes.md

# 2. Add phases
py ~/.ai-instructions/tools/workboard.py add-phase \
    --feature "Voice Notes" --title "Phase 1: Schema"
py ~/.ai-instructions/tools/workboard.py add-phase \
    --feature "Voice Notes" --title "Phase 2: Backend API"

# 3. Add waves under a phase (optional layer)
py ~/.ai-instructions/tools/workboard.py add-wave \
    --feature "Voice Notes" --phase "Phase 2: Backend API" \
    --title "Wave 2.1: Routes"

# 4. Add tasks (under any phase/wave, or directly under the plan)
py ~/.ai-instructions/tools/workboard.py add-task \
    --feature "Voice Notes" --phase "Phase 2: Backend API" \
    --wave "Wave 2.1: Routes" --title "POST /voice"
```

### During work — mark things as you go

```bash
# Mark a node active when you start working on it
py ~/.ai-instructions/tools/workboard.py start \
    --feature "Voice Notes" \
    --at "Phase 2: Backend API / Wave 2.1: Routes / POST /voice"

# Mark it done when finished (descendants are auto-marked done;
# ancestors auto-roll up when all their children are done)
py ~/.ai-instructions/tools/workboard.py done \
    --feature "Voice Notes" \
    --at "Phase 2: Backend API / Wave 2.1: Routes / POST /voice"
```

**Path addressing**: titles are joined with ` / ` (space-slash-space). Titles may contain `/` (e.g., `POST /foo`) — only space-slash-space separates levels.

**Granularity rule**: you must `start` / `done` at **task level** whenever the plan has tasks. If a plan only has phases (no tasks underneath), phase-level updates are sufficient. The point is maximum fine-grained visibility.

### Inspecting progress

```bash
# Print the full board + progress tree
py ~/.ai-instructions/tools/workboard.py show

# Scope to a specific feature
py ~/.ai-instructions/tools/workboard.py show --feature "Voice Notes"

# Force-regenerate the markdown mirrors (rarely needed — happens on every write)
py ~/.ai-instructions/tools/workboard.py refresh-markdown
```

**Reading** `WORKBOARD.json`, `PROGRESS.json`, `WORKBOARD.md`, or `PROGRESS.md` directly is always fine. Only writes go through the script.

### Migration from legacy `WORKBOARD.md`

The first time `workboard.py` runs in a project that has a hand-written `WORKBOARD.md`, it parses the old markdown into `WORKBOARD.json` automatically. The original `WORKBOARD.md` is then overwritten with the auto-generated mirror. Historical entries are preserved but may have blank timestamps — that's expected.

### Gitignore

Add `WORKBOARD.json`, `PROGRESS.json`, `WORKBOARD.md`, and `PROGRESS.md` to `.gitignore` — they're local coordination state, not source code.

## Subagents

### Completion

When finishing a feature, call `complete` as before. This auto-marks the plan as done in `PROGRESS.json` too.

```bash
py ~/.ai-instructions/tools/workboard.py complete \
    --feature "Voice Notes" --files "server/routes.ts,client/VoiceRecorder.tsx" --merged no
```

### Sub-agents — parent reports on their behalf

Sub-agents do NOT call `workboard.py` directly. The dispatching (parent) agent reports for them:

```bash
# When dispatching a sub-agent, register it under yourself:
py ~/.ai-instructions/tools/workboard.py register-subagent \
    --parent "Voice Notes" \
    --feature "Routes tests" \
    --task "Phase 2: Backend API / Wave 2.1: Routes / POST /voice" \
    --branch feat/voice-notes/routes-tests \
    --worktree ../.worktrees/reply-flow/feat/voice-notes/routes-tests

# Update the sub-agent's current position if it moves:
py ~/.ai-instructions/tools/workboard.py update-subagent-path \
    --parent "Voice Notes" --sub "Routes tests" \
    --path "Phase 2: Backend API / Wave 2.1: Routes / GET /voice"

# When the sub-agent finishes, the parent reports completion
# (this also marks its task as done in PROGRESS.json):
py ~/.ai-instructions/tools/workboard.py complete-subagent \
    --parent "Voice Notes" --sub "Routes tests"
```

The sub-agent appears as a nested entry inside the parent's workboard entry — not as its own top-level agent. This matches the merge hierarchy (sub-agents merge into the parent's feature branch, not into `main`/`dev` directly).

## Summary on phase or plan completion

The moment you mark a **phase** or a **plan** as done (via `workboard.py done --at "Phase …"` or `workboard.py complete`), you MUST include a plain-English summary in your reply to the user. This is your main signal that real progress happened — don't skip it.

**The completion summary is FIVE labeled sections, in THIS order, with THESE exact headings** — do not rename, reorder, or merge them:

`List of What Was Done` → `Summary Of What Was Done` → `Where To Check` → `Verification` → `What's Next`

**1. List of What Was Done** — a checklist, every item ticked (✓), as the very first thing in the completion turn. **This is NOT a copy of your TodoWrite list.** Your TodoWrite items are technical tasks ("Task 1 — `cloneSequence` service, 3/3 tests"); this list is a *fresh, rewritten* one where **every item is an outcome the user can now do or see**, in words a non-technical stakeholder understands. **Banned here** (these read as gibberish to a non-technical reader — put them under *Verification*, not here): commit hashes, file or function names, "Task 1/2/3" labels, test counts, build/typecheck/`tsc`/lint output, and process jargon ("adversarial review", "TDD", "tenant isolation", "endpoint", "404"). **If an item names a file or a hash, you've copied the todo list — rewrite it.** Good: "✓ You can duplicate a finished campaign and get a complete, working copy." Bad: "✓ Task 2 — endpoint rewritten to deep-clone (`63c287a4`)."

**2. Summary Of What Was Done** — one short paragraph (or 2-4 bullets) in plain language a non-technical stakeholder could follow. Not a file-by-file diff. Describe what now *works*, or what the user can *do* that they couldn't before.

**3. Where To Check** — a short bulleted walkthrough the user can follow to test it themselves: the exact nav path (page → click → button), what to enter, and **what they should see if it worked**. A test they can run, not just a location. **Do NOT answer this with a list of source-file paths** (`clone.ts`, `SequenceDetailPage.tsx`, …) — those are where the code lives, not how the user checks it. Include the local dev URL when you know it (e.g., `http://localhost:5173/settings/agents`). If observing the change needs a scenario set up first (e.g. drive a send-once campaign until nobody's left so it auto-completes), spell those steps out. If the change is back-end only with no visible UI, say so explicitly — and give the next-best way to confirm it (an action with an observable result, a log line, or a value to check) so the user is never left unable to verify.

**4. Verification** — the concrete checks you actually ran, with their results, as *evidence* — not a claim that it "should" work. List what passed: build, typecheck, lint, and tests (with pass counts and a one-line note on what new tests cover). A compact single line is fine, e.g. `Client build + typecheck ✓ · server build + typecheck ✓ · lint clean ✓ · 5/5 new tests pass`. **Run these checks BEFORE writing the summary — never assert success you haven't observed.** If a check was skipped, failed, or couldn't run, say so explicitly rather than implying everything passed; a partial summary with an honest gap beats a clean-looking one that's untrue.

**5. What's Next** — the next pending phase or task from `PROGRESS.json`. If nothing remains, say **"Plan complete."** explicitly. If the next step needs a user action (DB migration to run, env var to set, decision to make), call it out as a checklist the user can tick off.

**Keep your TodoWrite list updated live during execution too** — mark each item `completed` the instant it's done via its OWN TodoWrite call (one status change per call, never batched), so the list visibly re-renders with each tick as work progresses. That live TodoWrite list is your technical working tracker; the `List of What Was Done` above is the plain-English rewrite of it you present at the end — never the raw list itself.

**Trigger granularity**: phase completion AND plan completion trigger this summary. Wave and task completions do NOT (they'd flood the chat). If a plan has no phases (flat task list), then only plan completion triggers the summary.

**Example** (phase just completed in a fictional feature):

> **Phase 2: Backend API — done.**
>
> **List of What Was Done**
> - ✓ Voice messages you record against a contact are saved
> - ✓ Each recording is turned into text automatically
> - ✓ You can play the audio back and edit the text
> - ✓ A failed recording shows an error instead of breaking the page
>
> **Summary Of What Was Done**
> The server now accepts voice recordings, turns them into text automatically, and stores both the audio and the transcript against the contact. Playback and transcript editing work end-to-end against real data.
>
> **Where To Check**
> - Open any contact in the inbox (`http://localhost:5173/inbox/<contactId>`) — a new "Voice notes" tab appears next to "Notes".
> - Click the mic button, record a few seconds, and stop.
> - Within ~5 seconds the recording should appear in the list with its transcript beneath it.
> - Click the transcript to edit a word, refresh the page, and confirm your edit stuck.
>
> **Verification**
> Client build + typecheck ✓ · server build + typecheck ✓ · lint clean on authored files ✓ · 5/5 new tests pass (4 service tests covering transcribe / store / playback / error paths, 1 component test proving the tab renders the transcript).
>
> **What's Next**
> Phase 3 — Notifications. The unread-count badge in the sidebar should bump when a new voice note arrives in a contact you're subscribed to. First task: `Add voice_note_received event to notificationService`.

**✗ BAD vs ✓ GOOD** — the exact failure mode this rule exists to prevent (don't dump your todo list + source files):

> **✗ BAD — List of What Was Done** (raw todo list — hashes, file/function names, test counts, build output):
> - ✓ Task 1 — `cloneSequence` service, TDD, 3/3 tests (`692e953d`)
> - ✓ Task 2 — endpoint rewritten to deep-clone, 404 when not owned (`63c287a4`)
> - ✓ Verification — server `tsc` exit 0, `build:client` exit 0
>
> **✗ BAD — Where To Check** (source-file paths, not a test the user can run):
> Service: `clone.ts` · endpoint: `sequences.ts` · button: `SequenceDetailPage.tsx`
>
> **✓ GOOD — List of What Was Done** (outcomes a non-technical reader understands):
> - ✓ You can duplicate a finished campaign and get a complete, working copy
> - ✓ The copy brings everything across — emails, A/B variants, attachments, automations
> - ✓ The copy opens as a fresh draft with nobody enrolled
> - ✓ There's a Duplicate button in the campaign header
>
> **✓ GOOD — Where To Check** (an in-app test):
> - Go to **Sequences** → open a **Completed** campaign → click **Duplicate** in the header.
> - You should land on a new **"Copy of…"** draft showing **0 recipients**, with the same emails, variants, and attachments.
> - Reopen the original and confirm it's unchanged.
>
> The test counts and `tsc`/build results from the BAD list still get reported — under **Verification**, where they belong.

## Parallel-agent specifics

**Note:** The global instruction files (`CLAUDE.md`, `GEMINI.md`, `AGENTS.md`) now mandate worktree isolation for ALL work — not just parallel agents. The rules below are additional constraints specific to running multiple agents concurrently.

### Isolation
- **Each sub-agent MUST run in its own worktree** — This is already required by the global "Worktree Isolation" rule, but for parallel agents it is especially critical since they run concurrently.
- **Never run parallel agents on the same working tree** — Concurrent file edits without worktree isolation will cause conflicts and corrupted state.
- **All sub-agent worktrees branch off the main agent's feature branch** — NOT off `main`/`dev`. This way all sub-agent work funnels back into the parent feature branch, and only the main agent merges into `main`/`dev`.

### Before Launching Agents — Shared Contracts First
- **Define shared type contracts before launching agents** — If multiple agents will add to the same type file, define all new type additions in the main branch FIRST, then launch agents. This prevents multiple agents each writing incompatible versions of the same type file.
- **Standardize shared utilities before parallel work** — If agents will share infrastructure, create the shared utility in the main branch first with a stable API.
- **Identify integration files upfront** — Before launching agents, list all "hub" files that multiple agents will need to modify. Either:
  - **(Preferred)** Make those changes in the main branch before launching agents, OR
  - Designate a single "integration agent" that runs AFTER all feature agents complete to handle all hub-file modifications.

### Agent Scoping Rules
- **Agents must NOT modify shared integration files, and must never blindly overwrite them** — Each agent should only create/modify files within its own feature scope (route registrations, nav components, barrel exports, shared types/stores are off-limits unless the agent is the sole modifier). If an agent must add to a shared file, it must READ the current content first and ADD to it — never wholesale replace. Worktree agents start from a snapshot and may be missing other agents' changes.

### Agent Prompt Template
When launching a worktree agent, always include these instructions in the prompt:
- Which files the agent owns (can create/modify freely)
- Which files are OFF-LIMITS (hub/shared files)
- Any naming conventions or prefixes to use (e.g., migration number prefixes)
- "Do NOT modify any files outside your feature scope."
- "Run `npm install --prefix <worktree-path>` before building or typechecking."
- If migrations are needed: "Use timestamp-based migration names: `YYYYMMDD_HHMMSS_<description>.sql` to avoid number collisions with other agents."
- "Push your feature branch to remote before cleanup: `git push -u origin <branch>`"

### Merging Strategy (Sub-agents → Main Agent's Feature Branch)

Sub-agents merge into the **main agent's feature branch**, not into `main`/`dev`. See the "Merge Back — Two-Level Hierarchy" section in the global instruction files for the full protocol.

- **Merge new-file-only agents first** — No conflict risk.
- **Then merge single-modifier files** — Copy that agent's version directly.
- **Then handle multi-modifier files manually** — Read each agent's version and merge additions.
- **The main agent performs all sub-agent merges inside its own worktree.**
- **Always run a full typecheck after merging each sub-agent** — Fix all errors before merging the next.
- **Only after ALL sub-agents are merged and passing** does the main agent request permission to merge into `main`/`dev`.

### Worktree Cleanup
- **Clean up worktrees immediately after parallel agent work** — After all parallel agents complete and their work is merged, run `git worktree prune` and delete stale worktree branches. Do not leave worktrees lingering across sessions.
- **Verify worktree cleanup** — Run `git worktree list` to confirm only the main working tree remains.
- `.claude/worktrees/` must be in `.gitignore`.

### WORKBOARD.md Coordination
- **Before launching agents**, run the overlap check and read WORKBOARD.md:
  ```bash
  py ~/.ai-instructions/tools/overlap_check.py --detailed
  ```
- **Perform Dependency Analysis** for any file overlaps — see the "Dependency Analysis" section in the global instruction files. Most overlaps are independent additions and can proceed in parallel.
- **Each agent must register** using the workboard script:
  ```bash
  py ~/.ai-instructions/tools/workboard.py register --feature "<name>" --tool <tool> \
      --plan <plan-path> --files "<file1,file2>" --branch <branch> --worktree <worktree-path>
  ```
- **If waiting on a dependency**, update status via the script:
  ```bash
  py ~/.ai-instructions/tools/workboard.py update-status --feature "<name>" --status waiting \
      --reason "Needs X from <other feature>"
  ```
- **When done**, move your entry to Completed:
  ```bash
  py ~/.ai-instructions/tools/workboard.py complete --feature "<name>" --files "<final,file,list>"
  ```
- See the WORKBOARD.md format in your global instruction file for the full entry template.

### Merge Ordering for Multiple Completed Agents
When multiple sub-agents or main agents are ready to merge, use the merge order tool:
```bash
py ~/.ai-instructions/tools/merge_order.py --detailed
```
This analyzes actual diffs and recommends the optimal merge sequence. Follow the output.
