"""SPEC A1 -- every gate prints a DIGEST of the lane table it consumed.

THE ONE CLAIM: if two gates in one run analysed different lane tables, the run
fails -- without anyone having to go looking for the copy.

⛔⛔ WHY A DIGEST AND NOT A CODE REVIEW. Two stale copies of the lane table
turned up in a single batch:
  * `gate_pyrta.py` carried a hand-typed second table, edited from memory
    whenever a deadline moved;
  * `periodic_equivalence()` hard-coded UART-rx as (n=10, t=434, T=4340) long
    after P1 re-synthesized the lane to (t=414, T=4140) -- and it PASSED, because
    `n*t == T` holds for both. A green check was certifying the gaplessness of a
    lane the project no longer ships, and that substitution is the thing the
    whole pyRTA comparison rests on.
Two in one batch is a class, not luck. Grepping for copies finds the ones that
exist; a digest catches the one that has not been written yet.

⭐⭐ AND THE OBVIOUS VERSION OF THIS CHECK WOULD NOT WORK. If each gate printed
the digest of the table it IMPORTED, then a gate that imports the table and then
analyses a hand-typed copy prints a matching digest while using the copy -- the
guard would pass BECAUSE of the defect it screens for. So there are two digests
per gate and the distinction is the whole mechanism:

    BASE  the shipped table as this module computes it, from `bursty`. Every
          gate in a run must report the same BASE, or the run failed.
    USED  the lane objects the gate actually handed to the analyser. A gate that
          claims to analyse the shipped table must report USED == BASE.

A hand-typed copy changes USED and leaves BASE alone, which is exactly the
signature the second field exists to expose. A gate that deliberately analyses a
VARIANT (a C sweep, a different SCL split, a constructed instance) declares that,
and then USED != BASE is the expected reading rather than a failure.

⛔ THE DIGEST COVERS EVERY FIELD THAT CHANGES A RESULT, including the two R2
added. Leaving `D_sched` out would let a gate schedule on a different key and
still match -- which is the same error in a new place.
"""

from __future__ import annotations

import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MARKER = "LANE-DIGEST"          # what `run_a2.py` greps for

