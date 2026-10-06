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
# `"$VLCOV" --write-info` reports those arms as lcov `BRDA:` records.
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
# ⛔⛔ THE RESET MODE IS A PARAMETER NOW, AND ALL THREE ARE RUN (Wilson's
# ruling (c)). It was pinned at +0 because three benches failed at +1/+2 --
# which turned out to be the HOST FEEDER's own uninitialised state, not the
# design: `hf_en`/`hf_mask`/`hf_q` had no declaration initialisers, so the
# feeder could push before `hf_init` cleared it. With initialisers every bench
# passes at all three modes, so there is no longer any reason to measure only
# one.
RMODES="${PE_RESET_MODES:-0 1 2}"
PY="${PE_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

# ⛔⛔ THE PREVIOUS MEASUREMENT IS DESTROYED BEFORE THIS ONE STARTS, and the
# reason is a green this very script produced: the delegated CI run failed all
# nineteen arms, and `ci/run_gates.sh` then pointed the gate at the
# `merged.dat` left behind by an EARLIER successful run. The gate passed on
# data describing a tree that no longer existed -- the dirty-tree lesson in
# its worst form, because nothing in the output said the data was stale.
rm -f "$OUT/merged.dat" "$OUT/merged.info" coverage.dat

# ⛔⛔ THE VERILATOR IS NAMED, NOT TAKEN FROM PATH, so CI and this box can use
# THE SAME PINNED BINARY without adopting the rest of a suite. `PE_VERILATOR`
# points at the pinned OSS CAD Suite build; its yosys and iverilog are
# deliberately NOT put on PATH, because the netlist-derived gates must describe
# the chip the HARDENING FLOW builds and the published `cj_measured` numbers are
# iverilog 12.0 measurements. Absolute invocation was verified to build (the
# suite's `verilator` is a perl wrapper that finds its own root).
# ⚠ The version is PRINTED below and travels with the measurement, because the
# toggle ceilings are exact point counts and a release can emit a different
# number of them.
VL="${PE_VERILATOR:-verilator}"
VLCOV="${PE_VERILATOR_COVERAGE:-verilator_coverage}"
if [ "$VL" != "verilator" ] && [ ! -x "$VL" ]; then
  echo "*** PE_VERILATOR=$VL is not executable"; exit 2
fi
if [ "$VLCOV" = "verilator_coverage" ] && [ "$VL" != "verilator" ]; then
  VLCOV="$(dirname "$VL")/verilator_coverage"
fi
for t in "$VL" "$VLCOV"; do
  command -v "$t" >/dev/null 2>&1 || [ -x "$t" ] || {
    echo "*** $t is not available -- the sweep cannot run"; exit 2; }
done

echo "=============================================================================="
echo "  COVERAGE SWEEP -- Verilator $("$VL" --version 2>&1 | awk '{print $2}')  rand-reset=+{$RMODES}"
echo "  binary : $VL"
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

