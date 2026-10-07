#!/usr/bin/env bash
# RULING M3 -- CAN A LANE'S PC REACH A BYTE PAST ITS PROGRAM? The sentinel run.
#
# ⛔⛔ THE STORE HAS NO RESET. A byte no image wrote is whatever powered up, and
# a lane that fetches it executes it on real pins. The RTL answer (SPEC §20) is
# that the PC moves in exactly three ways -- +ACT_BYTES on a retiring non-REARM,
# to `l_base` on a looping REARM, not at all on a chaining REARM -- and the
# prefetch reads only `l_pc`, `l_base` or `l_fpc` (= the last fetch + 3). So a
# lane leaves its program only if the program has no terminating REARM, or its
# header base lies outside it. THIS RUN IS THE EVIDENCE for that answer:
#
#   pad_*.hex    shipped images written whole with `pe_isa.STORE_FILLER`;
#                Layer M must report every capture clean.
#   falloff.hex  THE MUST-FIRE: a lane with no terminating REARM. Layer M must
#                name lane 0 at the first filler address -- the fall-through
#                path, shown, and the filler parking it rather than walking on.
#
# ⚠ One Verilator build, ~40s, declared.
# Usage:  bash test/store_run.sh [outdir]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="${1:-$ROOT/probe_store}"
PY="${PE_PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3
VL="${PE_VERILATOR:-verilator}"
command -v "$VL" >/dev/null 2>&1 || { echo "  *** no verilator at $VL"; exit 1; }

echo "=============================================================================="
echo "  RULING M3 -- NO LANE FETCHES PAST ITS PROGRAM (sentinel = store filler)"
echo "=============================================================================="
echo "  verilator : $VL  $("$VL" --version 2>&1 | head -1)"
echo

rm -rf "$OUT"; mkdir -p "$OUT"
"$PY" test/store_probe.py || exit 1
echo

SRCS="test/tb_trace.v test/fram_i2c.v test/fram_spi.v src/pe_engine.v src/pe_store.v src/project.v"
FLAGS="--cc --exe --main --timing --public-flat-rw -Wno-fatal"
BDIR="$OUT/build"
# shellcheck disable=SC2086
"$VL" $FLAGS +incdir+test +incdir+. -Mdir "$BDIR" \
      -o store.sim --top-module tb_trace $SRCS > "$OUT/build.log" 2>&1
[ -f "$BDIR/Vtb_trace.mk" ] || { echo "  *** generate failed"
    grep '^%Error' "$OUT/build.log" | head -4; exit 1; }
make -C "$BDIR" -f Vtb_trace.mk -j 4 >> "$OUT/build.log" 2>&1
[ -x "$BDIR/store.sim" ] || { echo "  *** build failed"
    grep -E '^%Error' "$OUT/build.log" | head -4; exit 1; }

rc=0
JSON="$OUT/store.json"
want="$(cat "$OUT/falloff_addr.txt")"
rows=""
for img in "$OUT"/pad_*.hex "$OUT"/falloff.hex; do
  base="$(basename "$img" .hex)"
  ( cd "$BDIR" && ./store.sim +IMG="$img" +NBYTES=256 +PEER=none \
        +NCYC=60000 +SCLHOLD=0 +OUT="$OUT/trace_$base.txt" \
        --x-initial unique +verilator+rand+reset+2 ) > "$OUT/run_$base.log" 2>&1
  verdict="$(grep 'clocked_conform\[M\]' "$OUT/run_$base.log" | tail -1)"
  if [ -z "$verdict" ]; then
    echo "  *** $base: Layer M never spoke -- no verdict"; rc=1; continue
  fi
  printf '  %-26s %s\n' "$base" "${verdict#  }"
  # the verdict line, as numbers: "F of N ... fetched" or "ok -- N ..., none"
  caps="$(printf '%s' "$verdict" | sed -n 's/.* of \([0-9]*\) prefetch.*/\1/p; s/.*ok -- \([0-9]*\) prefetch.*/\1/p')"
  fills="$(printf '%s' "$verdict" | sed -n 's/.*\[M\]: \([0-9]*\) of .*/\1/p')"
  [ -n "$fills" ] || fills=0
  named=0
  grep -q "lane 0 fetched the STORE FILLER at address $want " "$OUT/run_$base.log" && named=1
  rows="$rows${rows:+,}
  \"$base\": {\"captures\": ${caps:-0}, \"filler_fetches\": $fills, \"lane0_named_at_first_filler\": $named}"
  case "$base" in
    falloff)
      if grep -q "lane 0 fetched the STORE FILLER at address $want " "$OUT/run_$base.log"; then
        echo "  ${base}: must-fire ok -- lane 0 named at address $want"
        grep 'FAIL clocked_conform\[M\]: lane' "$OUT/run_$base.log" | head -2 | sed 's/^/      | /'
      else
        echo "  *** $base: MUST-FIRE MISSED -- lane 0 at $want was not named"; rc=1
      fi ;;
    *)
      case "$verdict" in
        *"none fetched"*) ;;
        *) echo "  *** $base: a shipped image fetched the filler"; rc=1 ;;
      esac ;;
  esac
done
printf '{"first_filler_addr": %s, "runs": {%s\n}}\n' "$want" "$rows" > "$JSON"
echo
echo "  ⇒ measurement written to $JSON"
echo "    PE_STORE_JSON=$JSON"
[ $rc -eq 0 ] && echo "  M3 sentinel run: PASSED" || echo "  M3 sentinel run: FAILED"
exit $rc