# =========================================================================
# THE DIGEST LEDGER -- every bump, with its reason, newest LAST
# =========================================================================
# ⛔⛔ THIS EXISTS BECAUSE A DIGEST BUMP IS THE ONE CHANGE THAT INVALIDATES
# EVERY PUBLISHED NUMBER AT ONCE, and until now it was recorded only in prose
# across seven closeout documents. A bump that is merely described can be done
# twice, or done and not described, and the cross-check cannot tell: it only
# ever compares gates against EACH OTHER within one run, so a whole run can
# agree on a table nobody authorised.
#
# ⭐ `assert_current()` turns that into a check: the live shipped table must
# hash to the newest entry here. A bump therefore requires an explicit, reviewed
# line in this list -- and an UNINTENDED bump (a lane edited in passing, a
# second builder that drops a field) goes RED instead of propagating quietly.
# The second case is not hypothetical: `gate_lane_class.five_lanes` dropped `J`
# and reported the previous digest under the current table's name.
DIGEST_LEDGER = [
    ("8ea5756203e1",
     "the J = 0 table. Five lanes with R1's derived deadlines and R2's "
     "D_sched/D_tol split, every lane carrying J = 0. ⛔ RECORDED AS AN ERROR: "
     "the stated design point was always (C = 2, J_pipe = 1), so every r_i "
     "published against this digest was a J = 0 analysis matching NEITHER 1.3 "
     "candidate. r = {10, 7, 3, 9, 5}, min margin 14."),
    ("b4e51034e283",
     "THE J = 1 RE-BASELINE (Wilson's Ruling 1(b), after 78d8f40). Every lane "
     "now carries its DERIVED J: J_SHIPPED = j_of(d_min = 25) = 1 from the "
     "refill structure, with I2C at 1 + L_JIT = 2 for asynchronous capture. "
     "r = {11, 8, 5, 10, 6}, min margin 12, identical under our bound and "
     "pyRTA's on all five lanes. ⭐ This is the digest `frontier.py` had been "
     "declaring as its (C=2, J=1) VARIANT, so that gate now MATCHES -- the "
     "design point and the shipped table finally agree. The universal worst "
     "case over admissible programs (J = 8) is published ALONGSIDE this table, "
     "not inside it: J is a program property, and gate_j_program.py derives it "
     "from d_min."),
    # ⛔⛔ THE DIGEST IS UNCHANGED ON PURPOSE, AND THIS ENTRY IS STILL
    # REQUIRED. The SHIPPED lane table did not move: every lane still carries
    # its derived J (1, and 2 on I2C). What changed is a PUBLISHED CLAIM ABOUT
    # it -- the universal worst case over admissible programs, published as
    # J = 8, is RETRACTED as unsound.
    # ⚠ Live measurement exceeded the derivation at TEN admissible points
    # (d = 8..18). The cause: `j_of` capped the stall at L_CAP = 7, while the
    # witness chain gives (refills queued ahead + 1) x L_REFILL, up to
    # k x L_REFILL = 20. The cap sat below what the chain can produce.
    # ⭐ REPLACED BY A SCOPED CLAIM: d_min >= D* = k*L_REFILL = 20 -> J = 1,
    # live-measured 0 at d = 20,21,22,25,30,40,60 on 200k-cycle runs with
    # asserted windows. The shipped program (d_min = 25) is inside it.
    # ⛔ The `J_pipe = 8` lane-table VARIANT that gate_pyrta_jitter declared
    # for its arm 3 is withdrawn with it -- that subject no longer exists.
    # ⚠ NO replacement universal number is published: k*L_REFILL + 1 = 21
    # rests on an underived premise about the scan's arbitration order.
    # ⇒ Recorded against the unchanged digest because bumping a hash that
    # nothing hashed would be a fabricated provenance, and the ledger's job is
    # to say WHY a published number moved -- which this one did.
    ("b4e51034e283",
     "RETRACTION, table unchanged: universal J = 8 withdrawn as unsound "
     "(ten admissible points measured above the derivation; L_CAP = 7 capped "
     "a chain that reaches k*L_REFILL = 20). Replaced by the scoped claim "
     "d_min >= D* = 20 -> J = 1. The gate_pyrta_jitter J=8 variant is "
     "withdrawn with it. Shipped J = 1 unaffected and measured clean."),

    # ⛔⛔ C CORRECTED 2 -> 3 BY SATURATION MEASUREMENT (Wilson's ruling 1).
    ("65bc3c8114e5",
     "C = 3 ON EVERY LANE. `docs/PREREG_C_SAT.md` pre-registered the minimum "
     "inter-dispatch spacing at 2 and named 3 as the falsifier; "
     "`test/run_csat.py` measured 3 on four arms over 32,677 spacings in which "
     "a successor was ALREADY ELIGIBLE during the predecessor's writeback, and "
     "not one was 2. The dispatch FSM is a THREE-state cycle and ST_WB returns "
     "to ST_IDLE unconditionally, so the next dispatch decision waits a further "
     "cycle. The old figure, `svc_cycles/svc_jobs` = 688/344 = 2.00, counted "
     "cycles with `st != ST_IDLE` -- the engine's OCCUPANCY per job, not the "
     "SPACING between the jobs it can deliver. Occupancy 2 and spacing 3 are "
     "both exact; the error was using one for the other, and it survived "
     "because a structural derivation and a simulation mean AGREED -- both "
     "about occupancy. "
     "⛔ TWO FIELDS MOVED, NOT ONE: SPI-target's `D_tol` is DERIVED by "
     "`abs_tolerance(25, completion, C)`, which SUBTRACTS C, so it re-derives "
     "18 -> 17. A deadline carries C too. "
     "r = {16, 12, 7, 15, 9}, min margin 12 -> 11, IDENTICAL under our bound "
     "and pyRTA on all five lanes. "
     "⭐ THE EDF ORDER IS UNCHANGED (I2C < SPI-target < SPI-tx < UART-rx < "
     "UART-tx) and I2C stays the tightest lane, which is what makes this a "
     "re-quote rather than a reschedule -- spec R2 split D_sched from D_tol "
     "precisely because a tolerance correction had silently reordered the set "
     "once. Nothing shipped becomes infeasible: the bar is 4 and the minimum "
     "is 11."),
    ("b9a51e13a772",
     "SPI-TARGET: ONE EVENT PER BIT, NOT PER EDGE (Wilson 10-18 ruling 3, "
     "built 10-20). The lane was modelled as n = 16 events per byte at t = 25 "
     "-- an event on every SCK edge. The program that ships "
     "(`pe_proto.SPITarget`, MISO out) answers one change-edge per bit, so "
     "its demand is n = 8 at t = 50, the master's claimed maximum clock "
     "(T_ext, 1 MHz); T 400 and D_tol 17 unchanged (the half-period is still "
     "25). PREDICTED BEFORE THE CHANGE, ours and pinned pyRTA "
     "(probe_reports/spi_target_b2_prediction.txt): "
     "r = {16, 12, 7, 15, 9}, min margin 11 -- EVERY r UNCHANGED, U "
     "0.32083 -> 0.26083. A re-quote of the burst shape, not a reschedule: "
     "the EDF order and every published response stand; the bar is 4 and "
     "the minimum is 11."),
    ("5cf5d9412aea",
     "UART-RX AT THE VERIFIED BACK-TO-BACK FLOOR, 421 NOT 414 (B3b Finding 1, "
     "Wilson 10-20). The admitted peer band was the single-frame sampling-"
     "phase band [414, 458]; B3b measured a 414 peer failing every frame after "
     "the first, back-to-back (the ARM re-arms after the next start edge). "
     "UART_BAND -> [421, 447] = run_uartrx's verified 434 * (1 +- 0.030), and "
     "the lane moves to its fastest admitted peer: t 414 -> 421, T 4140 -> "
     "4210. PREDICTED BEFORE THE CHANGE (probe_reports/"
     "uart_band_f1_prediction.txt): every r unchanged -- pinned pyRTA r = "
     "{16, 12, 7, 15, 9}, min margin 11, measured after. A slower fastest "
     "peer can only lower interference; the EDF order and every published "
     "response stand; the bar is 4 and the minimum is 11."),
]

