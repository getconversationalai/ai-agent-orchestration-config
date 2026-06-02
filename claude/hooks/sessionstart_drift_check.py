"""
SessionStart hook: surfaces uncommitted code drift in the MAIN working tree at
the start of a session.

Informational — does not block. Outputs both:
  - systemMessage: shown to the user in the UI
  - hookSpecificOutput.additionalContext: injected into Claude's context so it
    can plan migration before taking any code actions.
"""
import sys
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main_tree_drift_check import (  # noqa: E402
    get_main_tree_path,
    get_code_drift,
    format_drift_message,
    format_remediation,
)


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    main_path = get_main_tree_path()
    if not main_path:
        sys.exit(0)

    drift = get_code_drift(main_path)
    if not drift:
        sys.exit(0)

    drift_msg = format_drift_message(drift, main_path)
    context = (
        f"[main-tree drift detected at session start]\n"
        f"{drift_msg}\n"
        f"\n"
        f"{format_remediation()}"
    )

    print(json.dumps({
        "systemMessage": (
            f"Main-tree drift: {len(drift)} uncommitted code file(s) in {main_path}. "
            f"See injected context for migration steps."
        ),
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        },
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
