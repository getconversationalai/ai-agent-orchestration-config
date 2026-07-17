"""
Shared helper: detects uncommitted code-file changes in the MAIN working tree
regardless of where the caller currently is.

Used by:
  - sessionstart_drift_check.py (SessionStart)
  - pretooluse_git_drift_check.py (PreToolUse Bash matching git commit/push/merge)

When called from a worktree, it resolves the main tree's path via
`git worktree list --porcelain` (main is always the first entry) and runs
git status against that path — not against the caller's CWD.
"""
import os
import subprocess


CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".kt",
    ".css", ".scss", ".less", ".html", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml",
    ".sql", ".sh", ".bash",
}


def _run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, cwd=cwd).stdout
    except Exception:
        return ""


def get_main_tree_path():
    """Absolute path of the main working tree, or empty string if not in a repo."""
    output = _run(["git", "worktree", "list", "--porcelain"])
    if not output:
        return ""
    for line in output.splitlines():
        if line.startswith("worktree "):
            return line[len("worktree "):].strip()
    return ""


def get_code_drift(main_path):
    """List of (status, path) tuples for code-file changes in the main tree."""
    if not main_path:
        return []
    output = _run(["git", "-C", main_path, "status", "--porcelain"])
    drift = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        _, ext = os.path.splitext(path)
        if ext.lower() in CODE_EXTENSIONS:
            drift.append((status.strip(), path))
    return drift


def format_drift_message(drift, main_path):
    """Human-readable multi-line description of the drift."""
    if not drift:
        return ""
    lines = [f"Main working tree at `{main_path}` has {len(drift)} uncommitted code file(s):"]
    for status, path in drift[:15]:
        lines.append(f"  [{status}] {path}")
    if len(drift) > 15:
        lines.append(f"  ... and {len(drift) - 15} more")
    return "\n".join(lines)


def format_remediation():
    return (
        "These files are orphaned in the main tree and will not be committed by any worktree.\n"
        "Migrate them into a worktree via a PATCH — do NOT `git stash`: the stash stack is\n"
        "shared across ALL worktrees, so stash/pop can destroy another session's work.\n"
        "  1. git -C <main-tree-path> diff HEAD --binary > <main-tree-path>/migrate-drift.patch\n"
        "     (untracked new files are not in the patch — copy them into the worktree by path)\n"
        "  2. git -C <main-tree-path> worktree add ../.worktrees/<project>/<branch> -b <branch> dev\n"
        "  3. git -C <worktree-path> apply <main-tree-path>/migrate-drift.patch\n"
        "  4. Commit the migrated work from inside the worktree.\n"
        "  5. Only after that commit exists: discard the main-tree drift\n"
        "     (git -C <main-tree-path> checkout -- <paths>) and delete migrate-drift.patch.\n"
    )
