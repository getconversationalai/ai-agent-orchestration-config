"""
Global PostToolUse hook for Write tool.
Prints reminders after writing certain file types.
"""
import sys
import json


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        sys.exit(0)

    # Normalize path
    normalized = file_path.replace("\\", "/")

    # After writing a SQL migration file, remind about schema refresh
    if normalized.endswith(".sql") and ("migration" in normalized or "supabase/migrations" in normalized):
        print(
            "📋 Migration file written. After executing this migration, "
            "remember to refresh the schema (e.g., py scripts/get_schema.py) "
            "so your schema cache stays current."
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
