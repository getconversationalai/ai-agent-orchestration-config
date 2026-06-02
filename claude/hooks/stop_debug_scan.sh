#!/bin/bash
# Global Stop hook: scan git diff for debug code left behind.
# Warns (does not block) if console.log or debugger statements are found in changed lines.

# Only run in git repos
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    exit 0
fi

# Get added lines (+ lines) from staged and unstaged changes in code files
DEBUG_LINES=$(git diff --unified=0 -- '*.ts' '*.tsx' '*.js' '*.jsx' '*.py' '*.mjs' '*.cjs' 2>/dev/null \
    | grep -E '^\+' \
    | grep -v '^\+\+\+' \
    | grep -iE '(console\.log\(|^\+\s*debugger\s*;?\s*$)' \
    | head -5)

if [ -n "$DEBUG_LINES" ]; then
    echo "⚠️ Debug code detected in your changes:"
    echo "$DEBUG_LINES" | sed 's/^\+/  /'
    echo ""
    echo "Remove console.log() and debugger statements before committing."
fi
