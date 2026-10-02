#!/usr/bin/env bash
# TA-02 parametric re-synthesis over TABLE FIELDS.
#
# SCRIPT FILE, never `bash -lc` -- inline $VAR expansion across the
# Git-Bash/WSL boundary has eaten these variables before (TA-01c lost $TK and $f
# that way, and run_pnr.sh's own header records five separate corruptions).
set -uo pipefail
cd /mnt/d/ProtocolEmulator/model/ta02

# The close-out model is DERIVED from the general one by adding exactly one
# constraint, so the two models provably differ by that line and nothing else.
# Retyping it would let an unintended difference in.
sed 's|^\(\t\t& G0 > 0\)$|\1\n\t\t\& G0 = G|' table_guard.imi > table_guard_closeout.imi
cp table_guard.imiprop table_guard_closeout.imiprop

echo "=== the derived close-out model differs from the general one by: ==="
diff table_guard.imi table_guard_closeout.imi
echo

RC=0
for m in table_guard_closeout table_guard; do
    echo "============================================================"
    echo "=== $m"
    echo "============================================================"
    /opt/ta/bin/imitator "${m}.imi" "${m}.imiprop" 2>&1 \
        | grep -vE "^\s*$" \
        | sed -n '1,200p'
    echo
done

# THE ASSERTIONS. Without them this script prints two synthesized regions and
# exits 0 whichever regions they are -- a gate that cannot fail. The close-out's
# whole job is to REPRODUCE TA-01c's band over the table field; if it does not,
# the re-parametrization changed the model and nothing downstream transfers.
# Matched INSIDE the BEGIN/END CONSTRAINT block, so a line of model commentary
# cannot satisfy the grep. And the conjunct COUNT is asserted too: an extra
# conjunct nobody predicted would otherwise pass silently, which is the whole
# hazard of checking a result against a list of things you expected to see.
want_in() {   # want_in <file> <description> <expected-count> <pattern>...
    local f="$1" desc="$2" want_n="$3"; shift 3
    local body n
    body=$(sed -n '/BEGIN CONSTRAINT/,/END CONSTRAINT/p' "$f" \
           | grep -vE "BEGIN CONSTRAINT|END CONSTRAINT|^\s*$")
    if [ -z "$body" ]; then
        echo "    *** ${desc}: no CONSTRAINT block in ${f}"; RC=1; return
    fi
    for pat in "$@"; do
        if echo "$body" | grep -qF "$pat"; then
            echo "    ok      ${desc}: ${pat}"
        else
            echo "    *** MISSING  ${desc}: ${pat}"; RC=1
        fi
    done
    n=$(echo "$body" | wc -l)
    if [ "$n" = "$want_n" ]; then
        echo "    ok      ${desc}: exactly ${want_n} conjuncts, none unaccounted for"
    else
        echo "    *** ${desc}: ${n} conjuncts, expected ${want_n} -- an UNPREDICTED"
        echo "        conjunct is a change to the synthesized region:"
        echo "$body" | sed 's/^/          /'
        RC=1
    fi
    # soundness, termination and nature are three separate claims in the .res and
    # all three are load-bearing: a depth-limited run yields an UNDER-approximation
    # that reads like an answer.
    for k in "Constraint soundness                    : exact" \
             "Termination                             : regular termination" \
             "Constraint nature                       : good"; do
        grep -qF "$k" "$f" \
            && echo "    ok      ${desc}: ${k%% *}... ${k##*: }" \
            || { echo "    *** ${desc}: expected '${k}'"; RC=1; }
    done
}

echo "=== assertions ==="
want_in table_guard_closeout.res "close-out" 3 \
    "19*U > 9*G0" "10*G0 > 19*U" "G0 = G"
want_in table_guard.res "general" 3 \
    "19*U > G0 + 8*G" "G0 + 9*G > 19*U" "G0 > U"
echo
[ "$RC" = 0 ] \
    && echo "    PASS -- the close-out reproduces TA-01c's band as a constraint on the TABLE FIELD, and the general region adds G0 > U." \
    || echo "    *** FAIL -- synthesized regions are not the ones TA-02 reports."
exit "$RC"