#: ⛔⛔ RULING A9 -- THE ANALYSIS LEDGER. `DIGEST_LEDGER` records why the
#: LANE TABLE moved, keyed by its digest, and `assert_current` requires the live
#: table to hash to its newest entry. An ANALYSIS of an unchanged table can
#: move too, and that is a different record: it names the digest it analyses
#: (which must be the current one -- `selftest` checks it), what changed in the
#: analysis, and the numbers before and after. Immutable, like its sibling.
#: (digest analysed, change id, text, {"ours_r": [...], "ours_margin": n})
ANALYSIS_LEDGER = [
    ("65bc3c8114e5", "Z-spuri-candidates",
     "RULING Z: our recurrence (`bursty.response_time_b`) searched only the "
     "subject's own release offsets; Spuri's EDF candidate set also needs "
     "every interferer's deadline step. The old search fell BELOW TChecker's "
     "exact worst case on 7 of 8 queue-depth-one instances and below the full "
     "set on 184 of 6,601 with no jitter. Fixed (Spuri step set). PUBLISHED "
     "(pyRTA) numbers UNCHANGED: shipped r = {16, 12, 7, 15, 9}, min margin "
     "11. OURS moved: r = {16, 12, 9, 16, 9}, min margin 9 -- PESSIMISTIC, "
     "not a disagreement: TChecker on the scaled I2C / UART-rx shapes "
     "(ruling Z4, all tie rules) gives truth = pyRTA, so ours is 2 / 1 "
     "cycles high there. Ours is now the asserted cross-check (>= pyRTA) and "
     "CI's pyRTA-free floor; every published number reads pyRTA (ruling A).",
     {"ours_r": [16, 12, 9, 16, 9], "ours_margin": 9}),
    ("b9a51e13a772", "SPI-target-one-event-per-bit",
     "The same analysis on the re-quoted table (SPI-target n 8, t 50). OURS "
     "unchanged lane for lane: r = {16, 12, 9, 16, 9}, min margin 9; pyRTA "
     "unchanged: {16, 12, 7, 15, 9}, min margin 11. Computed before the "
     "change (probe_reports/spi_target_b2_prediction.txt).",
     {"ours_r": [16, 12, 9, 16, 9], "ours_margin": 9}),
    ("5cf5d9412aea", "UART-rx-verified-band",
     "The same analysis on the re-quoted table (UART-rx t 421, T 4210). OURS "
     "unchanged lane for lane: r = {16, 12, 9, 16, 9}, min margin 9; pyRTA "
     "unchanged: {16, 12, 7, 15, 9}, min margin 11 "
     "(probe_reports/uart_band_f1_prediction.txt).",
     {"ours_r": [16, 12, 9, 16, 9], "ours_margin": 9}),
]

