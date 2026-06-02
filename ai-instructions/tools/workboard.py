#!/usr/bin/env python3
"""
workboard.py — Atomic coordination for multi-agent work.

Manages two JSON files at the project root:
  WORKBOARD.json — who is doing what, where (agents, branches, files, current progress path)
  PROGRESS.json  — hierarchical progress tree (plan -> phase -> wave -> task; titles + status only)

Both files are auto-mirrored to WORKBOARD.md / PROGRESS.md so other agents and humans can
grep/eyeball the state without running a tool. All WRITES go through this script to prevent
race conditions under concurrent multi-agent use.

See the "Progress Tracking (MANDATORY)" section in ~/.claude/CLAUDE.md (and parallel files
for Gemini/Codex) for usage guidance.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows terminals default to cp1252. Force UTF-8 for stdout/stderr so we can
# print em-dashes and unicode status glyphs without crashing.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Cross-platform file locking
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import msvcrt

    def _lock(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------
def find_project_root() -> Path:
    """Walk up from CWD to find the repo root (directory containing .git)."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def wb_json_path() -> Path:
    return find_project_root() / "WORKBOARD.json"


def prog_json_path() -> Path:
    return find_project_root() / "PROGRESS.json"


def wb_md_path() -> Path:
    return find_project_root() / "WORKBOARD.md"


def prog_md_path() -> Path:
    return find_project_root() / "PROGRESS.md"


def lock_path() -> Path:
    return find_project_root() / ".workboard.lock"


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------
def acquire_lock(timeout: float = 10.0):
    """Acquire an exclusive lock used for ALL workboard + progress writes."""
    lf = open(lock_path(), "w")
    start = time.monotonic()
    while True:
        try:
            _lock(lf)
            return lf
        except (IOError, OSError):
            if time.monotonic() - start > timeout:
                lf.close()
                print(
                    f"ERROR: Could not acquire lock on {lock_path()} within {timeout}s",
                    file=sys.stderr,
                )
                sys.exit(1)
            time.sleep(0.1)


def release_lock(lf):
    try:
        _unlock(lf)
    finally:
        lf.close()


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------
def _read_json(path: Path, default) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_workboard() -> dict:
    return _read_json(wb_json_path(), {"active": [], "completed": []})


def write_workboard(data: dict):
    _write_json(wb_json_path(), data)


def read_progress() -> dict:
    return _read_json(prog_json_path(), {})


def write_progress(data: dict):
    _write_json(prog_json_path(), data)


