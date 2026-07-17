"""
PreToolUse hook (Edit/Write): DENIES writes to code files in the MAIN working tree.

Instead of prompting the user per edit (which doesn't fix anything), this hook
denies the tool call and returns a detailed remediation playbook as the deny
reason. Claude reads the reason, creates a worktree, migrates any pending
changes, and retries the edit from inside the worktree — no user click needed.

Enforces the worktree-isolation rule from ~/.claude/CLAUDE.md.
"""
import sys
import json
import os
import subprocess
import tempfile


CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".kt",
    ".css", ".scss", ".less", ".html", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml",
    ".sql", ".sh", ".bash",
}

ALLOWED_FILENAMES = {
    "workboard.md", "memory.md", "project_scope.md",
    "claude.md", "gemini.md", "agents.md",
    ".gitignore", "package.json", "package-lock.json",
}


def _run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, cwd=cwd).stdout.strip()
    except Exception:
        return ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    # Session scratchpads / OS temp files are never project code -> allow.
    # (2026-07-17: this guard wrongly blocked a scratchpad .py write — HOME is
    # itself a git repo, so repo detection resolved it as a "main tree".)
    abs_target = os.path.normcase(os.path.abspath(file_path))
    temp_root = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
    if abs_target.startswith(temp_root + os.sep):
        sys.exit(0)

    # Target is inside a worktree directory -> allow
    normalized = file_path.replace("\\", "/").lower()
    if "/.worktrees/" in normalized:
        sys.exit(0)

    # Not in a git repo at all -> hook doesn't apply
    repo_root = _run(["git", "rev-parse", "--show-toplevel"])
    if not repo_root:
        sys.exit(0)

    # HOME itself is a (dotfiles) git repo, not a project tree. Global config
    # (~/.claude/**, ~/.ai-instructions/**) is edited live per the documented
    # capture.ps1 sync flow — the worktree-isolation rule does not apply there.
    if os.path.normcase(os.path.abspath(repo_root)) == os.path.normcase(os.path.abspath(os.path.expanduser("~"))):
        sys.exit(0)

    # Target file is OUTSIDE the CWD's repo (e.g. ~/.claude/hooks/*, other
    # projects, global config) -> hook doesn't apply. This rule protects the
    # CURRENT project's main tree, not arbitrary files anywhere on disk.
    abs_file = os.path.abspath(file_path).replace("\\", "/").lower().rstrip("/")
    abs_repo = os.path.abspath(repo_root).replace("\\", "/").lower().rstrip("/")
    if not (abs_file == abs_repo or abs_file.startswith(abs_repo + "/")):
        sys.exit(0)

    # Caller's CWD is a worktree -> allow
    git_dir = _run(["git", "rev-parse", "--git-dir"])
    if "worktrees" in git_dir.replace("\\", "/").lower():
        sys.exit(0)

    # Main working tree: allow non-code / allowlisted files
    basename = os.path.basename(file_path).lower()
    _, ext = os.path.splitext(file_path)
    if basename in ALLOWED_FILENAMES:
        sys.exit(0)
    if ext.lower() == ".md":
        sys.exit(0)
    if ext.lower() not in CODE_EXTENSIONS:
        sys.exit(0)

    # Code file in main working tree -> deny with playbook
    project_name = os.path.basename(repo_root) if repo_root else "<project>"
    branches = _run(["git", "branch", "--list", "dev", "main"])
    base_branch = "dev" if "dev" in branches else "main"

    reason = (
        f"BLOCKED: Edit/Write to code file `{basename}` in the MAIN working tree is not allowed.\n"
        f"Per ~/.claude/CLAUDE.md worktree-isolation rule, ALL code changes must happen inside a git worktree.\n"
        f"\n"
        f"REMEDIATION PLAYBOOK — do the following, then retry the edit using the worktree path.\n"
        f"DO NOT ask the user for permission; this is the required workflow.\n"
        f"\n"
        f"1. Check for existing uncommitted code drift in the main tree:\n"
        f"     git -C \"{repo_root}\" status --porcelain\n"
        f"   If any code files show as M/A/D, capture them as a PATCH. Do NOT `git stash` —\n"
        f"   the stash stack is shared across ALL worktrees and concurrent agent sessions:\n"
        f"     git -C \"{repo_root}\" diff HEAD --binary > \"{repo_root}/migrate-drift.patch\"\n"
        f"   (untracked new files are not in the patch — copy them into the worktree by path)\n"
        f"\n"
        f"2. Ensure the base branch `{base_branch}` is up to date:\n"
        f"     git -C \"{repo_root}\" fetch origin {base_branch}\n"
        f"     git -C \"{repo_root}\" merge origin/{base_branch}\n"
        f"\n"
        f"3. Pick a SPECIFIC branch name for THIS task — e.g. `feat/<scope>`, `fix/<scope>`,\n"
        f"   `refactor/<scope>`, `chore/<scope>`. Must be globally unique. Verify availability:\n"
        f"     git -C \"{repo_root}\" branch --list <branch-name>\n"
        f"     git -C \"{repo_root}\" worktree list\n"
        f"\n"
        f"4. Create the worktree OUTSIDE the project tree (this path is mandatory):\n"
        f"     git -C \"{repo_root}\" worktree add ../.worktrees/{project_name}/<branch-name> -b <branch-name> {base_branch}\n"
        f"   Resulting absolute path: <parent-of-{project_name}>/.worktrees/{project_name}/<branch-name>/\n"
        f"\n"
        f"5. Install dependencies in the worktree (node_modules is NOT shared):\n"
        f"     npm install --prefix <worktree-absolute-path>\n"
        f"   For monorepos, install in each package directory (e.g. server/, client/).\n"
        f"\n"
        f"6. If you captured a patch in step 1, apply it INSIDE the worktree:\n"
        f"     git -C <worktree-absolute-path> apply \"{repo_root}/migrate-drift.patch\"\n"
        f"   Copy any untracked new files in as well. Leave the main tree's drift in place\n"
        f"   until the worktree commit exists; only then discard it\n"
        f"   (git -C \"{repo_root}\" checkout -- <paths>) and delete migrate-drift.patch.\n"
        f"\n"
        f"7. NEVER `cd` into the worktree (CLAUDE.md forbids it — breaks project hooks).\n"
        f"   Use absolute paths for all subsequent Edit/Write/Bash calls against the worktree.\n"
        f"\n"
        f"8. Retry the edit using the WORKTREE path, not the main-tree path:\n"
        f"     Main-tree path (BLOCKED):  {file_path}\n"
        f"     Worktree path (USE THIS):  <worktree-absolute-path>/<relative-file-path>\n"
        f"\n"
        f"9. Register the work in WORKBOARD.md so other agents coordinate:\n"
        f"     py ~/.ai-instructions/tools/workboard.py register --feature \"<name>\" --tool claude \\n"
        f"         --plan <plan-path> --files \"<files>\" --branch <branch-name> --worktree <worktree-absolute-path>\n"
    )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
