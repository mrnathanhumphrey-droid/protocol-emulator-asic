#!/usr/bin/env bash
# VERILATOR SEED SWEEP -- Wilson's amendment 2, the RUNTIME check behind the
# reset allowlist.
#
# THE ONE CLAIM: with `--x-initial unique`, three different seeds randomise
# every unreset flop to three different patterns, so if any of them is READ
# BEFORE IT IS WRITTEN the port trace differs between seeds. Three identical
# traces are therefore evidence that `gate_reset_audit.py`'s allowlist prose
# ("write-before-read because ...") is true of the running design, not just
# stated about it.
#
# ⛔ WHY NOT `--x-initial 0`. Zero-init gives an unread-before-write flop a
# PLAUSIBLE value, identically on every run, so the bug becomes a stable wrong
# answer -- the kind that ships. `unique` turns it into a visible disagreement.
#
# ⛔ SEEDS ARE RECORDED, not just used. A passing run with an unrecorded seed is
# not reproducible, which this project has already paid for once.
#
# ⛔⛔⛔ `--x-initial unique` ALONE IS A NO-OP, AND THIS SWEEP PASSED
# VACUOUSLY BECAUSE OF IT. The compile flag only emits the randomisation hooks;
# the RUNTIME reset mode still defaults to all-zeros, so three seeds produced
# three IDENTICAL traces on a model that was zero-initialising every unreset
# flop. The sweep reported "SEEDS AGREE" and proved nothing whatsoever.
# ⭐ IT WAS THE MUST-FIRE THAT CAUGHT IT: the M_PFETCH_NOWAIT arm -- a
# deliberate read-before-write -- ALSO reported SEEDS AGREE. Measured directly,
# a 32-bit never-written reg read `00000000` under all three seeds; with
# `+verilator+rand+reset+2` it read fffffffc / fffffff0 / ffff9f8c.
# ⇒ BOTH FLAGS ARE REQUIRED, and the randomisation is ASSERTED LIVE below
#   rather than assumed, because its absence is silent and green.
#
# Usage (a SCRIPT FILE, never `bash -lc` with inline $VAR across the
# Git-Bash/WSL boundary -- that has eaten arguments here before):
#   MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash \
#     .../verilator_trace.sh <root> <nbytes> <ncyc> <outdir> [img] [peer] [async] [defines]
# TWO DIFFERENT SEEDS LIVE IN THIS SCRIPT AND CONFLATING THEM MADE THE SWEEP
# ASSERT SOMETHING FALSE BY CONSTRUCTION:
#   * `+verilator+seed+N` randomises UNINITIALISED STATE. Changing it must
#     NOT change the trace -- that is the whole check.
#   * `+SEED=N` seeds the bench peer-phase LCG, which deliberately MOVES THE
#     STIMULUS: different peer edge phases, a different experiment.
# Passing the sweep index to both made the check "different stimulus produces
# the same trace", false on purpose, and the all-lane program duly disagreed
# on 2,904 lines. The phase seed is now an ARGUMENT held fixed across the
# sweep; varying it is a separate arm that re-runs the cross-sim compare.
set -uo pipefail

ROOT="${1:-/mnt/d/ProtocolEmulator}"
NBYTES="${2:-51}"
NCYC="${3:-1500}"
OUTDIR="${4:-/mnt/c/tmp/vtrace}"
IMG="${5:-test/smoke_image.hex}"
PEER="${6:-none}"
ASYNCA="${7:-0}"
PHASE="${8:-1}"
DEFS="${9:-}"
STAYLOAD="${10:-0}"
SCLHOLD="${11:-0}"
SEEDS="1 7 12345"          # ⭐ recorded here and echoed with every result

