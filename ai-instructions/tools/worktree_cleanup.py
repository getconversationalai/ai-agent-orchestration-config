"""
Safely removes git worktrees on Windows.

On Windows, npm workspace projects create NTFS junctions in node_modules that point
back to the worktree root. Most deletion tools (rm -rf, Remove-Item, shutil.rmtree,
rimraf, git worktree remove) follow these junctions and can destroy the main .git
directory. This script:

1. Uses os.scandir() + st_reparse_tag for BULLETPROOF junction/symlink detection
   (not dir /AL which misses junctions on some Windows builds)
2. Verifies no junction targets point into the main .git directory before deletion
3. Checks .git integrity AFTER EACH worktree removal, not just at the end
4. Uses cmd /c "rmdir" to remove junctions without following them

Usage:
    py ~/.ai-instructions/tools/worktree_cleanup.py <worktree-path>
    py ~/.ai-instructions/tools/worktree_cleanup.py --all-merged
    py ~/.ai-instructions/tools/worktree_cleanup.py --all-merged --base dev
"""
import argparse
import os
import subprocess
import sys

# NTFS reparse point tags
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # Directory junctions
# Note: Some references swap these values. We check for ANY non-zero reparse tag
# to be safe — if st_reparse_tag != 0, it's some kind of link/reparse point.


def main():
    parser = argparse.ArgumentParser(description="Safely remove git worktrees on Windows.")
    parser.add_argument("worktree_path", nargs="?", help="Path to the worktree to remove.")
    parser.add_argument("--all-merged", action="store_true",
                        help="Remove all worktrees whose branches are merged into the base branch.")
    parser.add_argument("--base", default=None,
                        help="Base branch for --all-merged (default: auto-detect main or dev).")
    parser.add_argument("--delete-branch", action="store_true", default=True,
                        help="Delete the branch after removing the worktree (default: true).")
    parser.add_argument("--no-delete-branch", action="store_false", dest="delete_branch",
                        help="Keep the branch after removing the worktree.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be cleaned up and exit without touching anything.")
    args = parser.parse_args()

    if not args.worktree_path and not args.all_merged:
        parser.print_help()
        sys.exit(1)

    # Find the main repo root
    repo_root = find_repo_root()
    if not repo_root:
        error("Could not find a git repository. Are you inside a git project?")

    # Verify .git exists
    git_dir = os.path.join(repo_root, ".git")
    if not os.path.exists(git_dir):
        error(f".git does not exist at {git_dir}. The repository may already be corrupted.\n"
              "Recovery: git init && git remote add origin <url> && git fetch origin "
              "&& git checkout -B main origin/main")

    if args.dry_run:
        dry_run_report(repo_root, args)
        return

    if args.all_merged:
        cleanup_all_merged(repo_root, args.base, args.delete_branch)
    else:
        cleanup_one(repo_root, args.worktree_path, args.delete_branch)


def dry_run_report(repo_root, args):
    """Print what would be cleaned up without touching anything.

    Same selection logic as the real run, but no deletes, no `--force`,
    no junction removal. Output: one line per worktree, with reason it
    was selected and any safety gate that would currently refuse it.
    """
    print("DRY RUN — no changes will be made.\n")
    base_branch = args.base or detect_base_branch(repo_root)
    worktrees = list_worktrees(repo_root)

    if args.all_merged:
        # Same merged-set computation as cleanup_all_merged
        merged = set()
        try:
            r = subprocess.run(
                ["git", "branch", "--merged", base_branch],
                capture_output=True, text=True, timeout=10, cwd=repo_root,
            )
            merged.update(b.strip().lstrip("* ") for b in r.stdout.splitlines())
        except Exception as e:
            print(f"  Failed to list merged branches: {e}")

        for wt_path, wt_branch in worktrees:
            if not wt_branch or wt_branch in merged:
                continue
            try:
                cnt = subprocess.run(
                    ["git", "rev-list", "--count", f"{base_branch}..{wt_branch}"],
                    capture_output=True, text=True, timeout=10, cwd=repo_root,
                )
                if cnt.returncode == 0 and cnt.stdout.strip() == "0":
                    merged.add(wt_branch)
            except Exception:
                pass

        targets = [(p, b) for (p, b) in worktrees if b in merged]
    else:
        # Single-target dry run
        wt_path = os.path.abspath(args.worktree_path)
        wt_branch = detect_worktree_branch(repo_root, wt_path)
        targets = [(wt_path, wt_branch)]

    if not targets:
        print(f"  No worktrees would be cleaned (base: {base_branch}).")
        return

    print(f"  Base branch: {base_branch}")
    print(f"  Targets ({len(targets)}):")
    for wt_path, wt_branch in targets:
        gate = _dry_run_gate_check(repo_root, wt_path, wt_branch, base_branch)
        marker = "WOULD CLEAN" if gate is None else f"REFUSED ({gate})"
        print(f"    [{marker}] {wt_branch}  @ {wt_path}")


