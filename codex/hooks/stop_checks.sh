#!/bin/bash
# Global Stop hook for Codex CLI.
# Runs after each turn: branch guard, WORKBOARD check, debug code scan.
# Equivalent to Claude's Stop hooks.
# Note: Codex only supports SessionStart and Stop hooks, so pre-tool-use
# checks (secrets, eval, etc.) must remain as manual checks in AGENTS.md.

# Only run in git repos
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    exit 0
fi

WARNINGS=""

# --- Branch guard ---
BRANCH=$(git branch --show-current 2>/dev/null)
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
    CHANGES=$(git diff --name-only -- '*.ts' '*.tsx' '*.js' '*.jsx' '*.py' '*.css' '*.json' 2>/dev/null | head -1)
    if [ -n "$CHANGES" ]; then
        WARNINGS="${WARNINGS}WARNING: You have uncommitted code changes on $BRANCH. Create a feature branch.\n"
    fi
fi

# --- WORKBOARD check ---
CHANGED=$(git diff --name-only -- '*.ts' '*.tsx' '*.js' '*.jsx' '*.py' '*.go' '*.rs' 2>/dev/null | head -1)
if [ -n "$CHANGED" ] && [ ! -f "WORKBOARD.md" ]; then
    WARNINGS="${WARNINGS}WARNING: Code changes detected but no WORKBOARD.md. Create one to coordinate with other agents.\n"
fi

# --- Debug code scan ---
DEBUG_LINES=$(git diff --unified=0 -- '*.ts' '*.tsx' '*.js' '*.jsx' '*.py' '*.mjs' '*.cjs' 2>/dev/null \
    | grep -E '^\+' \
    | grep -v '^\+\+\+' \
    | grep -iE '(console\.log\(|^\+\s*debugger\s*;?\s*$)' \
    | head -5)

if [ -n "$DEBUG_LINES" ]; then
    WARNINGS="${WARNINGS}WARNING: Debug code detected in your changes:\n"
    WARNINGS="${WARNINGS}$(echo "$DEBUG_LINES" | sed 's/^\+/  /')\n"
    WARNINGS="${WARNINGS}Remove console.log() and debugger statements before committing.\n"
fi

# --- Worktree check ---
STALE=$(git worktree list 2>/dev/null | grep -v "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null | head -5)
if [ -n "$STALE" ]; then
    WARNINGS="${WARNINGS}WARNING: Stale worktrees detected:\n${STALE}\nRun: git worktree prune\n"
fi

# --- .git corruption detection (post-hoc since Codex cannot pre-block) ---
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
if [ -n "$GIT_DIR" ] && [ ! -d "$GIT_DIR" ]; then
    WARNINGS="${WARNINGS}CRITICAL: .git directory missing or corrupted at ${GIT_DIR}!\n"
    WARNINGS="${WARNINGS}STOP ALL WORK. Recovery: git init && git remote add origin <url> && git fetch origin && git checkout -B main origin/main\n"
fi

# --- node_modules in worktrees (prevents safe cleanup) ---
MAIN_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
while IFS= read -r WT_LINE; do
    WT_PATH=$(echo "$WT_LINE" | awk '{print $1}')
    # Skip the main working tree
    if [ "$WT_PATH" = "$MAIN_ROOT" ]; then
        continue
    fi
    for NM_DIR in "$WT_PATH/node_modules" "$WT_PATH/server/node_modules" "$WT_PATH/client/node_modules"; do
        if [ -d "$NM_DIR" ]; then
            WARNINGS="${WARNINGS}WARNING: node_modules exists at ${NM_DIR}. Delete it BEFORE running 'git worktree remove' to prevent symlink recursion: rm -rf ${NM_DIR}\n"
            break
        fi
    done
done < <(git worktree list 2>/dev/null)

# --- Merge in main working tree detection ---
# Check if git reflog shows a recent merge on the main working tree's branch
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ] || [ "$BRANCH" = "dev" ]; then
    RECENT_MERGE=$(git reflog -1 --format='%gs' 2>/dev/null | grep -i "merge" 2>/dev/null)
    if [ -n "$RECENT_MERGE" ]; then
        WARNINGS="${WARNINGS}WARNING: A merge was detected on ${BRANCH} in the main working tree. Merges should happen inside worktrees using 'git update-ref'. If this was unintentional, review the merge.\n"
    fi
fi

# Print warnings to stderr (Codex displays stderr)
if [ -n "$WARNINGS" ]; then
    echo -e "$WARNINGS" >&2
fi

exit 0