# ⛔⛔ GENERATE, PATCH, BUILD -- NOT `--binary`, AND THIS IS A PORTABILITY FIX
# ESTABLISHED FROM VERILATOR'S OWN SOURCE RATHER THAN GUESSED AT. On 5.020 the
# arms ran, PASSED, and produced no coverage file; `src/V3EmitCMain.cpp` at tag
# v5.020 emits `topp->final(); return 0;` with NO coverage write anywhere, and
# `+verilator+coverage+file+` does not exist there either. 5.032 emits
# `contextp->coveragep()->write();`. ⇒ So the generated main is patched when it
# lacks that call, which works on both: `VerilatedCovContext::write()` and
# `VerilatedContext::coveragep()` are present in 5.020's `verilated_cov.h`.
# ⚠ `--binary` is exactly `--main --exe --build --timing`, so this spells those
# out and inserts the patch between generating and building.
FLAGS="--cc --exe --main --timing --coverage --public-flat-rw -Wno-fatal"
nbuild=0; nbfail=0
for line in "${BUILDS[@]}"; do
  key="${line%% *}"; rest="${line#* }"
  top="${rest%% *}"; rest="${rest#* }"
  gp="${rest%% -- *}"; srcs="${rest#* -- }"
  bdir="$OUT/build_$key"
  rm -rf "$bdir"
  # shellcheck disable=SC2086
  "$VL" $FLAGS +incdir+test +incdir+. -Mdir "$bdir" \
      -o "$key.sim" --top-module "$top" $gp $srcs \
      > "$OUT/build_$key.log" 2>&1
  gen_rc=$?
  MAIN="$bdir/V${top}__main.cpp"
  if [ $gen_rc -eq 0 ] && [ -f "$MAIN" ]; then
    if ! grep -q 'coveragep()->write' "$MAIN"; then
      echo "    (patching $(basename "$MAIN"): this Verilator emits no" \
           "coverage write)" >> "$OUT/build_$key.log"
      awk '{ print }
           /topp->final\(\);/ && !done {
             print "    contextp->coveragep()->write();"; done = 1 }' \
        "$MAIN" > "$MAIN.patched" && mv -f "$MAIN.patched" "$MAIN"
      grep -q 'coveragep()->write' "$MAIN" || {
        echo "    *** the patch did not take -- no topp->final() to anchor to" \
          >> "$OUT/build_$key.log"; }
    fi
    make -C "$bdir" -f "V${top}.mk" -j 4 >> "$OUT/build_$key.log" 2>&1
  fi
  if [ -x "$OUT/build_$key/$key.sim" ]; then
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
# ⛔⛔ EVERY ARM AT EVERY RESET MODE (Wilson's ruling (c)). The binaries do
# NOT depend on the mode -- it is a runtime plusarg -- so the build phase runs
# once and only the RUN phase repeats, which is why three modes cost three
# times the simulation and not three times the build.
# ⭐ The merged coverage is then the UNION over the three modes, which is
# strictly more of the design than any single mode reaches.
for RMODE in $RMODES; do
echo "  --- rand-reset +$RMODE ---"
for i in $(seq 0 $((NARM - 1))); do
  read -r top label key xfail <<<"$("$PY" -c "
