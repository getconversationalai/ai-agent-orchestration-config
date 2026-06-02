#!/usr/bin/env python3
"""
overlap_check.py — Diff-based overlap detection for multi-agent coordination.

Compares actual git diffs across active branches to detect file-level and
hunk-level overlaps. Runs at key checkpoints:
  - Before an agent starts (to inform planning)
  - Before marking a branch ready for merge
  - Before the actual merge

Usage:
    python overlap_check.py                       # compare all active branches from WORKBOARD.md
    python overlap_check.py --branches feat/a feat/b   # compare specific branches
    python overlap_check.py --branch feat/a       # compare one branch against all others
    python overlap_check.py --detailed            # show hunk-level overlap (changed line ranges)
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
    """Detect base branch (dev if it exists, otherwise main)."""
    branches = git("branch", "--list", "dev", "main")
    if "dev" in branches:
        return "dev"
    return "main"


def get_active_branches_from_workboard() -> list[dict]:
    """Parse WORKBOARD.md for active branches."""
    root = find_project_root()
    wb_path = root / "WORKBOARD.md"
    if not wb_path.exists():
        return []

    content = wb_path.read_text(encoding="utf-8")
    active_match = re.search(r"## Active Work\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not active_match:
        return []

    entries = []
    for match in re.finditer(
        r"- \*\*(.+?)\*\*.*?Branch: ([\w/\-]+)",
        active_match.group(1),
        re.DOTALL
    ):
        entries.append({"feature": match.group(1), "branch": match.group(2)})

    return entries


def get_changed_files(branch: str, base: str) -> set[str]:
    """Get files changed on a branch relative to base."""
    output = git("diff", "--name-only", f"{base}...{branch}")
    if not output:
        return set()
    return set(output.splitlines())


def get_changed_hunks(branch: str, base: str, filepath: str) -> list[tuple[int, int]]:
    """Get changed line ranges for a specific file on a branch."""
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


def ranges_overlap(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple]:
    """Check if any line ranges overlap between two sets."""
    overlaps = []
    for a_start, a_end in a:
        for b_start, b_end in b:
            if a_start <= b_end and b_start <= a_end:
                overlaps.append((max(a_start, b_start), min(a_end, b_end)))
    return overlaps


def compare_branches(branches: list[dict], base: str, detailed: bool = False) -> list[dict]:
    """Compare all branch pairs for overlap."""
    # Get changed files for each branch
    branch_files = {}
    for entry in branches:
        branch = entry["branch"]
        files = get_changed_files(branch, base)
        if files:
            branch_files[branch] = {"feature": entry["feature"], "files": files}

    if not branch_files:
        return []

    results = []
    branch_list = list(branch_files.keys())

    for i in range(len(branch_list)):
        for j in range(i + 1, len(branch_list)):
            b1, b2 = branch_list[i], branch_list[j]
            f1, f2 = branch_files[b1]["files"], branch_files[b2]["files"]
            overlap_files = f1 & f2

            if not overlap_files:
                results.append({
                    "branch_a": b1, "feature_a": branch_files[b1]["feature"],
                    "branch_b": b2, "feature_b": branch_files[b2]["feature"],
                    "overlap_files": set(),
                    "risk": "none",
                    "details": {}
                })
                continue

            risk = "low"  # file overlap but maybe different lines
            details = {}

            if detailed:
                for filepath in overlap_files:
                    hunks_a = get_changed_hunks(b1, base, filepath)
                    hunks_b = get_changed_hunks(b2, base, filepath)
                    line_overlaps = ranges_overlap(hunks_a, hunks_b)

                    if line_overlaps:
                        risk = "high"
                        details[filepath] = {
                            "hunks_a": hunks_a,
                            "hunks_b": hunks_b,
                            "line_overlaps": line_overlaps
                        }
                    else:
                        details[filepath] = {
                            "hunks_a": hunks_a,
                            "hunks_b": hunks_b,
                            "line_overlaps": []
                        }

            results.append({
                "branch_a": b1, "feature_a": branch_files[b1]["feature"],
                "branch_b": b2, "feature_b": branch_files[b2]["feature"],
                "overlap_files": overlap_files,
                "risk": risk,
                "details": details
            })

    return results


def print_results(results: list[dict], detailed: bool):
    if not results:
        print("No active branches to compare.")
        return

    has_overlap = False
    for r in results:
        if not r["overlap_files"]:
            continue
        has_overlap = True

        risk_icon = {"none": " ", "low": "~", "high": "!"}[r["risk"]]
        print(f"\n[{risk_icon}] {r['feature_a']} ({r['branch_a']})")
        print(f"    vs {r['feature_b']} ({r['branch_b']})")
        print(f"    Overlapping files ({len(r['overlap_files'])}):")

        for f in sorted(r["overlap_files"]):
            if detailed and f in r["details"]:
                d = r["details"][f]
                if d["line_overlaps"]:
                    ranges_str = ", ".join(f"L{s}-{e}" for s, e in d["line_overlaps"])
                    print(f"      ! {f}  — LINE CONFLICT at {ranges_str}")
                else:
                    print(f"      ~ {f}  — different lines (safe to merge)")
            else:
                print(f"      - {f}")

    if not has_overlap:
        print("No file overlaps detected between active branches.")
    else:
        print("\nLegend: [!] high risk (same lines)  [~] low risk (same file, different lines)  [ ] no overlap")


def main():
    parser = argparse.ArgumentParser(description="Diff-based overlap detection")
    parser.add_argument("--branches", nargs="+", help="Specific branches to compare")
    parser.add_argument("--branch", help="Compare one branch against all others")
    parser.add_argument("--base", help="Base branch (auto-detected if omitted)")
    parser.add_argument("--detailed", action="store_true", help="Show hunk-level overlap")
    args = parser.parse_args()

    base = args.base or get_base_branch()

    if args.branches:
        branches = [{"feature": b, "branch": b} for b in args.branches]
    elif args.branch:
        wb_branches = get_active_branches_from_workboard()
        branches = [{"feature": args.branch, "branch": args.branch}]
        for entry in wb_branches:
            if entry["branch"] != args.branch:
                branches.append(entry)
    else:
        branches = get_active_branches_from_workboard()

    if len(branches) < 2:
        print("Need at least 2 branches to compare. Use --branches or register in WORKBOARD.md.")
        sys.exit(0)

    results = compare_branches(branches, base, detailed=args.detailed)
    print_results(results, args.detailed)


if __name__ == "__main__":
    main()
