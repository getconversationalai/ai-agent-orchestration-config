"""
Second-pass confirmation hook for dangerous Bash commands.
Fires AFTER the primary pretooluse_bash.py hook.
Together they create a two-step approval for high-risk operations.

Only double-confirms operations that affect shared state (main branch, database).
Feature branch operations (push, merge within worktrees) are single-confirm only.
"""
import sys
import json
import re


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    # --- DOUBLE-CHECK: Database writes (skip read-only commands like --help, SELECT-only) ---
    if "execute_sql.py" in command:
        # Skip if it's just a help/info command
        if re.search(r"--help|-h\b", command):
            pass
        else:
            write_keywords = r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|REPLACE|UPSERT)\b"
            sql_file_match = re.search(r"execute_sql\.py\s+[\"']?([^\s\"']+\.sql)", command)
            sql_content = None
            if sql_file_match:
                try:
                    with open(sql_file_match.group(1), "r") as f:
                        sql_content = f.read()
                except Exception:
                    sql_content = None
            # If the file isn't readable yet (e.g. heredoc-in-same-shell creates it),
            # fall back to scanning the command text itself. This keeps SELECT-only
            # reads friction-free per the tier-1 DATABASE GATE rule.
            haystack = sql_content if sql_content is not None else command
            if re.search(write_keywords, haystack, re.IGNORECASE):
                ask("DOUBLE CHECK: This will execute SQL writes against the live database. Are you sure?")

    # --- DOUBLE-CHECK: Push to main/master only (feature branch pushes are fine) ---
    if re.search(r"git\s+push\b", command):
        if re.search(r"\b(main|master)\b", command):
            ask("DOUBLE CHECK: This will push to MAIN. Are you sure?")

    # --- DOUBLE-CHECK: Merge to main/dev only (worktree merges are fine) ---
    if re.search(r"git\s+merge\b", command):
        if re.search(r"HEAD:(main|master|dev)\b", command) or \
           re.search(r"-C\s+[^.]*\s+merge\b", command):
            # Only double-confirm if merge target is main tree or main/dev branch
            c_match = re.search(r"git\s+-C\s+[\"']?([^\"'\s]+)", command)
            if c_match:
                target = c_match.group(1)
                if ".worktrees" not in target and "worktree" not in target.lower():
                    ask("DOUBLE CHECK: This merge targets the main working tree. Are you sure?")

    # --- DOUBLE-CHECK: update-ref to main/dev (new merge strategy) ---
    if re.search(r"git\s+update-ref\s+refs/heads/(main|master|dev)\b", command):
        ask("DOUBLE CHECK: This will move the main/dev branch pointer. Are you sure?")

    # --- DOUBLE-CHECK: History-rewriting operations ---
    if re.search(r"git\s+rebase\b", command):
        ask("DOUBLE CHECK: This will rebase and rewrite history. Are you sure?")

    if re.search(r"git\s+cherry-pick\b", command):
        ask("DOUBLE CHECK: This will cherry-pick commits. Are you sure?")

    if re.search(r"git\s+stash\s+(drop|clear)\b", command):
        ask("DOUBLE CHECK: This will permanently delete stashed work. Are you sure?")

    if re.search(r"git\s+tag\s+-d\b", command):
        ask("DOUBLE CHECK: This will delete a tag. Are you sure?")

    if re.search(r"git\s+remote\s+(set-url|remove|rename|rm)\b", command):
        ask("DOUBLE CHECK: This will modify remote configuration. Are you sure?")

    sys.exit(0)


def ask(reason):
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
