"""
Global PreToolUse hook for Bash commands.
Blocks dangerous or incorrect command patterns across ALL projects.
"""
import sys
import json
import re
import os
import subprocess


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    # ============================================================
    # HARD BLOCKS — these NEVER proceed, no override possible
    # ============================================================

    # Block rm -rf on .git directories
    if re.search(r"rm\s+.*-[a-zA-Z]*r[a-zA-Z]*f?\s+.*\.git\b", command) or \
       re.search(r"rm\s+.*-[a-zA-Z]*f[a-zA-Z]*r?\s+.*\.git\b", command):
        block("NEVER delete .git directories. This destroys the entire repository.")

    # Block ALL rm -rf on worktree paths (including node_modules inside worktrees).
    # On Windows, rm -rf / Remove-Item / shutil.rmtree follow NTFS junctions and can
    # destroy the .git directory. Use the cleanup script instead.
    if re.search(r"rm\s+.*-[a-zA-Z]*r[a-zA-Z]*\s+.*\.worktrees?\b", command) or \
       re.search(r"rm\s+.*-[a-zA-Z]*r[a-zA-Z]*\s+.*worktrees?\b", command):
        block("NEVER use rm -rf on worktree paths (including node_modules inside worktrees). "
              "On Windows, rm -rf follows NTFS junctions and can destroy the .git directory. "
              "Use the cleanup script instead: py ~/.ai-instructions/tools/worktree_cleanup.py <worktree-path>")

    # Block ALL direct git worktree remove — must use the cleanup script.
    # git worktree remove does its own recursive directory deletion which follows
    # NTFS junctions (created by npm workspaces) and can destroy .git.
    if re.search(r"git\s+(?:-C\s+\S+\s+)?worktree\s+remove\b", command):
        block("NEVER run 'git worktree remove' directly. It follows NTFS junctions during "
              "directory deletion and can destroy the .git directory. "
              "Use the cleanup script instead: py ~/.ai-instructions/tools/worktree_cleanup.py <worktree-path>\n"
              "Or to clean all merged worktrees: py ~/.ai-instructions/tools/worktree_cleanup.py --all-merged")

    branch_del_for_wb = re.search(
        r"git\s+(?:-C\s+\S+\s+)?branch\s+-[dD]\s+[\"']?([^\"'\s]+)", command
    )
    if branch_del_for_wb:
        check_workboard_active_worktree(branch_name=branch_del_for_wb.group(1).strip("\"'"))

    # Verify .git exists before any destructive operation
    if re.search(r"rm\s+.*-[a-zA-Z]*r[a-zA-Z]*", command):
        git_dir = find_git_root()
        if git_dir and not is_healthy_git(git_dir):
            block(
                f".git at {git_dir} is not a valid repo or worktree pointer — possibly "
                "corrupted. STOP and investigate manually before running destructive "
                "commands. If this is a worktree, check the .git file still holds its "
                "'gitdir:' pointer. Do NOT blindly re-init."
            )

    # Block 'python ' and 'python3 ' (Windows uses py launcher)
    if re.match(r"^python\s+", command) or re.match(r"^python3\s+", command):
        block("Use 'py' instead of 'python' on Windows. Example: py scripts/my_script.py")

    # Block git add on sensitive files
    if re.search(r"git\s+add\s+.*\.(env|pem|key|p12|pfx)\b", command):
        block("Never commit sensitive files (.env, .pem, .key). These must stay in .gitignore.")

    if re.search(r"git\s+add\s+.*(credentials|secrets|service.account)", command, re.IGNORECASE):
        block("Never commit credential files. These must stay in .gitignore.")

    # ============================================================
    # ASK USER — require confirmation before proceeding
    # ============================================================

    # NOTE: bare `cd` no longer prompts. Per the Autonomy / Permission Policy
    # (see ~/.claude/CLAUDE.md), only main-branch git ops, history/loss git ops,
    # and DB writes prompt. `cd` drift is a workflow nudge, not one of those
    # categories, so it now runs silently.

    # --- Git merge checks (most specific first) ---
    if re.search(r"git\s+.*merge\b", command):
        # Check 0 (HARD BLOCK — runs before any `ask()` so it can't be short-circuited):
        # If the current branch is a base branch, this merge ADVANCES the base
        # pointer — require a preceding `git fetch` per the Git Merge rule in
        # ~/.claude/CLAUDE.md.
        current_for_fetch_check = get_current_branch_for_command(command)
        if current_for_fetch_check in ("main", "master", "dev"):
            require_fetch_before(command, current_for_fetch_check, "git merge")

        # Check 1: Is this merge happening in the main working tree?
        c_flag_match = re.search(r"git\s+-C\s+[\"']?([^\"'\s]+)[\"']?\s+.*merge", command)
        if c_flag_match:
            target_dir = c_flag_match.group(1)
            if ".worktrees" not in target_dir and "worktree" not in target_dir.lower():
                ask(
                    "⚠️ This git merge targets the MAIN working tree, not a worktree. "
                    "Merges should happen inside worktrees. Use 'git update-ref' to "
                    "update the base branch ref instead. "
                    "Are you sure you want to merge in the main working tree?"
                )
        elif not re.search(r"git\s+-C\s+", command):
            # No -C flag — runs in CWD, check if CWD is the main working tree
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and "worktrees" not in result.stdout.strip():
                    ask(
                        "⚠️ This git merge runs in the MAIN working tree (CWD is not a worktree). "
                        "Merges should happen inside worktrees. Use 'git update-ref' to "
                        "update the base branch ref instead. "
                        "Are you sure you want to merge in the main working tree?"
                    )
            except Exception:
                pass

        # General merge confirmation (ANY branch). Per the Autonomy / Permission
        # Policy, merge always prompts. This single ask covers feature-branch
        # merges AND merge-from-main-into-current alike — no second workboard
        # prompt on top of it (keeps it to one confirmation).
        ask("git merge modifies branch history. Approve to proceed.")

    # --- Git push checks (differentiated: main=ask, feature branches=allow) ---
    # NOTE: `(?:-C\s+\S+\s+)?` tolerates the `git -C <path> push ...` form this
    # user relies on (never `cd`s — always `git -C <worktree>`). Without it, a
    # push to main via `-C` would slip past the gate entirely.
    if re.search(r"git\s+(?:-C\s+\S+\s+)?push\b", command):
        # Push to main/master — always ask
        # Match main/master as a standalone refspec (e.g., "git push origin main", "git push -u origin main")
        # but NOT inside branch names like "feat/main-page-redesign"
        push_to_base = (
            re.search(r"git\s+(?:-C\s+\S+\s+)?push\s+(?:-[a-zA-Z]+\s+)*\S+\s+(main|master)\s*$", command)
            or re.search(r"git\s+(?:-C\s+\S+\s+)?push\s+(?:-[a-zA-Z]+\s+)*(main|master)\s*$", command)
            or re.search(r"\S+:(main|master)\s*$", command)
        )
        if push_to_base:
            # Per ~/.claude/CLAUDE.md Git Merge rule, fetch must precede.
            require_fetch_before(command, push_to_base.group(1), "git push")
            ask("⚠️ git push targeting MAIN/MASTER. This affects the shared main branch. Approve to proceed.")
        # Bare git push (no branch specified) — ask to be safe
        elif re.search(r"git\s+(?:-C\s+\S+\s+)?push\s*$", command) or \
             re.search(r"git\s+(?:-C\s+\S+\s+)?push\s+-[a-zA-Z]+\s*$", command):
            ask(
                "git push with no explicit branch specified. "
                "Verify you're not pushing to main. Approve to proceed."
            )
        # Push to feature branch — ALLOWED without confirmation (remote backup)

    # --- Git pull that pulls MAIN into the current branch — ask (autonomy policy) ---
    # A pull whose SOURCE ref is main/master merges the base branch into the branch
    # you're on. Bare `git pull` on a feature branch merges that branch's OWN
    # upstream (not main), so it stays silent.
    if re.search(r"git\s+(?:-C\s+\S+\s+)?pull\b", command) and \
       re.search(r"(?:^|\s)(origin/)?(main|master)\b", command):
        ask("⚠️ git pull is merging MAIN into your current branch. Approve to proceed.")

    # --- Git update-ref to main/dev (new merge strategy needs confirmation) ---
    update_ref_match = re.search(r"git\s+(?:-C\s+\S+\s+)?update-ref\s+refs/heads/(main|master|dev)\b", command)
    if update_ref_match:
        # Per ~/.claude/CLAUDE.md Git Merge rule, fetch must precede.
        require_fetch_before(command, update_ref_match.group(1), "git update-ref")
        ask(
            "git update-ref will move the main/dev branch pointer. "
            "This is equivalent to merging into main. Approve to proceed."
        )

    # --- Block writes to SQL approval token files (prevents Claude from forging tokens) ---
    # --- Database SQL execution — require user confirmation for WRITES only ---
    if "execute_sql.py" in command:
        write_keywords = ["INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "GRANT", "REVOKE", "TRUNCATE"]
        # Check the full command text for SQL content (handles heredoc patterns)
        command_upper = command.upper()
        is_write = any(kw in command_upper for kw in write_keywords)
        if not is_write:
            # Also try reading the SQL file if it already exists
            sql_file_match = re.search(r"execute_sql\.py\s+[\"']?([^\s\"']+)", command)
            if sql_file_match:
                sql_file = sql_file_match.group(1)
                try:
                    with open(sql_file, "r") as f:
                        sql_content = f.read().upper()
                    is_write = any(kw in sql_content for kw in write_keywords)
                except Exception:
                    pass  # File doesn't exist yet or can't read — check command text only
        if is_write:
            ask("SQL WRITE operation detected. Confirm to proceed.")

    # --- Branch deletion of unpushed branches ---
    branch_delete_match = re.search(
        r"git\s+(?:-C\s+\S+\s+)?branch\s+-[dD]\s+[\"']?([^\"'\s]+)", command
    )
    if branch_delete_match:
        branch_name = branch_delete_match.group(1).strip("\"'")
        try:
            result = subprocess.run(
                ["git", "branch", "-r", "--list", f"origin/{branch_name}"],
                capture_output=True, text=True, timeout=5,
            )
            if not result.stdout.strip():
                ask(
                    f"⚠️ Branch '{branch_name}' has NOT been pushed to remote. "
                    "Deleting it will permanently lose all commits on it. "
                    "Push the branch first to preserve work, or approve to delete."
                )
        except Exception:
            pass

    # --- Other destructive git operations ---
    if re.search(r"git\s+rebase\b", command):
        ask("git rebase rewrites history. Approve to proceed.")

    if re.search(r"git\s+cherry-pick\b", command):
        ask("git cherry-pick modifies branch history. Approve to proceed.")

    if re.search(r"git\s+stash\s+(drop|clear)\b", command):
        ask("git stash drop/clear permanently deletes stashed work. Approve to proceed.")

    if re.search(r"git\s+tag\s+-d\b", command):
        ask("git tag deletion affects the repository. Approve to proceed.")

    if re.search(r"git\s+remote\s+(set-url|remove|rename|rm)\b", command):
        ask("git remote modifications change repository configuration. Approve to proceed.")

    # ============================================================
    # npm-workspace install location guard
    # ============================================================
    # In an npm workspaces monorepo, running `npm install` from a workspace
    # subdirectory (e.g. client/, server/, affiliate-portal/) creates a
    # sub-lockfile that conflicts with the root package-lock.json and causes
    # arborist crashes. This block stops three failure modes:
    #
    #   (A) An inline cd into a subpkg followed by an install
    #       e.g. `cd client && npm install`, `(cd server; npm i foo)`
    #   (B) `--prefix <subpkg>` pointing into a workspace subdir
    #       e.g. `npm install --prefix server foo`
    #   (C) The shell's CWD is already inside a workspace subdir at the time
    #       a bare `npm install` runs
    #
    # All three are bypassed if `--workspace=<name>` or `-w <name>` is
    # present (that's the correct way to scope a workspace install).
    check_npm_install_in_subpkg(command)

    sys.exit(0)


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

    # Parse active entries — look for lines with Branch: or Worktree: fields
    # that match what's being removed, and whose status is active or waiting
    entries = re.split(r"(?=^- \*\*)", active_section, flags=re.MULTILINE)
    for entry in entries:
        if not entry.strip():
            continue
        # Extract feature name
        name_match = re.search(r"\*\*(.+?)\*\*", entry)
        feature_name = name_match.group(1) if name_match else "unknown"

        # Check status — skip completed entries that haven't been moved yet
        status_match = re.search(r"Status:\s*(active|waiting|blocked)", entry, re.IGNORECASE)
        if not status_match:
            continue

        # Match by worktree path
        if worktree_path:
            wt_match = re.search(r"Worktree:\s*(\S+)", entry)
            if wt_match:
                entry_path = wt_match.group(1).rstrip(".")
                # Normalize paths for comparison
                norm_entry = os.path.normpath(entry_path).lower()
                norm_target = os.path.normpath(worktree_path).lower()
                if norm_entry == norm_target:
                    block(
                        f"BLOCKED: Worktree '{worktree_path}' belongs to active work "
                        f"'{feature_name}' (status: {status_match.group(1)}). "
                        "Only the agent that created this worktree should clean it up, "
                        "and only after its work is complete."
                    )

        # Match by branch name
        if branch_name:
            branch_match = re.search(r"Branch:\s*(\S+)", entry)
            if branch_match:
                entry_branch = branch_match.group(1).rstrip(".")
                if entry_branch == branch_name:
                    block(
                        f"BLOCKED: Branch '{branch_name}' belongs to active work "
                        f"'{feature_name}' (status: {status_match.group(1)}). "
                        "Only the agent that created this branch should clean it up, "
                        "and only after its work is complete."
                    )


def fetch_precedes_in_command(command, base_branch):
    """True if a `git fetch` covering base_branch appears in a segment preceding
    the operation in the same Bash invocation. Splits on `&&` and `;`.

    A `git pull` segment also counts (it performs a fetch). `--all`,
    `git fetch <remote>` (no branch), and an explicit `<base_branch>` ref all
    satisfy the requirement — being too strict about the exact branch token
    produces false positives on the most common idiom.

    Set ALLOW_UNFETCHED_BASE_MERGE=1 to bypass (offline work, recovery flows).
    """
    if os.environ.get("ALLOW_UNFETCHED_BASE_MERGE") == "1":
        return True
    segments = re.split(r"\s*(?:&&|;)\s*", command)
    if len(segments) < 2:
        return False
    # The operation we're gating is in the final segment(s). Every earlier
    # segment is a candidate "preceding fetch."
    for seg in segments[:-1]:
        seg = seg.strip()
        # `git pull ...` includes a fetch
        if re.match(r"git\s+(?:-C\s+\S+\s+)?pull\b", seg):
            if "--all" in seg or re.search(rf"\b{re.escape(base_branch)}\b", seg) \
               or re.match(r"git\s+(?:-C\s+\S+\s+)?pull(\s+\S+)?\s*$", seg):
                return True
            continue
        if not re.match(r"git\s+(?:-C\s+\S+\s+)?fetch\b", seg):
            continue
        if "--all" in seg:
            return True
        if re.search(rf"\b{re.escape(base_branch)}\b", seg):
            return True
        # `git fetch` or `git fetch <remote>` (no explicit branch) fetches every
        # configured ref from the remote — that includes the base branch.
        if re.match(r"git\s+(?:-C\s+\S+\s+)?fetch(\s+\S+)?\s*$", seg):
            return True
    return False


def require_fetch_before(command, base_branch, op_description):
    """Hard-block the command if it doesn't include a preceding `git fetch` for
    base_branch. Enforces the global Git Merge rule in ~/.claude/CLAUDE.md."""
    if fetch_precedes_in_command(command, base_branch):
        return
    suggestion_op = op_description.split()[1] if " " in op_description else op_description
    block(
        f"Missing `git fetch` before {op_description} targeting `{base_branch}`. "
        f"The base branch may have moved on origin since your last fetch — advancing "
        f"`{base_branch}` (or pushing it) without a fresh fetch can silently leave new "
        f"commits behind or produce a stale merge.\n\n"
        f"Run as a single compound command so the fetch is structurally guaranteed to "
        f"precede the operation:\n"
        f"    git fetch origin {base_branch} && {suggestion_op} ...\n\n"
        f"To bypass (offline work, recovery flows), set ALLOW_UNFETCHED_BASE_MERGE=1 "
        f"in the environment."
    )


def get_current_branch_for_command(command):
    """Resolve the current branch in the directory the command will run in.
    Mirrors the -C-flag handling used elsewhere in this hook."""
    c_match = re.search(r"git\s+-C\s+['\"]?([^'\"\s]+)['\"]?\s+", command)
    target_dir = c_match.group(1) if c_match else "."
    try:
        result = subprocess.run(
            ["git", "-C", target_dir, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def check_workboard_active_agents():
    """Check WORKBOARD.md for active agents and warn if any exist."""
    if os.path.isfile("WORKBOARD.md"):
        try:
            with open("WORKBOARD.md", "r") as f:
                content = f.read()
            active_count = content.lower().count("status: active")
            if active_count > 0:
                ask(
                    f"⚠️ WORKBOARD.md shows {active_count} active agent(s) still working. "
                    "Merging to main/dev while other agents are active may cause conflicts. "
                    "Approve to proceed."
                )
        except Exception:
            pass


def is_healthy_git(git_path):
    """Healthy if .git is a directory (normal checkout) OR a file that is a valid
    worktree pointer (starts with 'gitdir:'). Anything else is treated as corrupt."""
    if os.path.isdir(git_path):
        return True
    if os.path.isfile(git_path):
        try:
            with open(git_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(8).startswith("gitdir:")
        except OSError:
            return False
    return False


def find_git_root():
    """Walk up from CWD to find the .git directory."""
    current = os.getcwd()
    while True:
        git_path = os.path.join(current, ".git")
        if os.path.exists(git_path):
            return git_path
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


# Regexes for the install-shaped npm subcommands. We DO NOT intercept
# `npm run`, `npm exec`, `npm test`, etc. — those don't touch lockfiles.
_NPM_INSTALL_VERBS = r"(?:install|i|add|ci|uninstall|remove|rm|un|update|up|upgrade)"


def _has_workspace_flag(cmd):
    """True if `--workspace=<name>` or `-w <name>` appears in the command."""
    return bool(
        re.search(r"--workspace(?:s)?(?:=|\s+)\S", cmd)
        or re.search(r"(?:^|\s)-w\s+\S", cmd)
    )


def _resolve_workspace_subpkgs(repo_root):
    """Return the set of directory names that are npm workspaces in this repo.

    Reads the `workspaces` field from <repo_root>/package.json. Supports both
    forms documented by npm:
      - Plain object form: ["client", "server", "packages/*"]
      - Object form with .packages: {"packages": ["client", "server"]}
    Glob patterns like "packages/*" are expanded by listing the parent
    directory and including each direct child that has a package.json.

    Returns ({"<leaf-name>",...}, repo_root) where leaf-name is what gets
    matched against `cd <subpkg>` and the shell's CWD basename.
    """
    pkg_path = os.path.join(repo_root, "package.json")
    if not os.path.isfile(pkg_path):
        return set()
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()

    raw = data.get("workspaces")
    if not raw:
        return set()
    # Object form: {"packages": [...], "nohoist": [...]}
    if isinstance(raw, dict):
        raw = raw.get("packages", [])
    if not isinstance(raw, list):
        return set()

    leaves = set()
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            continue
        entry = entry.strip().rstrip("/\\")

        if "*" in entry or "?" in entry:
            # Glob-shape: expand by listing direct children of the prefix dir
            # that contain a package.json. Anything fancier (recursive globs,
            # negations) is rare and not worth pulling in fnmatch for.
            prefix = entry.split("*", 1)[0].rstrip("/\\").rstrip("/")
            base = os.path.join(repo_root, prefix) if prefix else repo_root
            if os.path.isdir(base):
                try:
                    for name in os.listdir(base):
                        child = os.path.join(base, name)
                        if os.path.isdir(child) and os.path.isfile(os.path.join(child, "package.json")):
                            leaves.add(name.lower())
                except OSError:
                    pass
        else:
            # Plain path: take the LEAF, since that's what `cd <leaf>` and the
            # shell CWD basename produce. "packages/foo" -> "foo".
            leaves.add(os.path.basename(entry).lower())

    return leaves


def _path_is_workspace_subpkg(path, subpkg_names):
    """True if a path's leaf component matches any known workspace subpkg name."""
    if not path or not subpkg_names:
        return False
    cleaned = path.strip().strip("'\"").rstrip("/\\")
    leaf = os.path.basename(cleaned).lower()
    return leaf in subpkg_names


def _get_workspace_repo_info():
    """Returns (repo_root, subpkg_names) if CWD is inside an npm-workspaces repo,
    or (None, set()) otherwise. Single source of truth for `is this a workspaces
    repo, and what are the workspace leaf names?` so we don't read package.json
    twice per hook invocation."""
    git_root = find_git_root()
    if not git_root:
        return None, set()
    repo_root = os.path.dirname(git_root) if os.path.basename(git_root) == ".git" else git_root
    leaves = _resolve_workspace_subpkgs(repo_root)
    if not leaves:
        return None, set()
    return repo_root, leaves


def check_npm_install_in_subpkg(command):
    """Block bad-CWD npm install patterns in workspace monorepos.
    See the call site for the full rationale."""
    # Only intercept install-shaped npm commands.
    if not re.search(rf"\bnpm\s+{_NPM_INSTALL_VERBS}\b", command):
        return

    # Workspace flag present? Then the install is correctly scoped — allow.
    if _has_workspace_flag(command):
        return

    # Only enforce in workspace monorepos. Resolve the actual workspace leaf
    # names from the repo's package.json so we work in any monorepo, not just
    # those using client/server/affiliate-portal naming.
    repo_root, subpkg_names = _get_workspace_repo_info()
    if not subpkg_names:
        return

    # (A) Inline cd into a subpkg, then npm install. Catches both:
    #       cd client && npm install ...
    #       (cd ./server && npm install ...)
    #     The cd target's leaf component must match a known workspace subpkg.
    cd_match = re.search(
        rf"\bcd\s+['\"]?([^'\"\s;&|()]+)['\"]?\s*(?:&&|;)\s*[^;&|]*\bnpm\s+{_NPM_INSTALL_VERBS}\b",
        command,
    )
    if cd_match and _path_is_workspace_subpkg(cd_match.group(1), subpkg_names):
        leaf = os.path.basename(cd_match.group(1).strip().strip(chr(34)+chr(39)).rstrip('/\\'))
        block(
            f"npm install inside `{cd_match.group(1)}` would create a sub-lockfile that "
            f"conflicts with the workspace root's package-lock.json (arborist crash).\n"
            "Run from the repo root instead, scoped with --workspace:\n"
            f"    npm install --workspace={leaf} <pkg>\n"
            "Or to install all workspace deps:\n"
            "    npm install   (from the repo root)"
        )

    # (B) --prefix <subpkg> or --prefix=<subpkg> pointing at a workspace subdir.
    prefix_match = re.search(r"--prefix(?:=|\s+)['\"]?([^'\"\s]+)", command)
    if prefix_match and _path_is_workspace_subpkg(prefix_match.group(1), subpkg_names):
        leaf = os.path.basename(prefix_match.group(1).strip().strip(chr(34)+chr(39)).rstrip('/\\'))
        block(
            f"`npm install --prefix {prefix_match.group(1)}` doesn't do what it looks like — "
            "npm reads the source package.json from the SHELL'S CWD, not from --prefix. "
            "This still creates a sub-lockfile.\n"
            "Run from the repo root with the workspace flag instead:\n"
            f"    npm install --workspace={leaf} <pkg>"
        )

    # (C) Shell CWD is already inside a workspace subdir, and the command is
    #     a bare `npm install` (no `cd` to override CWD, no --prefix override).
    cwd = os.getcwd()
    if (_path_is_workspace_subpkg(cwd, subpkg_names)
            and not re.search(r"\bcd\s+", command)
            and "--prefix" not in command):
        leaf = os.path.basename(cwd)
        block(
            f"Shell is currently inside `{leaf}/`, which is a workspace subpackage. "
            "Running npm install here creates a sub-lockfile that conflicts with the "
            "workspace root's package-lock.json (arborist crash).\n"
            "Go back to the repo root and run with --workspace:\n"
            f"    npm install --workspace={leaf} <pkg>\n"
            "Or to install all workspace deps:\n"
            "    npm install   (from the repo root)"
        )


# Read-only command leaders. A `cd <dir>; <read>; <read>` chain made up only
# of these is safe to run without the cd-drift confirmation.
_READONLY_LEADERS = {
    "grep", "egrep", "fgrep", "rg", "ag", "cat", "head", "tail", "ls", "ll",
    "echo", "printf", "find", "wc", "sort", "uniq", "cut", "tr", "pwd", "tree",
    "stat", "file", "dirname", "basename", "which", "type", "column", "nl",
    "tac", "pg_dump", "jq", "true", "test", "realpath", "readlink",
}
# git subcommands that only read.
_READONLY_GIT_SUBCMDS = {
    "status", "log", "diff", "show", "branch", "ls-files", "ls-tree",
    "rev-parse", "blame", "describe", "cat-file", "shortlog", "reflog",
    "show-ref", "for-each-ref", "rev-list", "name-rev", "whatchanged",
    "remote", "config", "tag", "stash",  # read-only forms only; see below
}


def _segment_is_readonly(seg):
    """True if a single shell segment only reads (no file writes, no mutations)."""
    seg = seg.strip()
    if not seg:
        return True  # empty (e.g. trailing ';') is harmless
    # Any output redirection writes a file — not read-only.
    if ">" in seg:
        return False
    tokens = seg.split()
    if not tokens:
        return True
    leader = tokens[0]
    if leader == "git":
        # Skip leading flags and `-C <path>` to find the subcommand.
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t == "-C" and i + 1 < len(tokens):
                i += 2
                continue
            if t.startswith("-"):
                i += 1
                continue
            break
        sub = tokens[i] if i < len(tokens) else ""
        if sub not in _READONLY_GIT_SUBCMDS:
            return False
        # Reject mutating forms of otherwise-read subcommands.
        rest = tokens[i + 1:]
        if sub == "remote" and any(a in rest for a in ("add", "remove", "rm", "set-url", "rename", "prune")):
            return False
        if sub == "config" and not any(a in rest for a in ("--get", "--get-all", "--list", "-l", "--get-regexp")):
            return False
        if sub == "tag" and any(not a.startswith("-") for a in rest):
            return False  # `git tag <name>` creates; `git tag -l`/`git tag` lists
        if sub == "stash" and any(a in rest for a in ("drop", "clear", "pop", "apply", "push", "save", "store")):
            return False
        return True
    if leader == "sed":
        return "-i" not in tokens  # `sed -i` edits in place
    return leader in _READONLY_LEADERS


def _is_readonly_after_cd(command):
    """True if `command` is `cd <dir>` followed by one or more read-only
    commands (chained with ; && || |) and nothing that writes. Lets pure
    information-gathering run without the cd-drift confirmation prompt."""
    segments = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)
    if not segments or not re.match(r"^cd\s+", segments[0].strip()):
        return False
    rest = [s for s in segments[1:] if s.strip()]
    if not rest:
        return False  # bare `cd` with nothing after still warns (CWD drift)
    return all(_segment_is_readonly(s) for s in rest)


def block(reason):
    """Hard block - exit 2, stderr message."""
    print(f"BLOCKED: {reason}", file=sys.stderr)
    sys.exit(2)


def ask(reason):
    """Ask user to confirm before proceeding."""
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
