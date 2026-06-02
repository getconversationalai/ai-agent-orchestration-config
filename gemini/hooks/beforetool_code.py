"""
Global BeforeTool hook for file write/edit tools (Gemini CLI).
Blocks dangerous code patterns across ALL projects.
Equivalent to Claude's pretooluse_code.py.
"""
import sys
import json
import re


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    content = (
        tool_input.get("new_string", "")
        or tool_input.get("content", "")
        or tool_input.get("new_content", "")
        or tool_input.get("text", "")
    )

    if not content:
        allow()

    # Normalize path for consistent matching
    normalized_path = file_path.replace("\\", "/")
    is_code = any(normalized_path.endswith(ext) for ext in (
        ".ts", ".tsx", ".js", ".jsx", ".py", ".mjs", ".cjs"
    ))

    # --- HARD BLOCKS ---

    # Block hardcoded Stripe secret keys
    if re.search(r"sk_(live|test)_[a-zA-Z0-9]{10,}", content):
        block("Hardcoded Stripe secret key detected. Use environment variables instead.")

    # Block hardcoded AWS access keys
    if re.search(r"AKIA[0-9A-Z]{16}", content):
        block("Hardcoded AWS access key detected. Use environment variables instead.")

    # Block eval() in code files (security risk — code injection)
    if is_code and re.search(r"\beval\s*\(", content):
        if not re.search(r"//.*\beval\b|/\*.*\beval\b|\\.eval\b", content):
            block("eval() is a security risk (code injection). Use a safer alternative.")

    # Block debugger statements in code files
    if is_code and re.search(r"^\s*debugger\s*;?\s*$", content, re.MULTILINE):
        block("debugger statement detected. Remove it — it will pause execution in production.")

    allow()


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
