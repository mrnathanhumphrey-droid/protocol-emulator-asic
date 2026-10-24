#!/usr/bin/env bash
# THE COCOTB COVERAGE ARM (Wilson's ruling 2) -- the one bench the sweep
# excludes, measured.
#
# ⛔⛔ WHY IT EXISTS. `test/benchset.py` excludes `tb.v`: it has no
# self-checking `initial` block, so a Verilator `--binary` run cannot read a
# verdict from it. That exclusion produced TWO FALSE "never fired" GAPS --
# `cfgerr_image.hex`'s open-drain refusal arms had been exercised by
# `test_config_error_refuses_to_run` all along, and I relayed them to Wilson as
# a silicon gap. Twice.
#
# ⛔ IT NEEDS A PINNED TOOLCHAIN, AND THAT IS THE WHOLE REASON THIS WAS BLOCKED:
#     cocotb 2.0.1 requires Verilator >= 5.036  (its own version check)
#     the distro ships Verilator 5.032; the CI runner installs 5.020
#     cocotb 2.0.1 caps at Python 3.13; Ubuntu 26.04 ships 3.14 and has no
#     python3.12 package
# ⇒ A dated OSS CAD Suite release supplies the simulators and an isolated
# uv-managed CPython supplies a supported interpreter. Both are PINNED here:
# a floating "latest" would make a coverage number that moves on its own.
#
# ⚠ THE PINNED SUITE ALSO CARRIES NEW yosys AND iverilog (0.69 and 14.0-devel
# against the 0.52 and 12.0 in use), and those feed PUBLISHED numbers -- the
# yosys netlist drives `gate_reset_audit`'s flop classification and F2's
# structural check, and `cj_measured.txt`'s pinned values are IVERILOG
# measurements. So this script uses the suite's VERILATOR ONLY and leaves the
# other two alone; switching them needs the same treatment `C` is getting for
# the clocked SHIFT -- re-measure first, adopt second.
#
# Usage:  bash test/coverage_cocotb.sh [outdir]
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/probe_cov}"
# ⛔ ABSOLUTE BEFORE THE `cd`. This script runs `make` from `test/`, and a
# relative outdir then resolves against the wrong directory -- the first run
# wrote its log nowhere and the tally guard correctly refused to call that a
# pass. Same class as the sweep invoking `./$bin` on an absolute path.
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

SUITE="${PE_OSS_CAD_SUITE:-/opt/oss-cad-suite-2026-09-30}"
VENV="${PE_COCOTB_VENV:-$ROOT/probe_venv312}"

VL="${PE_VERILATOR:-$SUITE/bin/verilator}"
[ -x "$VL" ] || { echo "*** missing verilator: $VL"
                  echo "    the arm needs Verilator >= 5.036 (cocotb 2.0.1's"
                  echo "    floor). RED, not skipped."; exit 2; }

# ⛔⛔ THE INTERPRETER IS WHICHEVER ONE SUPPORTS cocotb, and it differs by
# environment. CI's `actions/setup-python` pins 3.11 and pip-installs the
# pinned cocotb, so the AMBIENT python is already correct there and a venv
# would be pure overhead. This box needs one, because the distro ships 3.14
# and cocotb 2.0.1 caps at 3.13. So: use the venv IF it exists, otherwise use
# the ambient python -- and in both cases CHECK that cocotb imports and that
# the version is in range, rather than assuming the environment is right.
if [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi
[ -n "${PY:-}" ] || { echo "*** no python found"; exit 2; }
"$PY" - <<'PYEOF' || exit 2
import sys
v = sys.version_info
if v >= (3, 14):
    print("*** python %d.%d is above cocotb 2.0.1's 3.13 cap"
          % (v.major, v.minor))
    raise SystemExit(1)
try:
    import cocotb
except Exception as exc:
    print("*** cocotb does not import: %s" % exc)
    raise SystemExit(1)
print("  interpreter and cocotb both in range")
PYEOF

echo "=============================================================================="
echo "  COCOTB COVERAGE ARM -- the bench the sweep excludes"
echo "=============================================================================="
printf '  %-11s %s\n' python "$("$VENV/bin/python" --version 2>&1)"
printf '  %-11s %s\n' cocotb "$("$VENV/bin/python" -c 'import cocotb;print(cocotb.__version__)' 2>&1)"
printf '  %-11s %s\n' verilator "$("$SUITE/bin/verilator" --version 2>&1 | head -1)"

cd "$ROOT/test" || exit 1
# ⛔ ONLY the suite's verilator is put on PATH ahead of the system tools; its
# yosys and iverilog are deliberately NOT adopted here (see the header).
export PATH="$(dirname "$PY"):$(dirname "$VL"):$PATH"
rm -rf sim_build/vlcov results.xml coverage.dat
make -B SIM=verilator SIM_BUILD=sim_build/vlcov \
     EXTRA_ARGS="--coverage --public-flat-rw --timing -Wno-fatal" \
     > "$OUT/cocotb_cov.log" 2>&1
rc=$?

TALLY="$(grep -oE 'TESTS=[0-9]+ PASS=[0-9]+ FAIL=[0-9]+ SKIP=[0-9]+' \
         "$OUT/cocotb_cov.log" | tail -1)"
echo "  make rc=$rc   $TALLY"
# ⛔ R4 #4 (10-23): make's rc was printed and never tested, and a suite that
# found NO tests ("TESTS=0 PASS=0 FAIL=0 SKIP=0") matched the pass case below.
if [ "$rc" -ne 0 ]; then
  echo "  *** make exited $rc -- not a clean cocotb run"
  exit 1
fi
case "$TALLY" in
  "TESTS=0 "*) echo "  *** the cocotb suite ran ZERO tests -- nothing was covered"
               exit 1 ;;
esac
# ⛔ THE TALLY IS REQUIRED, NOT OPTIONAL. A run that built and then failed to
# start would leave no tally and `rc=0` on some paths -- "no failures" because
# nothing ran is the vacuous pass this project keeps finding.
case "$TALLY" in
  *"FAIL=0 SKIP=0") : ;;
  "") echo "  *** NO TALLY in the log -- the suite did not report, so this run"
      echo "      proves nothing. See $OUT/cocotb_cov.log"
      exit 1 ;;
  *)  echo "  *** the cocotb suite did not pass cleanly"; exit 1 ;;
esac

if [ ! -s coverage.dat ]; then
  echo "  *** no coverage.dat -- the suite ran but emitted no coverage."
  exit 1
fi
# ⛔ NOT `cov_*.dat`: the sweep clears that glob at startup and DELETED this
# arm's data, so the gate then reported "no cocotb coverage" after a run that
# had produced it. Two producers sharing a filename namespace.
mv -f coverage.dat "$OUT/cocotb_coverage.dat"
echo "  coverage : $OUT/cocotb_coverage.dat ($(grep -c . "$OUT/cocotb_coverage.dat") records)"
echo
echo "  ⚠ NOT merged into the adjudicated measurement. The sweep adjudicates at"
echo "    rand-reset+0 over its own 25 arms; folding a differently-driven bench"
echo "    into that set would change what the ratchet is counting. This arm's"
echo "    job is to answer: does cocotb reach a point the sweep calls"
echo "    uncovered -- and test/gate_coverage.py reads it for exactly that."
exit 0
