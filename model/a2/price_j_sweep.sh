#!/usr/bin/env bash
# RE-MEASURE THE RECORDED J SWEEP -- the script gate_j_program.py names.
#
# ⛔⛔ IT WAS REFERENCED AND DID NOT EXIST. `gate_j_program.py` says the sweep is
# "RECORDED, NOT RE-RUN ... `price_j_sweep.sh` is what re-measures it, and a sim
# value ABOVE the derivation stops everything" -- and no such file was in the
# repo. So the sweep that the published `J` rests on had never been re-measured
# by anything, and the sentence promising otherwise read as a guarantee.
# ⇒ This is that script. Same class as `noop_image_h19.hex`: a named artefact
#   with no implementation, invisible until someone goes looking.
#
# ⚠ AND IT IS WHY THE PROVENANCE QUESTION MATTERS. `five_image.hex` had two
# recipes for a while, so any measurement that loaded it without regenerating it
# first could have been taken on the wrong program. The sweep's own recipe is
# per-point -- `--five d d+1 d+2 d+3 d+4` for each d -- so each point rebuilds
# the image it measures, which is what this script preserves.
#
# Usage, from the repo root:
#   bash model/a2/price_j_sweep.sh            # the whole recorded sweep
#   bash model/a2/price_j_sweep.sh 12         # one d
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
SP="${PE_SCRATCH:-/tmp}"
mkdir -p "$SP"

DS="${1:-2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 18 20 25}"

echo "=============================================================="
echo "J SWEEP, RE-MEASURED -- five active lanes, double buffer, primed"
echo "=============================================================="
echo "  recipe per point: --five d d+1 d+2 d+3 d+4, then tb_smoke on it"
echo

VVP="$SP/j_sweep.vvp"
iverilog -g2012 -o "$VVP" -s tb_smoke \
    test/tb_smoke.v src/pe_engine.v src/pe_store.v src/project.v 2>/dev/null
if [ ! -f "$VVP" ]; then
    echo "  *** iverilog build failed -- cannot re-measure"
    exit 1
fi

# the recorded values, read OUT OF the gate so this cannot drift from it
DER=$(python - <<'PY2'
import os, sys
sys.path.insert(0, os.path.join("model", "a2"))
import gate_j_program as g
print(" ".join("%d:%d" % (d, g.j_stall(d)) for d in sorted(g.SWEEP)))
PY2
)
ADMS=$(python - <<'PY3'
import os, sys
sys.path.insert(0, os.path.join("model", "a2"))
import gate_j_program as g
print(" ".join("%d:%s" % (d, "yes" if g.admissible(d) else "no")
               for d in sorted(g.SWEEP)))
PY3
)
REC=$(python - <<'PY'
import os, sys
sys.path.insert(0, os.path.join("model", "a2"))
import gate_j_program as g
print(" ".join("%d:%d" % (k, v) for k, v in sorted(g.SWEEP.items())))
PY
)

