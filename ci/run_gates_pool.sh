#!/usr/bin/env bash
# run_gates_pool.sh -- THE WHOLE SUITE LOCALLY, SHARDS IN PARALLEL, EACH IN ITS OWN COPY
# OF THE TREE (Wilson 11-12 addendum: "finish run_gates' worker pool"; SPEEDUP_SCOPE
# 11-05 D: every launch copies the tree, so editing continues while gates run).
#
#   bash ci/run_gates_pool.sh [--jobs N] [--shards a,b,c] [--keep]
#
# ⛔ WHY COPIES, NOT PARALLEL GATES IN ONE TREE: gates write fixed paths (probe_sda/,
#   probe_nl/, generated test/*.hex), so two gates in one tree can corrupt each other's
#   inputs. CI runs the shards on separate runners; this does the same on one machine.
# ⭐ THE SNAPSHOT IS THE WORKING TREE, not HEAD: `git stash create` makes a commit object
#   of the tracked edits WITHOUT touching the stash list or the tree; untracked,
#   non-ignored files are copied on top. Each shard gets a `git worktree` at that commit
#   (several gates need git: blob hashes, `git show <sha>:`, moved-since-v1-lock).
# ⚠ THE COPIES LIVE UNDER $ROOT/probe_pool (gitignored, on the repo's drive): WSL cannot
#   see Git Bash's /tmp, and two steps delegate to WSL (run_gates.sh, wsl_root).
# ⛔ GREEN ONLY IF EVERY SHARD REPORTED: each shard's own `GATES: n of m passed` line
#   is read back; a shard with no line (crash, kill) is RED as itself -- the rule CI's
#   gates-complete job enforces. --self-test plants a missing and a failing verdict.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PE_PYTHON:-$(command -v python3 || command -v python)}"
JOBS="${PE_GATE_JOBS:-4}"; ONLY=""; KEEP=0; SELF=0
while [ $# -gt 0 ]; do
  case "$1" in
    --jobs) JOBS="$2"; shift 2 ;;
    --shards) ONLY="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --self-test) SELF=1; shift ;;
    *) echo "usage: run_gates_pool.sh [--jobs N] [--shards a,b] [--keep] [--self-test]"; exit 2 ;;
  esac
done

# verdict over a directory of <shard>.rc / <shard>.gates files -> 0 green, 1 red
verdict() {
  local dir="$1"; shift; local rc=0 s line
  for s in "$@"; do
    line="$(cat "$dir/$s.gates" 2>/dev/null)"
    if [ -z "$line" ]; then
      echo "  ***  $s: NO VERDICT -- the shard never reported (rc $(cat "$dir/$s.rc" 2>/dev/null || echo '?'))"; rc=1
    elif [ "$(cat "$dir/$s.rc" 2>/dev/null)" != "0" ]; then
      echo "  ***  $s: rc $(cat "$dir/$s.rc") --$line"; rc=1
    else
      echo "  ok   $s:$line"
    fi
  done
  return $rc
}

if [ "$SELF" = "1" ]; then
  T="$(mktemp -d)"
  echo 0 > "$T/a.rc"; echo "  GATES: 3 of 3 passed" > "$T/a.gates"
  echo 0 > "$T/b.rc"; echo "  GATES: 2 of 2 passed" > "$T/b.gates"
  verdict "$T" a b > /dev/null; ctl=$?
  verdict "$T" a b c > /dev/null; miss=$?                       # c never reported
  echo 1 > "$T/b.rc"; verdict "$T" a b > /dev/null; fail=$?     # b failed
  rm -rf "$T"
  echo "  control: every shard reported and passed     $([ $ctl -eq 0 ] && echo 'green ok' || echo '*** RED')"
  echo "  must-fire: a shard with no verdict          $([ $miss -ne 0 ] && echo 'red  ok' || echo '*** STAYED GREEN')"
  echo "  must-fire: a shard that failed              $([ $fail -ne 0 ] && echo 'red  ok' || echo '*** STAYED GREEN')"
  [ $ctl -eq 0 ] && [ $miss -ne 0 ] && [ $fail -ne 0 ] && exit 0 || exit 1
fi

cd "$ROOT" || exit 1
"$PY" ci/shards.py check > /dev/null || { echo "  *** the shard map does not cover GATES: RED"; exit 1; }
mapfile -t SHARDS < <("$PY" ci/shards.py list | tr -d '[]" ' | tr ',' '\n' | sed '/^$/d')
if [ -n "$ONLY" ]; then
  mapfile -t SHARDS < <(echo "$ONLY" | tr ',' '\n' | sed '/^$/d')
  echo "  ⚠ --shards: a SUBSET ($ONLY) -- not the whole suite"
fi
SNAP="$(git stash create)"; SNAP="${SNAP:-$(git rev-parse HEAD)}"
POOL="$ROOT/probe_pool/$(date +%Y%m%d_%H%M%S)"; mkdir -p "$POOL/_out"
echo "  snapshot ${SNAP:0:10} (working tree incl. edits), ${#SHARDS[@]} shard(s), $JOBS at a time -> $POOL"
mapfile -t UNTRACKED < <(git ls-files -o --exclude-standard)

run_one() {   # <shard>
  local s="$1" w="$POOL/$1" t0=$(date +%s)
  git worktree add -q --detach "$w" "$SNAP" > /dev/null 2>&1 || { echo 9 > "$POOL/_out/$s.rc"; return; }
  local f; for f in "${UNTRACKED[@]}"; do mkdir -p "$w/$(dirname "$f")"; cp -p "$f" "$w/$f"; done
  ( cd "$w" && bash ci/run_gates.sh --shard "$s" > "$POOL/_out/$s.log" 2>&1 ); echo $? > "$POOL/_out/$s.rc"
  grep -E "^  GATES: " "$POOL/_out/$s.log" | tail -1 | sed 's/^  GATES:/ GATES:/' > "$POOL/_out/$s.gates"
  echo "  done $s rc $(cat "$POOL/_out/$s.rc") in $(( $(date +%s) - t0 )) s"
}

T0=$(date +%s)
for s in "${SHARDS[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
  run_one "$s" &
done
wait
echo
echo "=============================================================================="
echo "  POOL: ${#SHARDS[@]} shard(s) in $(( $(date +%s) - T0 )) s (logs: $POOL/_out)"
verdict "$POOL/_out" "${SHARDS[@]}"; rc=$?
if [ "$KEEP" = "0" ]; then
  for s in "${SHARDS[@]}"; do git worktree remove --force "$POOL/$s" > /dev/null 2>&1; done
  git worktree prune
fi
echo "  POOL VERDICT: $([ $rc -eq 0 ] && echo 'every shard reported and passed' || echo 'RED')${ONLY:+ (subset only)}"
exit $rc
