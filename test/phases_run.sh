#!/usr/bin/env bash
# THE CLOCKED PHASE MEASUREMENT -- clean and mutant, both arms, one JSON (F4).
#
# ⛔⛔ TWO ARMS, AND THE MUTANT ONE IS WHY THIS IS A SCRIPT RATHER THAN A LINE.
# `gate_um10204.py` requires the clean build to MEET the UM10204 minima and the
# `M_CK_RISE_ELIGIBLE` build to MISS them. Without the second arm the gate would
# be a check nobody has seen fail -- and this project has already shipped a
# watchdog whose failure path had never once executed.
#
# ⚠ IT COSTS TWO VERILATOR BUILDS, declared rather than hidden: ~40s. The gate
# is RED without the measurement rather than skipping, the same rule the
# coverage gate follows.
#
# Usage:  bash test/phases_run.sh [outdir]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="${1:-$ROOT/probe_phases}"
PY="${PE_PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3
. "$ROOT/ci/tools.sh"     # ruling V: $VL from PE_VERILATOR, made absolute
command -v "$VL" >/dev/null 2>&1 || { echo "  *** no verilator at $VL"; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"
JSON="$OUT/phases.json"
IMG=test/ckod_image.hex
CTRL=test/ckfive_image.hex

# the images are GENERATED here, so the measurement cannot run against a stale
# artefact left on disk by an older encoder.
"$PY" test/make_smoke_image.py --ckod   > "$OUT/img.log" 2>&1 || exit 1
"$PY" test/make_smoke_image.py --ckfive >> "$OUT/img.log" 2>&1 || exit 1
NB=$(tr -s ' \n' '\n' < "$IMG"  | grep -cv '^$')
NC=$(tr -s ' \n' '\n' < "$CTRL" | grep -cv '^$')

SRCS="test/tb_trace.v test/fram_i2c.v test/fram_spi.v src/pe_engine.v src/pe_store.v src/project.v"
FLAGS="--cc --exe --main --timing --public-flat-rw -Wno-fatal"

build_arm() {   # $1=armname  $2=extra verilator defines
  local arm="$1"
  local extra="$2"
  local bdir="$OUT/build_$arm"
  # shellcheck disable=SC2086
  "$VL" $FLAGS $extra +incdir+test +incdir+. -Mdir "$bdir" \
        -o trace.sim --top-module tb_trace $SRCS > "$OUT/build_$arm.log" 2>&1
  [ -f "$bdir/Vtb_trace.mk" ] || { echo "  *** $arm: generate failed"
      grep '^%Error' "$OUT/build_$arm.log" | head -4; return 1; }
  make -C "$bdir" -f Vtb_trace.mk -j 4 >> "$OUT/build_$arm.log" 2>&1
  [ -x "$bdir/trace.sim" ] || { echo "  *** $arm: build failed"
      grep -E '^%Error' "$OUT/build_$arm.log" | head -4; return 1; }
  return 0
}

# ⛔⛔ EACH BUILD'S `SDA_HOLD_NS` IS RECORDED HERE AND TRAVELS WITH ITS DATA.
# It is a BUILD parameter, so three arms of this run sit at three different
# boundaries -- and `gate_um10204` was printing a literal for one of them. A
# run condition that exists only in the launching script cannot be checked
# against the measurement it produced. `run_arm` reads it out of this map by
# ARM NAME, so an arm added without an entry records UNKNOWN rather than
# inheriting the default.
arm_hold_ns() {
  case "$1" in
    hold0)   echo 0 ;;
    holdbig) echo 500 ;;
    *)       echo 300 ;;      # the RTL's own default; clean/mutant builds
  esac
}

