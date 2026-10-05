#!/usr/bin/env bash
# THE COVERAGE SWEEP -- Verilator line/branch/toggle over every bench, merged.
#
# ⛔⛔ WHY, FROM WILSON'S RULING. "The bigger move code is pointing at: a
# coverage sweep, not more one-at-a-time finds." The I2C peer's address-match
# branch had NEVER FIRED and nothing said so -- a zero in a coverage report
# would have. ⇒ Every uncovered branch, FSM state, opcode arm and peer branch
# gets either a test that reaches it or a WRITTEN reason it is unreachable,
# checked like the reset allowlist. This script produces the measurement;
# `test/gate_coverage.py` adjudicates it against the waivers.
#
# ⚠ WHAT VERILATOR ACTUALLY GIVES, stated because the ruling names three
# metrics and the tool has two switches. `--coverage` turns on LINE and TOGGLE
# (and SVL user) coverage; there is no `--coverage-branch` in Verilator 5.032.
# Line points are emitted PER BASIC BLOCK, so each arm of an `if`/`else`/`case`
# carries its own point -- which is branch coverage in substance, and
# `verilator_coverage --write-info` reports those arms as lcov `BRDA:` records.
# ⛔ So "branch" below means lcov BRDA derived from Verilator's per-block line
# points, NOT a separate Verilator metric. Calling it a third independent
# measurement would overstate what was run.
#
# ⛔⛔ THE RESET MODE IS DECLARED, AND IT IS NOT THE PROJECT'S USUAL ONE. This
# sweep runs `+verilator+rand+reset+0`. At `+1` and `+2` -- the setting this
# project's own convention names -- three benches (`tb_smoke`, `tb_tx`,
# `tb_i2c`) FAIL, and the resolved I2C bus diverges from cycle 119. That is an
# open finding recorded in `docs/SPEC_V4_COVERAGE_SWEEP.md`, not something this
# script may paper over: coverage of a FAILING run measures a path the project
# does not certify, so the sweep measures the run the gates certify and says
# which one that is. ⚠ A consequence, stated: paths reached only from a
# nonzero power-on state are NOT measured here.
#
# Usage:  bash test/coverage_sweep.sh [outdir]
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="${1:-probe_cov}"
# ⛔ NORMALISED TO AN ABSOLUTE PATH, because the binary is invoked by this
# path. The first delegated CI run passed `"$PWD/probe_cov"` and every one of
# the nineteen arms died with `timeout: failed to execute process` -- the
# invocation was `./$bin`, and `./` in front of an absolute path is
# `./mnt/d/...`, which does not exist.
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
PY="${PE_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

# ⛔⛔ THE PREVIOUS MEASUREMENT IS DESTROYED BEFORE THIS ONE STARTS, and the
# reason is a green this very script produced: the delegated CI run failed all
# nineteen arms, and `ci/run_gates.sh` then pointed the gate at the
# `merged.dat` left behind by an EARLIER successful run. The gate passed on
# data describing a tree that no longer existed -- the dirty-tree lesson in
# its worst form, because nothing in the output said the data was stale.
rm -f "$OUT/merged.dat" "$OUT/merged.info"

for t in verilator verilator_coverage; do
  command -v "$t" >/dev/null 2>&1 || {
    echo "*** $t is not on PATH -- the sweep cannot run"; exit 2; }
done

echo "=============================================================================="
echo "  COVERAGE SWEEP -- Verilator $(verilator --version 2>&1 | awk '{print $2}')"
echo "=============================================================================="

PLAN="$OUT/plan.json"
mkdir -p "$OUT"
"$PY" test/benchset.py --json > "$PLAN" || {
  echo "*** the bench set is not clean -- fix it before measuring coverage"
  exit 1; }

