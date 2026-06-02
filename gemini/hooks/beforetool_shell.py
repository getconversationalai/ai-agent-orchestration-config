"""
Global BeforeTool hook for shell commands (Gemini CLI).
Blocks dangerous or incorrect command patterns across ALL projects.
Equivalent to Claude's pretooluse_bash.py.
"""
import sys
import json
import re
import os
import time


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        allow()

    # --- HARD BLOCKS ---

    # Block ALL rm -rf on worktree paths (including node_modules inside worktrees).
    # On Windows, rm -rf / Remove-Item / shutil.rmtree follow NTFS junctions and can
    # destroy the .git directory. Use the cleanup script instead.
    if re.search(r"rm\s+.*-[a-zA-Z]*r[a-zA-Z]*\s+.*\.worktrees?\b", command) or \
       re.search(r"rm\s+.*-[a-zA-Z]*r[a-zA-Z]*\s+.*worktrees?\b", command):
        block("NEVER use rm -rf on worktree paths (including node_modules inside worktrees). "
              "On Windows, rm -rf follows NTFS junctions and can destroy the .git directory. "
              "Use the cleanup script: py ~/.ai-instructions/tools/worktree_cleanup.py <worktree-path>")

    # Block ALL direct git worktree remove — must use the cleanup script.
    if re.search(r"git\s+(?:-C\s+\S+\s+)?worktree\s+remove\b", command):
        block("NEVER run 'git worktree remove' directly. It follows NTFS junctions during "
              "directory deletion and can destroy the .git directory. "
              "Use the cleanup script: py ~/.ai-instructions/tools/worktree_cleanup.py <worktree-path>")

    # Block 'python ' and 'python3 ' (Windows uses py launcher)
    if re.match(r"^python\s+", command) or re.match(r"^python3\s+", command):
        block("Use 'py' instead of 'python' on Windows. Example: py scripts/my_script.py")

    # Block git push to main/master — match main/master as a standalone refspec target
    # but NOT inside branch names like "feat/main-page-redesign"
    if re.search(r"git\s+push\s+(?:-[a-zA-Z]+\s+)*\S+\s+(main|master)\s*$", command) or \
       re.search(r"git\s+push\s+(?:-[a-zA-Z]+\s+)*(main|master)\s*$", command) or \
       re.search(r"\S+:(main|master)\s*$", command):
        block("Never push directly to main/master. Use feature branches and PRs.")

    # Block git add on sensitive files
    if re.search(r"git\s+add\s+.*\.(env|pem|key|p12|pfx)\b", command):
        block("Never commit sensitive files (.env, .pem, .key). These must stay in .gitignore.")

    # Block git add on credentials files
    if re.search(r"git\s+add\s+.*(credentials|secrets|service.account)", command, re.IGNORECASE):
        block("Never commit credential files. These must stay in .gitignore.")

    # --- DENY with reason (schema freshness gate) ---

    # When running execute_sql.py with a migration file, check schema freshness
    if "execute_sql.py" in command and re.search(r"\.sql\b", command):
        schema_file = find_schema_file()
        if schema_file:
            try:
                mtime = os.path.getmtime(schema_file)
                age_minutes = (time.time() - mtime) / 60
                if age_minutes > 10:
                    block(
                        f"Schema file is {int(age_minutes)} minutes old. "
                        "Run your schema refresh command (e.g., py scripts/get_schema.py) "
                        "before executing migrations."
                    )
            except OSError:
                pass

    # Block worktree removal / branch deletion if WORKBOARD.md shows it as active/waiting
    wt_remove_match = re.search(
        r"git\s+(?:-C\s+\S+\s+)?worktree\s+remove\s+[\"']?([^\"'\s]+)", command
    )
    if wt_remove_match:
        check_workboard_active_worktree(worktree_path=wt_remove_match.group(1).strip("\"'"))

    branch_del_match = re.search(
        r"git\s+(?:-C\s+\S+\s+)?branch\s+-[dD]\s+[\"']?([^\"'\s]+)", command
    )
    if branch_del_match:
        check_workboard_active_worktree(branch_name=branch_del_match.group(1).strip("\"'"))

    allow()


def check_workboard_active_worktree(worktree_path=None, branch_name=None):
    """Block removal of worktrees/branches that are active or waiting in WORKBOARD.md."""
    if not os.path.isfile("WORKBOARD.md"):
        return
    try:
        with open("WORKBOARD.md", "r") as f:
            content = f.read()
    except Exception:
        return

    # Only check entries under "Active Work" section
    active_section = ""
    in_active = False
    for line in content.splitlines():
        if re.match(r"##\s+Active Work", line, re.IGNORECASE):
            in_active = True
            continue
        if in_active and re.match(r"##\s+", line):
            break
        if in_active:
            active_section += line + "\n"

    if not active_section:
        return

    entries = re.split(r"(?=^- \*\*)", active_section, flags=re.MULTILINE)
    for entry in entries:
        if not entry.strip():
            continue
        name_match = re.search(r"\*\*(.+?)\*\*", entry)
        feature_name = name_match.group(1) if name_match else "unknown"

        status_match = re.search(r"Status:\s*(active|waiting|blocked)", entry, re.IGNORECASE)
        if not status_match:
            continue

        if worktree_path:
            wt_match = re.search(r"Worktree:\s*(\S+)", entry)
            if wt_match:
                norm_entry = os.path.normpath(wt_match.group(1).rstrip(".")).lower()
                norm_target = os.path.normpath(worktree_path).lower()
                if norm_entry == norm_target:
                    block(
                        f"Worktree '{worktree_path}' belongs to active work "
                        f"'{feature_name}' (status: {status_match.group(1)}). "
                        "Only the agent that created this worktree should clean it up."
                    )

        if branch_name:
            branch_match = re.search(r"Branch:\s*(\S+)", entry)
            if branch_match and branch_match.group(1).rstrip(".") == branch_name:
                block(
                    f"Branch '{branch_name}' belongs to active work "
                    f"'{feature_name}' (status: {status_match.group(1)}). "
                    "Only the agent that created this branch should clean it up."
                )


def find_schema_file():
    """Look for supabase_full_schema.json in the current directory tree."""
    candidates = [
        "supabase_full_schema.json",
        os.path.join("supabase", "supabase_full_schema.json"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def block(reason):
    """Block the tool call — Gemini protocol: deny decision on stdout."""
    print(json.dumps({"decision": "deny", "reason": reason}))
    sys.exit(0)


def allow():
    """Allow the tool call."""
    print(json.dumps({"decision": "allow"}))
    sys.exit(0)


if __name__ == "__main__":
    main()
