"""
UserPromptSubmit hook: pushsql approval gate.

When the user types exactly "pushsql" and there is a pending SQL command
in /tmp/.pending_sql, this hook creates the approval token at /tmp/.sql_approved
so the next execute_sql.py call will be allowed through.
"""
import sys
import json
import os


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Get the user's message
    message = data.get("message", "").strip()

    # Only respond to the exact command
    if message != "pushsql":
        sys.exit(0)

    claude_dir = os.path.join(os.path.expanduser("~"), ".claude")
    pending_path = os.path.join(claude_dir, ".sql_pending")
    token_path = os.path.join(claude_dir, ".sql_approved")

    if not os.path.exists(pending_path):
        result = {
            "systemMessage": "No pending SQL command to approve."
        }
        print(json.dumps(result))
        sys.exit(0)

    # Read the pending command for display
    try:
        with open(pending_path, "r") as f:
            pending_cmd = f.read().strip()
    except OSError:
        pending_cmd = "(could not read)"

    # Create approval token
    try:
        with open(token_path, "w") as f:
            f.write("approved")
    except OSError as e:
        result = {
            "systemMessage": f"Failed to create approval token: {e}"
        }
        print(json.dumps(result))
        sys.exit(1)

    # Delete pending file
    try:
        os.remove(pending_path)
    except OSError:
        pass

    result = {
        "systemMessage": f"SQL APPROVED. Claude can now retry the command:\n  {pending_cmd}"
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
