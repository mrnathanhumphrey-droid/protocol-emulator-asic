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
    OUT=$(vvp "$VVP" +IMG=test/five_image.hex 2>&1)
    M=$(echo "$OUT" | sed -n 's/.*max prefetch stall, STEADY *: *\([0-9]*\).*/\1/p' | head -1)
    R=$(echo "$REC" | tr ' ' '\n' | sed -n "s/^$d://p")
    [ -z "$R" ] && R="-"
    if [ -z "$M" ]; then
        printf "  %-5s %-10s %-10s %s\n" "$d" "$R" "?" "*** no reading"
        RC=1
        continue
    fi
    if [ "$R" = "-" ]; then
        V="(not in the record)"
    elif [ "$M" -eq "$R" ]; then
        V="confirms"
    elif [ "$M" -gt "$R" ]; then
        # ⛔ A MEASURED VALUE ABOVE THE RECORD IS THE DIRECTION THAT MATTERS:
        # the derivation is an upper bound on the stall, so a bigger stall means
        # the published J is UNSOUND, not merely stale.
        V="*** ABOVE THE RECORD -- the published J may be unsound"
        NABOVE=$((NABOVE+1))
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
