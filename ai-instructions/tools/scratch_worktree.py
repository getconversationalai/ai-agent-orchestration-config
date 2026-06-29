"""
Reusable "scratch" worktree for quick, single-concern fixes.

Problem: spinning up a fresh per-fix worktree costs a full `npm install`
(minutes) plus a slow Windows teardown. For a one-or-two-file fix that's almost
all overhead. This helper keeps ONE long-lived worktree per repo at

    ../.worktrees/<project>/_scratch

whose node_modules persists between uses, and resets it to a fresh branch off
the latest origin/<base> on demand. It is protected from worktree_cleanup.py
(by the `_scratch` basename and a `.scratch-keep` marker) so it is never
deleted — there's no create / install / teardown overhead for the common case.

When to use it:
  ✅ quick single-concern fixes you'll finish and merge in one pass
  ❌ NOT feature-sized, long-running, or parallel multi-agent work — those get
     their own dedicated per-branch worktree (scratch holds one branch at a
     time, so it is inherently serial).

ONE scratch per repo, shared by every agent → CONCURRENCY HAZARD. If a second
agent recycles it while a first agent is mid-fix, the reset --hard / clean / -B
silently destroys the first agent's uncommitted work. To prevent that, this
script refuses to recycle a BUSY scratch (see is_scratch_busy) and only proceeds
once the previous occupant has committed + pushed and walked away — or when you
pass --force to override. Each successful acquire stamps a heartbeat so a crashed
session's lock ages out after STALE_MINUTES instead of blocking forever.

Usage (run from anywhere inside the repo):
    py ~/.ai-instructions/tools/scratch_worktree.py fix/<scope>
    py ~/.ai-instructions/tools/scratch_worktree.py fix/<scope> --base dev
    py ~/.ai-instructions/tools/scratch_worktree.py fix/<scope> --force  # clobber a busy scratch
    py ~/.ai-instructions/tools/scratch_worktree.py --path   # just print the path

It will:
  1. Create the scratch worktree on first use (one-time npm install).
  2. Refuse if the scratch is BUSY (another agent's uncommitted/unpushed work, or
     a fresh heartbeat) unless --force is given.
  3. git fetch origin <base>; reset the scratch tree to a fresh <branch> off
     origin/<base> (discarding any leftover state from the previous fix).
  4. npm install — skipped automatically when package-lock.json is unchanged
     since the last run, so repeat resets are near-instant.
  5. Stamp a heartbeat and print the path to edit in.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

SCRATCH_DIRNAME = "_scratch"
SCRATCH_MARKER = ".scratch-keep"
SCRATCH_HEARTBEAT = ".scratch-heartbeat"  # touched on every acquire; ages out for busy-detection
DEPS_STAMP = "scratch-deps.sha256"  # stored in the main repo's .git (one scratch per repo)
STALE_MINUTES = 30  # heartbeat older than this = the previous session walked away; safe to recycle


def main():
    parser = argparse.ArgumentParser(
        description="Create/reset the reusable scratch worktree to a fresh branch off origin/<base>.")
    parser.add_argument("branch", nargs="?",
                        help="Branch to (re)create off origin/<base>, e.g. fix/email-popover-url")
    parser.add_argument("--base", default=None,
                        help="Base branch (default: auto-detect dev else main).")
    parser.add_argument("--path", action="store_true",
                        help="Just print the scratch worktree path and exit.")
    parser.add_argument("--force", action="store_true",
                        help="Recycle the scratch worktree even if another agent appears to be "
                             "using it (DESTROYS their uncommitted work). Only when you are sure "
                             "no one else is mid-fix.")
    args = parser.parse_args()

    start = os.getcwd()
    main_root = find_main_root(start)
    if not main_root:
        die("Not inside a git repository.")

    project = os.path.basename(main_root)
    scratch_path = os.path.join(os.path.dirname(main_root), ".worktrees", project, SCRATCH_DIRNAME)

    if args.path:
        print(scratch_path)
        return

    if not args.branch:
        parser.print_help()
        sys.exit(1)

    base = args.base or detect_base(main_root)

    # Ensure the marker + heartbeat are excluded repo-wide (idempotent; covers
    # scratch worktrees created before this guard existed).
    add_exclude(main_root)

    # 1. Fetch the latest base.
    info(f"Fetching origin/{base} ...")
    run(["git", "fetch", "origin", base], cwd=main_root, timeout=180)

    origin_base = f"origin/{base}"
    if not ref_exists(main_root, origin_base):
        # Fall back to a local base ref (offline / no origin configured).
        if ref_exists(main_root, base):
            origin_base = base
            warn(f"origin/{base} not found; using local {base}.")
        else:
            die(f"Neither origin/{base} nor {base} exists. Pass --base <branch>.")

    # 2. Ensure the scratch worktree exists (one-time create).
    created = ensure_scratch(main_root, scratch_path, origin_base)

    # 2b. Refuse to clobber a scratch another agent is mid-fix in (unless --force).
    if not created:
        reasons = scratch_busy_reasons(scratch_path)
        if reasons and not args.force:
            die("Scratch worktree is BUSY — another agent appears to be working in it:\n"
                + "\n".join(f"      - {r}" for r in reasons)
                + f"\n\n    Path: {scratch_path}\n"
                  "    Recycling now would DESTROY their uncommitted work.\n"
                  "    Options:\n"
                  "      - Wait for them to commit + push, then re-run this command.\n"
                  "      - Use a dedicated per-branch worktree instead:\n"
                  "          git worktree add ../.worktrees/<project>/<branch> -b <branch> origin/"
                  + base + "\n"
                  "      - If you are CERTAIN no one else is in it (e.g. a crashed session), re-run "
                  "with --force.")
        if reasons and args.force:
            warn("--force: recycling a BUSY scratch worktree. Discarding:\n"
                 + "\n".join(f"      - {r}" for r in reasons))

    # 3. Reset to a fresh branch off the base.
    info(f"Resetting scratch worktree to '{args.branch}' off {origin_base} ...")
    dirty = run(["git", "status", "--porcelain"], cwd=scratch_path).stdout.strip()
    if dirty:
        warn("Scratch worktree had leftover changes from a previous fix — discarding them.")
    run(["git", "reset", "--hard"], cwd=scratch_path, timeout=60)
    run(["git", "clean", "-fd"], cwd=scratch_path, timeout=120)  # no -x: keeps node_modules + marker
    co = run(["git", "checkout", "-B", args.branch, origin_base], cwd=scratch_path, timeout=60)
    if co.returncode != 0:
        die(f"Could not checkout -B {args.branch}: {co.stderr.strip()}\n"
            "Is that branch checked out in another worktree? Pick a different name "
            "or remove the other worktree first.")
    write_marker(scratch_path)

    # 4. npm install — skipped when the lockfile is unchanged.
    maybe_npm_install(main_root, scratch_path, force=created)

    # 5. Stamp the heartbeat so a concurrent agent sees this slot as busy.
    touch_heartbeat(scratch_path)

    print()
    info(f"Scratch worktree ready on branch '{args.branch}':")
    print(f"    {scratch_path}")
    info("Edit there -> build/verify -> commit -> push to main (or open a PR) -> walk away.")
    info("Next quick fix: re-run this with a new branch name. Never delete the scratch worktree.")


# ─────────────────────────────────────────────
# Repo / ref helpers
# ─────────────────────────────────────────────

def find_main_root(start):
    """Resolve the MAIN repo root, even when run from inside a worktree.

    `--git-common-dir` points at the shared <main>/.git for every worktree, so
    its parent is always the main repo root."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5, cwd=start,
        )
        if r.returncode != 0:
            return None
        common = os.path.normpath(os.path.join(start, r.stdout.strip()))
        return os.path.dirname(common)
    except Exception:
        return None


