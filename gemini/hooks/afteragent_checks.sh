#!/bin/bash
# Global AfterAgent hook for Gemini CLI.
# Runs after each turn: branch guard, WORKBOARD check, debug code scan.
# Equivalent to Claude's Stop hooks.

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

# Print all warnings to stderr (Gemini displays stderr to the user)
if [ -n "$WARNINGS" ]; then
    echo -e "$WARNINGS" >&2
fi

exit 0
