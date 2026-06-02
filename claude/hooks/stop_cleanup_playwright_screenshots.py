#!/usr/bin/env python3
"""
Stop hook: prune stale Playwright screenshots from `.playwright-mcp/`.

Why: the Playwright MCP server writes PNGs/page snapshots/console logs to a
`.playwright-mcp/` folder. Without pruning, every verification run leaves
artifacts behind, bloating the repo and confusing later sessions. Files at
the project root (from runs that forgot to pass `filename`) are also caught
by the same broom.

Behavior:
  - Looks at every git worktree root reachable from CWD (so it covers main
    + active worktrees).
  - For each root, deletes files in `<root>/.playwright-mcp/` that match
    typical Playwright artifact names AND are older than RETENTION_SECONDS.
  - Also deletes loose verification PNGs at the root that match known
    Playwright naming patterns AND are older than RETENTION_SECONDS.
  - Silent on success. Prints a single line if anything was removed.

Retention window: 10 minutes. Recent screenshots survive long enough for the
user to glance at; older ones get swept.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RETENTION_SECONDS = 600  # 10 minutes

# Files inside `.playwright-mcp/` that are safe to prune by age.
MCP_FOLDER_PATTERNS = (
    re.compile(r".*\.png$", re.IGNORECASE),
    re.compile(r"^page-.*\.ya?ml$", re.IGNORECASE),
    re.compile(r"^console-.*\.log$", re.IGNORECASE),
)

# Loose PNGs at project root that look like Playwright verification dumps.
# We deliberately keep this conservative — only obvious verification names.
ROOT_LOOSE_PATTERNS = (
    re.compile(r"^(landing|hero|verify|screenshot|snap|page)[-_].*\.png$", re.IGNORECASE),
    re.compile(r"^(landing|hero|verify|screenshot|snap|page)\.png$", re.IGNORECASE),
)


def _git_worktree_roots(start: Path) -> list[Path]:
    """Return list of worktree roots; falls back to [start] if git fails."""
    try:
        out = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return [start]
        roots: list[Path] = []
        for line in out.stdout.splitlines():
            if line.startswith("worktree "):
                roots.append(Path(line[len("worktree ") :].strip()))
        return roots or [start]
    except Exception:
        return [start]


def _too_old(p: Path, now: float) -> bool:
    try:
        return (now - p.stat().st_mtime) > RETENTION_SECONDS
    except OSError:
        return False


def _prune_root(root: Path, now: float) -> int:
    removed = 0

    # 1. Inside .playwright-mcp/
    mcp_dir = root / ".playwright-mcp"
    if mcp_dir.is_dir():
        for entry in mcp_dir.iterdir():
            if not entry.is_file():
                continue
            if not any(rx.match(entry.name) for rx in MCP_FOLDER_PATTERNS):
                continue
            if not _too_old(entry, now):
                continue
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass

    # 2. Loose verification PNGs at the project root
    if root.is_dir():
        for entry in root.iterdir():
            if not entry.is_file():
                continue
            if not any(rx.match(entry.name) for rx in ROOT_LOOSE_PATTERNS):
                continue
            if not _too_old(entry, now):
                continue
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass

    return removed


def main() -> int:
    # Stop hook receives JSON on stdin; we don't need any of it, but read &
    # discard so the harness doesn't see a broken pipe.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    cwd = Path.cwd()
    now = time.time()
    total = 0
    seen: set[Path] = set()
    for root in _git_worktree_roots(cwd):
        try:
            real = root.resolve()
        except OSError:
            real = root
        if real in seen:
            continue
        seen.add(real)
        total += _prune_root(real, now)

    if total:
        print(f"[playwright-cleanup] pruned {total} stale screenshot(s)/snapshot(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
