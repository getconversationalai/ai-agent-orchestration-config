#!/usr/bin/env bash
# Session-start resource health check.
# Surfaces disk / worktree / process drift EARLY (at #10, not #96) so the
# silent-accumulation crisis can't recur. Fast (no `du`); fails safe (exit 0).

free=$(MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' wmic logicaldisk where "DeviceID='C:'" get FreeSpace /value 2>/dev/null | tr -d '\r' | grep -o '[0-9][0-9]*' | head -1)
free_gb=$(awk "BEGIN{printf \"%.1f\", ${free:-0}/1073741824}")

wt=0
for r in /c/dev/*/; do
  r="${r%/}"
  git -C "$r" rev-parse --git-dir >/dev/null 2>&1 || continue
  c=$(git -C "$r" worktree list 2>/dev/null | grep -c .)
  [ "$c" -gt 1 ] && wt=$((wt + c - 1))
done

node=$(MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' tasklist /fi "imagename eq node.exe" /fo csv /nh 2>/dev/null | tr -d '\r' | grep -c node)

echo "[resource] C: ${free_gb} GB free | worktrees: ${wt} | node procs: ${node}"

warn=""
awk "BEGIN{exit !(${free_gb} < 15)}" && warn="${warn} LOW-DISK(<15GB)"
[ "$wt" -gt 20 ]  && warn="${warn} WORKTREES(>20)"
[ "$node" -gt 60 ] && warn="${warn} NODE-PROCS(>60)"

if [ -n "$warn" ]; then
  echo "  WARN:${warn}"
  echo "  -> clean:  py ~/.ai-instructions/tools/worktree_cleanup.py --all-merged   (run per repo)"
  echo "  -> reset:  full-quit & reopen Cursor   |   detail: bash ~/recovery-info.sh"
fi
exit 0
