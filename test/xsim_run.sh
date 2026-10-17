#!/usr/bin/env bash
# CROSS-SIMULATOR RUN -- the Verilator half of `test/gate_xsim.py` (audit #3).
#
# One bench: build it ONCE with the pinned Verilator, then run every arm listed
# in ARMSFILE (one line each: `<label> <plusargs...>`), writing each arm's
# stdout to OUTDIR/<label>.vl.txt for the driver to compare with iverilog's.
#
# ⛔ THE PINNED VERILATOR, BY NAME (ruling V): `$VL` from `ci/tools.sh`, and
# `tool_banner verilator` so the driver can refuse a run on any other release.
# ⭐ GENTLE BY DESIGN: the C++ build is the heavy part, so it runs at nice 19
# with two build jobs; the arms run one at a time.
#
# Usage: bash test/xsim_run.sh <root> <outdir> <top> <armsfile> "<srcs>" ["<-G flags>"]
set -uo pipefail
ROOT="$1"; OUTDIR="$2"; TOP="$3"; ARMS="$4"; SRCS="$5"; GFLAGS="${6:-}"
cd "$ROOT" || exit 1
mkdir -p "$OUTDIR"
. "$ROOT/ci/tools.sh"
command -v "$VL" >/dev/null 2>&1 || [ -x "$VL" ] \
    || { echo "  *** no Verilator at '$VL' (set PE_VERILATOR)"; exit 1; }
tool_banner verilator
# ⛔ THE BUILD TREE LIVES IN /tmp (Verilator's C++ build across a 9p mount is
# slow); only the arm outputs cross over to OUTDIR.
OBJ="/tmp/pe_xsim_${TOP}_$(printf '%s' "$GFLAGS" | tr -c 'A-Za-z0-9' '_')"
rm -rf "$OBJ"
# shellcheck disable=SC2086
nice -n 19 "$VL" --binary --build-jobs 2 --timing -Wno-fatal \
    +incdir+test +incdir+. --top-module "$TOP" -o sim --Mdir "$OBJ" \
    $GFLAGS $SRCS > "$OUTDIR/$TOP.build.log" 2>&1
RC=$?
if [ "$RC" -ne 0 ] || [ ! -x "$OBJ/sim" ]; then
    echo "  *** verilator build FAILED (exit $RC): $OUTDIR/$TOP.build.log"
    tail -15 "$OUTDIR/$TOP.build.log"
    exit 1
fi
while read -r LABEL ARGS; do
    [ -z "$LABEL" ] && continue
    # shellcheck disable=SC2086
    nice -n 19 "$OBJ/sim" +verilator+rand+reset+0 $ARGS > "$OUTDIR/$LABEL.vl.txt" 2>&1
    echo "  ran $LABEL"
done < "$ARMS"
