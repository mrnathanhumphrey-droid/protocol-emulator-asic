"""ONE jitter instance list, and the foreign verdicts recorded against it.

THE ONE CLAIM: the three witnesses for the jitter extension -- our recurrence,
TChecker, and pyRTA -- are judged on the SAME instances, and a change to any of
them shows up as a disagreement instead of as a new table.

⛔⛔ WHY THIS IS A FILE AND NOT A LIST IN EACH RUNNER. `gate_pyrta.py` already
carries the scar: it held a hand-typed second copy of the shipped answers, and
the only reason a stale literal is detectable there is that arm 0 compares the
two every run. Three witnesses on three private instance lists is the same
hazard cubed -- each could be green on a set the others never saw, and the
"three independent confirmations" would be three unrelated runs.

⭐ THE TCHECKER NUMBERS ARE RECORDED HERE, NOT RE-DERIVED. `run_jitter.py` needs
WSL and ~40k states per instance; a gate that must shell into a VM to have an
opinion is a gate that gets skipped. So the foreign verdicts are written down
with the run that produced them, and `run_jitter.py` CHECKS the live result
against this record. A recorded number that no longer matches its source is the
exact failure this project calls "a summary value is not evidence until checked
against its run", so the check runs in the direction that catches it.

⛔ TUPLE SHAPE is `gen_edf.gen`'s: (name, T, C, D, n, t, J). `n`/`t` are the
burst parameters and are pinned at (1, T) throughout -- the generator REFUSES
bursty-with-jitter, so every instance here is periodic, and the reactive
m_i > 1 lanes are NOT covered by any of this.
"""

from __future__ import annotations

# ============================================================================
# THE INSTANCES
# ============================================================================
# ⛔ CHOSEN FOR WHAT THEY STRESS, NOT FOR BEING SMALL:
#   J1  the must-fire shape: subject J=0, interferer carries ALL the jitter, so
#       any movement in the subject's r is attributable to the interference term
#       alone and cannot leak in through the subject's own `+ J_i`
#   J2  jitter on the MORE URGENT lane -- the only one whose interference counts
#       under EDF, so the inflated arrival count has somewhere to bite
#   J3  jitter on BOTH lanes -- where a double-count would show up
#   J4  N=3, distinct C and distinct D, jitter on the middle lane
#   J5  J large against T (3 vs 5): releases can close to T-J=2, the BUNCHING
#       regime the inflated count exists to bound
JINSTANCES = [
    ("J1  must-fire shape",
     [("subject", 8, 2, 4, 1, 8, 0), ("jittery", 7, 2, 5, 1, 7, 1)]),
    ("J2  jitter on the urgent lane",
     [("relaxed", 9, 2, 8, 1, 9, 0), ("urgent", 6, 2, 3, 1, 6, 2)]),
    ("J3  jitter on both",
     [("A", 9, 2, 6, 1, 9, 2), ("B", 7, 2, 5, 1, 7, 1)]),
    ("J4  N=3 distinct C and D",
     [("A", 11, 2, 7, 1, 11, 0), ("B", 8, 1, 4, 1, 8, 2),
      ("C", 13, 3, 11, 1, 13, 0)]),
    ("J5  bunching: J=3 against T=5",
     [("slow", 14, 2, 10, 1, 14, 0), ("bunchy", 5, 1, 4, 1, 5, 3)]),
]

MUSTFIRE = JINSTANCES[0][1]

# ============================================================================
# THE RECORDED FOREIGN VERDICTS
# ============================================================================
# Produced by: python model/a2/zone/run_jitter.py
# TChecker at /opt/ta/tchecker/bin (WSL Ubuntu), tck-reach -a reach, discrete
# time, release delay nondeterministic in [0, J] re-rolled at every nominal
# release. 11 of 11 lane-instances judged, `ovr` unreachable on all of them.
#
# (instance_prefix, lane) -> {"tck": true worst case, "old": the pre-fix
#                             nominal-curve sum, "ours": the fixed recurrence}
#
# ⭐ THE `old` COLUMN IS THE EVIDENCE THE FIX NEEDED, and it is kept because a
# fix with no failing case is a fix on no evidence. On J1/subject and J3/B the
# old sum sits BELOW the true worst case -- not conservative, WRONG.
TCHECKER_RECORDED = {
    ("J1", "subject"): {"tck": 4, "old": 3, "ours": 5},
    ("J1", "jittery"): {"tck": 5, "old": 5, "ours": 5},
    ("J2", "relaxed"): {"tck": 4, "old": 4, "ours": 4},
    ("J2", "urgent"):  {"tck": 5, "old": 5, "ours": 5},
    ("J3", "A"):       {"tck": 6, "old": 6, "ours": 6},
    ("J3", "B"):       {"tck": 5, "old": 4, "ours": 6},
    ("J4", "A"):       {"tck": 5, "old": 5, "ours": 5},
    ("J4", "B"):       {"tck": 5, "old": 5, "ours": 5},
    ("J4", "C"):       {"tck": 6, "old": 6, "ours": 6},
    ("J5", "slow"):    {"tck": 3, "old": 3, "ours": 3},
    ("J5", "bunchy"):  {"tck": 5, "old": 5, "ours": 5},
}

