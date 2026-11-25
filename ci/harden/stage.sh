#!/usr/bin/env bash
# harden.yml stage runner (Wilson ruling 11-25). Runs ONE LibreLane stage and watches it:
#   * silent-log watchdog: if nothing under the run dir (and the stage log) changed for SILENT_S seconds,
#     kill the flow and exit 124 with "WATCHDOG".
#   * detailed-routing progress gate (J3): DRT_GATE="0:45000,3:5000" -> if the violation count at the
#     end of pass k is above its line, kill the flow and exit 3 with "DRT GATE".
# usage: stage.sh <stage> <run_dir> <log> -- <command...>
#   SILENT_S (default from gates.json), DRT_GATE (optional)
# The job's own timeout-minutes is the hard wall-time limit above this.
set -uo pipefail
STAGE=$1; RUNDIR=$2; LOG=$3; shift 3; [ "${1:-}" = "--" ] && shift
HERE=$(cd "$(dirname "$0")" && pwd)
SILENT_S=${SILENT_S:-$(python3 -c "import json;print(json.load(open('$HERE/gates.json'))['silent_log_limit_s'])")}
mkdir -p "$RUNDIR"; : > "$LOG"
echo "[stage $STAGE] start $(date -u +%H:%M:%S) silent limit ${SILENT_S}s drt gate '${DRT_GATE:-none}'"
"$@" >> "$LOG" 2>&1 &
PID=$!
reason=""
stop() {  # kill the flow and any container it started
  reason=$1
  pkill -TERM -P $PID 2>/dev/null; kill -TERM $PID 2>/dev/null
  for c in $(docker ps -q 2>/dev/null); do docker kill "$c" >/dev/null 2>&1; done
  sleep 5; kill -KILL $PID 2>/dev/null
}
while kill -0 $PID 2>/dev/null; do
  sleep 30
  newest=$(find "$RUNDIR" "$LOG" -type f -printf '%T@\n' 2>/dev/null | sort -n | tail -1)
  age=$(python3 -c "import time;print(int(time.time()-float('${newest:-0}')))")
  if [ "$age" -gt "$SILENT_S" ]; then
    echo "[stage $STAGE] WATCHDOG: no change under $RUNDIR for ${age}s (> ${SILENT_S}s) -- killing"
    stop watchdog; break
  fi
  if [ -n "${DRT_GATE:-}" ]; then
    # current per-pass counts: the router's own per-pass reports (DRT_SAVE_DRC_REPORT_ITERS=1), not the buffered log
    verdict=$(python3 - "$HERE/drt_counts.py" "$RUNDIR" "$DRT_GATE" <<'PYG'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("drt_counts", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
v = m.counts(sys.argv[2])
for kv in sys.argv[3].split(","):
    k, lim = (int(x) for x in kv.split(":"))
    if len(v) > k and v[k] > lim:
        print(f"pass {k}: {v[k]} violations > {lim} (passes so far {v})"); break
PYG
)
    if [ -n "$verdict" ]; then echo "[stage $STAGE] DRT GATE: $verdict -- stopping"; stop drt_gate; break; fi
  fi
done
wait $PID; rc=$?
tail -n 30 "$LOG"
case "$reason" in
  watchdog) echo "[stage $STAGE] END: WATCHDOG"; exit 124;;
  drt_gate) echo "[stage $STAGE] END: DRT GATE"; exit 3;;
esac
echo "[stage $STAGE] END rc=$rc $(date -u +%H:%M:%S)"
exit $rc
