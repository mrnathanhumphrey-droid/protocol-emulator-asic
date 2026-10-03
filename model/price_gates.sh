#!/usr/bin/env bash
# PRICE EVERY FOREIGN-AUTHORITY GATE BY REMOVING ITS AUTHORITY.
#
# THE ONE CLAIM: each gate below is actually using the foreign tool it names.
#
# ⛔⛔ WHY THIS EXISTS. Four gates in this repo passed without ever reading
# whether their tool ran:
#   * gate_jitter_sigrok.py  -- never checked sigrok's exit status, and a sigrok
#                               that failed on only the ABOVE-band rungs yields
#                               no annotations there, which is exactly the
#                               refusal the gate expects. All four of its
#                               conditions passed, non-vacuity included.
#   * run_imi.sh             -- never deleted the .res and never read Imitator's
#                               status, so a failed run asserted against the
#                               PREVIOUS run's region.
#   * price_imi_gate.sh      -- scored a missing .res as "mutant REJECTED", i.e.
#                               reported that its assertions discriminate while
#                               nothing had been evaluated.
#   * run_zone_edge.sh       -- never read the generator's status; its content
#                               greps cannot detect staleness because the
#                               FILENAME encodes the parameter they check for.
#
# Each of those is the same failure: the gate's verdict did not depend on the
# tool. The only way to find that is to remove the tool and require red.
# "Tool absent => gate red" is one adversarial run per gate, and it is the
# acceptance test for the fixes, not the diff.
#
# SCRIPT FILE, never `bash -lc`.
set -uo pipefail
cd "$(dirname "$0")/.."

NOPE=/nonexistent/definitely-not-a-tool
RC=0
PASS=0
FAIL=0

run_must_be_red() {   # run_must_be_red <label> <command...>
    local label="$1"; shift
    echo "------------------------------------------------------------"
    echo "  $label"
    "$@" > /tmp/price_gate.out 2>&1
    local rc=$?
    if [ "$rc" != 0 ]; then
        echo "    RED (exit $rc) -- the gate depends on its tool. PASS"
        PASS=$((PASS+1))
    else
        echo "    *** GREEN (exit 0) WITH THE TOOL REMOVED -- this gate's verdict"
        echo "        does not depend on its foreign authority. FAIL"
        sed -n '1,20p' /tmp/price_gate.out | sed 's/^/        | /'
        FAIL=$((FAIL+1))
        RC=1
    fi
}

echo "============================================================"
echo "PRICING THE FOREIGN-AUTHORITY GATES (tool absent => must be red)"
echo "============================================================"

# --- sigrok-backed gates -------------------------------------------------
SIGROK_CLI="$NOPE" run_must_be_red \
    "gate_jitter_sigrok.py with SIGROK_CLI removed" \
    env SIGROK_CLI="$NOPE" python model/a2/gate_jitter_sigrok.py

SIGROK_CLI="$NOPE" run_must_be_red \
    "ta01/gate0_external.py with SIGROK_CLI removed" \
    env SIGROK_CLI="$NOPE" python model/ta01/gate0_external.py

# --- Imitator-backed gates (run inside WSL) ------------------------------
run_must_be_red \
    "ta02/run_imi.sh with IMITATOR removed" \
    env MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- env IMITATOR="$NOPE" \
        bash /mnt/d/ProtocolEmulator/model/ta02/run_imi.sh

run_must_be_red \
    "ta02/price_imi_gate.sh with IMITATOR removed" \
    env MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- env IMITATOR="$NOPE" \
        bash /mnt/d/ProtocolEmulator/model/ta02/price_imi_gate.sh

# --- pyRTA-backed gates (SPEC H1) ----------------------------------------
# ⛔⛔ THESE TWO WERE UNPRICEABLE UNTIL H1. `gate_pyrta.py`'s discovery function
# fell back to walking TEMP and ~ for a clone whenever PYRTA_SRC was not a
# directory, so setting PYRTA_SRC to a non-path did NOT remove the authority --
# the walk found the clone anyway and the gate went green. An arm here would
# have reported "GREEN with the tool removed" and the fix would have looked like
# weakening the arm. `pyrta_src.find_pyrta` now honours an explicit setting
# exactly, refusal included, which is what makes these two lines mean anything.
# ⚠ `pyrta_src.py` itself is deliberately NOT priced here. It manages PYRTA_SRC
#   internally to exercise both faces, so an outer setting cannot take the
#   authority away from it -- the attempt exits 0 and would be scored as a
#   failure of the wrong thing. Its must-fire faces are self-contained; run it
#   as an ordinary gate (`python model/a2/pyrta_src.py`), where it is red unless
#   BOTH the success and the refusal path have run.
run_must_be_red \
    "gate_pyrta.py with PYRTA_SRC removed" \
    env PYRTA_SRC="$NOPE" python model/a2/gate_pyrta.py

run_must_be_red \
    "gate_twin_pair.py with PYRTA_SRC removed" \
    env PYRTA_SRC="$NOPE" python model/a2/gate_twin_pair.py

run_must_be_red \
    "gate_rearm.py with PYRTA_SRC removed (Ruling 2's 6-lane check)" \
    env PYRTA_SRC="$NOPE" python model/a2/gate_rearm.py

# --- the A1 digest meta-check, priced by MUTATING THE ARTEFACT ------------
# ⛔ Not "remove a tool" like the arms above -- this one injects a gate that
# analyses a STALE hand-typed lane table, which is the defect A1 screens for,
# and requires the suite to go red. `run_a2.py --price` inverts its own verdict,
# so a ZERO exit here means the suite correctly went red.
echo "------------------------------------------------------------"
echo "  run_a2.py --price : a gate analysing a STALE lane table must take the run down"
if python model/a2/run_a2.py --price > /tmp/price_gate.out 2>&1; then
    echo "    RED detected by the meta-check (probe killed the run). PASS"
    PASS=$((PASS+1))
else
    echo "    *** the suite stayed GREEN with a stale lane table in it -- the"
    echo "        digest meta-check does not detect the defect it exists for. FAIL"
    sed -n '/META-CHECK/,$p' /tmp/price_gate.out | sed -n '1,20p' | sed 's/^/        | /'
    FAIL=$((FAIL+1))
    RC=1
fi

# --- TChecker-backed gate ------------------------------------------------
run_must_be_red \
    "ta02/run_zone_edge.sh with TCHECKER_BIN removed" \
    env MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- env TCHECKER_BIN="$NOPE" \
        bash /mnt/d/ProtocolEmulator/model/ta02/run_zone_edge.sh

echo "------------------------------------------------------------"
echo
echo "  gates priced: $((PASS+FAIL))   went red (good): ${PASS}   stayed green (bad): ${FAIL}"
if [ "$RC" = 0 ]; then
    echo "  PASS -- every gate's verdict depends on the foreign tool it names."
else
    echo "  *** FAIL -- ${FAIL} gate(s) are green without their authority."
    echo "      Those gates are not evidence of anything. Fix before quoting them."
fi
exit "$RC"