run_arm() {     # $1=armname $2=image $3=nbytes $4=ncyc $5=label $6=sclhold
  local arm="$1"
  local img="$2"
  local nb="$3"
  local ncyc="$4"
  local label="$5"
  local hold="${6:-0}"
  local hns
  hns="$(arm_hold_ns "$arm")"
  ( cd "$OUT/build_$arm" && sim_exec "$ROOT/$img" ./trace.sim \
      +IMG="$ROOT/$img" +NBYTES="$nb" +PEER=none +NCYC="$ncyc" \
      +SCLHOLD="$hold" +OUT="$OUT/trace_$label.txt" \
      --x-initial unique +verilator+rand+reset+2 ) \
      > "$OUT/run_$label.log" 2>&1
  # ⛔⛔ SAY **WHY** THERE IS NO TRACE. This line used to print `no trace` and
  # stop, and that is all five failing CI runs ever said: the bench had
  # truncated a 99-byte `+OUT`, `$fopen` returned 0, and the simulation exited
  # 0 with a clean `$finish`. The reason was sitting in the run log the whole
  # time and nothing printed it. An error message is not a fix, but a failure
  # with no message is not even a report.
  if [ ! -s "$OUT/trace_$label.txt" ]; then
    echo "  *** $label: no trace at $OUT/trace_$label.txt"
    echo "      (+OUT was $(printf '%s' "$OUT/trace_$label.txt" | wc -c) bytes;"
    echo "       tb_trace's filename buffer is 256)"
    sed -n '1,12p' "$OUT/run_$label.log" 2>/dev/null | sed 's/^/      | /'
    return 1
  fi
  # ⛔⛔ S1g (10-22): A TRACE THAT EXISTS IS NOT A RUN THAT FINISHED. The two
  # CE1 half arms ran an image missing from v3_table.vh, V3-ID stopped the
  # bench FATAL at 34 us of 60,000 cycles, the partial trace was non-empty, and
  # `gate_um10204` passed on zero lanes from 10-13 to 10-22. So every arm must
  # now prove it COMPLETED: no fatal stop, the bench's own end-of-loop line
  # with the planned cycle count, at least one retired action, and (after the
  # measurement) at least one clock period.
  # (the FATAL + planned-cycles check is ci/tools.sh's trace_completed, shared
  # with refill_run / a2_run / store_run; R3 made the cycle line honest)
  trace_completed "$OUT/run_$label.log" "$ncyc" "$label" || return 1
  local nret
  nret=$(grep -o '[0-9]* action(s) retired' "$OUT/run_$label.log" | head -1 \
         | cut -d' ' -f1)
  if [ -z "$nret" ] || [ "$nret" -eq 0 ]; then
    echo "  *** $label: 0 actions retired -- the program never ran"
    return 1
  fi
  "$PY" test/measure_phases.py --trace "$OUT/trace_$label.txt" \
        --image "$img" --arm "$label" --json "$JSON" \
        --hold-ns "$hns" || return 1
  if ! "$PY" -c "import json,sys; a=json.load(open(sys.argv[1]))[sys.argv[2]]; \
sys.exit(0 if sum(l['periods'] for l in a['lanes']) > 0 else 1)" \
        "$JSON" "$label"; then
    echo "  *** $label: 0 clock periods measured on every lane"
    return 1
  fi
  return 0
}

echo "=============================================================================="
echo "  CLOCKED PHASE MEASUREMENT (F4)"
echo "=============================================================================="
tool_banner verilator
echo "  image     : $IMG ($NB bytes)   control: $CTRL ($NC bytes)"
echo

