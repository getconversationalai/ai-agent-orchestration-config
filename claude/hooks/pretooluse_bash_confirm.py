"""
DISABLED — second-pass confirmation hook (deprecated 2026-07).

This hook used to add a SECOND approval prompt on top of pretooluse_bash.py for
high-risk operations (push to main, DB writes, rebase, etc.). Under the Autonomy
/ Permission Policy (see ~/.claude/CLAUDE.md) every gated operation prompts
exactly ONCE, so double-confirmation is removed. pretooluse_bash.py is now the
sole single-confirm gate for Bash.

The hook is also unregistered in ~/.claude/settings.json. This file is kept as a
no-op (rather than deleted) so that anything still pointing at it fails safe —
it never blocks and never re-introduces a second prompt.
"""
import sys


def main():
    # No-op: single-confirm policy. Never emit a permission decision.
    sys.exit(0)


if __name__ == "__main__":
    main()
