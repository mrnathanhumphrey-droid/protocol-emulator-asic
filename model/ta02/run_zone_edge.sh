#!/usr/bin/env bash
# TA-02 -- the zone model's BAND EDGE, the item TA-01b left owed.
#
# WHY THIS ISOLATES FINDING 1. The zone monitor checks the LINE LEVEL, exactly as
# the Python receiver does -- but its guards (`xm==half`, `xm==t_mon`) are EXACT
# equalities on a resetting clock, so it has no +1-per-bit error. Holding the
# checked property constant and varying only the timing is what makes the
# comparison an isolation rather than a corroboration:
#
#   fixpoint (level check, 435-cycle period)  -> high edge 459
#   zone     (level check, 434-cycle period)  -> high edge should be 458
#
# A 1-cycle difference with the property held fixed is the defect, measured.
#
# THE LOW EDGE IS NOT COMPARABLE and this script does not pretend otherwise: the
# zone model's data bits are nondeterministic and it carries NO data conjunct, so
# a far-too-slow executor is caught by the start sample rather than by a wrong
# byte. Its low edge answers a different question.
#
# SCRIPT FILE, never `bash -lc` -- inline $VAR expansion across the Git-Bash/WSL
# boundary has eaten these before.
set -uo pipefail
TK=/opt/ta/tchecker/bin
cd /mnt/d/ProtocolEmulator/model/ta02

T=434
echo "=== zone band edge: T_mon = ${T}, sweeping T_exec ==="
echo "    synthesized high edge (9*Te < 19*U): Te <= 458"
echo "    fixpoint high edge (level check, 435-cycle period): 459"
echo

RC=0
LAST_FALSE=""
FIRST_TRUE=""
for TE in 455 456 457 458 459 460 461; do
    # RUN CONDITION IN THE FILENAME, both states named, asserted at generation.
    # A generated model whose period is not the one the filename claims would
    # make every row below a confident wrong answer.
    F="uart_T${T}_Te${TE}"
    python3 ../ta01b/zone/gen_tck.py --t "${T}" --te "${TE}" -o "${F}.tck" >/dev/null
    grep -q "xe<=${TE}" "${F}.tck" || { echo "${F}: GEN MISMATCH -- no xe<=${TE}"; RC=1; continue; }
    grep -q "xm<=${T}"  "${F}.tck" || { echo "${F}: GEN MISMATCH -- no xm<=${T}";  RC=1; continue; }
    OUT=$(timeout 600 "$TK/tck-reach" -a reach -l bad "${F}.tck" 2>&1)
    R=$(echo "$OUT" | grep -E "REACHABLE|VISITED_STATES" | tr '\n' ' ')
    echo "    Te=${TE}  ${R}"
    case "$OUT" in
        *"REACHABLE false"*) LAST_FALSE="${TE}" ;;
        *"REACHABLE true"*)  [ -z "$FIRST_TRUE" ] && FIRST_TRUE="${TE}" ;;
        *) echo "      *** no REACHABLE verdict parsed"; RC=1 ;;
    esac
done

# THE ASSERTION. Without it this script prints a table and exits 0 whatever it
# measured -- a gate that cannot fail, which is the anti-pattern this whole rung
# is about. The edge is a MEASURED FACT and this is its regression gate.
echo
echo "    highest conforming Te = ${LAST_FALSE};  lowest violating Te = ${FIRST_TRUE}"
if [ "$LAST_FALSE" = "458" ] && [ "$FIRST_TRUE" = "459" ]; then
    echo "    PASS -- zone high edge is 458, matching Imitator's synthesized edge."
    echo "            The Python fixpoint says 459. Same property checked (level),"
    echo "            exact timing vs 435-cycle timing: that one cycle IS the defect."
else
    echo "    *** FAIL -- expected the edge at 458/459, measured ${LAST_FALSE}/${FIRST_TRUE}."
    echo "    Finding 1's isolation rests on this edge; do not report it unchanged."
    RC=1
fi
exit "$RC"