cd "$ROOT" || exit 1
mkdir -p "$OUTDIR"
# ⛔ THE BUILD TREE LIVES IN /tmp AND THE TRACES DO NOT. WSL's /tmp is WIPED
# between `wsl.exe` invocations here, so an artefact another command has to read
# must sit on /mnt/c or /mnt/d; but Verilator's C++ build across the 9p mount is
# slow, so only the traces cross over.
OBJ="/tmp/pe_vobj"
# ---- BUILD CACHE, keyed on SOURCES AND DEFINES ------------------------
# The netlist does not depend on the phase seed or the image, so sweeping
# phases would otherwise pay for a full C++ rebuild each time. ⛔ But a cached
# binary is a STALE-ARTEFACT hazard, and this project has already read a
# verdict off a stale build once: the fix is to key the cache on what can
# change the binary -- every source file's timestamp and the define string --
# and rebuild whenever either moves.
STAMP="$OBJ/.stamp"
WANT="$DEFS|$(ls -la --time-style=+%s test/tb_trace.v test/fram_spi.v     test/fram_i2c.v test/pinmap.vh src/pe_engine.v src/pe_store.v     src/project.v 2>/dev/null | awk '{print $6, $7}' | tr '
' ' ')"
if [ -x "$OBJ/tr" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANT" ]; then
    SKIP_BUILD=1
else
    SKIP_BUILD=0
    rm -rf "$OBJ"
fi

# shellcheck disable=SC2086
if [ "$SKIP_BUILD" -eq 1 ]; then
    RC=0
else
verilator --binary --timing --x-initial unique \
    -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-UNOPTFLAT -Wno-fatal \
    --top-module tb_trace -o tr --Mdir "$OBJ" +incdir+test \
    $DEFS \
    test/tb_trace.v test/fram_spi.v test/fram_i2c.v \
    src/pe_engine.v src/pe_store.v src/project.v \
    > "$OUTDIR/build.log" 2>&1
RC=$?
printf '%s' "$WANT" > "$STAMP" 2>/dev/null
fi
if [ "$RC" -ne 0 ] || [ ! -x "$OBJ/tr" ]; then
    echo "  *** verilator build FAILED (exit $RC). Log: $OUTDIR/build.log"
    tail -25 "$OUTDIR/build.log"
    exit 1
fi

echo "  verilator  : $(verilator --version)"
echo "  image      : $IMG  peer=$PEER  async=$ASYNCA"
echo "  phase seed : $PHASE  (the STIMULUS seed, held FIXED)"
echo "  stayload=$STAYLOAD  sclhold=$SCLHOLD"
echo "  defines    : ${DEFS:-<none>}"
echo "  x-initial  : unique + runtime +verilator+rand+reset+2"
echo "               (NOT 0, and NOT the compile flag alone)"
echo "  seeds      : $SEEDS"

# ---- ASSERT THE RANDOMISATION IS LIVE, before trusting any agreement -------
# The sweep's whole claim is "different seeds, different initial state". That
# is a PRECONDITION, and it was FALSE for an entire pass of this gate -- so it
# is measured here on a reg that is never written, by construction, rather than
# inferred from the right flags having been typed.
PRE=/tmp/pe_vpre
mkdir -p "$PRE"
cat > "$PRE/probe.v" <<'PV'
`timescale 1ns/1ps
module probe;
  reg [31:0] never_written;
  initial begin #1 $display("PROBE %h", never_written); $finish; end
endmodule
PV
verilator --binary --timing --x-initial unique --top-module probe \
    -o pr --Mdir "$PRE/obj" "$PRE/probe.v" > "$PRE/build.log" 2>&1
PV_VALS=""
for S in $SEEDS; do
    V=$("$PRE/obj/pr" "+verilator+rand+reset+2" "+verilator+seed+$S" \
        2>/dev/null | sed -n 's/^PROBE //p')
    PV_VALS="$PV_VALS ${V:-MISSING}"
done
PV_N=$(printf '%s\n' $PV_VALS | wc -l)
PV_UNIQ=$(printf '%s\n' $PV_VALS | sort -u | wc -l)
echo "  randomisation precheck : never-written reg =$PV_VALS"
if [ "$PV_N" -eq 0 ] || [ "$PV_UNIQ" -lt "$PV_N" ]; then
    echo "  *** THE SEEDS DO NOT VARY INITIAL STATE ($PV_UNIQ distinct of $PV_N)."
    echo "      Every comparison below would be vacuously identical. This is the"
    echo "      exact defect that made this gate report SEEDS AGREE on a"
    echo "      deliberate read-before-write mutant: the compile flag was"
    echo "      present and +verilator+rand+reset+2 was not."
    exit 1
fi
echo "  => $PV_UNIQ distinct initial states for $PV_N seeds: the detector is live"

echo

# ⛔ RUN FROM THE REPO ROOT. The first Verilator run of this bench reported
# `bytes=256` against iverilog's `bytes=51` -- the relative image path did not
# resolve from the object directory, and the provenance header in the trace is
# the only reason that was caught before traces were compared.
for S in $SEEDS; do
    # BOTH FLAGS: rand+reset+2 selects RANDOM initial state; without it the
    # seed is accepted and silently ignored and every seed is all-zeros.
    "$OBJ/tr" "+IMG=$IMG" "+NBYTES=$NBYTES" \
              "+OUT=$OUTDIR/s$S.txt" "+NCYC=$NCYC" \
              "+PEER=$PEER" "+ASYNC=$ASYNCA" "+SEED=$PHASE" \
              "+STAYLOAD=$STAYLOAD" "+SCLHOLD=$SCLHOLD" \
              "+verilator+rand+reset+2" "+verilator+seed+$S" \
              > "$OUTDIR/run_s$S.log" 2>&1
              > "$OUTDIR/run_s$S.log" 2>&1
    if [ ! -s "$OUTDIR/s$S.txt" ]; then
        echo "  *** seed $S produced no trace. Log: $OUTDIR/run_s$S.log"
        tail -15 "$OUTDIR/run_s$S.log"
        exit 1
    fi
    printf "  seed %-6s lines=%-6s sha=%s  %s\n" "$S" \
        "$(wc -l < "$OUTDIR/s$S.txt")" \
        "$(sha256sum "$OUTDIR/s$S.txt" | cut -c1-12)" \
        "$(head -1 "$OUTDIR/s$S.txt")"
done

echo
FIRST=""
NDIFF=0
NPAIR=0
for S in $SEEDS; do
    if [ -z "$FIRST" ]; then FIRST="$S"; continue; fi
    NPAIR=$((NPAIR + 1))
    # BODIES, NOT WHOLE FILES. The provenance header records the seed --
    # correctly, so two runs cannot be confused -- and comparing whole files
    # therefore reported every pair as DIFFERENT on exactly the header line:
    # a guard defeated by a field added to make runs distinguishable.
    grep -v '^#' "$OUTDIR/s$FIRST.txt" > "$OUTDIR/b$FIRST.txt"
    grep -v '^#' "$OUTDIR/s$S.txt"     > "$OUTDIR/b$S.txt"
    if ! diff -q "$OUTDIR/b$FIRST.txt" "$OUTDIR/b$S.txt" > /dev/null; then
        N=$(diff "$OUTDIR/b$FIRST.txt" "$OUTDIR/b$S.txt" | grep -c '^[<>]')
        echo "  seed $FIRST vs seed $S : DIFFER on $N body line(s)"
        diff "$OUTDIR/b$FIRST.txt" "$OUTDIR/b$S.txt" | head -4 | sed 's/^/      /'
        NDIFF=$((NDIFF + 1))
    else
        echo "  seed $FIRST vs seed $S : identical"
    fi
done

echo
if [ "$NDIFF" -eq 0 ]; then
    echo "  SEEDS AGREE  (0 of $NPAIR pairs differ)"
    exit 0
fi
echo "  SEEDS DISAGREE  ($NDIFF pair(s))"
echo "  ⇒ a flop is READ BEFORE IT IS WRITTEN and the reset allowlist missed"
echo "    it. This is the expected result for the M_PFETCH_NOWAIT arm and a"
echo "    FINDING for the clean arm."
exit 2