def _dry_run_gate_check(repo_root, wt_path, wt_branch, base_branch):
    """Replicate the safety gates without side effects. Returns reason string
    if any gate would refuse, None if all pass."""
    # Gate 1: WORKBOARD active (JSON source of truth, .md fallback)
    if _workboard_json_blocks(repo_root, wt_path) or _workboard_md_blocks(repo_root, wt_path):
        return "active in WORKBOARD"

    # Gate 2: branch pushed to remote (with ancestor-only bypass)
    if wt_branch:
        try:
            cnt = subprocess.run(
                ["git", "rev-list", "--count", f"{base_branch}..{wt_branch}"],
                capture_output=True, text=True, timeout=10, cwd=repo_root,
            )
            if cnt.returncode != 0 or cnt.stdout.strip() != "0":
                # Not ancestor-only — require it to be on origin
                r = subprocess.run(
                    ["git", "branch", "-r", "--list", f"origin/{wt_branch}"],
                    capture_output=True, text=True, timeout=10, cwd=repo_root,
                )
                if not r.stdout.strip():
                    return "branch not pushed to origin"
        except Exception:
            pass

    return None


def cleanup_all_merged(repo_root, base_branch, delete_branch):
    """Find and remove all worktrees whose branches are merged into the base branch."""
    if not base_branch:
        base_branch = detect_base_branch(repo_root)

    worktrees = list_worktrees(repo_root)
    if not worktrees:
        info("No worktrees to clean up.")
        return

    # Collect branches whose work is fully on the base branch.
    # Two categories — both safe to sweep because their tips are reachable from base:
    #   1. Strictly merged: `git branch --merged` — base has moved past them via real merge commits.
    #   2. Ancestor-only: branch tip IS an old commit on base's history. Common with squash/rebase
    #      merges (the original commits are gone but their content is in base). `--merged` misses
    #      these, which is why projects accumulate orphan worktrees the script can't sweep.
    merged_branches = set()
    try:
        result = subprocess.run(
            ["git", "branch", "--merged", base_branch],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        merged_branches.update(b.strip().lstrip("* ") for b in result.stdout.splitlines())
    except Exception as e:
        error(f"Failed to list merged branches: {e}")

    # Detect ancestor-only branches: rev-list count of <base>..<branch> == 0 means every commit
    # on the branch is reachable from base. Only check branches that have worktrees, since
    # those are the only ones we'd act on.
    for wt_path, wt_branch in worktrees:
        if not wt_branch or wt_branch in merged_branches:
            continue
        try:
            count_result = subprocess.run(
                ["git", "rev-list", "--count", f"{base_branch}..{wt_branch}"],
                capture_output=True, text=True, timeout=10, cwd=repo_root,
            )
            if count_result.returncode == 0 and count_result.stdout.strip() == "0":
                merged_branches.add(wt_branch)
        except Exception:
            # If rev-list fails for one branch, skip it — don't fail the whole sweep
            pass

    git_dir = os.path.join(repo_root, ".git")
    cleaned = 0
    for wt_path, wt_branch in worktrees:
        if wt_branch in merged_branches:
            # ── INTEGRITY CHECK before each removal ──
            if not os.path.exists(git_dir) or not os.path.isdir(git_dir):
                error(f"CRITICAL: .git was destroyed during batch cleanup!\n"
                      f"This happened AFTER cleaning worktree #{cleaned}.\n"
                      "STOPPING immediately. Recovery:\n"
                      "  git init && git remote add origin <url> && git fetch origin "
                      "&& git checkout -B main origin/main")

            info(f"\n--- Cleaning up: {wt_path} (branch: {wt_branch}) ---")
            try:
                cleanup_one(repo_root, wt_path, delete_branch)
                cleaned += 1
            except SystemExit:
                warn(f"Failed to clean up {wt_path}, skipping.")
                # ── INTEGRITY CHECK after failed removal ──
                if not os.path.exists(git_dir) or not os.path.isdir(git_dir):
                    error(f"CRITICAL: .git was destroyed while cleaning {wt_path}!\n"
                          "STOPPING immediately — do NOT continue batch cleanup.\n"
                          "Recovery: git init && git remote add origin <url> && git fetch origin "
                          "&& git checkout -B main origin/main")
                continue

        # ── INTEGRITY CHECK after each successful removal ──
        if not os.path.exists(git_dir) or not os.path.isdir(git_dir):
            error(f"CRITICAL: .git was destroyed after cleaning worktree #{cleaned}!\n"
                  "STOPPING immediately. Recovery:\n"
                  "  git init && git remote add origin <url> && git fetch origin "
                  "&& git checkout -B main origin/main")

    if cleaned == 0:
        info("No merged worktrees found to clean up.")
    else:
        info(f"\nCleaned up {cleaned} worktree(s).")


def cleanup_one(repo_root, worktree_path, delete_branch):
    """Safely remove a single worktree."""
    worktree_path = os.path.abspath(worktree_path)
    git_dir = os.path.join(repo_root, ".git")

    # ── Step 1: Verify .git exists BEFORE we start ──
    if not os.path.exists(git_dir) or not os.path.isdir(git_dir):
        error(f".git does not exist at {git_dir}. STOP — repository may be corrupted.")

    # Snapshot .git contents for post-removal integrity check
    git_snapshot = snapshot_git_dir(git_dir)

    # ── Step 2: Verify worktree exists ──
    if not os.path.isdir(worktree_path):
        warn(f"Worktree directory does not exist: {worktree_path}")
        info("Running git worktree prune to clean up stale refs...")
        run_git(["git", "worktree", "prune"], cwd=repo_root)
        return

    # ── Step 3: Check WORKBOARD.md for active entries ──
    check_workboard(repo_root, worktree_path)

    # ── Step 4: Detect branch name ──
    branch_name = detect_worktree_branch(repo_root, worktree_path)

    # ── Step 5: Verify branch is pushed to remote ──
    if branch_name:
        check_branch_pushed(repo_root, branch_name)

    # ── Step 6: Comprehensive junction/symlink scan using Python reparse tags ──
    info(f"Scanning for junctions/symlinks in {worktree_path}...")
    junctions = scan_junctions_python(worktree_path)

    # ── Step 6b: SAFETY CHECK — verify no junction targets point into .git ──
    if junctions:
        check_junction_targets_safe(junctions, git_dir, repo_root)

    if junctions:
        info(f"Found {len(junctions)} junction(s)/symlink(s). Removing safely...")

        # ── Step 7: Delete each junction using rmdir (junction-safe) ──
        for jpath, jtype in junctions:
            delete_junction_safe(jpath)

        # ── Step 8: Re-scan to verify zero junctions remain ──
        remaining = scan_junctions_python(worktree_path)
        if remaining:
            error(f"FAILED: {len(remaining)} junction(s) still remain after deletion:\n"
                  + "\n".join(f"  - {p} ({t})" for p, t in remaining) +
                  "\nRefusing to run git worktree remove. Investigate manually.")
        info("All junctions removed successfully.")
    else:
        info("No junctions found — safe to proceed.")

    # ── Step 9: Verify .git STILL intact before running git worktree remove ──
    if not os.path.exists(git_dir) or not os.path.isdir(git_dir):
        error(f"CRITICAL: .git was destroyed during junction removal for {worktree_path}!\n"
              "This should not happen — the junction removal itself damaged .git.\n"
              "Recovery: git init && git remote add origin <url> && git fetch origin "
              "&& git checkout -B main origin/main")

    # ── Step 10: Run git worktree remove ──
    # We pass --force because by the time we reach this step, the script has already
    # verified: (a) the worktree is not active in WORKBOARD, (b) the branch is pushed
    # to origin (so committed work is recoverable), and (c) no junction targets point
    # into .git. The only thing --force overrides is "uncommitted changes / untracked
    # files in the working tree" — which after those three gates is always one of:
    # npm install noise, build artifacts, or stray editor files. Real in-progress work
    # would have failed gate (a) or (b).
    info(f"Running git worktree remove --force {worktree_path}...")
    result = subprocess.run(
        ["git", "worktree", "remove", "--force", worktree_path],
        capture_output=True, text=True, timeout=60, cwd=repo_root,
    )
    remove_succeeded = (result.returncode == 0)
    if not remove_succeeded:
        stderr = result.stderr.strip()
        # If the directory is already gone or not a worktree, treat as success-by-prune
        if "is not a working tree" in stderr or "does not exist" in stderr:
            info(f"git worktree remove reported: {stderr}")
            info("Running git worktree prune instead...")
            run_git(["git", "worktree", "prune"], cwd=repo_root)
            remove_succeeded = True
        else:
            warn(f"git worktree remove failed: {stderr}")
            warn("Junctions were already removed, so .git should be safe.")
            # Still try to prune in case the ref is dangling
            run_git(["git", "worktree", "prune"], cwd=repo_root)

    # ── Step 11: COMPREHENSIVE .git integrity check AFTER removal ──
    verify_git_integrity(git_dir, git_snapshot, worktree_path)

    info(".git verified intact.")

    # If the remove failed, do NOT continue to branch deletion or claim success.
    # Surface a real error and exit non-zero so callers see the failure.
    if not remove_succeeded:
        error(f"FAILED to remove worktree at {worktree_path}.\n"
              "The worktree directory still exists. Investigate manually.")

    # ── Step 12: Delete merged branch ──
    if delete_branch and branch_name:
        # Only delete with -d (safe — refuses if not merged)
        result = subprocess.run(
            ["git", "branch", "-d", branch_name],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if result.returncode == 0:
            info(f"Deleted branch: {branch_name}")
        else:
            warn(f"Could not delete branch {branch_name}: {result.stderr.strip()}")
            warn("Branch may not be fully merged. Delete manually with git branch -D if certain.")

    # ── Step 13: Prune worktree refs ──
    run_git(["git", "worktree", "prune"], cwd=repo_root)

    info(f"Cleanup complete: {worktree_path}")


# ─────────────────────────────────────────────
# Junction scanning — Python-native (bulletproof)
# ─────────────────────────────────────────────

def scan_junctions_python(root_path):
    """
    Scan a directory tree for ALL junctions, symlinks, and reparse points
    using os.scandir() + st_reparse_tag. This is far more reliable than
    cmd /c dir /AL which misses junctions on some Windows builds.

    Returns list of (path, type_description) tuples.
    """
    found = []
    try:
        _scan_recursive(root_path, found, depth=0, max_depth=50)
    except Exception as e:
        warn(f"Junction scan encountered an error: {e}")
        # If scan failed, treat as "potentially unsafe" — return a sentinel
        found.append((f"SCAN_ERROR: {e}", "error"))
    return found


def _scan_recursive(path, found, depth, max_depth):
    """Recursively scan for junctions/symlinks using os.scandir()."""
    if depth > max_depth:
        warn(f"Max scan depth ({max_depth}) reached at {path}. Possible circular links.")
        found.append((path, "max_depth_exceeded"))
        return

    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    entry_path = entry.path

                    # Check if this entry is any kind of link/reparse point
                    is_link = False
                    link_type = ""

                    # Method 1: os.path.islink (catches symlinks)
                    if os.path.islink(entry_path):
                        is_link = True
                        link_type = "symlink"

                    # Method 2: os.path.isjunction (Python 3.12+, catches NTFS junctions)
                    if hasattr(os.path, 'isjunction') and os.path.isjunction(entry_path):
                        is_link = True
                        link_type = "junction"

                    # Method 3: st_reparse_tag (catches ALL reparse points)
                    # This is the most comprehensive check
                    try:
                        stat_info = entry.stat(follow_symlinks=False)
                        reparse_tag = getattr(stat_info, 'st_reparse_tag', 0) or 0
                        if reparse_tag != 0:
                            is_link = True
                            if not link_type:  # Don't override more specific detection
                                if reparse_tag == 0xA0000003:
                                    link_type = f"junction (reparse_tag=0x{reparse_tag:08X})"
                                elif reparse_tag == 0xA000000C:
                                    link_type = f"symlink (reparse_tag=0x{reparse_tag:08X})"
                                else:
                                    link_type = f"reparse_point (tag=0x{reparse_tag:08X})"
                    except (OSError, AttributeError):
                        pass

                    if is_link:
                        found.append((entry_path, link_type))
                        # Do NOT recurse into links — they may point outside the tree
                        continue

                    # Recurse into real directories
                    if entry.is_dir(follow_symlinks=False):
                        _scan_recursive(entry_path, found, depth + 1, max_depth)

                except PermissionError:
                    warn(f"Permission denied scanning: {entry.path}")
                except OSError as e:
                    warn(f"OS error scanning {entry.path}: {e}")

    except PermissionError:
        warn(f"Permission denied scanning directory: {path}")
    except OSError as e:
        warn(f"OS error scanning directory {path}: {e}")


# ─────────────────────────────────────────────
# Junction target safety check
# ─────────────────────────────────────────────

def check_junction_targets_safe(junctions, git_dir, repo_root):
    """
    Verify no junction/symlink targets point into the main .git directory
    or the main repo root. If any do, REFUSE to proceed.

    Special case: npm workspace projects create an EXPECTED junction at
    <worktree>/node_modules/<repo-name> pointing to the repo root. This is
    normal npm behavior. The junction itself is dangerous (would let
    `git worktree remove` cascade-delete .git), but the *cause* is benign.
    We pre-emptively delete just this one junction so the rest of the flow
    can proceed, instead of refusing and asking the human to do it manually.
    """
    git_dir_norm = os.path.normpath(os.path.abspath(git_dir)).lower()
    repo_root_norm = os.path.normpath(os.path.abspath(repo_root)).lower()

    # First pass: identify and pre-emptively remove the npm workspace self-ref junction.
    # This is the ONLY junction we auto-handle; everything else still goes through the
    # full danger check.
    repo_name = os.path.basename(repo_root_norm)
    auto_handled = []
    for jpath, jtype in junctions:
        if jtype == "error" or "SCAN" in jpath:
            continue
        try:
            target = os.path.realpath(jpath)
            target_norm = os.path.normpath(target).lower()
            jbasename = os.path.basename(os.path.normpath(jpath)).lower()
            # Match the npm workspace self-ref pattern:
            #   - junction lives at <something>/node_modules/<repo-name>
            #   - target is exactly the repo root
            if (target_norm == repo_root_norm
                    and jbasename == repo_name
                    and os.sep + "node_modules" + os.sep in os.path.normpath(jpath).lower()):
                info(f"Pre-emptively removing expected npm workspace self-ref junction: {jpath}")
                delete_junction_safe(jpath)
                auto_handled.append(jpath)
        except (OSError, ValueError):
            pass

    # Filter out the auto-handled junctions from the original list — caller will
    # use the filtered list for subsequent processing.
    if auto_handled:
        junctions[:] = [(p, t) for p, t in junctions if p not in auto_handled]

    # Second pass: any remaining junction whose target points at .git or its parents
    # is a real danger and we refuse to proceed.
    dangerous = []
    for jpath, jtype in junctions:
        if jtype == "error" or "SCAN" in jpath:
            continue

        # Try to resolve the junction target
        try:
            target = os.path.realpath(jpath)
            target_norm = os.path.normpath(target).lower()

            # DANGER: target is inside .git directory
            if target_norm.startswith(git_dir_norm + os.sep) or target_norm == git_dir_norm:
                dangerous.append((jpath, target, "POINTS INTO .git DIRECTORY"))

            # DANGER: target is the repo root itself (junction could traverse back to .git)
            if target_norm == repo_root_norm:
                dangerous.append((jpath, target, "POINTS TO REPO ROOT (contains .git)"))

            # DANGER: target is a parent of .git
            if git_dir_norm.startswith(target_norm + os.sep):
                dangerous.append((jpath, target, "POINTS TO PARENT OF .git"))

        except (OSError, ValueError):
            # Can't resolve target — treat as suspicious but not blocking
            warn(f"Could not resolve junction target for: {jpath}")

    if dangerous:
        msg = "BLOCKED: Found junction(s) whose targets could damage .git:\n"
        for jpath, target, reason in dangerous:
            msg += f"\n  Junction: {jpath}\n  Target:   {target}\n  Reason:   {reason}\n"
        msg += ("\nThese junctions point into the git repository. Deleting them with "
                "git worktree remove would follow the junction and destroy .git.\n"
                "The junctions themselves have been identified but NOT deleted.\n"
                "Manual investigation required — use 'cmd /c rmdir <junction>' to remove "
                "individual junctions, then retry.")
        error(msg)


# ─────────────────────────────────────────────
# .git integrity verification
# ─────────────────────────────────────────────

def snapshot_git_dir(git_dir):
    """Take a snapshot of critical .git contents for integrity comparison."""
    snapshot = {}
    try:
        # Check that .git is a directory (not a file, which would mean it's a worktree .git pointer)
        snapshot["is_dir"] = os.path.isdir(git_dir)
        snapshot["exists"] = os.path.exists(git_dir)

        if os.path.isdir(git_dir):
            # Check critical subdirectories
            critical = ["HEAD", "config", "refs", "objects"]
            for item in critical:
                item_path = os.path.join(git_dir, item)
                snapshot[item] = os.path.exists(item_path)

            # Count refs to detect mass deletion
            refs_dir = os.path.join(git_dir, "refs")
            if os.path.isdir(refs_dir):
                ref_count = sum(len(files) for _, _, files in os.walk(refs_dir))
                snapshot["ref_count"] = ref_count

            # Count objects (just the pack files, not loose objects)
            pack_dir = os.path.join(git_dir, "objects", "pack")
            if os.path.isdir(pack_dir):
                snapshot["pack_count"] = len(os.listdir(pack_dir))

    except Exception as e:
        snapshot["error"] = str(e)
    return snapshot


def verify_git_integrity(git_dir, before_snapshot, worktree_path):
    """
    Verify .git integrity after a worktree removal by comparing before/after state.
    Catches cases where .git was partially damaged (not just fully deleted).
    """
    # Basic existence check
    if not os.path.exists(git_dir):
        error(f"CRITICAL: .git has been DESTROYED at {git_dir}!\n"
              f"This happened during cleanup of: {worktree_path}\n"
              "Recovery: git init && git remote add origin <url> && git fetch origin "
              "&& git checkout -B main origin/main")

    if not os.path.isdir(git_dir):
        error(f"CRITICAL: .git exists but is no longer a directory at {git_dir}!\n"
              f"This happened during cleanup of: {worktree_path}\n"
              "Recovery: remove the file, then git init && git remote add origin <url>")

    # Check critical files still exist
    critical = ["HEAD", "config", "refs", "objects"]
    missing = []
    for item in critical:
        item_path = os.path.join(git_dir, item)
        if not os.path.exists(item_path):
            missing.append(item)

    if missing:
        error(f"CRITICAL: .git is DAMAGED — missing critical items: {', '.join(missing)}\n"
              f"This happened during cleanup of: {worktree_path}\n"
              "Recovery: git init && git remote add origin <url> && git fetch origin "
              "&& git checkout -B main origin/main")

    # Check if refs were mass-deleted (sign of junction traversal damage)
    if "ref_count" in before_snapshot:
        refs_dir = os.path.join(git_dir, "refs")
        if os.path.isdir(refs_dir):
            current_ref_count = sum(len(files) for _, _, files in os.walk(refs_dir))
            before_count = before_snapshot["ref_count"]
            # Allow some reduction (the worktree's own ref gets cleaned up)
            # but flag if >50% of refs disappeared
            if before_count > 5 and current_ref_count < before_count * 0.5:
                error(f"CRITICAL: .git refs were mass-deleted! "
                      f"Before: {before_count}, After: {current_ref_count}\n"
                      f"This happened during cleanup of: {worktree_path}\n"
                      "This strongly suggests a junction followed into .git/refs/.\n"
                      "Recovery: git init && git remote add origin <url> && git fetch origin "
                      "&& git checkout -B main origin/main")

    # Check if pack files disappeared
    if "pack_count" in before_snapshot and before_snapshot["pack_count"] > 0:
        pack_dir = os.path.join(git_dir, "objects", "pack")
        if os.path.isdir(pack_dir):
            current_pack_count = len(os.listdir(pack_dir))
            if current_pack_count == 0:
                error(f"CRITICAL: .git pack files were destroyed!\n"
                      f"Before: {before_snapshot['pack_count']} packs, After: 0\n"
                      f"This happened during cleanup of: {worktree_path}\n"
                      "Recovery: git init && git remote add origin <url> && git fetch origin "
                      "&& git checkout -B main origin/main")


# ─────────────────────────────────────────────
# Junction deletion
# ─────────────────────────────────────────────

def delete_junction_safe(junction_path):
    """
    Delete a junction/symlink without following it.
    Uses os.unlink for file symlinks, and rmdir for directory junctions/symlinks.
    Falls back to cmd /c rmdir for stubborn cases.
    """
    try:
        # For directory junctions/symlinks: os.rmdir removes the link, not the target
        if os.path.isdir(junction_path):
            try:
                os.rmdir(junction_path)
                return
            except OSError:
                pass  # Fall through to rmdir cmd

        # For file symlinks: os.unlink removes the link
        if os.path.islink(junction_path):
            try:
                os.unlink(junction_path)
                return
            except OSError:
                pass  # Fall through to rmdir cmd

        # Fallback: cmd /c rmdir (junction-safe on Windows)
        win_path = to_windows_path(junction_path)
        result = subprocess.run(
            ["cmd", "/c", "rmdir", win_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            # Try rd /s /q as last resort
            result = subprocess.run(
                ["cmd", "/c", "rd", "/s", "/q", win_path],
                capture_output=True, text=True, timeout=30,
            )

        # Verify removal
        if os.path.exists(junction_path):
            error(f"Failed to delete junction at {junction_path}. "
                  "Refusing to continue — investigate manually.")

    except subprocess.TimeoutExpired:
        error(f"Deletion timed out for {junction_path}. The path may have infinite recursion. "
              "Try deleting from Windows Explorer or use robocopy empty-dir trick.")
    except Exception as e:
        error(f"Failed to delete junction at {junction_path}: {e}")


# ─────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────

def find_repo_root():
    """Find the git repo root from CWD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def detect_base_branch(repo_root):
    """Detect main or dev branch."""
    try:
        result = subprocess.run(
            ["git", "branch", "--list", "dev", "main"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        branches = [b.strip().lstrip("* ") for b in result.stdout.splitlines()]
        if "dev" in branches:
            return "dev"
        if "main" in branches:
            return "main"
    except Exception:
        pass
    return "main"


def detect_worktree_branch(repo_root, worktree_path):
    """Get the branch name for a worktree."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        current_wt = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                current_wt = os.path.normpath(line[len("worktree "):].strip())
            elif line.startswith("branch ") and current_wt:
                norm_target = os.path.normpath(worktree_path)
                if current_wt.lower() == norm_target.lower():
                    # branch refs/heads/feat/foo -> feat/foo
                    return line[len("branch refs/heads/"):].strip()
    except Exception:
        pass
    return None


def list_worktrees(repo_root):
    """List all worktrees except the main one. Returns [(path, branch), ...]."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        worktrees = []
        current_path = None
        current_branch = None
        is_first = True  # Skip the main worktree (first entry)
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current_path and not is_first:
                    worktrees.append((current_path, current_branch))
                current_path = line[len("worktree "):].strip()
                current_branch = None
                if is_first:
                    is_first = False
                    current_path = None  # Skip main
            elif line.startswith("branch "):
                current_branch = line[len("branch refs/heads/"):].strip()
        # Don't forget the last entry
        if current_path:
            worktrees.append((current_path, current_branch))
        return worktrees
    except Exception:
        return []


def check_workboard(repo_root, worktree_path):
    """Refuse to clean a worktree that's marked active/waiting in the workboard.

    Source of truth: WORKBOARD.json (managed by workboard.py). The markdown
    mirror (WORKBOARD.md) can be stale — workboard.py only regenerates it on
    write, so manual cleanups or external edits leave it out of sync. Falls
    back to WORKBOARD.md only if WORKBOARD.json doesn't exist (older repos
    that haven't migrated to the JSON workboard yet).
    """
    if _workboard_json_blocks(repo_root, worktree_path):
        error("BLOCKED: This worktree is referenced in WORKBOARD.json as active/waiting.\n"
              "Only the agent that owns this worktree should clean it up, "
              "and only after work is complete.")
    if _workboard_md_blocks(repo_root, worktree_path):
        error("BLOCKED: This worktree is referenced in WORKBOARD.md as active/waiting.\n"
              "Only the agent that owns this worktree should clean it up, "
              "and only after work is complete.")


def _workboard_json_blocks(repo_root, worktree_path):
    """Returns True if WORKBOARD.json has an active/waiting entry for this path."""
    import json as _json
    wb_json = os.path.join(repo_root, "WORKBOARD.json")
    if not os.path.isfile(wb_json):
        return False
    try:
        with open(wb_json, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception:
        return False
    norm_wt = os.path.normpath(os.path.abspath(worktree_path)).lower()

    def _entry_matches(entry):
        wt = (entry.get("worktree") or "").strip()
        if not wt:
            return False
        if os.path.normpath(os.path.abspath(wt)).lower() != norm_wt:
            return False
        return entry.get("status") in ("active", "waiting")

    for entry in data.get("active", []):
        if _entry_matches(entry):
            return True
        for sub in entry.get("subagents", []) or []:
            if _entry_matches(sub):
                return True
    return False


def _workboard_md_blocks(repo_root, worktree_path):
    """Fallback: scan WORKBOARD.md if WORKBOARD.json isn't present."""
    if os.path.isfile(os.path.join(repo_root, "WORKBOARD.json")):
        return False  # JSON exists → JSON is source of truth, don't double-check
    wb_path = os.path.join(repo_root, "WORKBOARD.md")
    if not os.path.isfile(wb_path):
        return False
    try:
        with open(wb_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return False

    in_active = False
    active_lines = []
    for line in content.splitlines():
        if line.strip().lower().startswith("## active work"):
            in_active = True
            continue
        if in_active and line.strip().startswith("## "):
            break
        if in_active:
            active_lines.append(line)

    active_text = "\n".join(active_lines)
    norm_wt = os.path.normpath(worktree_path).lower()
    for line in active_lines:
        if "worktree:" in line.lower():
            parts = line.lower().split("worktree:")
            if len(parts) > 1:
                entry_path = parts[1].strip().rstrip(".")
                if os.path.normpath(entry_path).lower() == norm_wt:
                    if any(s in active_text.lower() for s in ["status: active", "status: waiting"]):
                        return True
    return False


def check_branch_pushed(repo_root, branch_name):
    """Verify branch exists on remote — UNLESS the branch is ancestor-only.

    The check exists to protect unpushed work that could be lost. But if the
    branch contains zero commits beyond the base branch (every commit on the
    branch is already reachable from main/dev), there is nothing to lose:
    every commit is on origin via origin/<base>. In that case we skip the
    requirement and let the cleanup proceed.
    """
    # Detect ancestor-only state first. Try main, then dev, as base candidates.
    for base in ("main", "dev"):
        try:
            base_check = subprocess.run(
                ["git", "rev-parse", "--verify", base],
                capture_output=True, text=True, timeout=5, cwd=repo_root,
            )
            if base_check.returncode != 0:
                continue
            count_result = subprocess.run(
                ["git", "rev-list", "--count", f"{base}..{branch_name}"],
                capture_output=True, text=True, timeout=10, cwd=repo_root,
            )
            if count_result.returncode == 0 and count_result.stdout.strip() == "0":
                info(f"Branch '{branch_name}' is ancestor-only of {base} "
                     "(every commit already on origin via origin/" + base + ") — skipping push check.")
                return
        except Exception:
            pass

    # Otherwise, require the branch to be on origin.
    try:
        result = subprocess.run(
            ["git", "branch", "-r", "--list", f"origin/{branch_name}"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if not result.stdout.strip():
            error(f"Branch '{branch_name}' has NOT been pushed to remote.\n"
                  f"Push it first: git push -u origin {branch_name}\n"
                  "Then re-run this script. Unpushed branches are unrecoverable if .git is corrupted.")
    except Exception:
        warn(f"Could not verify if branch '{branch_name}' is pushed to remote.")


def run_git(cmd, cwd=None):
    """Run a git command, warn on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        if result.returncode != 0 and result.stderr.strip():
            warn(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    except Exception as e:
        warn(f"{' '.join(cmd)} failed: {e}")


def to_windows_path(path):
    """Convert a path to Windows format (backslashes) for cmd.exe."""
    return os.path.abspath(path).replace("/", "\\")


def info(msg):
    print(f"  {msg}")


def warn(msg):
    print(f"  WARNING: {msg}", file=sys.stderr)


def error(msg):
    print(f"  ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
