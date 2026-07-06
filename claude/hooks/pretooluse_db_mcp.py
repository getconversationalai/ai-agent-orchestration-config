"""
PreToolUse hook for MCP database tools.

Guarantees that database WRITES always prompt for confirmation — even under
`defaultMode: "bypassPermissions"`, where the settings `ask` list may be
bypassed. Hooks fire regardless of permission mode, so a hook returning
`permissionDecision: "ask"` is the reliable way to enforce the DB-write
exception in the Autonomy / Permission Policy (see ~/.claude/CLAUDE.md).

Matches:
  - mcp__plugin_supabase_supabase__apply_migration  -> always a schema write
  - mcp__plugin_supabase_supabase__execute_sql      -> ask only on write SQL
    (SELECT-only reads run silently, matching the Bash execute_sql.py behavior)
"""
import sys
import json
import re


# Anything that mutates data or schema. COMMENT ON / VACUUM / REINDEX are
# included because they change catalog/physical state.
WRITE_KEYWORDS = (
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|"
    r"REPLACE|UPSERT|MERGE|VACUUM|REINDEX|CLUSTER|COMMENT\s+ON|"
    r"REFRESH\s+MATERIALIZED)\b"
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}

    # apply_migration is always a schema write against the live project.
    if tool.endswith("apply_migration"):
        ask("This applies a database migration (schema write) to the live project. Approve to proceed.")

    if tool.endswith("execute_sql"):
        # supabase MCP uses `query`; accept `sql` as a fallback.
        query = tool_input.get("query") or tool_input.get("sql") or ""
        if re.search(WRITE_KEYWORDS, query, re.IGNORECASE):
            ask("This executes a SQL WRITE against the live database. Approve to proceed.")

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