#: ⛔⛔ P6 -- THE pyRTA THESE NUMBERS ARE WITNESSED BY, recorded beside the
#: digest they were re-derived for. Until P6 the primary foreign authority for
#: every timing claim was picked up from a scratch-directory clone with NO
#: recorded commit, so the ledger could say WHY a number moved but not WHICH
#: witness had certified it.
#: ⭐ WHAT IS CLAIMED, PRECISELY: at this commit, `gate_pyrta` reproduces
#: entry `65bc3c8114e5`'s quoted responses EXACTLY on all five lanes --
#: r = {UART-tx 16, SPI-tx 12, I2C 7, UART-rx 15, SPI-target 9}, matching our
#: own bound lane for lane. ⚠ It is a REPRODUCTION. Which clone produced the
#: entry the first time was never written down -- that gap is the finding --
#: so this records the witness that stands behind the number NOW, not an
#: archaeology of the one that stood behind it then.
#: ⛔ ONE HASH, TWO PLACES, CHECKED EQUAL: the enforced pin lives in
#: `pyrta_src.PINNED_COMMIT`; `selftest()` below fails if this record and
#: that pin ever disagree, so the ledger cannot describe a witness the gates no
#: longer accept.
PYRTA_PIN = {
    "commit": "1f3a649ced61709620857ec28653b51a0c6ce28d",
    "repo": "https://github.com/PROSA-Project/pyRTA",
    "date": "2026-06-16",
    "digest": "5cf5d9412aea",
    "reproduces": {"UART-tx": 16, "SPI-tx": 12, "I2C": 7, "UART-rx": 15,
                   "SPI-target": 9},
}


def assert_current(verbose: bool = True) -> bool:
    """The live shipped table must hash to the newest ledger entry."""
    want, why = DIGEST_LEDGER[-1]
    got = base_digest()
    ok = (got == want)
    if verbose:
        if ok:
            print("  %s LEDGER ok: shipped table is %s (entry %d of %d)"
                  % (MARKER, got, len(DIGEST_LEDGER), len(DIGEST_LEDGER)))
        else:
            known = dict(DIGEST_LEDGER)
            print("  %s *** LEDGER MISMATCH: shipped table hashes to %s, the "
                  "newest ledger entry is %s ***" % (MARKER, got, want))
            if got in known:
                print("      %s is an OLDER ledger entry -- the table has been "
                      "reverted, or a second builder is dropping a field."
                      % got)
            else:
                print("      %s is in NO ledger entry: this is an "
                      "UNAUTHORISED bump. Either add a reviewed line to "
                      "DIGEST_LEDGER saying what changed and why, or revert "
                      "the edit that moved the table." % got)
    return ok


