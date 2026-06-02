"""
UserPromptSubmit hook: injects a compact worktree-state block into Claude's
context on every prompt.

Purpose: make worktree-creation a PROACTIVE decision at task start (based on
injected state) rather than a REACTIVE correction after a PreToolUse deny.

State is recomputed fresh per prompt, so mid-session CWD changes are caught
automatically with no staleness and no false positives from a session-start
snapshot.
"""
import sys
import json
import os
import subprocess


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    repo_root = _run(["git", "rev-parse", "--show-toplevel"])
    if not repo_root:
        sys.exit(0)

    git_dir = _run(["git", "rev-parse", "--git-dir"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "(detached)"
    cwd = os.getcwd()
    project_name = os.path.basename(repo_root)

    in_worktree = "worktrees" in git_dir.replace("\\", "/").lower()

    if in_worktree:
        worktree_name = os.path.basename(git_dir.rstrip("/\\"))
        context = (
            f"[worktree state]\n"
            f"  CWD: {cwd}\n"
            f"  Location: worktree `{worktree_name}` (branch `{branch}`) — OK to edit code here.\n"
        )
    else:
        branches = _run(["git", "branch", "--list", "dev", "main"])
        base_branch = "dev" if "dev" in branches else "main"
        context = (
            f"[worktree state]\n"
            f"  CWD: {cwd}\n"
            f"  Location: MAIN working tree for `{project_name}` (branch `{branch}`).\n"
            f"  Code edits in the main tree are BLOCKED by pretooluse_main_worktree_guard.\n"
            f"  If this prompt requires code changes, create a worktree FIRST:\n"
            f"    git worktree add ../.worktrees/{project_name}/<branch-name> -b <branch-name> {base_branch}\n"
            f"  Use a specific branch name: feat/<scope>, fix/<scope>, refactor/<scope>, chore/<scope>.\n"
        )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
