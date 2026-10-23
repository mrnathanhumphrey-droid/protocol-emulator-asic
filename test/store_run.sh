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
#   short51      RULING M5: the same image loaded as its 51 program bytes only.
#                The chip must REFUSE it (CONFIG_ERR at run entry, 0
#                writebacks); full loads must not be refused.
#   mut_short51  the same 51-byte load on `-DM_NO_STORE_FULL`: it must RUN,
#                or the guard is not what refused it.
#
# ⚠ Two Verilator builds (clean + M_NO_STORE_FULL), ~80s, declared.
# Usage:  bash test/store_run.sh [outdir]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="${1:-$ROOT/probe_store}"
PY="${PE_PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3
. "$ROOT/ci/tools.sh"     # ruling V: $VL from PE_VERILATOR, made absolute
command -v "$VL" >/dev/null 2>&1 || { echo "  *** no verilator at $VL"; exit 1; }

echo "=============================================================================="
echo "  RULING M3 -- NO LANE FETCHES PAST ITS PROGRAM (sentinel = store filler)"
echo "=============================================================================="
tool_banner verilator
echo

rm -rf "$OUT"; mkdir -p "$OUT"
"$PY" test/store_probe.py || exit 1
echo

SRCS="test/tb_trace.v test/fram_i2c.v test/fram_spi.v src/pe_engine.v src/pe_store.v src/project.v"
FLAGS="--cc --exe --main --timing --public-flat-rw -Wno-fatal"
build_arm() {   # $1=armname  $2=extra verilator defines
  local bdir="$OUT/build_$1"
  # shellcheck disable=SC2086
  "$VL" $FLAGS $2 +incdir+test +incdir+. -Mdir "$bdir" \
        -o store.sim --top-module tb_trace $SRCS > "$OUT/build_$1.log" 2>&1
  [ -f "$bdir/Vtb_trace.mk" ] || { echo "  *** $1: generate failed"
      grep '^%Error' "$OUT/build_$1.log" | head -4; return 1; }
  make -C "$bdir" -f Vtb_trace.mk -j 4 >> "$OUT/build_$1.log" 2>&1
  [ -x "$bdir/store.sim" ] || { echo "  *** $1: build failed"
      grep -E '^%Error' "$OUT/build_$1.log" | head -4; return 1; }
}
# ⛔ M5's MUST-FIRE NEEDS THE MUTANT BUILD: a 51-byte load refused by the clean
# build proves nothing unless the same load RUNS once the guard is removed.
build_arm clean ""                 || exit 1
build_arm nofull "-DM_NO_STORE_FULL" || exit 1

rc=0
JSON="$OUT/store.json"
want="$(cat "$OUT/falloff_addr.txt")"
rows=""
# arm|build|image|nbytes -- `short51` loads only corpus_i2c's 51 program bytes
RUNS="pad_ckod_image|clean|pad_ckod_image|256
pad_corpus_all5|clean|pad_corpus_all5|256
pad_corpus_i2c|clean|pad_corpus_i2c|256
pad_smoke_image|clean|pad_smoke_image|256
falloff|clean|falloff|256
short51|clean|pad_corpus_i2c|51
mut_short51|nofull|pad_corpus_i2c|51"
while IFS='|' read -r base build imgb nb; do
  img="$OUT/$imgb.hex"
  ( cd "$OUT/build_$build" && sim_exec "$img" ./store.sim +IMG="$img" +NBYTES="$nb" +PEER=none \
        +NCYC=60000 +SCLHOLD=0 +OUT="$OUT/trace_$base.txt" \
        --x-initial unique +verilator+rand+reset+2 ) > "$OUT/run_$base.log" 2>&1
  if ! trace_completed "$OUT/run_$base.log" 60000 "$base"; then rc=1; continue; fi
  verdict="$(grep 'clocked_conform\[M\]' "$OUT/run_$base.log" | tail -1)"
  m5="$(grep 'clocked_conform\[M5\]' "$OUT/run_$base.log" | tail -1)"
  if [ -z "$verdict" ] || [ -z "$m5" ]; then
    echo "  *** $base: Layer M never spoke -- no verdict"; rc=1; continue
  fi
  printf '  %-26s %s\n' "$base" "${verdict#  }"
  printf '  %-26s %s\n' "" "${m5#  }"
  # the verdict line, as numbers: "F of N ... fetched" or "ok -- N ..., none"
  caps="$(printf '%s' "$verdict" | sed -n 's/.* of \([0-9]*\) prefetch.*/\1/p; s/.*ok -- \([0-9]*\) prefetch.*/\1/p')"
  fills="$(printf '%s' "$verdict" | sed -n 's/.*\[M\]: \([0-9]*\) of .*/\1/p')"
  [ -n "$fills" ] || fills=0
  sf="$(printf '%s' "$m5" | sed -n 's/.*store_full=\([01]\).*/\1/p')"
  ce="$(printf '%s' "$m5" | sed -n 's/.*config_err=\([01]\).*/\1/p')"
  wb="$(printf '%s' "$m5" | sed -n 's/.*writebacks=\([0-9]*\).*/\1/p')"
  named=0
  grep -q "lane 0 fetched the STORE FILLER at address $want " "$OUT/run_$base.log" && named=1
  rows="$rows${rows:+,}
  \"$base\": {\"build\": \"$build\", \"nbytes\": $nb, \"captures\": ${caps:-0}, \"filler_fetches\": $fills, \"lane0_named_at_first_filler\": $named, \"store_full\": ${sf:-9}, \"config_err\": ${ce:-9}, \"writebacks\": ${wb:-0}}"
  case "$base" in
    falloff)
      if [ "$named" = "1" ]; then
        echo "  ${base}: must-fire ok -- lane 0 named at address $want"
        grep 'FAIL clocked_conform\[M\]: lane' "$OUT/run_$base.log" | head -2 | sed 's/^/      | /'
      else
        echo "  *** $base: MUST-FIRE MISSED -- lane 0 at $want was not named"; rc=1
      fi ;;
    short51)
      if [ "$ce" = "1" ] && [ "$sf" = "0" ] && [ "$wb" = "0" ]; then
        echo "  ${base}: M5 ok -- a 51-byte load is REFUSED (CONFIG_ERR, 0 writebacks)"
      else
        echo "  *** $base: a 51-byte load was NOT refused"; rc=1
      fi ;;
    mut_short51)
      # ⚠ RUNNING is the criterion, not config_err: the mutant removes only the
      # engine gate, so the release still reports the short load.
      if [ "${wb:-0}" -gt 0 ]; then
        echo "  ${base}: M5 must-fire ok -- without the guard the same load RUNS ($wb writebacks)"
      else
        echo "  *** $base: the mutant did not run the short load -- the guard is not what refuses"; rc=1
      fi ;;
    *)
      case "$verdict" in
        *"none fetched"*) ;;
        *) echo "  *** $base: a shipped image fetched the filler"; rc=1 ;;
      esac
      if [ "$ce" != "0" ] || [ "$sf" != "1" ]; then
        echo "  *** $base: a FULL load was refused or not marked full"; rc=1
      fi ;;
  esac
done <<RUNSEOF
$RUNS
RUNSEOF
printf '{"first_filler_addr": %s, "runs": {%s\n}}\n' "$want" "$rows" > "$JSON"
echo
echo "  ⇒ measurement written to $JSON"
echo "    PE_STORE_JSON=$JSON"
[ $rc -eq 0 ] && echo "  M3/M5 sentinel run: PASSED" || echo "  M3/M5 sentinel run: FAILED"
exit $rc