def detect_base(main_root):
    """Prefer dev if the repo has one, else main."""
    try:
        r = subprocess.run(
            ["git", "branch", "--list", "dev", "main"],
            capture_output=True, text=True, timeout=5, cwd=main_root,
        )
        names = [b.strip().lstrip("* ") for b in r.stdout.splitlines()]
        if "dev" in names:
            return "dev"
    except Exception:
        pass
    return "main"


def ref_exists(cwd, ref):
    try:
        return subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        ).returncode == 0
    except Exception:
        return False


# ─────────────────────────────────────────────
# Busy-detection (concurrency guard)
# ─────────────────────────────────────────────

def scratch_busy_reasons(scratch_path):
    """Return a list of human-readable reasons the scratch is in active use, or
    [] if it is safe to recycle.

    Busy when ANY of:
      - the working tree has uncommitted changes (excludes the marker/heartbeat,
        which live in .git/info/exclude), OR
      - the checked-out branch has commits not yet on its remote (work at risk if
        we reset before it's pushed), OR
      - the heartbeat was touched within STALE_MINUTES (a live session).

    The normal end-state — committed AND pushed AND walked away long enough for the
    heartbeat to age out — reports NOT busy, so recycling stays frictionless."""
    reasons = []

    # Ignore our own marker/heartbeat files — they are bookkeeping, not user work,
    # and would otherwise make the scratch look perpetually dirty if .git/info/exclude
    # wasn't applied for any reason.
    own = {SCRATCH_MARKER, SCRATCH_HEARTBEAT}
    dirty_lines = [
        ln for ln in run(["git", "status", "--porcelain"], cwd=scratch_path).stdout.splitlines()
        if ln.strip() and os.path.basename(ln[3:].strip()) not in own
    ]
    if dirty_lines:
        reasons.append(f"{len(dirty_lines)} uncommitted change(s) in the working tree")

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=scratch_path).stdout.strip()
    if branch and branch != "HEAD":
        # Commits on this branch not reachable from any remote-tracking ref = unpushed.
        unpushed = run(
            ["git", "rev-list", "--count", "HEAD", "--not", "--remotes"],
            cwd=scratch_path,
        ).stdout.strip()
        if unpushed.isdigit() and int(unpushed) > 0:
            reasons.append(f"branch '{branch}' has {unpushed} unpushed commit(s)")

    age = heartbeat_age_minutes(scratch_path)
    if age is not None and age < STALE_MINUTES:
        reasons.append(f"heartbeat is {age:.0f} min old (< {STALE_MINUTES} min — a live session)")

    return reasons