def _fields(lane) -> tuple:
    """Every field that can change a response time. Order is part of the hash.

    ⛔ `D_sched` and `D_tol` are BOTH here. They are different objects (spec R2)
    and a gate that confused them would otherwise digest identically.
    """
    return (lane.name,
            int(lane.T), int(lane.C),
            int(getattr(lane, "n", 1)),
            int(getattr(lane, "t", lane.T)),
            int(getattr(lane, "J", 0)),
            int(lane.D_tol), int(lane.D_sched), int(lane.D))


def digest(lanes) -> str:
    """A short, stable hash of a lane set. Order-insensitive by construction."""
    h = hashlib.sha256()
    for f in sorted(_fields(l) for l in lanes):
        h.update(repr(f).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


def shipped():
    """THE shipped five-lane table, from the one place it is defined."""
    from bursty import TX, SPI_RX, UART_RX
    return list(TX) + [UART_RX, SPI_RX]


def base_digest() -> str:
    return digest(shipped())


def announce(gate: str, used=None, variant: str | None = None) -> str:
    """Print this gate's BASE and USED digests. Returns the USED digest.

    `used`    the lane objects actually analysed. None means "this gate does not
              analyse the shipped table at all" (e.g. constructed instances), and
              that is recorded rather than silently skipped.
    `variant` a one-line reason USED is expected to differ from BASE. A gate that
              analyses a variant without declaring one is a finding.
    """
    b = base_digest()
    if used is None:
        print("  %s base=%s used=NONE  (%s analyses no shipped lane: %s)"
              % (MARKER, b, gate, variant or "*** UNDECLARED ***"))
        return "NONE"
    u = digest(used)
    if u == b:
        print("  %s base=%s used=%s  MATCH  (%s)" % (MARKER, b, u, gate))
    else:
        print("  %s base=%s used=%s  VARIANT  (%s: %s)"
              % (MARKER, b, u, gate, variant or "*** UNDECLARED VARIANT ***"))
    return u


# ============================================================================
def selftest() -> int:
    """⛔ A digest that has never been seen to DIFFER is not a check.

    ⭐ Also runs `assert_current()`: the ledger has to agree with the live
    table, or the suite is cross-checking gates against each other on a table
    nobody authorised.

    Both faces, plus the one that matters most: a single-field change in the
    field most recently added to the model must move the hash. R2's `D_sched`
    went in last and is the one a future edit is most likely to forget.
    """
    from bursty import BLane
    # ⛔ P6: the ledger's recorded witness must BE the pin the gates enforce.
    from pyrta_src import PINNED_COMMIT
    if PYRTA_PIN["commit"] != PINNED_COMMIT:
        print("  *** FAIL lane_digest.PYRTA_PIN records pyRTA %s but the gates"
              % PYRTA_PIN["commit"][:12])
        print("      enforce %s -- the ledger names a witness the gates refuse."
              % PINNED_COMMIT[:12])
        return 1
    print("  pyRTA pin recorded beside %s: %s -- matches the enforced pin"
          % (PYRTA_PIN["digest"], PYRTA_PIN["commit"][:12]))
    # ⛔ A9: the newest analysis entry must analyse the CURRENT table, and its
    # recorded `ours` must be what our recurrence says today (LIVE).
    a_dig, a_id, _t, a_num = ANALYSIS_LEDGER[-1]
    if a_dig != DIGEST_LEDGER[-1][0]:
        print("  *** FAIL ANALYSIS_LEDGER's newest entry (%s) analyses %s, but "
              "the current table is %s" % (a_id, a_dig, DIGEST_LEDGER[-1][0]))
        return 1
    from bursty import response_time_b as _rtb
    _ls = shipped()
    live = [_rtb(l, _ls)["r"] for l in _ls]
    live_m = min(l.margin(r) for l, r in zip(_ls, live))
    if live != a_num["ours_r"] or live_m != a_num["ours_margin"]:
        print("  *** FAIL ANALYSIS_LEDGER %s records ours r = %s (margin %d); "
              "our recurrence now gives %s (margin %d)"
              % (a_id, a_num["ours_r"], a_num["ours_margin"], live, live_m))
        return 1
    print("  analysis ledger: %s on %s -- ours r = %s, min margin %d, live"
          % (a_id, a_dig, live, live_m))
    print()
    print("=" * 78)
    print("SPEC A1 -- the lane-table digest, both faces")
    print("=" * 78)
    rc = 0
    ship = shipped()
    b = digest(ship)
    print("  shipped base digest: %s  (%d lanes)" % (b, len(ship)))

    # face 1: the same table, rebuilt independently, must digest the same
    same = [BLane(l.name, l.T, l.C, n=l.n, t=l.t, J=l.J,
                  D_tol=l.D_tol, D_sched=l.D_sched) for l in ship]
    print("  face 1  an independent rebuild of the same values -> %s  %s"
          % (digest(same), "MATCH" if digest(same) == b else "*** DIFFERS ***"))
    if digest(same) != b:
        rc = 1

    # face 2: order must not matter -- gates assemble the set in their own order
    print("  face 2  the same set, reversed -> %s  %s"
          % (digest(list(reversed(ship))),
             "MATCH" if digest(list(reversed(ship))) == b else "*** DIFFERS ***"))
    if digest(list(reversed(ship))) != b:
        rc = 1

    # face 3: THE MUST-FIRE -- one field at a time, each must move the hash
    print("  face 3  must-fire: a single-field change must CHANGE the digest")
    moves = []
    for field, kw in (("T", {"T": ship[1].T + 1}),
                      ("C", {"C": ship[1].C + 1}),
                      ("n/t", {"n": 2, "t": ship[1].T // 2}),
                      ("J", {"J": ship[1].J + 1}),
                      ("D_tol", {"D_tol": ship[1].D_tol + 1}),
                      ("D_sched", {"D_sched": ship[1].D_sched - 1})):
        args = dict(name=ship[1].name, T=ship[1].T, C=ship[1].C,
                    n=ship[1].n, t=ship[1].t, J=ship[1].J,
                    D_tol=ship[1].D_tol, D_sched=ship[1].D_sched)
        args.update(kw)
        mut = [BLane(args["name"], args["T"], args["C"], n=args["n"],
                     t=args["t"], J=args["J"], D_tol=args["D_tol"],
                     D_sched=args["D_sched"])] + ship[2:] + [ship[0]]
        d = digest(mut)
        ok = d != b
        moves.append((field, ok))
        print("      %-8s -> %s  %s" % (field, d, "moved" if ok else "*** UNCHANGED ***"))
        if not ok:
            rc = 1
    dead = [f for f, ok in moves if not ok]
    if dead:
        # ⛔ this branch had a %s with no argument: it would have raised
        # TypeError at the exact moment it was trying to report a failure.
        # A reporting path that only runs on failure is a path nothing exercises.
        print("      *** FAIL: %s do not enter the digest, so a gate could"
              % ", ".join(dead))
        print("          analyse a different value and still match. ***")
    else:
        print("      => every result-changing field is inside the hash")

    # ---- the ledger: the live table must be the authorised one ----------
    print()
    print("  --- digest ledger (%d entries, newest last) ---"
          % len(DIGEST_LEDGER))
    for i, (d, why) in enumerate(DIGEST_LEDGER):
        print("    %d. %s%s" % (i + 1, d, "  <- CURRENT"
                                if i == len(DIGEST_LEDGER) - 1 else ""))
        for line in _wrap(why, 68):
            print("       %s" % line)
    if not assert_current():
        rc = 1

    print()
    print("  GATE A1-selftest: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


def _wrap(text: str, width: int) -> list:
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    if cur:
        out.append(cur)
    return out


if __name__ == "__main__":
    raise SystemExit(selftest())
