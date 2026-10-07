#!/usr/bin/env bash
# TWO-SIM CYCLE-EXACT COMPARE -- iverilog vs Verilator, on the same RTL.
#
# THE ONE CLAIM: two independent simulators, same design, same stimulus, produce
# byte-identical port traces for every cycle. Neither is a model of the other,
# so an agreement is two engines witnessing each other and a disagreement is a
# real tool-or-design problem.
#
# RUN IT FROM THE REPO ROOT, after the iverilog trace exists:
#   MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash \
#     /mnt/d/ProtocolEmulator/test/two_sim_trace.sh <iv_trace> <vl_trace>
set -uo pipefail

IV="${1:-/mnt/c/tmp/tr_iv.txt}"
VL="${2:-/mnt/c/tmp/vtrace_clean/s1.txt}"

for f in "$IV" "$VL"; do
    [ -s "$f" ] || { echo "  *** missing or empty: $f"; exit 1; }
done

# ---- LINE ENDINGS ARE NORMALISED, AND THE NORMALISATION IS JUSTIFIED -------
# iverilog here runs natively on Windows and $fopen(...,"w") translates "\n" to
# CRLF; Verilator runs under WSL and does not. That is a FILE-FORMAT difference
# and nothing to do with the design -- but stripping CR silently would also
# hide a real difference that happened to involve CR, so the claim "the raw
# files differ ONLY by trailing CR" is PROVEN rather than assumed: every CR in
# the file must be at end-of-line, and there must be exactly one per line.
NL=$(wc -l < "$IV")
NCR=$(tr -dc '\r' < "$IV" | wc -c)
NCR_EOL=$(grep -c $'\r$' "$IV")
echo
echo "  iverilog lines=$NL  CR total=$NCR  CR at end-of-line=$NCR_EOL"
if [ "$NCR" -ne 0 ]; then
    if [ "$NCR" -ne "$NL" ] || [ "$NCR_EOL" -ne "$NL" ]; then
        echo "  *** CR appears somewhere other than one-per-end-of-line."
        echo "      Normalisation would hide a real difference. Not normalising."
        exit 1
    fi
    echo "  => every CR is a line terminator: normalisation is a format fix"
fi

# ⛔⛔ THE NORMALISED COPIES GO IN A FRESH TEMP DIRECTORY, NOT /mnt/c/tmp.
# They were written to `/mnt/c/tmp/{iv,vl}.norm`, which exists under WSL on the
# development box and NOWHERE on CI's Linux runner -- so when ruling Q2 put the
# corpus witness in CI, both copies came out empty, both headers printed blank,
# and every program reported a "CROSS-SIM DISAGREEMENT" on ZERO lines. A local
# run could not catch it: WSL HAS /mnt/c. ⇒ mktemp, removed on exit.
NORM="$(mktemp -d)"
trap 'rm -rf "$NORM"' EXIT
tr -d '\r' < "$IV" > "$NORM/iv.norm" || { echo "  *** cannot write $NORM"; exit 1; }
tr -d '\r' < "$VL" > "$NORM/vl.norm" || { echo "  *** cannot write $NORM"; exit 1; }

# ---- PROVENANCE FIRST ------------------------------------------------------
# The header is compared BEFORE the body, because the first run of this pair
# differed on `bytes=256` vs `bytes=51` -- Verilator could not resolve the
# relative image path from its object directory, and a body diff would have
# been read as a design disagreement rather than as two different programs.
# ⛔ READ FROM THE NORMALISED COPIES. This check compared the RAW first lines
# and failed on two headers that were character-for-character the same text --
# the iverilog one carried a trailing CR. A provenance guard defeated by the
# very file-format difference it sits downstream of.
HI=$(head -1 "$NORM/iv.norm"); HV=$(head -1 "$NORM/vl.norm")
echo "  iverilog  header : $HI"
echo "  verilator header : $HV"
if [ "$HI" != "$HV" ]; then
    echo "  *** THE TWO RUNS ARE NOT THE SAME EXPERIMENT. Compare stimulus,"
    echo "      not traces, until these match."
    exit 1
fi

# ---- X CENSUS, ON THE DATA LINES ONLY --------------------------------------
# The header contains `smoke_image.hex`, so a whole-file grep for `x` matches
# the provenance line and reports 1 X on a trace that has none. Measured on the
# body.
XIV=$(grep -v '^#' "$NORM/iv.norm" | grep -c 'x')
echo
echo "  iverilog X-bearing cycles : $XIV"
if [ "$XIV" -ne 0 ]; then
    echo "  ⚠ iverilog drives X onto a port. Verilator is 2-state and CANNOT"
    echo "    reproduce that, so the comparison below is NOT MEANINGFUL until"
    echo "    the X is gone: the two engines differ by construction."
    grep -v '^#' "$NORM/iv.norm" | grep -n 'x' | head -3 | sed 's/^/      /'
fi

# ---- THE COMPARE -----------------------------------------------------------
echo
if diff -q "$NORM/iv.norm" "$NORM/vl.norm" > /dev/null; then
    echo "  CYCLE-EXACT: identical on all $NL lines"
    echo "    iverilog  sha256 $(sha256sum "$NORM/iv.norm" | cut -c1-16)"
    echo "    verilator sha256 $(sha256sum "$NORM/vl.norm" | cut -c1-16)"
    exit 0
fi
ND=$(diff "$NORM/iv.norm" "$NORM/vl.norm" | grep -c '^[<>]')
FIRST=$(diff "$NORM/iv.norm" "$NORM/vl.norm" | grep -m1 -n '^[<>]')
echo "  DISAGREE on $ND line(s). First divergence:"
diff "$NORM/iv.norm" "$NORM/vl.norm" | head -6 | sed 's/^/      /'
echo "  (first: $FIRST)"
exit 2
