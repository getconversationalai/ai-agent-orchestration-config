#!/usr/bin/env bash
# Weekly hygiene sweep — the "enforce" half of create-without-destroy.
# CONSERVATIVE: only removes worktrees that are CLEAN (no uncommitted changes)
# AND pushed (the cleanup script refuses unpushed). Never touches dirty/unpushed
# work. Appends a log; never deletes branches. Safe to run unattended.
#
# Register once (ADMIN terminal):
#   schtasks /create /tn "DevHygieneSweep" /f /sc weekly /d SUN /st 03:00 \
#     /tr "\"C:\Program Files\Git\bin\bash.exe\" -lc \"~/.claude/hooks/weekly_hygiene.sh\""

log="$HOME/dev-hygiene.log"
{
  echo "================= $(date) ================="
  pruned=0
  for r in /c/dev/*/; do
    r="${r%/}"
    git -C "$r" rev-parse --git-dir >/dev/null 2>&1 || continue
    ( cd "$r" && \
      git worktree list --porcelain 2>/dev/null | awk '/^worktree /{wt=$2} /^branch /{print wt"\t"$2}' | \
      while IFS=$'\t' read p b; do
        case "$p" in *worktree*) ;; *) continue;; esac
        case "$p" in *_scratch*) continue;; esac
        [ -z "$b" ] && continue
        [ -n "$(git -C "$p" status --porcelain 2>/dev/null | head -1)" ] && continue   # skip dirty
        if py C:/Users/yehos/.ai-instructions/tools/worktree_cleanup.py "$p" --no-delete-branch >/dev/null 2>&1; then
          echo "  pruned: $(basename "$r") | ${b#refs/heads/}"
        fi
      done )
  done

  echo "  -- orphan node/claude processes (report only, not auto-killed) --"
  MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' tasklist /fi "imagename eq node.exe" /fo csv /nh 2>/dev/null | tr -d '\r' | grep -c node | sed 's/^/  live node procs: /'

  free=$(MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' wmic logicaldisk where "DeviceID='C:'" get FreeSpace /value 2>/dev/null | tr -d '\r' | grep -o '[0-9][0-9]*' | head -1)
  awk "BEGIN{printf \"  C: %.1f GB free\n\", ${free:-0}/1073741824}"
} >> "$log" 2>&1