# ⛔ ONE BINARY PER BUILD KEY, SHARED BY THE ARMS THAT USE IT. Arms differing
# only in plusargs share a binary; arms differing in a BUILD-TIME parameter do
# not, and the plan's `build` field is what distinguishes them. Keying this on
# the top module alone would run the SPL = 1 arm against the SPL = 2 binary.
mapfile -t BUILDS < <("$PY" -c "
import json,sys
p=json.load(open(sys.argv[1]))
seen={}
for r in p:
    g=' '.join('-G%s=%s'%(k,v) for k,v in sorted(r['gparams'].items()))
    seen[r['build']]=' '.join([r['build'],r['top'],g,'--',' '.join(r['srcs'])])
print('\n'.join(seen[k] for k in seen))
" "$PLAN")

FLAGS="--binary --coverage --timing --public-flat-rw -Wno-fatal -j 4"
nbuild=0; nbfail=0
for line in "${BUILDS[@]}"; do
  key="${line%% *}"; rest="${line#* }"
  top="${rest%% *}"; rest="${rest#* }"
  gp="${rest%% -- *}"; srcs="${rest#* -- }"
  # shellcheck disable=SC2086
  verilator $FLAGS +incdir+test +incdir+. -Mdir "$OUT/build_$key" \
      -o "$key.sim" --top-module "$top" $gp $srcs \
      > "$OUT/build_$key.log" 2>&1
  if [ $? -eq 0 ] && [ -x "$OUT/build_$key/$key.sim" ]; then
    nbuild=$((nbuild + 1)); printf '  build %-18s ok %s\n' "$key" "$gp"
  else
    nbfail=$((nbfail + 1)); printf '  build %-18s *** FAILED (see %s)\n' \
        "$key" "$OUT/build_$key.log"
    grep '^%Error' "$OUT/build_$key.log" | head -3 | sed 's/^/      /'
  fi
done

echo
rm -f "$OUT"/cov_*.dat
NARM=$("$PY" -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$PLAN")
npass=0; nfail=0
for i in $(seq 0 $((NARM - 1))); do
  read -r top label key <<<"$("$PY" -c "
import json,sys
r=json.load(open(sys.argv[1]))[int(sys.argv[2])]
print(r['top'], r['label'], r['build'])
" "$PLAN" "$i")"
  bin="$OUT/build_$key/$key.sim"
  [ -x "$bin" ] || { printf '  run   %-11s %-14s *** no binary\n' "$top" "$label"
                     nfail=$((nfail + 1)); continue; }
  mapfile -t ARGS < <("$PY" -c "
import json,sys
print('\n'.join(json.load(open(sys.argv[1]))[int(sys.argv[2])]['args']))
" "$PLAN" "$i")
  log="$OUT/run_${top}_${label}.log"
  dat="$OUT/cov_${top}_${label}.dat"
  timeout 900 "$bin" +verilator+rand+reset+0 \
      "+verilator+coverage+file+$dat" "${ARGS[@]}" > "$log" 2>&1
  rc=$?
  # ⛔ A RUN THAT ABORTED MUST NOT COUNT AS CLEAN. A Verilator abort produces a
  # log with no FAIL line in it, and "FAIL=0" then reads exactly like a pass --
  # which it did in an earlier probe here, where every run aborted on a
  # `$readmem` bound and reported zero failures.
  #
  # ⛔⛔ AND THE LOG IS CUT AT THE FIRST `$finish`, BECAUSE VERILATOR RUNS PAST
  # IT. iverilog stops an `initial` block dead at `$finish`; Verilator exits at
  # the end of the enclosing TIME STEP, so a verdict section that follows with
  # no delay in between executes anyway. `tb_tx +BADCLK=1` printed
  # "PASS (1.6x refusal)", hit `$finish`, and then ran the ordinary
  # queue-ownership verdict -- which of course failed, because the program it
  # was judging had been refused on purpose. ⇒ Everything after the first
  # `$finish` is output iverilog never produces, and judging the run by it
  # reports a pass as eleven failures.
  # ⚠ THE SAME CAVEAT APPLIES TO THE COVERAGE, and is declared in
  # `gate_coverage.py`: bench lines after a `$finish` can be credited here
  # though they never execute under iverilog. That is why the gate's verdict
  # covers `src/` and the peer models, not bench bodies.
  cut="$OUT/cut_${top}_${label}.log"
  awk '/Verilog \$finish/{exit} {print}' "$log" > "$cut"
  # ⚠ CASE-SENSITIVE ON PURPOSE. `-i` matched the word "failure" inside
  # `tb_csat`'s own line "sticky_ovr observed : 0 (recorded, not a failure)"
  # and failed an arm that had passed.
  nf=$(grep -cE '\*\*\* FAIL|FAILURE\(S\)|FAILED|%Error|Aborting' "$cut")
  if [ $rc -eq 0 ] && [ "$nf" -eq 0 ] && [ -s "$dat" ]; then
    npass=$((npass + 1)); printf '  run   %-11s %-14s ok\n' "$top" "$label"
  else
    nfail=$((nfail + 1))
    printf '  run   %-11s %-14s *** rc=%s fail-lines=%s dat=%s\n' \
        "$top" "$label" "$rc" "$nf" "$([ -s "$dat" ] && echo yes || echo EMPTY)"
    grep -E '\*\*\* FAIL|FAILURE\(S\)|FAILED|%Error|Aborting' "$cut" \
        | head -2 | sed 's/^/      /'
  fi
done

echo
echo "  builds  : $nbuild ok, $nbfail failed"
echo "  arms    : $npass ok, $nfail failed  (of $NARM)"

DATS=("$OUT"/cov_*.dat)
if [ ! -e "${DATS[0]}" ]; then
  echo "  *** no coverage data at all -- nothing to merge"
  exit 1
fi
echo
echo "  --- merging $(ls -1 "$OUT"/cov_*.dat | wc -l) coverage files ---"
verilator_coverage --write "$OUT/merged.dat" "$OUT"/cov_*.dat \
    > "$OUT/merge.log" 2>&1 || { echo "  *** merge failed"; tail -3 "$OUT/merge.log"; exit 1; }
verilator_coverage --write-info "$OUT/merged.info" "$OUT/merged.dat" \
    > "$OUT/info.log" 2>&1 || { echo "  *** write-info failed"; tail -3 "$OUT/info.log"; exit 1; }
rm -rf "$OUT/ann"
verilator_coverage --annotate "$OUT/ann" --annotate-all --annotate-points \
    "$OUT/merged.dat" > "$OUT/ann.log" 2>&1
grep -iE 'total coverage' "$OUT/ann.log" | sed 's/^/  /'
echo "  merged  : $OUT/merged.dat  $OUT/merged.info  $OUT/ann/"

# ⛔ THE SWEEP'S OWN EXIT CODE REPORTS THE MEASUREMENT, not the verdict. The
# verdict against the waiver list is `test/gate_coverage.py`'s, so that one
# place decides what an uncovered point means.
[ "$nbfail" -eq 0 ] && [ "$nfail" -eq 0 ] || exit 1
exit 0