rc=0
echo "  --- building ---"
build_arm clean  ""                          || rc=1
build_arm mutant "-DM_CK_RISE_ELIGIBLE"      || rc=1
# ⛔⛔ THE TWO t_HD;DAT MUST-FIRE BUILDS (H3). `SDA_HOLD` is a PARAMETER and not
# an `ifdef`, so each is an ordinary build with one number changed:
#   hold0   -- restores the MEASURED defect (SDA moves in the same cycle SCL
#              falls), which must fail the >= 15 cycle requirement at every d.
#   holdbig -- a hold so long that `t_HD;DAT + t_r` runs past `t_VD;DAT`, which
#              must fail at Fm+ where that budget is tightest. ⭐ A requirement
#              with a floor and no ceiling is half a requirement: without this
#              arm the gate would accept any hold at all above 15.
#
# ⛔⛔ `holdbig` WAS 800 ns AND RULING D1 MADE THAT ARM VACUOUS. 800 ns is 40
# cycles, and `ckod`'s lowest delay is 33 -- so under D1 the lane is REFUSED
# (`d <= SDA_HOLD`), `config_err` halts the engine, and the program that was
# demonstrating the ceiling violation produces no traffic at all. MEASURED:
# the must-fire went from firing to "0 lane(s) moved SDA while SCL high, 0
# over the Fm+ budget" -- a must-fire that stopped being able to fire because
# the chip got stricter, which is the most dangerous direction for one to fail.
# ⇒ 500 ns = 25 cycles: still FAR over the Fm+ `t_VD;DAT - t_r` budget of 17,
#   so the ceiling is genuinely violated, but BELOW `ckod`'s 33 so the program
#   is legal, runs, and can be measured violating it.
# ⚠ THE TWO CONSTRAINTS ARE NAMED BECAUSE THEY SQUEEZE: the hold must sit
#   strictly between the Fm+ budget (17) and the image's smallest delay (33).
#   Raise `CKOD_DELAYS[0]` or tighten the budget and this arm needs rechoosing
#   -- `gate_um10204` reads the arm's own `sda_hold` out of the JSON rather
#   than a literal, so it reports the boundary it actually measured.
# ⭐ RULING CE1: HALF_HIGH measured on the same instrument, and its must-fire
# build (`M_HALF_IGNORED`: the selector read as 0, so the HIGH phase is d).
build_arm halfign "-DM_HALF_IGNORED"                 || rc=1
build_arm hold0   "-GSDA_HOLD_NS=0"                 || rc=1
build_arm holdbig "-GSDA_HOLD_NS=500"                || rc=1
[ $rc -eq 0 ] || { echo "  *** a build failed; no measurement"; exit 1; }
echo "    clean + mutant built"
echo
echo "  --- measuring ---"
# ⭐ THE CONTROL ARM IS PUSH-PULL AND RUNS ON THE CLEAN BUILD: it never parks,
# so its high phase is the programmed delay by a DIFFERENT route. If it ever
# disagreed with the open-drain arm after the fix, the bench would be the
# suspect rather than the design.
run_arm clean  "$IMG"  "$NB" 40000 clean          || rc=1
run_arm clean  "$CTRL" "$NC" 40000 control        || rc=1
# ⛔ STRETCH ARMS: F1 is stretch-safe at ANY stretch, so t_HIGH must be
# unchanged by a peer holding the clock down. `+SCLHOLD` holds the bench's SCL
# pin low for n cycles from cycle 100.
run_arm clean  "$IMG"  "$NB" 40000 stretch_mid  200   || rc=1
run_arm clean  "$IMG"  "$NB" 40000 stretch_long 4000  || rc=1
run_arm mutant "$IMG"  "$NB" 40000 mutant         || rc=1
# ⭐ RULING CE1: the F1 instrument with every lane HALF_HIGH (a probe image,
# generated here), on the clean build and on the selector-ignored mutant
"$PY" test/make_smoke_image.py --ckhalf probe_ckhalf >> "$OUT/img.log" 2>&1 || rc=1
HALF=test/probe_ckhalf.hex
NH=$(tr -s ' \n' '\n' < "$HALF" | grep -cv '^$')
run_arm clean   "$HALF" "$NH" 60000 half          || rc=1
run_arm halfign "$HALF" "$NH" 60000 half_mutant   || rc=1
run_arm hold0   "$IMG" "$NB" 40000 hold0         || rc=1
run_arm holdbig "$IMG" "$NB" 40000 holdbig       || rc=1
# ⛔⛔ THE CERTIFIED TWO-ACTION FRAME, MEASURED ON THE SAME INSTRUMENT (H4).
# `build_i2cframe` drives SCL with explicit OP_LEVEL actions and its SHIFTs
# carry lvl=0, so it is NOT the clocked scheme -- but its own docstring says it
# "puts the data bit on SDA and takes SCL LOW in one dispatch", which is the
# same shape as the clocked defect. Whether the certified frame violates
# t_HD;DAT is therefore a question to MEASURE, not to assume either way, and
# sigrok's decode certification says nothing about it.
# ⛔ THE GENERATOR'S EXIT IS CHECKED (10-22 sweep): the image is TRACKED, so
# `-f` below is always true and a failed regeneration measured the committed
# file in silence.
if ! "$PY" test/make_smoke_image.py --i2cframe 62 >> "$OUT/img.log" 2>&1; then
  echo "  *** make_smoke_image --i2cframe 62 failed; H4 NOT MEASURED"
  rc=1
fi
CERT=test/i2cframe_image.hex
if [ -f "$CERT" ]; then
  NCERT=$(tr -s ' 
' '
' < "$CERT" | grep -cv '^$')
  run_arm clean "$CERT" "$NCERT" 40000 certified || rc=1
else
  echo "  *** the certified frame image is absent; H4 NOT MEASURED"
  rc=1
fi
# ⛔⛔ RULING K4: corpus_i2c, ON THE SAME INSTRUMENT. Every arm above runs a
# SHIFT-only image (`ckod`) or the unclocked frame, so the clocked SHIFTIN's
# release into the ACK slot -- t_HD;DAT = 0 on every one before ruling K --
# was a transition this measurement could not contain. `gate_um10204` now
# holds this arm to the same hold floor as the others.
run_arm clean "test/corpus_i2c.hex" 256 40000 corpus_i2c || rc=1

echo
if [ $rc -eq 0 ]; then
  echo "  ⇒ measurement written to $JSON"
  echo "    PE_PHASES_JSON=$JSON"
else
  echo "  *** the measurement did not complete"
fi
exit $rc