def heartbeat_age_minutes(scratch_path):
    """Minutes since the heartbeat was last touched, or None if it doesn't exist."""
    hb = os.path.join(scratch_path, SCRATCH_HEARTBEAT)
    try:
        return (time.time() - os.path.getmtime(hb)) / 60.0
    except OSError:
        return None


def touch_heartbeat(scratch_path):
    """Write/refresh the heartbeat marker so concurrent agents see this slot busy."""
    try:
        with open(os.path.join(scratch_path, SCRATCH_HEARTBEAT), "w", encoding="utf-8") as f:
            f.write(f"acquired={int(time.time())} pid={os.getpid()}\n")
    except Exception as e:
        warn(f"Could not write {SCRATCH_HEARTBEAT}: {e}")


def is_registered_worktree(main_root, scratch_path):
    target = os.path.normpath(os.path.abspath(scratch_path)).lower()
    try:
        r = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=10, cwd=main_root,
        )
        for line in r.stdout.splitlines():
            if line.startswith("worktree "):
                p = os.path.normpath(os.path.abspath(line[len("worktree "):].strip())).lower()
                if p == target:
                    return True
    except Exception:
        pass
    return False


def ensure_scratch(main_root, scratch_path, origin_base):
    """Create the scratch worktree if missing. Returns True if newly created."""
    if is_registered_worktree(main_root, scratch_path) and os.path.isdir(scratch_path):
        return False
    # Stale registration without a dir (or vice versa) → prune, then re-add cleanly.
    run(["git", "worktree", "prune"], cwd=main_root)
    os.makedirs(os.path.dirname(scratch_path), exist_ok=True)
    info(f"Creating scratch worktree at {scratch_path} (one-time) ...")
    r = run(["git", "worktree", "add", "--detach", scratch_path, origin_base],
            cwd=main_root, timeout=300)
    if r.returncode != 0:
        die(f"Failed to create scratch worktree: {r.stderr.strip()}")
    write_marker(scratch_path)
    add_exclude(main_root)  # ignore the marker repo-wide so it never shows in status / gets cleaned
    return True


