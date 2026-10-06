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
VL="${PE_VERILATOR:-verilator}"
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

run_arm() {     # $1=armname $2=image $3=nbytes $4=ncyc $5=label $6=sclhold
  local arm="$1"
  local img="$2"
  local nb="$3"
  local ncyc="$4"
  local label="$5"
  local hold="${6:-0}"
  ( cd "$OUT/build_$arm" && ./trace.sim \
      +IMG="$ROOT/$img" +NBYTES="$nb" +PEER=none +NCYC="$ncyc" \
      +SCLHOLD="$hold" +OUT="$OUT/trace_$label.txt" \
      --x-initial unique +verilator+rand+reset+2 ) \
      > "$OUT/run_$label.log" 2>&1
  [ -s "$OUT/trace_$label.txt" ] || { echo "  *** $label: no trace"; return 1; }
  "$PY" test/measure_phases.py --trace "$OUT/trace_$label.txt" \
        --image "$img" --arm "$label" --json "$JSON" || return 1
  return 0
}

echo "=============================================================================="
echo "  CLOCKED PHASE MEASUREMENT (F4)"
echo "=============================================================================="
echo "  verilator : $("$VL" --version 2>&1 | head -1)"
echo "  image     : $IMG ($NB bytes)   control: $CTRL ($NC bytes)"
echo

rc=0
echo "  --- building ---"
build_arm clean  ""                          || rc=1
build_arm mutant "-DM_CK_RISE_ELIGIBLE"      || rc=1
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

echo
if [ $rc -eq 0 ]; then
  echo "  ⇒ measurement written to $JSON"
  echo "    PE_PHASES_JSON=$JSON"
else
  echo "  *** the measurement did not complete"
fi
exit $rc
