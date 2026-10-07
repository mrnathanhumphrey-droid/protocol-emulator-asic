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

# ⭐ THE SWEEP REACHES WELL ABOVE D*, because the scoped claim is only as
# strong as the number of port-feasible points it is checked on -- two
# (d = 20, 25) is not a regime, it is a pair.
DS="${1:-2 4 6 8 10 11 12 14 16 18 19 20 21 22 25 30 40 60}"

echo "=============================================================="
echo "J SWEEP, RE-MEASURED -- five active lanes, double buffer, primed"
echo "=============================================================="
echo "  recipe per point: --five d d+1 d+2 d+3 d+4, then tb_smoke on it"
echo

. ci/tools.sh              # ruling V: $IV / $VVP, made absolute
tool_banner iverilog vvp
VVPF="$SP/j_sweep.vvp"
"$IV" -g2012 -o "$VVPF" -s tb_smoke \
    test/tb_smoke.v src/pe_engine.v src/pe_store.v src/project.v 2>/dev/null
if [ ! -f "$VVPF" ]; then
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
PFS=$(python - <<'PY4'
import os, sys
sys.path.insert(0, os.path.join("model", "a2"))
import gate_j_program as g
print(" ".join("%d:%s" % (d, "yes" if g.port_feasible(d) else "no")
               for d in sorted(g.SWEEP)))
PY4
)
DSTAR=$(python -c "import sys; sys.path.insert(0,'model/a2'); import gate_j_program as g; print(g.D_STAR)")
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
    python test/make_smoke_image.py --five "$d" $((d+1)) $((d+2)) $((d+3)) $((d+4)) probe_five \
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
    OUT=$("$VVP" "$VVPF" +IMG=test/probe_five.hex +NCYC=200000 +WARMUP=4000 2>&1)
    NB=$(echo "$OUT" | grep -o "probe_five.hex: [0-9]* bytes" | grep -o "[0-9]*" | head -1)
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
    DV=$(echo "$DER" | tr ' ' '
' | sed -n "s/^$d://p")
    # PORT FEASIBILITY FROM d DIRECTLY, not from a lookup limited to the
    # recorded keys: extending the sweep above D* put d = 21, 30, 40 and 60
    # into the table with EMPTY feasibility, so they printed as "below D*"
    # and the claim was being checked on two points while appearing to
    # cover ten. A lookup keyed on the old record cannot judge new points.
    if [ "$d" -ge "$DSTAR" ]; then PF=yes; else PF=no; fi
    # THE SCOPED CLAIM IS WHAT IS GATED: at or above D*, the single fetch port
    # can serve one refill per lane per action period, so the steady stall must
    # be ZERO and J is the winner-registration cycle alone. Below D* the regime
    # is explicitly UNCLAIMED -- reported, never passed off as a bound.
    if [ "$PF" = "yes" ]; then
        if [ "${M:-1}" -eq 0 ]; then
            V="port-feasible: stall 0 => J = 1  [SCOPED CLAIM holds]"
        else
            V="*** PORT-FEASIBLE BUT STALLS ($M) -- SCOPED CLAIM FAILS"
            NABOVE=$((NABOVE+1))
            RC=1
        fi
    else
        V="below D*=$DSTAR -- UNCLAIMED (measured $M, old derivation $DV)"
    fi
    printf "  %-5s %-10s %-10s %s\n" "$d" "$R" "$M" "$V"
done

# ⭐ NOTHING TO RESTORE ANY MORE: this sweep writes only probe_five.hex,
# so it cannot leave a reserved artefact holding an experiment's program.
# It used to end with `--all` to undo its own clobber, and a probe that
# has to clean up after itself is one interrupted run from drift.

echo
if [ "$RC" -eq 0 ]; then
    echo "  PASS -- every PORT-FEASIBLE point measures a steady stall of 0, so"
echo "  J = 1 holds in the scoped regime d_min >= D*. Points below D* are"
echo "  REPORTED AND EXPLICITLY UNCLAIMED -- the old derivation is unsound"
echo "  there and no bound is asserted."
else
    echo "  *** THE SCOPED CLAIM FAILS at $NABOVE port-feasible point(s)."
    echo "  At or above D* the stall must be 0; anything else means the port"
    echo "  feasibility argument itself is wrong, not merely the constant."
fi
echo "  the sweep wrote only test/probe_five.hex; no reserved name touched."
exit $RC
