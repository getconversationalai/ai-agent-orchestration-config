"""
Global AfterTool hook for file write tools (Gemini CLI).
Prints reminders after writing certain file types.
Equivalent to Claude's posttooluse_write.py.
"""
import sys
import json


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")

    if not file_path:
        sys.exit(0)

    normalized = file_path.replace("\\", "/")

    if normalized.endswith(".sql") and ("migration" in normalized or "supabase/migrations" in normalized):
        print(
            "Migration file written. After executing this migration, "
            "refresh the schema cache (e.g., py scripts/get_schema.py).",
            file=sys.stderr
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
