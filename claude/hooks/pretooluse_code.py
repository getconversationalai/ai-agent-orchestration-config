"""
Global PreToolUse hook for Edit/Write tools.
Blocks dangerous code patterns across ALL projects.
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
    file_path = tool_input.get("file_path", "")
    content = tool_input.get("new_string", "") or tool_input.get("content", "")

    if not content:
        sys.exit(0)

    # Normalize path for consistent matching
    normalized_path = file_path.replace("\\", "/")
    is_code = any(normalized_path.endswith(ext) for ext in (
        ".ts", ".tsx", ".js", ".jsx", ".py", ".mjs", ".cjs"
    ))

    # --- HARD BLOCKS ---

    # Block writes to SQL approval token files (pushsql gate)
    if re.search(r"(\.sql_approved|\.sql_pending)", normalized_path):
        block("NEVER write to .sql_approved or .sql_pending files. These are controlled by the pushsql approval system.")

    # Block hardcoded Stripe secret keys
    if re.search(r"sk_(live|test)_[a-zA-Z0-9]{10,}", content):
        block("Hardcoded Stripe secret key detected. Use environment variables instead.")

    # Block hardcoded AWS access keys
    if re.search(r"AKIA[0-9A-Z]{16}", content):
        block("Hardcoded AWS access key detected. Use environment variables instead.")

    # Block eval() in code files (security risk — code injection)
    if is_code and re.search(r"\beval\s*\(", content):
        # Allow common false positives: JSON.parse, window.eval references in comments
        if not re.search(r"//.*\beval\b|/\*.*\beval\b|\\.eval\b", content):
            block("eval() is a security risk (code injection). Use a safer alternative like JSON.parse(), Function constructor, or a proper parser.")

    # Block debugger statements in code files
    if is_code and re.search(r"^\s*debugger\s*;?\s*$", content, re.MULTILINE):
        block("debugger statement detected. Remove it before committing — it will pause execution in production.")

    sys.exit(0)


def block(reason):
    """Hard block - exit 2, stderr message."""
    print(f"BLOCKED: {reason}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