printf "  %-5s %-10s %-10s %s\n" "d" "recorded" "measured" "verdict"
printf "  %-5s %-10s %-10s %s\n" "-----" "--------" "--------" "-------"
RC=0
NABOVE=0
for d in $DS; do
    python test/make_smoke_image.py --five "$d" $((d+1)) $((d+2)) $((d+3)) $((d+4)) \
        > /dev/null 2>&1
    # CONVERGE THE WARM-UP WINDOW; DO NOT PICK A CONSTANT. The bench default
    # of 200 cycles was sized for the SHIPPED program (periods 25..4140). A
    # 5-lane stress set at periods 12..16 has a contended transient running
    # past cycle 1270, so at the default window a TRANSIENT reads as steady
    # state -- which is how this script first reported 7 where the record says
    # 0, and nearly had me call the published universal J unsound.
    # The window is DOUBLED until two successive lengths agree: a convergence
    # criterion rather than a magic number. If the value still moves, the
    # transient has not ended.
    # A LONG RUN WITH AN ASSERTED NON-EMPTY WINDOW. Two vacuity traps were hit
    # before this settled, and both produced confident numbers:
    #   * the bench observed only 4000 cycles, so pushing the warm-up out to
    #     escape the transient left warm_from > run length -- ZERO EVENTS,
    #     which reads exactly like "no stalls" and is really "no window";
    #   * doubling the window until two readings agreed converged INSIDE the
    #     transient, because 500 and 1000 both saw it.
    # So: a 200k-cycle run, a fixed warm-up well inside it, and the window
    # length is CHECKED. A number from an empty window is refused.
    M=""; WINDOW=""
    OUT=$(vvp "$VVP" +IMG=test/five_image.hex +NCYC=200000 +WARMUP=4000 2>&1)
    NB=$(echo "$OUT" | grep -o "five_image.hex: [0-9]* bytes" | grep -o "[0-9]*" | head -1)
    WINDOW=$(echo "$OUT" | grep -o "window length *: *[0-9]*" | grep -o "[0-9]*$" | head -1)
    CUR=$(echo "$OUT" | grep -o "STEADY *: *[0-9]*" | grep -o "[0-9]*$" | head -1)
    EV=$(echo "$OUT" | grep -o "EVENTS in steady state *: *[0-9]*" | grep -o "[0-9]*$" | head -1)
    if [ -z "$NB" ] || [ "$NB" -lt 30 ]; then
        M=""            # the image never loaded
    elif [ -z "${WINDOW:-}" ] || [ "${WINDOW:-0}" -lt 100000 ]; then
        M=""            # the window is empty or too short to mean anything
    else
        M="$CUR"
    fi
    R=$(echo "$REC" | tr ' ' '\n' | sed -n "s/^$d://p")
    [ -z "$R" ] && R="-"
    if [ -z "$M" ]; then
        printf "  %-5s %-10s %-10s %s\n" "$d" "$R" "?" "*** no reading"
        RC=1
        continue
    fi
    DV=$(echo "$DER" | tr " " "
" | sed -n "s/^$d://p")
    ADM=$(echo "$ADMS" | tr " " "
" | sed -n "s/^$d://p")
    if [ "$ADM" = "no" ]; then
        V="inadmissible (U>1) -- excluded from the bound"
    elif [ -n "$DV" ] && [ "$M" -gt "$DV" ]; then
        # ⛔ THE SOUNDNESS DIRECTION: the derivation is an UPPER BOUND on the
        # stall, so a bigger measured stall makes the published J unsound, not
        # merely stale.
        V="*** ABOVE THE DERIVATION ($DV) -- UNSOUND"
        NABOVE=$((NABOVE+1))
        RC=1
    elif [ "$R" = "-" ]; then
        V="(not in the record)"
    elif [ "$M" -eq "$R" ]; then
        V="confirms"
    elif [ "$M" -gt "$R" ]; then
        V="above the record but within the derivation ($DV) -- record stale"
        RC=1
    else
        V="*** below the record (stale, publish a correction)"
        RC=1
    fi
    printf "  %-5s %-10s %-10s %s\n" "$d" "$R" "$M" "$V"
done

# leave the tree holding the recipe run_mutants expects
python test/make_smoke_image.py --all > /dev/null 2>&1

echo
if [ "$RC" -eq 0 ]; then
    echo "  PASS -- every recorded point re-measures to the same value, from"
    echo "  the per-point recipe. The published J rests on a sweep that has"
    echo "  now actually been re-run."
else
    echo "  *** THE SWEEP DOES NOT REPRODUCE ($NABOVE point(s) ABOVE the record)."
    echo "  A value above the record is an UNSOUNDNESS in the published J, not a"
    echo "  footnote; a value below it is a stale record that still needs a"
    echo "  correction published."
fi
echo "  \u26a0 the tree is left with the --all images restored."
exit $RC