# The two lane-instances where our bound is STRICTLY above the true worst case.
# ⚠ NAMED, not averaged: both gaps are +1 and both are on a lane INTERFERED
# WITH by a jittery lane, never on the jittery lane itself -- the inflated
# arrival count rounding a partial period up to a whole job. Spuri's recurrence
# is an upper bound and this is what that costs.
PESSIMISTIC = [("J1", "subject", 1), ("J3", "B", 1)]


# ============================================================================
# pyRTA ON THE SHIPPED FIVE LANES -- the bound comparison at J > 0
# ============================================================================
# Produced by: PYRTA_SRC=<clone>/src python model/a2/gate_pyrta_jitter.py (arm 3)
# Bursty lanes encoded as ArrivalCurvePrefix built from `BLane.N_J` and verified
# pointwise against it; per-subject deadline shift with the subject's own delay
# swept over [0, J_k] and the maximum taken.
#
# ⛔⛔ THESE ARE RECORDED BECAUSE `gate_j_sound.py` MUST NOT NEED pyRTA. That
# gate carries the margin verdict, and a verdict gate that goes red when a
# third-party clone is absent is a verdict nobody can reproduce. `price_gates.sh`
# removes pyRTA to prove the pyRTA gates are real; the margin sweep has to
# survive that.
#
# ⭐ THE COLUMN THAT MATTERS IS THE LAST ONE. At J_pipe = 2 the two bounds are
# IDENTICAL on all five lanes. The disagreement is entirely a large-J effect,
# which is why reducing J removes the ambiguity rather than merely improving a
# number.
# J_pipe -> {lane: (ours, pyrta)}
PYRTA_SHIPPED = {
    2: {"UART-tx 115200": (12, 12), "SPI-tx 1 MHz": (9, 9),
        "I2C 400 kHz": (6, 6), "UART-rx 115200": (11, 11),
        "SPI-target 1 MHz": (7, 7)},
    7: {"UART-tx 115200": (17, 17), "SPI-tx 1 MHz": (14, 14),
        "I2C 400 kHz": (13, 11), "UART-rx 115200": (18, 16),
        "SPI-target 1 MHz": (14, 12)},
    8: {"UART-tx 115200": (18, 18), "SPI-tx 1 MHz": (15, 15),
        "I2C 400 kHz": (16, 12), "UART-rx 115200": (19, 17),
        "SPI-target 1 MHz": (15, 13)},
}


def key_of(instance_label: str) -> str:
    """'J3  jitter on both' -> 'J3'."""
    return instance_label.split()[0]


def recorded(instance_label: str, lane: str) -> dict | None:
    return TCHECKER_RECORDED.get((key_of(instance_label), lane))


def selftest() -> int:
    """The record must COVER the instances, exactly -- no orphans either way.

    ⛔ An entry for a lane that no longer exists, or a lane with no entry, both
    read as "fine" to any consumer that iterates one side only.
    """
    want = {(key_of(lbl), l[0]) for lbl, lanes in JINSTANCES for l in lanes}
    have = set(TCHECKER_RECORDED)
    missing, orphan = want - have, have - want
    print("jitter_instances selftest")
    print("  instances: %d   lane-instances: %d   recorded: %d"
          % (len(JINSTANCES), len(want), len(have)))
    print("  lanes with no record: %s" % (sorted(missing) or "none"))
    print("  records with no lane: %s" % (sorted(orphan) or "none"))
    bad_dir = [(k, v) for k, v in TCHECKER_RECORDED.items()
               if v["ours"] < v["tck"]]
    print("  records where ours < TChecker (UNSOUND): %s" % (bad_dir or "none"))
    pess = [(k[0], k[1], v["ours"] - v["tck"])
            for k, v in TCHECKER_RECORDED.items() if v["ours"] > v["tck"]]
    ok_p = sorted(pess) == sorted(PESSIMISTIC)
    print("  PESSIMISTIC list matches the records: %s" % ("yes" if ok_p else
                                                          "NO -- %s" % (pess,)))
    ok = not missing and not orphan and not bad_dir and ok_p
    print("  => %s" % ("PASS" if ok else "*** FAIL ***"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