# ─────────────────────────────────────────────
# Marker + exclude (cleanup protection)
# ─────────────────────────────────────────────

def write_marker(scratch_path):
    try:
        with open(os.path.join(scratch_path, SCRATCH_MARKER), "w", encoding="utf-8") as f:
            f.write("This is the reusable scratch worktree. worktree_cleanup.py will never "
                    "delete it. Recycle it with: scratch_worktree.py <branch>\n")
    except Exception as e:
        warn(f"Could not write {SCRATCH_MARKER}: {e}")


def add_exclude(main_root):
    """Add the scratch marker + heartbeat to .git/info/exclude (shared across
    worktrees) so they never show up in `git status` (which would make the scratch
    look dirty and busy) or get removed by `git clean -fd`."""
    try:
        exclude = os.path.join(main_root, ".git", "info", "exclude")
        existing = ""
        if os.path.isfile(exclude):
            with open(exclude, "r", encoding="utf-8") as f:
                existing = f.read()
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        to_add = [name for name in (SCRATCH_MARKER, SCRATCH_HEARTBEAT) if name not in existing]
        if to_add:
            with open(exclude, "a", encoding="utf-8") as f:
                f.write("\n# reusable scratch worktree markers\n" + "".join(f"{n}\n" for n in to_add))
    except Exception as e:
        warn(f"Could not update .git/info/exclude: {e}")


# ─────────────────────────────────────────────
# Dependency install (lockfile-stamped, skips no-op installs)
# ─────────────────────────────────────────────

def maybe_npm_install(main_root, scratch_path, force):
    pkg = os.path.join(scratch_path, "package.json")
    if not os.path.isfile(pkg):
        return  # not a node project
    lock = os.path.join(scratch_path, "package-lock.json")
    stamp_path = os.path.join(main_root, ".git", DEPS_STAMP)
    current = file_sha256(lock) if os.path.isfile(lock) else "no-lock"

    if not force and os.path.isfile(stamp_path):
        try:
            with open(stamp_path, "r", encoding="utf-8") as f:
                if f.read().strip() == current:
                    info("Dependencies unchanged since last reset — skipping npm install.")
                    return
        except Exception:
            pass

    info("Installing dependencies (npm install) ...")
    r = run([npm_executable(), "install"], cwd=scratch_path, timeout=1200)
    if r.returncode != 0:
        warn("npm install reported a problem:\n" + (r.stderr.strip()[:800] or "(no stderr)"))
        return
    try:
        with open(stamp_path, "w", encoding="utf-8") as f:
            f.write(current)
    except Exception:
        pass


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────
# Process + logging helpers
# ─────────────────────────────────────────────

def npm_executable():
    """Resolve npm to a concrete executable (npm.cmd on Windows) so we never
    need shell=True — list-form args can't be reinterpreted as shell tokens."""
    return shutil.which("npm") or ("npm.cmd" if os.name == "nt" else "npm")


def run(cmd, cwd=None, timeout=60):
    """Run a command as a list (never via the shell), capturing output."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        warn(f"Command timed out after {timeout}s: {cmd}")
        class _R:  # minimal stand-in so callers can read .returncode/.stdout/.stderr
            returncode = 1
            stdout = ""
            stderr = f"timed out after {timeout}s"
        return _R()


def info(msg):
    print(f"  {msg}")


def warn(msg):
    print(f"  WARNING: {msg}", file=sys.stderr)


def die(msg):
    print(f"  ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
