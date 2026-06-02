---
name: git-safety
description: Git push protection (main/master), fetch-before-merge, update-ref, base-branch drift
when_to_read: before any git push, merge, update-ref, or rebase
sections:
  - Pushing to main/master
  - Pushing feature branches
  - Fetch before merging the base
  - How to apply
  - Hook enforcement
---
# Git Safety
> Navigation: read this frontmatter + section list, then `grep` the `##` heading you need and read only that section. Do not read the whole doc.

## Pushing to main/master

**Pushing to `main`/`master`**: NEVER push to main or master without explicitly asking the user first and receiving approval. This includes `--force`, `--force-with-lease`, or any variant. A push to main is an irreversible action that affects shared state.

**Bare `git push`** (no branch specified): Always ask the user, since it may push to main depending on the current branch.

## Pushing feature branches

**Pushing feature branches**: Pushing feature branches to remote (e.g., `git push -u origin feat/my-feature`) is ALLOWED and ENCOURAGED — it serves as a backup that prevents work loss. Feature branch pushes do NOT require user approval. Hooks will auto-allow pushes to branches starting with `feat/`, `fix/`, `refactor/`, or `chore/`.

## Fetch before merging the base

**Always `git fetch` the target branch immediately before merging into it.** Whenever you are about to move a base branch pointer — `main`, `master`, `dev`, or any other integration branch — you MUST first run `git fetch origin <base-branch>` (or equivalent for the relevant remote) as the immediately preceding step. No commands in between.

This applies to every mechanism that advances the base branch pointer, not just `git merge`:
- `git merge <feature>` while on `main`/`master`/`dev`
- `git update-ref refs/heads/<base> HEAD` (the worktree-based merge pattern in the Worktree Isolation section)
- `git rebase <base>` of the base onto something else
- `git push origin <base>` (push must be preceded by a fresh fetch — see also the `feedback_refetch_before_main_push.md` memory)
- `git pull origin <base>` is acceptable as the fetch+merge combined, but only when you actually want to fast-forward your local base — not as a substitute when merging *your* work in.

**Why:** A fetch from minutes ago is not fresh. Another agent, the user in another terminal, CI, or a teammate may have advanced the remote in the interval. Merging or update-ref'ing without a just-now fetch can silently leave their commits behind, produce a non-fast-forward push later, or land work that doesn't actually contain the latest base. The cost of an extra `git fetch` is ~1 second; the cost of recovering from a stale merge is significant.

## How to apply

- Treat `git fetch origin <base>` and the merge/update-ref/push as a single atomic pair in your tool calls — don't insert unrelated commands between them.
- If a build, typecheck, or any other slow step runs between the fetch and the merge, re-fetch right before the merge. Anything that takes more than a few seconds invalidates the freshness of the previous fetch.
- If the fetch reveals new commits on the remote base, **integrate them first** (merge `origin/<base>` into your feature branch inside your worktree, re-run build/typecheck), then re-fetch and merge.
- This rule applies in every environment (main working tree, worktrees, sub-agents) and to every tool (Claude Code, Gemini CLI, Codex, manual shell).

## Hook enforcement

**Enforcement:** In Claude Code, this rule is enforced by `~/.claude/hooks/pretooluse_bash.py` — `git merge` (when HEAD is on a base branch), `git update-ref refs/heads/(main|master|dev)`, and `git push origin (main|master)` are hard-blocked unless a `git fetch` (or `git fetch --all` / `git fetch origin` / `git pull origin <base>`) appears in a preceding segment of the same Bash invocation (split on `&&` or `;`). To bypass for legitimate offline or recovery flows, set `ALLOW_UNFETCHED_BASE_MERGE=1` in the environment for the single command. Gemini CLI and Codex rely on this text rule rather than a hook.
