"""
Global PostToolUse hook for Bash commands.
Prints reminders after certain operations complete.
"""
import sys
import json


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    # After creating a worktree, remind to install dependencies
    if "git worktree add" in command:
        print(
            "📋 Worktree created. Install dependencies before building/typechecking:\n"
            "   npm install --prefix <worktree-path>\n"
            "   (or: npm --prefix <worktree-path>/server install  for server-only projects)"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
