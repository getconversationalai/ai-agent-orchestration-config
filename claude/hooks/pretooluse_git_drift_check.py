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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main_tree_drift_check import (  # noqa: E402
    get_main_tree_path,
    get_code_drift,
    format_drift_message,
    format_remediation,
)


PROTECTED_BRANCHES = ("main", "master", "dev")


def classify(command: str):
    """Return ('ask' | 'deny' | None, short_label) based on command content."""
    c = command.strip()
    for sep in ("&&", ";", "||", "|"):
        if sep in c:
            c = c.split(sep)[-1].strip()

    if not re.search(r"\bgit\b", c):
        return None, ""

    m = re.search(r"\bgit\s+update-ref\s+refs/heads/(\S+)", c)
    if m:
        target = m.group(1)
        if target in PROTECTED_BRANCHES:
            return "deny", f"update-ref to protected branch `{target}`"
        return None, ""

    if re.search(r"\bgit\s+merge\b", c):
        return "deny", "merge"

    if re.search(r"\bgit\s+push\b", c):
        return "ask", "push"

    if re.search(r"\bgit\s+commit\b", c):
        return "ask", "commit"

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
        f"Why this matters:\n"
        f"  - commit / push: the drifted files are orphaned and will NOT be included in this operation.\n"
        f"  - merge / update-ref to protected branch: ~/.claude/CLAUDE.md's merge-back protocol calls\n"
        f"    `git -C <main-tree> checkout -f` after update-ref. That WILL DESTROY these uncommitted\n"
        f"    changes.\n"
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