import json,sys
r=json.load(open(sys.argv[1]))[int(sys.argv[2])]
print(r['top'], r['label'], r['build'], r.get('xfail', 0))
" "$PLAN" "$i")"
  bin="$OUT/build_$key/$key.sim"
  [ -x "$bin" ] || { printf '  run   %-11s %-14s *** no binary\n' "$top" "$label"
                     nfail=$((nfail + 1)); continue; }
  mapfile -t ARGS < <("$PY" -c "
import json,sys
print('\n'.join(json.load(open(sys.argv[1]))[int(sys.argv[2])]['args']))
" "$PLAN" "$i")
  log="$OUT/run_${top}_${label}_m${RMODE}.log"
  dat="$OUT/cov_${top}_${label}_m${RMODE}.dat"
  # ⛔⛔ THE COVERAGE FILE IS MOVED, NOT NAMED ON THE COMMAND LINE, AND THAT
  # IS A PORTABILITY FIX PAID FOR BY A RED CI RUN. `+verilator+coverage+file+`
  # does not exist in Verilator 5.020, which is what the CI runner installs;
  # this box has 5.032, where it works. Every one of the nineteen arms died
  # with `Unknown runtime argument` and SIGABRT while the builds all passed.
  # ⇒ Writing to the default `./coverage.dat` and moving it afterwards works
  # on both. ⚠ It also means the run must happen from the repo root (the
  # images are named by relative path) and that arms must stay SEQUENTIAL --
  # two at once would race for the same default filename.
  rm -f coverage.dat "$OUT/build_$key/coverage.dat"
  timeout 900 "$bin" "+verilator+rand+reset+$RMODE" "${ARGS[@]}" > "$log" 2>&1
  rc=$?
  # ⛔ AND IT IS SEARCHED FOR, NOT ASSUMED TO BE IN THE CWD. Under Verilator
  # 5.020 the arms RAN AND PASSED (rc=0, no failure line) and produced no
  # `coverage.dat` where 5.032 puts one -- so "where the file lands" is itself
  # version-dependent, after "what the file is called" already was.
  for cand in coverage.dat "$OUT/build_$key/coverage.dat" \
              "$OUT/build_$key/logs/coverage.dat"; do
    [ -s "$cand" ] && { mv -f "$cand" "$dat"; break; }
  done
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
  cut="$OUT/cut_${top}_${label}_m${RMODE}.log"
  # ⛔⛔ AND THE SHARED WATCHDOGS' SUMMARIES SURVIVE THE CUT, which the first
  # version of this line did not allow. `test/progress.vh` and
  # `test/clocked_conform.vh` report from `final` blocks, whose output lands
  # AFTER the `$finish` line -- so their verdicts, including the
  # anti-vacuity one ("no action was observed to retire"), were being
  # DISCARDED before the FAIL grep ever saw them. An arm could run a
  # completely vacuous watchdog and report `ok`, which is the exact shape
  # those files exist to prevent.
  # ⚠ THE ORIGINAL PROTECTION IS KEPT: everything else after `$finish` is
  # still dropped, because Verilator runs a bench's own verdict section past
  # it and iverilog does not (`tb_tx +BADCLK=1` printed a PASS, hit
  # `$finish`, then ran a verdict that of course failed). A `final` block is
  # DIFFERENT: it is defined to run at `$finish`, it is instrumentation
  # rather than bench-verdict code, and both simulators honour it.
  awk '/Verilog \$finish/{seen=1} !seen{print}
       seen && (/progress\.vh/ || /clocked_conform/){print}' "$log" > "$cut"
  # ⚠ CASE-SENSITIVE ON PURPOSE. `-i` matched the word "failure" inside
  # `tb_csat`'s own line "sticky_ovr observed : 0 (recorded, not a failure)"
  # and failed an arm that had passed.
  nf=$(grep -cE '\*\*\* FAIL|FAILURE\(S\)|FAILED|%Error|Aborting' "$cut")
  # ⛔⛔ A DECLARED XFAIL ARM MUST COME OUT RED, and that is how the VERDICT
  # PIPELINE itself is priced. This extraction is a checker, and it was
  # silently broken for as long as the watchdogs existed: the grep above
  # wants `*** FAIL` while they printed a bare `FAIL`, and the cut above
  # dropped `final`-block output, which is where they report from. "The
  # sweep catches it" was false twice over.
  # ⇒ `tb_verdict` emits a watchdog-shaped failure from a `final` block and
  #   nothing else. If either half regresses it goes GREEN -- so green is
  #   the failure here, and the message says why rather than just inverting.
  if [ "$xfail" = "1" ]; then
    if [ "$nf" -gt 0 ]; then
      npass=$((npass + 1)); printf '  run   %-11s %-14s ok (xfail: red as required)
' "$top" "$label"
    else
      nfail=$((nfail + 1))
      printf '  run   %-11s %-14s *** XFAIL ARM CAME OUT GREEN -- the arm verdict no longer sees watchdog FAIL lines (log cut, or grep pattern)
' "$top" "$label"
    fi
    continue
  fi
  if [ $rc -eq 0 ] && [ "$nf" -eq 0 ] && [ -s "$dat" ]; then
    npass=$((npass + 1)); printf '  run   %-11s %-14s ok\n' "$top" "$label"
  else
    nfail=$((nfail + 1))
    printf '  run   %-11s %-14s +%s *** rc=%s fail-lines=%s dat=%s\n' \
        "$top" "$label" "$RMODE" "$rc" "$nf" "$([ -s "$dat" ] && echo yes || echo EMPTY)"
    grep -E '\*\*\* FAIL|FAILURE\(S\)|FAILED|%Error|Aborting' "$cut" \
        | head -2 | sed 's/^/      /'
  fi
done   # arms
done   # reset modes

echo
echo "  builds  : $nbuild ok, $nbfail failed"
echo "  arms    : $npass ok, $nfail failed  (of $NARM x $(echo $RMODES | wc -w) modes)"

DATS=("$OUT"/cov_*.dat)
if [ ! -e "${DATS[0]}" ]; then
  echo "  *** no coverage data at all -- nothing to merge"
  # ⛔ SAY WHERE IT LOOKED AND WHAT EXISTS. "No coverage data" with a clean
  # run log is the hardest case to diagnose remotely, and guessing at it
  # across a toolchain this box does not have is how two CI rounds were spent.
  echo "      verilator : $("$VL" --version 2>&1)"
  echo "      any coverage*.dat anywhere under the tree:"
  find . -name 'coverage*.dat' -o -name 'cov_*.dat' 2>/dev/null \
    | head -10 | sed 's/^/        /'
  echo "      (none listed above means the simulator never wrote one --"
  echo "       on this toolchain '--coverage' with '--binary' does not"
  echo "       emit at exit, and the sweep needs a version that does.)"
  exit 1
fi
echo
# ⛔⛔⛔ THE ADJUDICATED MEASUREMENT IS MODE 0 ONLY, AND THIS IS MEASURED, NOT
# a conservative choice. Running all three modes added 160 points (716 -> 876
# of 2727) and EVERY ONE OF THEM IS A TOGGLE POINT: line and branch coverage
# was identical at 37 uncovered under the union and under +0 alone. The reason
# is immediate once seen -- `rand+reset+1/+2` sets every register bit to an
# arbitrary value, so nearly every bit "toggles" without the design doing
# anything. Uncovered toggle went 238 -> 0 in `pe_engine.v`, 74 -> 0 in
# `project.v`, 45 -> 1 in the I2C peer.
# ⇒ Toggle coverage at a randomised power-on measures THE RESET MODE, not the
# stimulus, and crediting it would raise the ratchet to a number no test earns.
# The union is still written, for information, as `merged_allmodes.dat`.
# ⚠ The three-mode run keeps its full value as the ROBUSTNESS gate: every arm
# must PASS at every mode, which is what ruling (c) asked for.
echo "  --- merging coverage ---"
echo "      adjudicated : $(ls -1 "$OUT"/cov_*_m0.dat 2>/dev/null | wc -l) files at rand-reset+0"
echo "      information : $(ls -1 "$OUT"/cov_*.dat | wc -l) files over all modes"
"$VLCOV" --write "$OUT/merged_allmodes.dat" "$OUT"/cov_*.dat \
    > "$OUT/merge_all.log" 2>&1 || echo "  ⚠ the all-mode union did not merge"
"$VLCOV" --write "$OUT/merged.dat" "$OUT"/cov_*_m0.dat \
    > "$OUT/merge.log" 2>&1 || { echo "  *** merge failed"; tail -3 "$OUT/merge.log"; exit 1; }
"$VLCOV" --write-info "$OUT/merged.info" "$OUT/merged.dat" \
    > "$OUT/info.log" 2>&1 || { echo "  *** write-info failed"; tail -3 "$OUT/info.log"; exit 1; }
rm -rf "$OUT/ann"
"$VLCOV" --annotate "$OUT/ann" --annotate-all --annotate-points \
    "$OUT/merged.dat" > "$OUT/ann.log" 2>&1
grep -iE 'total coverage' "$OUT/ann.log" | sed 's/^/  /'
# ⛔ THE TOOL VERSION TRAVELS WITH THE MEASUREMENT. The toggle ceilings in
# `gate_coverage.py` are EXACT COUNTS of emitted points, and how many points a
# file emits is a property of the Verilator release -- this box runs 5.032
# while the CI runner installs 5.020. A ceiling breached by a version change
# and a ceiling breached by a regression look identical without this line.
{
  "$VL" --version
  echo "arms $npass ok / $NARM"
  echo "reset modes +verilator+rand+reset+{$RMODES}"
} > "$OUT/sweep_env.txt"
echo "  tool    : $("$VL" --version 2>&1)"
echo "  merged  : $OUT/merged.dat  $OUT/merged.info  $OUT/ann/"

# ⛔ THE SWEEP'S OWN EXIT CODE REPORTS THE MEASUREMENT, not the verdict. The
# verdict against the waiver list is `test/gate_coverage.py`'s, so that one
# place decides what an uncovered point means.
[ "$nbfail" -eq 0 ] && [ "$nfail" -eq 0 ] || exit 1
exit 0
