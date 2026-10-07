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
# RULINGS Y-R AND Z -- the cases that retracted a claim and found a bug
# ============================================================================
# Produced by: python model/a2/zone/run_z.py (TChecker, same build and flags as
# above; `ovr` unreachable on every instance below -- the gate re-checks that
# field, because an instance where a job can be pending at its successor's
# release is one the exact model does not adjudicate).
# Tuple shape is `gen_edf.gen`'s (name, T, C, D, n, t, J); list order is lane
# index, which is the hardware's tie-break priority.
#
# ⛔⛔ Z_INSTANCES -- OUR RECURRENCE WAS BELOW THE TRUTH. `response_time_b`
# searched only the subject's own release offsets; Spuri's candidate set also
# holds every interferer's deadline step. Found by a random search for the
# ckdense signature, filtered to queue-depth-one, adjudicated here.
# "old" is the subject-releases-only search, kept to show it failing.
Z_INSTANCES = [
    ("Z1", 2, [("l0", 9, 3, 7, 1, 9, 0), ("l1", 11, 3, 7, 1, 11, 0),
               ("l2", 9, 1, 6, 1, 9, 1)]),
    ("Z2", 2, [("l0", 11, 3, 6, 1, 11, 2), ("l1", 11, 3, 9, 1, 11, 0),
               ("l2", 9, 1, 3, 1, 9, 0)]),
    ("Z3", 2, [("l0", 11, 2, 9, 1, 11, 1), ("l1", 6, 2, 4, 1, 6, 1),
               ("l2", 6, 1, 2, 1, 6, 0)]),
    ("Z4", 2, [("l0", 11, 3, 10, 1, 11, 0), ("l1", 9, 2, 7, 1, 9, 2),
               ("l2", 6, 1, 4, 1, 6, 0)]),
    ("Z5", 1, [("l0", 6, 2, 4, 1, 6, 1), ("l1", 13, 1, 8, 1, 13, 1),
               ("l2", 8, 3, 6, 1, 8, 0)]),
    ("Z6", 0, [("l0", 6, 2, 3, 1, 6, 0), ("l1", 9, 1, 4, 1, 9, 0),
               ("l2", 12, 1, 6, 1, 12, 2)]),
    ("Z7", 1, [("l0", 13, 1, 8, 1, 13, 4), ("l1", 8, 1, 3, 1, 8, 0),
               ("l2", 9, 1, 7, 1, 9, 3)]),
    ("Z8", 0, [("l0", 11, 1, 5, 1, 11, 0), ("l1", 13, 2, 11, 1, 13, 3),
               ("l2", 6, 3, 6, 1, 6, 0)]),
]
Z_RECORDED = {"Z1": {"tck": 6, "old": 4}, "Z2": {"tck": 5, "old": 3},
              "Z3": {"tck": 3, "old": 2}, "Z4": {"tck": 4, "old": 3},
              "Z5": {"tck": 7, "old": 7}, "Z6": {"tck": 3, "old": 2},
              "Z7": {"tck": 2, "old": 1}, "Z8": {"tck": 4, "old": 3}}

# ⛔⛔ LJ_INSTANCES -- RULING Y's PREMISE, RETRACTED. "pyRTA's D - J framing
# double-counts jitter" was asserted without a witness. At large J (about half
# the period, W1's regime) TChecker says the D - J framing is EXACT on all 7
# lanes and the "charge once" framing (interferer deadline D) is BELOW the
# truth on 5 of 7 -- unsound. (instance, subject index) -> truth.
LJ_INSTANCES = [
    ("L1", [("subj", 10, 2, 8, 1, 10, 0), ("jit", 9, 2, 6, 1, 9, 4)]),
    ("L2", [("subj", 10, 2, 9, 1, 10, 1), ("jit", 10, 2, 9, 1, 10, 5)]),
    ("L3", [("A", 9, 2, 8, 1, 9, 4), ("B", 10, 2, 9, 1, 10, 4)]),
    ("L4", [("A", 10, 2, 9, 1, 10, 0), ("B", 11, 2, 9, 1, 11, 5),
            ("C", 12, 2, 10, 1, 12, 5)]),
]
LJ_RECORDED = {("L1", 0): 4, ("L2", 0): 5, ("L2", 1): 8, ("L3", 0): 7,
               ("L3", 1): 8, ("L4", 0): 6, ("L4", 1): 9, ("L4", 2): 10}
#: the charge-once framing's answers on the same lanes (pyRTA @ the pin) --
#: below the truth on L2/0, L3/1, L4/0, L4/1, L4/2. L1/1 is not a subject
#: (it carries all the jitter; J1's must-fire shape).
LJ_CHARGE_ONCE = {("L1", 0): 4, ("L2", 0): 4, ("L2", 1): 8, ("L3", 0): 7,
                  ("L3", 1): 7, ("L4", 0): 5, ("L4", 1): 8, ("L4", 2): 8}

# ⭐ TIE_INSTANCES -- RULING Z4. The shipped I2C / UART-rx shapes, scaled to
# what TChecker can solve, each in both index orders. Truth is the same under
# NONDETERMINISTIC ties and the hardware's LOWEST-INDEX rule, so the published
# I2C 7 / UART-rx 15 stand and our widened recurrence (9 / 7 here) is
# pessimistic there, not a sign that pyRTA misses the hardware's tie rule.
TIE_INSTANCES = [
    ("T-I2C", 1, [("blk", 60, 3, 40, 1, 60, 1), ("i2c", 30, 3, 18, 1, 30, 2),
                  ("tie", 30, 3, 20, 1, 30, 1)]),
    ("T-I2C-mirror", 2, [("blk", 60, 3, 40, 1, 60, 1),
                         ("tie", 30, 3, 20, 1, 30, 1),
                         ("i2c", 30, 3, 18, 1, 30, 2)]),
    ("T-URX", 1, [("tie", 40, 3, 19, 1, 40, 1), ("urx", 40, 3, 16, 1, 40, 1),
                  ("blk", 60, 3, 50, 1, 60, 1)]),
    ("T-URX-mirror", 0, [("urx", 40, 3, 16, 1, 40, 1),
                         ("tie", 40, 3, 19, 1, 40, 1),
                         ("blk", 60, 3, 50, 1, 60, 1)]),
]
TIE_RECORDED = {"T-I2C": {"nondet": 7, "index": 7},
                "T-I2C-mirror": {"nondet": 7, "index": 7},
                "T-URX": {"nondet": 6, "index": 6},
                "T-URX-mirror": {"nondet": 6, "index": 6}}


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
