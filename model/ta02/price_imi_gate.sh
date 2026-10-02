#!/usr/bin/env bash
# PRICE THE RE-SYNTHESIS GATE BY MUTATING THE MODEL.
#
# The assertions in run_imi.sh had never rejected anything, which makes them
# assertions of unknown strength. Mutate the monitor's stop-sample point and the
# executor's data span; each mutant must make the gate's expected constraint
# ABSENT, and the mutant's own constraint must be visibly different -- not merely
# a red exit code. Scratch models only; the real ones are untouched.
set -uo pipefail
cd /mnt/d/ProtocolEmulator/model/ta02
D=$(mktemp -d)
trap 'rm -rf "$D"' EXIT
RC=0

# M1: the monitor samples the stop bit at 18U instead of 19U (a bit-count error)
sed 's/19\*U/18*U/g' table_guard.imi > "$D/m1.imi"
# M2: the executor's data span is 7 bits, not 8 (a wrong-width table)
sed 's/8\*G/7*G/g'   table_guard.imi > "$D/m2.imi"
cp table_guard.imiprop "$D/m1.imiprop"
cp table_guard.imiprop "$D/m2.imiprop"

echo "=== pricing the re-synthesis gate ==="
echo "  the real general region asserts: 19*U > G0 + 8*G | G0 + 9*G > 19*U | G0 > U"
echo
IMITATOR="${IMITATOR:-/opt/ta/bin/imitator}"

for m in m1 m2; do
    ( cd "$D" && "$IMITATOR" "${m}.imi" "${m}.imiprop" >/dev/null 2>&1 )
    IRC=$?
    # ⛔⛔ A MISSING .res IS NOT A MUTANT KILL, AND THIS SCRIPT SCORED IT AS ONE.
    # With the Imitator binary absent or failing, `body` came back empty, all
    # three conjuncts counted as "absent", and the mutant read as REJECTED -- so
    # the PRICING gate reported that its assertions discriminate while nothing
    # had been evaluated at all. A guard passing because of the breakage it
    # screens for. Absence of evidence is now COULD-NOT-EVALUATE, and red.
    if [ "$IRC" != 0 ] || [ ! -f "$D/${m}.res" ]; then
        if [ -f "$D/${m}.res" ]; then HAVE=yes; else HAVE=no; fi
        echo "  --- ${m}: *** COULD NOT EVALUATE (imitator rc=${IRC}, .res: ${HAVE})"
        echo "        This is NOT a mutant kill. The gate is unpriced, not passed."
        RC=1
        echo
        continue
    fi
    body=$(sed -n '/BEGIN CONSTRAINT/,/END CONSTRAINT/p' "$D/${m}.res" 2>/dev/null \
           | grep -vE "BEGIN CONSTRAINT|END CONSTRAINT|^[[:space:]]*$")
    echo "  --- ${m}: synthesized"
    echo "$body" | sed 's/^/        /'
    if [ -z "$body" ]; then
        echo "        *** COULD NOT EVALUATE: .res carries no CONSTRAINT block"
        RC=1; echo; continue
    fi
    miss=0
    for pat in "19*U > G0 + 8*G" "G0 + 9*G > 19*U" "G0 > U"; do
        echo "$body" | grep -qF "$pat" || miss=$((miss+1))
    done
    if [ "$miss" -gt 0 ]; then
        echo "        REJECTED: ${miss} of 3 asserted conjuncts absent -> gate goes red"
    else
        echo "        *** NOT REJECTED: the mutant satisfies every asserted conjunct,"
        echo "            so the gate cannot tell this model from the real one."
        RC=1
    fi
    echo
done
[ "$RC" = 0 ] \
    && echo "  PASS -- both mutants are rejected, and each for a visibly different region." \
    || echo "  *** FAIL -- the gate's assertions do not discriminate."
exit "$RC"
