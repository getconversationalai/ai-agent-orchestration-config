"""
PreToolUse hook (Bash): if the Bash command is a git commit/push/merge or
update-ref to a protected branch, AND the main working tree has uncommitted
code drift, gate the operation.

Risk tiers:
  - commit, push                                -> ask (drift is orphaned but safe)
  - merge, update-ref to main/master/dev        -> deny (drift can be destroyed
                                                   by the merge-back protocol's
                                                   `git checkout -f` step)
"""
import sys
import json
import os
import re
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main_tree_drift_check import (  # noqa: E402
    get_main_tree_path,
    get_code_drift,
    format_drift_message,
    format_remediation,
)


PROTECTED_BRANCHES = ("main", "master", "dev")


def _current_branch(command: str):
    """Resolve the branch the command operates on (honoring a `-C <dir>` flag),
    so we can tell whether a `git merge` actually UPDATES a protected branch."""
    c_match = re.search(r"git\s+-C\s+['\"]?([^'\"\s]+)['\"]?\s+", command)
    target_dir = c_match.group(1) if c_match else "."
    try:
        result = subprocess.run(
            ["git", "-C", target_dir, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def classify(command: str):
    """Return ('deny' | None, short_label) based on command content.

    Only DENY operations that UPDATE a protected branch while the main tree has
    drift — the merge-back protocol's `git checkout -f` on the main tree would
    destroy that uncommitted drift (real, irreversible data loss). This is a
    hard-block category the user chose to keep.

    Routine `git commit` and feature-branch `git push` are NOT gated here — they
    run silently per the Autonomy / Permission Policy. Feature-branch merges are
    handled by the normal single merge confirmation in pretooluse_bash.py, so
    they are not hard-denied here either.
    """
    c = command.strip()
    for sep in ("&&", ";", "||", "|"):
        if sep in c:
            c = c.split(sep)[-1].strip()

    if not re.search(r"\bgit\b", c):
        return None, ""

    m = re.search(r"\bgit\s+(?:-C\s+\S+\s+)?update-ref\s+refs/heads/(\S+)", c)
    if m:
        target = m.group(1)
        if target in PROTECTED_BRANCHES:
            return "deny", f"update-ref to protected branch `{target}`"
        return None, ""

    # A merge only endangers main-tree drift when it updates a PROTECTED branch
    # (i.e. the current branch is main/master/dev). Merges into a feature branch
    # never trigger the destructive checkout -f, so let them through.
    # `(?:-C\s+\S+\s+)?` tolerates the `git -C <path> merge` form.
    if re.search(r"\bgit\s+(?:-C\s+\S+\s+)?merge\b", c):
        cur = _current_branch(command)
        if cur in PROTECTED_BRANCHES:
            return "deny", f"merge into protected branch `{cur}`"
        return None, ""

    return None, ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    command = data.get("tool_input", {}).get("command", "")
    if not command:
        sys.exit(0)

    decision, label = classify(command)
    if not decision:
        sys.exit(0)

    main_path = get_main_tree_path()
    if not main_path:
        sys.exit(0)

    drift = get_code_drift(main_path)
    if not drift:
        sys.exit(0)

    reason = (
        f"Main-tree drift detected before `git {label}`.\n"
        f"\n"
        f"{format_drift_message(drift, main_path)}\n"
        f"\n"
        f"Why this is blocked:\n"
        f"  This operation updates a protected branch. ~/.claude/CLAUDE.md's merge-back protocol\n"
        f"  calls `git -C <main-tree> checkout -f` after update-ref — that WILL DESTROY the\n"
        f"  uncommitted changes above. Migrate the drift into a worktree first.\n"
        f"\n"
        f"{format_remediation()}"
    )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
