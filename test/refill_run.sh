#!/usr/bin/env bash
# PORT DEMAND PER RETIRED CLOCKED ACTION -- clean and the mutant, one JSON (R).
#
# ⛔⛔ WHY THIS IS A SCRIPT RATHER THAN A SWEEP ARM. `M_CK_HOLD_INVAL` is a
# `define`, and `test/benchset.py`'s arms carry plusargs and `-G` PARAMETERS --
# there is no define channel, and adding one to the coverage sweep would rebuild
# every bench for a mutation only one layer reads. The clocked measurement
# already has this shape (`test/phases_run.sh` + `gate_um10204`), so R follows
# it: one script that builds both arms, one gate that adjudicates the JSON.
#
# ⛔⛔ AND THE MUTANT ARM IS THE POINT, NOT A BONUS. `M_CK_HOLD_INVAL` survived
# EVERY gate in this repo for an entire arc. Layer A1 cannot see it: the PC does
# not advance during a hold, so the prefetch re-reads the same address and
# restores an IDENTICAL word, leaving every delay the park reads correct. Layer
# B cannot see it: a refill changes no dispatch count. What it breaks is
# Amendment A1's PORT PREMISE -- a refill per DISPATCH instead of per ACTION --
# which is what `D* = N_LANES * L_REFILL` and Theorem 3's port-feasible cells
# are computed from. A clean run here is only evidence if the mutant arm is RED.
#
# ⚠ ~80s for two Verilator builds, declared. The gate is RED without the
# measurement rather than skipping -- the same rule the coverage and phase
# gates follow.
#
# Usage:  bash test/refill_run.sh [outdir]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="${1:-$ROOT/probe_refill}"
PY="${PE_PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3
VL="${PE_VERILATOR:-verilator}"
command -v "$VL" >/dev/null 2>&1 || { echo "  *** no verilator at $VL"; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"
JSON="$OUT/refill.json"

# the images are GENERATED here, so the measurement cannot run against a stale
# artefact left on disk by an older encoder.
"$PY" test/make_smoke_image.py --ckod > "$OUT/img.log" 2>&1 || exit 1
"$PY" test/corpus.py >> "$OUT/img.log" 2>&1 || exit 1

SRCS="test/tb_trace.v test/fram_i2c.v test/fram_spi.v src/pe_engine.v src/pe_store.v src/project.v"
FLAGS="--cc --exe --main --timing --public-flat-rw -Wno-fatal"

build_arm() {   # $1=armname  $2=extra verilator defines
  local arm="$1" extra="$2" bdir="$OUT/build_$1"
  # shellcheck disable=SC2086
  "$VL" $FLAGS $extra +incdir+test +incdir+. -Mdir "$bdir" \
        -o refill.sim --top-module tb_trace $SRCS > "$OUT/build_$arm.log" 2>&1
  [ -f "$bdir/Vtb_trace.mk" ] || { echo "  *** $arm: generate failed"
      grep '^%Error' "$OUT/build_$arm.log" | head -4; return 1; }
  make -C "$bdir" -f Vtb_trace.mk -j 4 >> "$OUT/build_$arm.log" 2>&1
  [ -x "$bdir/refill.sim" ] || { echo "  *** $arm: build failed"
      grep -E '^%Error' "$OUT/build_$arm.log" | head -4; return 1; }
  return 0
}

run_arm() {     # $1=armname $2=image-path $3=label
  local arm="$1" img="$2" label="$3" nb
  nb=$(tr -s ' \n' '\n' < "$img" | grep -cv '^$')
  ( cd "$OUT/build_$arm" && ./refill.sim \
      +IMG="$ROOT/$img" +NBYTES="$nb" +PEER=none +NCYC=60000 \
      +SCLHOLD=0 +OUT="$OUT/trace_$label.txt" \
      --x-initial unique +verilator+rand+reset+2 ) \
      > "$OUT/run_$label.log" 2>&1
  # ⛔ NO `+RBOUND` ON PURPOSE: the arms must run at the ENFORCED DEFAULT, or
  # this measurement would describe a bound the shipped benches do not use.
  if ! grep -q "clocked_conform\[R\]" "$OUT/run_$label.log"; then
    echo "  *** $label: layer R never spoke -- the run produced no verdict"
    sed -n '1,12p' "$OUT/run_$label.log" | sed 's/^/      | /'
    return 1
  fi
  return 0
}

echo "=============================================================================="
echo "  PORT DEMAND PER RETIRED CLOCKED ACTION (ruling R)"
echo "=============================================================================="
echo "  verilator : $("$VL" --version 2>&1 | head -1)"
echo

rc=0
echo "  --- building ---"
build_arm clean  ""                      || rc=1
build_arm inval  "-DM_CK_HOLD_INVAL"     || rc=1
# ⛔⛔ R4's MUST-FIRE IS A **DIFFERENT** MUTANT, and that is the point of the
# ruling. `M_CK_HOLD_INVAL` raises the refill RATE while still owing one refill
# per dispatch, so it fails Layer R and PASSES R4a. `M_PFETCH_BOTH_INVAL` keeps
# the rate and makes one dispatch leave TWO slots to refill, so it fails R4a and
# PASSES Layer R. Two layers, two mutants, neither redundant -- which is why R4
# was ordered separately once R turned out to check a rate rather than the
# premise Theorem 3 reasons from.
build_arm both   "-DM_PFETCH_BOTH_INVAL" || rc=1
[ $rc -eq 0 ] || { echo "  *** a build failed; no measurement"; exit 1; }
echo "    clean + M_CK_HOLD_INVAL + M_PFETCH_BOTH_INVAL built"
echo
echo "  --- measuring ---"
for arm in clean inval both; do
  for img in test/ckod_image.hex test/corpus_i2c.hex test/corpus_all5.hex; do
    base="$(basename "$img" .hex)"
    run_arm "$arm" "$img" "${arm}_${base}" || rc=1
  done
done
[ $rc -eq 0 ] || { echo "  *** an arm produced no verdict"; exit 1; }

"$PY" test/refill_collect.py --dir "$OUT" --json "$JSON" || exit 1
echo
echo "  ⇒ measurement written to $JSON"
echo "    PE_REFILL_JSON=$JSON"
