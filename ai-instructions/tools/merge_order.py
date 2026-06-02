#!/usr/bin/env python3
"""
merge_order.py — Deterministic merge ordering for multi-agent coordination.

Analyzes completed/ready branches and recommends an optimal merge order
that minimizes conflict risk. Branches with no overlap merge first,
then low-overlap, then high-overlap.

Usage:
    python merge_order.py                    # auto-detect from WORKBOARD.md
    python merge_order.py --branches feat/a feat/b feat/c   # specify branches
    python merge_order.py --detailed         # show hunk-level analysis
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def find_project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def git(*args, cwd=None) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True, text=True,
        cwd=cwd or find_project_root()
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_base_branch() -> str:
    branches = git("branch", "--list", "dev", "main")
    if "dev" in branches:
        return "dev"
    return "main"


def get_ready_branches_from_workboard() -> list[dict]:
    """Parse WORKBOARD.md for branches that are ready to merge (completed or active+done)."""
    root = find_project_root()
    wb_path = root / "WORKBOARD.md"
    if not wb_path.exists():
        return []

    content = wb_path.read_text(encoding="utf-8")
    entries = []

    # Check completed section for unmerged branches
    completed_match = re.search(r"## Completed\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if completed_match:
        for match in re.finditer(
            r"- \*\*(.+?)\*\*.*?Branch: ([\w/\-]+).*?Merged: no",
            completed_match.group(1),
            re.DOTALL
        ):
            entries.append({"feature": match.group(1), "branch": match.group(2)})

    # Also check active section (agents may have finished but not moved to completed yet)
    active_match = re.search(r"## Active Work\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if active_match:
        for match in re.finditer(
            r"- \*\*(.+?)\*\*.*?Branch: ([\w/\-]+)",
            active_match.group(1),
            re.DOTALL
        ):
            # Only include if not already in completed list
            branch = match.group(2)
            if not any(e["branch"] == branch for e in entries):
                entries.append({"feature": match.group(1), "branch": branch})

    return entries


def get_changed_files(branch: str, base: str) -> set[str]:
    output = git("diff", "--name-only", f"{base}...{branch}")
    if not output:
        return set()
    return set(output.splitlines())


def get_changed_hunks(branch: str, base: str, filepath: str) -> list[tuple[int, int]]:
    output = git("diff", "--unified=0", f"{base}...{branch}", "--", filepath)
    if not output:
        return []
    ranges = []
    for match in re.finditer(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", output):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) else 1
        if count > 0:
            ranges.append((start, start + count - 1))
    return ranges


def compute_overlap_matrix(branches: list[dict], base: str, detailed: bool) -> dict:
    """Build a matrix of file overlaps between all branch pairs."""
    branch_files = {}
    for entry in branches:
        files = get_changed_files(entry["branch"], base)
        branch_files[entry["branch"]] = files

    matrix = {}
    for i, a in enumerate(branches):
        for j, b in enumerate(branches):
            if i >= j:
                continue
            key = (a["branch"], b["branch"])
            overlap = branch_files[a["branch"]] & branch_files[b["branch"]]

            hunk_conflicts = 0
            if detailed and overlap:
                for filepath in overlap:
                    hunks_a = get_changed_hunks(a["branch"], base, filepath)
                    hunks_b = get_changed_hunks(b["branch"], base, filepath)
                    for a_s, a_e in hunks_a:
                        for b_s, b_e in hunks_b:
                            if a_s <= b_e and b_s <= a_e:
                                hunk_conflicts += 1

            matrix[key] = {
                "files": overlap,
                "count": len(overlap),
                "hunk_conflicts": hunk_conflicts
            }

    return matrix, branch_files


def compute_merge_order(branches: list[dict], matrix: dict, branch_files: dict) -> list[dict]:
    """Determine optimal merge order: least overlap first."""
    # Score each branch by total overlap with all others
    scores = {}
    for entry in branches:
        b = entry["branch"]
        total_overlap = 0
        total_hunks = 0
        for key, val in matrix.items():
            if b in key:
                total_overlap += val["count"]
                total_hunks += val["hunk_conflicts"]
        scores[b] = {
            "feature": entry["feature"],
            "file_overlap": total_overlap,
            "hunk_conflicts": total_hunks,
            "files_changed": len(branch_files.get(b, set()))
        }

    # Sort: zero overlap first, then by ascending overlap count, then by hunk conflicts
    ordered = sorted(
        scores.items(),
        key=lambda x: (x[1]["file_overlap"], x[1]["hunk_conflicts"], x[1]["files_changed"])
    )

    return [{"branch": b, **info} for b, info in ordered]


def print_merge_order(order: list[dict], matrix: dict, detailed: bool):
    if not order:
        print("No branches ready to merge.")
        return

    print("=" * 60)
    print("  RECOMMENDED MERGE ORDER")
    print("=" * 60)

    for i, entry in enumerate(order, 1):
        risk = "NONE"
        if entry["hunk_conflicts"] > 0:
            risk = "HIGH"
        elif entry["file_overlap"] > 0:
            risk = "LOW"

        risk_color = {"NONE": " ", "LOW": "~", "HIGH": "!"}[risk]

        print(f"\n  {i}. [{risk_color}] {entry['feature']}  ({entry['branch']})")
        print(f"     Files changed: {entry['files_changed']}")
        print(f"     File overlaps with others: {entry['file_overlap']}")
        if detailed:
            print(f"     Hunk-level conflicts: {entry['hunk_conflicts']}")

    # Show pairwise overlaps
    has_overlap = any(v["count"] > 0 for v in matrix.values())
    if has_overlap:
        print(f"\n{'─' * 60}")
        print("  PAIRWISE OVERLAPS")
        print(f"{'─' * 60}")
        for (a, b), val in sorted(matrix.items(), key=lambda x: -x[1]["count"]):
            if val["count"] > 0:
                hunk_str = f", {val['hunk_conflicts']} hunk conflicts" if detailed else ""
                print(f"  {a} vs {b}: {val['count']} files{hunk_str}")
                for f in sorted(val["files"]):
                    print(f"    - {f}")

    print(f"\n{'=' * 60}")
    print("  MERGE INSTRUCTIONS")
    print("=" * 60)
    print("""
  For each branch in order above:
    1. Inside the agent's worktree:
       git fetch origin <base-branch>
       git merge origin/<base-branch>
    2. Resolve any conflicts (keep BOTH sides for additive conflicts)
    3. Run build/typecheck
    4. Fast-forward base: git push . HEAD:<base-branch>
    5. If fast-forward fails, repeat from step 1

  After ALL merges: run full build + audit each branch's changes.
""")


def main():
    parser = argparse.ArgumentParser(description="Merge order recommendation")
    parser.add_argument("--branches", nargs="+", help="Specific branches to order")
    parser.add_argument("--base", help="Base branch (auto-detected if omitted)")
    parser.add_argument("--detailed", action="store_true", help="Include hunk-level analysis")
    args = parser.parse_args()

    base = args.base or get_base_branch()

    if args.branches:
        branches = [{"feature": b, "branch": b} for b in args.branches]
    else:
        branches = get_ready_branches_from_workboard()

    if not branches:
        print("No branches found. Use --branches or complete work in WORKBOARD.md.")
        sys.exit(0)

    if len(branches) == 1:
        print(f"Only one branch: {branches[0]['branch']} — merge directly, no ordering needed.")
        sys.exit(0)

    matrix, branch_files = compute_overlap_matrix(branches, base, args.detailed)
    order = compute_merge_order(branches, matrix, branch_files)
    print_merge_order(order, matrix, args.detailed)


if __name__ == "__main__":
    main()