# ---------------------------------------------------------------------------
# Migration from legacy WORKBOARD.md
# ---------------------------------------------------------------------------
def migrate_legacy_markdown():
    """If WORKBOARD.json does not exist but WORKBOARD.md does, parse the old
    markdown format into a best-effort WORKBOARD.json. Runs once."""
    if wb_json_path().exists():
        return
    if not wb_md_path().exists():
        return

    content = wb_md_path().read_text(encoding="utf-8")
    data = {"active": [], "completed": []}

    for section, key in [("## Active Work", "active"), ("## Completed", "completed")]:
        m = re.search(re.escape(section) + r"\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if not m:
            continue
        text = m.group(1)
        blocks = re.split(r"(?=^- \*\*)", text, flags=re.MULTILINE)
        for block in blocks:
            block = block.strip()
            if not block.startswith("- **"):
                continue
            header = re.match(r"- \*\*(.+?)\*\*\s*—\s*(\w+)", block)
            if not header:
                continue
            feature = header.group(1).strip()
            tool = header.group(2).strip()
            entry = {
                "id": slugify(feature),
                "feature": feature,
                "tool": tool,
                "status": "active" if key == "active" else "completed",
                "started": "",
                "updated": "",
                "plan_path": "",
                "branch": "",
                "worktree": "",
                "files": [],
                "current_path": "",
                "subagents": [],
                "legacy_raw": block,
            }
            for pat, field in [
                (r"Plan:\s*([^\n]+)", "plan_path"),
                (r"Branch:\s*([\w/\-]+)", "branch"),
                (r"Worktree:\s*([^\s.]+)", "worktree"),
            ]:
                mm = re.search(pat, block)
                if mm:
                    entry[field] = mm.group(1).strip()
            files_m = re.search(
                r"Files(?: modified)?:\s*(.+?)"
                r"(?=\s*(?:Branch|Status|Plan|Depends on|Merged|Waiting|Overlaps|Worktree):"
                r"|\n\s*[A-Z]|\Z)",
                block, re.DOTALL,
            )
            if files_m:
                raw = files_m.group(1).strip().rstrip(".").strip("[]")
                entry["files"] = [f.strip() for f in raw.split(",") if f.strip()]
            data[key].append(entry)

    write_workboard(data)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "feature"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def find_agent(wb: dict, feature_or_id: str, section: str = "active") -> tuple | None:
    """Return (section_list, index, entry) or None."""
    target = feature_or_id.lower()
    lst = wb.get(section, [])
    for i, e in enumerate(lst):
        if e.get("id", "").lower() == target or e.get("feature", "").lower() == target:
            return lst, i, e
    return None


def find_subagent(parent: dict, sub_id_or_name: str) -> tuple | None:
    target = sub_id_or_name.lower()
    subs = parent.get("subagents", [])
    for i, s in enumerate(subs):
        if s.get("id", "").lower() == target or s.get("feature", "").lower() == target:
            return subs, i, s
    return None


# ---- Progress tree helpers ------------------------------------------------
# Separator requires whitespace on BOTH sides of '/', so titles containing '/'
# (e.g., "POST /foo") are not over-split.
PATH_SEP = re.compile(r"\s+/\s+")


def split_path(path: str) -> list[str]:
    if not path:
        return []
    return [p.strip() for p in PATH_SEP.split(path.strip()) if p.strip()]


def find_node(plan: dict, path_parts: list[str]) -> dict | None:
    """Walk plan tree by titles. Returns the node dict, or None if not found."""
    node = plan
    for part in path_parts:
        children = node.get("children") or []
        match = None
        for c in children:
            if c.get("title", "").lower() == part.lower():
                match = c
                break
        if match is None:
            return None
        node = match
    return node


def ensure_node(plan: dict, path_parts: list[str], level: str, create_intermediate: bool = False):
    """Ensure a node exists at path_parts. If missing and create_intermediate, create as 'node'.
    Returns the created/existing node."""
    node = plan
    for i, part in enumerate(path_parts):
        children = node.setdefault("children", [])
        match = None
        for c in children:
            if c.get("title", "").lower() == part.lower():
                match = c
                break
        if match is None:
            is_leaf = i == len(path_parts) - 1
            lvl = level if is_leaf else "node"
            new_node = {"title": part, "level": lvl, "status": "pending", "children": []}
            children.append(new_node)
            match = new_node
        node = match
    return node


def propagate_status(node: dict):
    """Bottom-up: if all children done, mark done. If any active/done but not all done, mark active.
    Leaves are unchanged."""
    children = node.get("children") or []
    for c in children:
        propagate_status(c)
    if not children:
        return
    statuses = [c.get("status", "pending") for c in children]
    if all(s == "done" for s in statuses):
        node["status"] = "done"
    elif any(s in ("active", "done") for s in statuses):
        if node.get("status") != "done":
            node["status"] = "active"
    else:
        node["status"] = "pending"


def mark_ancestors_active(plan: dict, path_parts: list[str]):
    """When marking a deep node active, walk down from root and flip each ancestor to active
    (unless already done)."""
    node = plan
    if node.get("status") != "done":
        node["status"] = "active"
    for part in path_parts[:-1]:
        children = node.get("children") or []
        for c in children:
            if c.get("title", "").lower() == part.lower():
                if c.get("status") != "done":
                    c["status"] = "active"
                node = c
                break
        else:
            return


# ---------------------------------------------------------------------------
# Markdown rendering (read-only mirror)
# ---------------------------------------------------------------------------
STATUS_ICON = {"pending": "[ ]", "active": "[→]", "done": "[x]", "blocked": "[!]", "waiting": "[~]"}


def render_workboard_md(wb: dict) -> str:
    lines = ["# Workboard",
             "",
             "_Auto-generated from WORKBOARD.json by workboard.py. Do not edit by hand._",
             "",
             "## Active Work"]

    if not wb.get("active"):
        lines.append("_(none)_")
    for e in wb.get("active", []):
        status = e.get("status", "active")
        started = e.get("started", "?")
        lines.append(f"- **{e.get('feature','?')}** ({e.get('id','?')}) — {e.get('tool','?')} — "
                     f"Started {started}. Status: {status}.")
        if e.get("plan_path"):
            lines.append(f"  Plan: {e['plan_path']}")
        if e.get("current_path"):
            lines.append(f"  Current: {e['current_path']}")
        if e.get("files"):
            lines.append(f"  Files: [{', '.join(e['files'])}]")
        if e.get("branch") or e.get("worktree"):
            b = e.get("branch", "?")
            w = e.get("worktree", "?")
            lines.append(f"  Branch: {b}. Worktree: {w}.")
        if e.get("overlap"):
            lines.append(f"  Overlaps with: {e['overlap']}")
        if e.get("waiting_reason"):
            lines.append(f"  Waiting reason: {e['waiting_reason']}")
        for sub in e.get("subagents", []):
            sub_status = sub.get("status", "active")
            sub_line = (f"  - _subagent_ **{sub.get('feature','?')}** ({sub.get('id','?')}) "
                        f"— status: {sub_status}")
            if sub.get("current_path"):
                sub_line += f" — at: {sub['current_path']}"
            lines.append(sub_line)
            if sub.get("branch"):
                lines.append(f"    Branch: {sub['branch']}. Worktree: {sub.get('worktree','?')}.")
        lines.append("")

    lines.append("## Completed")
    if not wb.get("completed"):
        lines.append("_(none)_")
    for e in wb.get("completed", []):
        completed_at = e.get("completed", e.get("updated", "?"))
        lines.append(f"- **{e.get('feature','?')}** ({e.get('id','?')}) — {e.get('tool','?')} "
                     f"— Completed {completed_at}. Branch: {e.get('branch','?')}. "
                     f"Merged: {e.get('merged','no')}.")
        if e.get("files"):
            lines.append(f"  Files modified: [{', '.join(e['files'])}]")

    lines.append("")
    return "\n".join(lines)


def render_progress_md(prog: dict) -> str:
    lines = ["# Progress",
             "",
             "_Auto-generated from PROGRESS.json by workboard.py. Do not edit by hand._",
             ""]

    if not prog:
        lines.append("_(no plans registered)_")
        lines.append("")
        return "\n".join(lines)

    for plan_id, plan in prog.items():
        icon = STATUS_ICON.get(plan.get("status", "pending"), "[ ]")
        lines.append(f"## {icon} {plan.get('title','?')} ({plan_id})")
        if plan.get("plan_path"):
            lines.append(f"_Plan file:_ `{plan['plan_path']}`")
        lines.append("")
        _render_children(plan, lines, depth=0)
        lines.append("")

    return "\n".join(lines)


def _render_children(node: dict, lines: list, depth: int):
    for child in node.get("children", []):
        icon = STATUS_ICON.get(child.get("status", "pending"), "[ ]")
        indent = "  " * depth
        agent = child.get("agent")
        tag = f" _({agent})_" if agent else ""
        lines.append(f"{indent}- {icon} {child.get('title','?')}{tag}")
        _render_children(child, lines, depth=depth + 1)


def write_mirrors(wb: dict, prog: dict):
    """Write the markdown mirrors for both files."""
    wb_md_path().write_text(render_workboard_md(wb), encoding="utf-8")
    prog_md_path().write_text(render_progress_md(prog), encoding="utf-8")


# ---------------------------------------------------------------------------
# Generic transaction wrapper
# ---------------------------------------------------------------------------
def transaction(fn):
    """Decorator: acquire lock, run handler with wb/prog loaded, persist + mirror."""
    def wrapper(args):
        lf = acquire_lock()
        try:
            migrate_legacy_markdown()
            wb = read_workboard()
            prog = read_progress()
            result = fn(args, wb, prog)
            write_workboard(wb)
            write_progress(prog)
            write_mirrors(wb, prog)
            return result
        finally:
            release_lock(lf)
    return wrapper


# ---------------------------------------------------------------------------
# Workboard commands (agent-level)
# ---------------------------------------------------------------------------
@transaction
def cmd_register(args, wb, prog):
    if find_agent(wb, args.feature):
        print(f"ERROR: Feature '{args.feature}' is already registered.", file=sys.stderr)
        sys.exit(1)
    entry = {
        "id": args.id or slugify(args.feature),
        "feature": args.feature,
        "tool": args.tool,
        "status": "active",
        "started": now_iso(),
        "updated": now_iso(),
        "plan_path": args.plan or "",
        "branch": args.branch,
        "worktree": args.worktree,
        "files": [f.strip() for f in (args.files or "").split(",") if f.strip()],
        "current_path": "",
        "overlap": args.overlap or "",
        "subagents": [],
    }
    wb.setdefault("active", []).append(entry)
    print(f"Registered '{entry['feature']}' (id: {entry['id']}).")


@transaction
def cmd_update_status(args, wb, prog):
    found = find_agent(wb, args.feature)
    if not found:
        print(f"ERROR: Feature '{args.feature}' not found.", file=sys.stderr)
        sys.exit(1)
    _, _, entry = found
    entry["status"] = args.status
    entry["updated"] = now_iso()
    if args.reason:
        entry["waiting_reason"] = args.reason
    elif args.status == "active":
        entry.pop("waiting_reason", None)
    print(f"Updated '{entry['feature']}' status to '{args.status}'.")


@transaction
def cmd_update_files(args, wb, prog):
    found = find_agent(wb, args.feature)
    if not found:
        print(f"ERROR: Feature '{args.feature}' not found.", file=sys.stderr)
        sys.exit(1)
    _, _, entry = found
    entry["files"] = [f.strip() for f in args.files.split(",") if f.strip()]
    entry["updated"] = now_iso()
    print(f"Updated '{entry['feature']}' file list ({len(entry['files'])} files).")


@transaction
def cmd_set_overlap(args, wb, prog):
    found = find_agent(wb, args.feature)
    if not found:
        print(f"ERROR: Feature '{args.feature}' not found.", file=sys.stderr)
        sys.exit(1)
    _, _, entry = found
    entry["overlap"] = args.overlap
    entry["updated"] = now_iso()
    print(f"Updated overlap info for '{entry['feature']}'.")


@transaction
def cmd_update_path(args, wb, prog):
    """Update an agent's current_path (where it's working in the progress tree)."""
    found = find_agent(wb, args.feature)
    if not found:
        print(f"ERROR: Feature '{args.feature}' not found.", file=sys.stderr)
        sys.exit(1)
    _, _, entry = found
    entry["current_path"] = args.path
    entry["updated"] = now_iso()
    print(f"'{entry['feature']}' current_path -> {args.path or '(cleared)'}.")


@transaction
def cmd_complete(args, wb, prog):
    found = find_agent(wb, args.feature)
    if not found:
        print(f"ERROR: Feature '{args.feature}' not found in Active Work.", file=sys.stderr)
        sys.exit(1)
    active_list, idx, entry = found
    entry["status"] = "completed"
    entry["completed"] = now_iso()
    entry["updated"] = now_iso()
    entry["merged"] = args.merged or "no"
    if args.files:
        entry["files"] = [f.strip() for f in args.files.split(",") if f.strip()]
    active_list.pop(idx)
    wb.setdefault("completed", []).append(entry)
    # Also mark the plan done in PROGRESS.json if it exists
    if entry["id"] in prog:
        prog[entry["id"]]["status"] = "done"
        # mark all nodes done recursively
        _mark_tree_done(prog[entry["id"]])
    print(f"Moved '{entry['feature']}' to Completed.")
    # Stash the worktree path so main() can invoke cleanup AFTER the transaction
    # releases the WORKBOARD lock. Auto-cleanup is opt-out via --no-auto-cleanup.
    wt_path = entry.get("worktree", "") or ""
    if wt_path and not getattr(args, "no_auto_cleanup", False):
        args._auto_cleanup_worktree = wt_path


def _mark_tree_done(node):
    node["status"] = "done"
    for c in node.get("children", []):
        _mark_tree_done(c)


# ---------------------------------------------------------------------------
# Sub-agent commands (parent reports on behalf of sub-agent)
# ---------------------------------------------------------------------------
@transaction
def cmd_register_subagent(args, wb, prog):
    parent = find_agent(wb, args.parent)
    if not parent:
        print(f"ERROR: Parent feature '{args.parent}' not found.", file=sys.stderr)
        sys.exit(1)
    _, _, pentry = parent
    sub_id = args.id or f"{pentry['id']}/{slugify(args.feature)}"
    if find_subagent(pentry, sub_id):
        print(f"ERROR: Sub-agent '{sub_id}' already exists under parent.", file=sys.stderr)
        sys.exit(1)
    sub = {
        "id": sub_id,
        "feature": args.feature,
        "status": "active",
        "started": now_iso(),
        "updated": now_iso(),
        "current_path": args.task or "",
        "branch": args.branch or "",
        "worktree": args.worktree or "",
        "files": [f.strip() for f in (args.files or "").split(",") if f.strip()],
    }
    pentry.setdefault("subagents", []).append(sub)
    pentry["updated"] = now_iso()
    # If a task path was given, mark that task active in the parent's plan
    if args.task and pentry["id"] in prog:
        parts = split_path(args.task)
        node = find_node(prog[pentry["id"]], parts)
        if node is not None:
            node["status"] = "active"
            node["agent"] = sub_id
            mark_ancestors_active(prog[pentry["id"]], parts)
    print(f"Registered sub-agent '{sub['feature']}' (id: {sub_id}) under parent '{pentry['feature']}'.")


@transaction
def cmd_complete_subagent(args, wb, prog):
    parent = find_agent(wb, args.parent)
    if not parent:
        print(f"ERROR: Parent feature '{args.parent}' not found.", file=sys.stderr)
        sys.exit(1)
    _, _, pentry = parent
    found = find_subagent(pentry, args.sub)
    if not found:
        print(f"ERROR: Sub-agent '{args.sub}' not found under parent.", file=sys.stderr)
        sys.exit(1)
    subs, idx, sub = found
    # Mark its task done if it had one
    if sub.get("current_path") and pentry["id"] in prog:
        parts = split_path(sub["current_path"])
        node = find_node(prog[pentry["id"]], parts)
        if node is not None:
            node["status"] = "done"
            propagate_status(prog[pentry["id"]])
    subs.pop(idx)
    pentry["updated"] = now_iso()
    print(f"Completed sub-agent '{sub['feature']}' under '{pentry['feature']}'.")


@transaction
def cmd_update_subagent_path(args, wb, prog):
    parent = find_agent(wb, args.parent)
    if not parent:
        print(f"ERROR: Parent feature '{args.parent}' not found.", file=sys.stderr)
        sys.exit(1)
    _, _, pentry = parent
    found = find_subagent(pentry, args.sub)
    if not found:
        print(f"ERROR: Sub-agent '{args.sub}' not found under parent.", file=sys.stderr)
        sys.exit(1)
    _, _, sub = found
    sub["current_path"] = args.path
    sub["updated"] = now_iso()
    pentry["updated"] = now_iso()
    print(f"Sub-agent '{sub['feature']}' current_path -> {args.path or '(cleared)'}.")


# ---------------------------------------------------------------------------
# Progress commands (plan / phase / wave / task)
# ---------------------------------------------------------------------------
@transaction
def cmd_register_plan(args, wb, prog):
    plan_id = args.id or slugify(args.feature)
    if plan_id in prog:
        print(f"ERROR: Plan '{plan_id}' already registered in PROGRESS.json.", file=sys.stderr)
        sys.exit(1)
    prog[plan_id] = {
        "title": args.plan_title or args.feature,
        "level": "plan",
        "status": "pending",
        "plan_path": args.plan_path or "",
        "children": [],
        "created": now_iso(),
    }
    # Also ensure the workboard entry carries the plan_path / id link
    found = find_agent(wb, args.feature) or find_agent(wb, plan_id)
    if found:
        _, _, entry = found
        if args.plan_path:
            entry["plan_path"] = args.plan_path
        entry["id"] = plan_id
        entry["updated"] = now_iso()
    print(f"Registered plan '{prog[plan_id]['title']}' (id: {plan_id}).")


def _add_child(prog, feature_id, parent_path, title, level):
    if feature_id not in prog:
        print(f"ERROR: Plan '{feature_id}' not registered. Call register-plan first.", file=sys.stderr)
        sys.exit(1)
    plan = prog[feature_id]
    parent_parts = split_path(parent_path) if parent_path else []
    if parent_parts:
        parent = find_node(plan, parent_parts)
        if parent is None:
            print(f"ERROR: Parent path '{parent_path}' not found in plan '{feature_id}'.",
                  file=sys.stderr)
            sys.exit(1)
    else:
        parent = plan
    children = parent.setdefault("children", [])
    for c in children:
        if c.get("title", "").lower() == title.lower():
            print(f"ERROR: '{title}' already exists under {parent_path or 'plan root'}.",
                  file=sys.stderr)
            sys.exit(1)
    new_node = {"title": title, "level": level, "status": "pending", "children": []}
    children.append(new_node)
    print(f"Added {level} '{title}' under {parent_path or 'plan root'}.")


@transaction
def cmd_add_phase(args, wb, prog):
    _add_child(prog, _resolve_plan_id(wb, prog, args.feature), None, args.title, "phase")


@transaction
def cmd_add_wave(args, wb, prog):
    pid = _resolve_plan_id(wb, prog, args.feature)
    _add_child(prog, pid, args.phase, args.title, "wave")


@transaction
def cmd_add_task(args, wb, prog):
    pid = _resolve_plan_id(wb, prog, args.feature)
    parent_path = " / ".join(p for p in [args.phase, args.wave] if p)
    _add_child(prog, pid, parent_path, args.title, "task")


@transaction
def cmd_add_node(args, wb, prog):
    """Generic add — create a node at any path with a given level."""
    pid = _resolve_plan_id(wb, prog, args.feature)
    _add_child(prog, pid, args.parent, args.title, args.level or "node")


@transaction
def cmd_start(args, wb, prog):
    pid = _resolve_plan_id(wb, prog, args.feature)
    plan = prog[pid]
    parts = split_path(args.at) if args.at else []
    if parts:
        node = find_node(plan, parts)
        if node is None:
            print(f"ERROR: Path '{args.at}' not found in plan '{pid}'.", file=sys.stderr)
            sys.exit(1)
        node["status"] = "active"
        mark_ancestors_active(plan, parts)
    else:
        plan["status"] = "active"
    # Reflect location on the agent's workboard entry
    found = find_agent(wb, pid) or find_agent(wb, args.feature)
    if found:
        _, _, entry = found
        entry["current_path"] = args.at or ""
        entry["updated"] = now_iso()
    print(f"Started {'/'.join(parts) if parts else pid}.")


@transaction
def cmd_done(args, wb, prog):
    pid = _resolve_plan_id(wb, prog, args.feature)
    plan = prog[pid]
    parts = split_path(args.at) if args.at else []
    if parts:
        node = find_node(plan, parts)
        if node is None:
            print(f"ERROR: Path '{args.at}' not found in plan '{pid}'.", file=sys.stderr)
            sys.exit(1)
        _mark_tree_done(node)
    else:
        _mark_tree_done(plan)
    propagate_status(plan)
    # Clear current_path on the agent entry if it matched
    found = find_agent(wb, pid) or find_agent(wb, args.feature)
    if found:
        _, _, entry = found
        if entry.get("current_path") == args.at:
            entry["current_path"] = ""
        entry["updated"] = now_iso()
    print(f"Done: {'/'.join(parts) if parts else pid}.")


def _resolve_plan_id(wb, prog, feature_or_id: str) -> str:
    """Resolve a user-supplied feature name/id to a plan id that exists in PROGRESS.json.
    Falls back to slugified name if the plan isn't registered yet (caller handles error)."""
    target = feature_or_id.lower()
    # Direct id match
    for pid in prog:
        if pid.lower() == target:
            return pid
    # Match by plan title
    for pid, plan in prog.items():
        if plan.get("title", "").lower() == target:
            return pid
    # Match by workboard feature name
    found = find_agent(wb, feature_or_id) or find_agent(wb, feature_or_id, section="completed")
    if found:
        _, _, entry = found
        return entry.get("id", slugify(feature_or_id))
    return slugify(feature_or_id)


# ---------------------------------------------------------------------------
# Show / refresh
# ---------------------------------------------------------------------------
def cmd_show(args):
    migrate_legacy_markdown()
    wb = read_workboard()
    prog = read_progress()
    if args.feature:
        pid = _resolve_plan_id(wb, prog, args.feature)
        found = find_agent(wb, pid) or find_agent(wb, args.feature, "completed")
        if found:
            _, _, entry = found
            print(render_workboard_md({"active": [entry], "completed": []}))
        if pid in prog:
            print(render_progress_md({pid: prog[pid]}))
    else:
        print(render_workboard_md(wb))
        print()
        print(render_progress_md(prog))


def cmd_refresh_markdown(args):
    lf = acquire_lock()
    try:
        migrate_legacy_markdown()
        wb = read_workboard()
        prog = read_progress()
        write_mirrors(wb, prog)
        print(f"Refreshed {wb_md_path().name} and {prog_md_path().name}.")
    finally:
        release_lock(lf)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Atomic multi-agent coordination (WORKBOARD + PROGRESS).")
    sub = p.add_subparsers(dest="command", required=True)

    # register (agent)
    r = sub.add_parser("register", help="Register a new feature/agent in Active Work")
    r.add_argument("--feature", required=True)
    r.add_argument("--tool", required=True, help="claude, gemini, codex, cursor, etc.")
    r.add_argument("--plan", default="", help="Path to plan file")
    r.add_argument("--files", default="", help="Comma-separated list of files to be touched")
    r.add_argument("--branch", required=True)
    r.add_argument("--worktree", required=True)
    r.add_argument("--overlap", default="")
    r.add_argument("--id", default="", help="Optional custom id (default: slugified feature)")
    r.set_defaults(func=cmd_register)

    us = sub.add_parser("update-status", help="Change status: active / waiting / blocked")
    us.add_argument("--feature", required=True)
    us.add_argument("--status", required=True, choices=["active", "waiting", "blocked"])
    us.add_argument("--reason", default="")
    us.set_defaults(func=cmd_update_status)

    uf = sub.add_parser("update-files", help="Replace the feature's tracked file list")
    uf.add_argument("--feature", required=True)
    uf.add_argument("--files", required=True)
    uf.set_defaults(func=cmd_update_files)

    so = sub.add_parser("set-overlap", help="Set the overlap description")
    so.add_argument("--feature", required=True)
    so.add_argument("--overlap", required=True)
    so.set_defaults(func=cmd_set_overlap)

    up = sub.add_parser("update-path", help="Update where the agent is in its progress tree")
    up.add_argument("--feature", required=True)
    up.add_argument("--path", required=True, help="E.g. 'Phase 2 / Wave 2.2 / Task 2.2.1' (use '' to clear)")
    up.set_defaults(func=cmd_update_path)

    comp = sub.add_parser("complete", help="Move feature from Active -> Completed")
    comp.add_argument("--feature", required=True)
    comp.add_argument("--files", default="", help="Optional final file list")
    comp.add_argument("--merged", default="no", choices=["yes", "no"])
    comp.add_argument("--no-auto-cleanup", action="store_true",
                      help="Skip the post-completion worktree cleanup (default: cleanup runs).")
    comp.set_defaults(func=cmd_complete)

    # sub-agent commands
    rs = sub.add_parser("register-subagent", help="Register a sub-agent under a parent feature")
    rs.add_argument("--parent", required=True, help="Parent feature name or id")
    rs.add_argument("--feature", required=True, help="Sub-agent feature name")
    rs.add_argument("--id", default="", help="Custom sub-agent id (default: parent/slug)")
    rs.add_argument("--task", default="", help="Optional task path the sub-agent owns")
    rs.add_argument("--branch", default="")
    rs.add_argument("--worktree", default="")
    rs.add_argument("--files", default="")
    rs.set_defaults(func=cmd_register_subagent)

    cs = sub.add_parser("complete-subagent", help="Mark a sub-agent finished (parent reports)")
    cs.add_argument("--parent", required=True)
    cs.add_argument("--sub", required=True, help="Sub-agent id or feature name")
    cs.set_defaults(func=cmd_complete_subagent)

    usp = sub.add_parser("update-subagent-path", help="Update sub-agent's current path")
    usp.add_argument("--parent", required=True)
    usp.add_argument("--sub", required=True)
    usp.add_argument("--path", required=True)
    usp.set_defaults(func=cmd_update_subagent_path)

    # progress commands
    rp = sub.add_parser("register-plan", help="Create a plan tree (titles only) in PROGRESS.json")
    rp.add_argument("--feature", required=True)
    rp.add_argument("--plan-title", default="", help="Human-readable plan title (default: feature name)")
    rp.add_argument("--plan-path", default="")
    rp.add_argument("--id", default="")
    rp.set_defaults(func=cmd_register_plan)

    ap = sub.add_parser("add-phase", help="Add a phase under the plan")
    ap.add_argument("--feature", required=True)
    ap.add_argument("--title", required=True)
    ap.set_defaults(func=cmd_add_phase)

    aw = sub.add_parser("add-wave", help="Add a wave (optionally under a phase)")
    aw.add_argument("--feature", required=True)
    aw.add_argument("--phase", default="", help="Parent phase title (omit for top-level wave)")
    aw.add_argument("--title", required=True)
    aw.set_defaults(func=cmd_add_wave)

    at = sub.add_parser("add-task", help="Add a task (under a phase/wave or directly)")
    at.add_argument("--feature", required=True)
    at.add_argument("--phase", default="")
    at.add_argument("--wave", default="")
    at.add_argument("--title", required=True)
    at.set_defaults(func=cmd_add_task)

    an = sub.add_parser("add-node", help="Generic: add a node at any parent path")
    an.add_argument("--feature", required=True)
    an.add_argument("--parent", default="", help="Parent path (e.g. 'Phase 1 / Wave 1.2')")
    an.add_argument("--title", required=True)
    an.add_argument("--level", default="node")
    an.set_defaults(func=cmd_add_node)

    st = sub.add_parser("start", help="Mark a node (or the whole plan) active")
    st.add_argument("--feature", required=True)
    st.add_argument("--at", default="", help="Path, e.g. 'Phase 2 / Wave 2.2 / Task 1' (empty = plan)")
    st.set_defaults(func=cmd_start)

    dn = sub.add_parser("done", help="Mark a node (and all descendants) done")
    dn.add_argument("--feature", required=True)
    dn.add_argument("--at", default="")
    dn.set_defaults(func=cmd_done)

    sh = sub.add_parser("show", help="Print WORKBOARD + PROGRESS as a readable tree")
    sh.add_argument("--feature", default="", help="Scope to one feature")
    sh.set_defaults(func=cmd_show)

    rm = sub.add_parser("refresh-markdown", help="Regenerate WORKBOARD.md / PROGRESS.md from JSON")
    rm.set_defaults(func=cmd_refresh_markdown)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    # Post-transaction actions: if `complete` flagged a worktree for auto-cleanup,
    # invoke the cleanup script now that the WORKBOARD lock has been released.
    # Doing this *outside* the transaction means a long-running cleanup doesn't
    # hold the lock and block other agents. The cleanup script has its own safety
    # gates (active-elsewhere check, unpushed-branch check, junction-into-.git
    # check) — if any fire, it refuses and prints why; we surface that to the
    # caller but do NOT roll back the completion (work tracking and worktree
    # disk hygiene are separate concerns).
    wt_to_clean = getattr(args, "_auto_cleanup_worktree", None)
    if wt_to_clean:
        _invoke_worktree_cleanup(wt_to_clean)


def _invoke_worktree_cleanup(worktree_path: str) -> None:
    """Invoke the worktree cleanup script as a subprocess. Best-effort — failures
    are surfaced but do not propagate (the workboard transaction has already
    succeeded by the time we get here)."""
    import subprocess
    script = Path.home() / ".ai-instructions" / "tools" / "worktree_cleanup.py"
    if not script.is_file():
        print(f"NOTE: skipped auto-cleanup ({script} not found).", file=sys.stderr)
        return
    if not Path(worktree_path).exists():
        # Worktree directory already gone — nothing to do.
        return
    print(f"\nAuto-cleanup: removing worktree at {worktree_path}")
    try:
        result = subprocess.run(
            ["py", str(script), worktree_path],
            capture_output=False, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"NOTE: auto-cleanup did not complete (exit {result.returncode}). "
                  "The completion is already recorded; clean up the worktree manually if needed.",
                  file=sys.stderr)
    except Exception as e:
        print(f"NOTE: auto-cleanup raised: {e}. Clean up the worktree manually if needed.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
