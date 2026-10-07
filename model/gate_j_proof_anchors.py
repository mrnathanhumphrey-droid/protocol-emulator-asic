"""THE J=9 PROOF'S PREMISES MUST STILL BE TRUE OF THE RTL.

`docs/J_LANE_PROOF.md` proves two theorems from seven premises, each cited to
`src/pe_engine.v`. A proof whose premises have quietly stopped holding is worse
than no proof: it reads as settled and is not.

⛔⛔ WHY LINE NUMBERS ARE NOT THE ANCHOR. The citations moved twice while the
document was being written -- once because the `SPL` parameter was added above
them, once because a comment grew -- and one of them (P7) pointed at the
edge-capture block by the time it was committed. A line number is a fact about
the file's layout, not about the design. So each premise is anchored to a
SUBSTRING THAT MUST BE PRESENT, the way `gate_ruling_audit.py` anchors a ruling,
and the line number in the document is documentation only.

⭐ AND THE PREMISES ARE THE INTERESTING HALF. Theorem 1 (`sum_L <= 9`) holds
only while the port serves the winner's head FIRST (P3) and a refill is
non-preemptible (P2). Delete the winner-first branch and the bound is false
while every test still passes -- the engine would be slower, not wrong.
"""

from __future__ import annotations

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RTL = os.path.join(ROOT, "src", "pe_engine.v")
PROOF = os.path.join(ROOT, "docs", "J_LANE_PROOF.md")

# (premise, what it asserts, a substring of the RTL that must be present)
PREMISES = [
    ("P1", "one prefetch FSM / one refill in flight engine-wide",
     "localparam [2:0] P_SCAN = 3'd0, P_REQ = 3'd1, P_WAIT = 3'd2, P_CAP = 3'd3;"),
    ("P2a", "the refill walk is 4 states, unconditional once started",
     "P_WAIT: pst <= P_CAP;"),
    ("P2b", "and the request state is registered before the read",
     "P_REQ:  pst <= P_WAIT;"),
    ("P3", "WINNER-FIRST: the port serves the winner's invalid head first",
     "if (winner_v && !l_actv[hix[winner]]) begin"),
    ("P4", "spare fills are strictly lower priority (the else-if)",
     "end else if (l_live[pl] && want_fetch(pl)) begin"),
    ("P5", "dispatch is gated only on the head slot being valid",
     "if (l_actv[hix[winner]]) begin"),
    ("P6a", "writeback INVALIDATES the consumed head",
     "l_actv[hix[cur]] <= 1'b0;"),
    ("P6b", "and flips the select, so the prefetched spare becomes the head",
     "if (SPL > 1) l_sel[cur] <= !l_sel[cur];"),
    ("P7", "the EDF select is combinational over REGISTERED keys",
     "reg [LW-1:0]   winner;"),
    # ⭐ The stall counter is what `sum_L` reconstructs, so it is part of the
    # proof's subject matter, not just of the measurement.
    ("S", "the stall branch the winner-blocked bound is about",
     "jitter_cnt <= jitter_cnt + 1'b1;"),
    # ---- Theorem 3 (D*), now the load-bearing claim --------------------
    # ⛔⛔ P8 IS THE ONE THAT CARRIES THE PUBLISHED GUARANTEE. If the
    # timestamp advance ever became RELATIVE (from completion rather than
    # from the previous timestamp) a lane's period would be d + r instead of
    # d, the refill demand per period would change, and D* = k*L_REFILL
    # would no longer be the right threshold. The RTL comment at that line
    # says the relative form drifts k*(r-C); the theorem needs the absolute
    # form for a different reason, and both want the same line.
    ("P8", "a lane's period is exactly d -- ABSOLUTE timestamp advance",
     "l_timestamp[cur] <= l_timestamp[cur] + {{(TS_W-DLY_W){1'b0}}, a_dly};"),
    # ⛔⛔ RULING W SPLIT READINESS IN TWO. `rel_due` is still "the timestamp
    # has arrived" (P9, re-anchored); `ready` adds W1's own-hold gate (P9w).
    # P9w is release jitter on a lane that loads the SDA hold, bounded by
    # `program_a2.w1_jitter` and ZERO whenever T_i >= HS + 1 + (r_i - C).
    # ⚠ SCOPE FOR THEOREM 3: on a CLOCKED lane the delayed job is the HIGH and
    # the next job is rebased from the observed rise, so W1 cannot bunch two
    # dispatches inside d. On an UNCLOCKED frame the job after a delayed SCL
    # rise is timed absolutely, so it can -- by up to J_w1. W7's mode floor
    # refuses the short frames where J_w1 > 0 alone; under heavy contention
    # it is the D* sweep's job to measure (SPEC §25).
    ("P9", "readiness is that timestamp arriving (`rel_due`)",
     "assign rel_due[gi] = l_live[gi] & ~diff[TS_W-1]"),
    ("P9w", "W1: ready also waits for the lane's own hold + setup",
     "assign ready[gi] = rel_due[gi] & (l_hcnt[gi] == {HOLDW{1'b0}});"),
]

# the two bounds the document states -- if either number changes in the RTL's
# parameters, the document is stale
L_REFILL, N_LANES, J_WINNER_REG = 4, 5, 1
BOUND_T1 = 2 * L_REFILL + J_WINNER_REG          # 9
BOUND_T2 = N_LANES * L_REFILL + J_WINNER_REG    # 21


def check():
    bad = []
    with open(RTL, encoding="utf-8", errors="replace") as fh:
        rtl = fh.read()
    for tag, what, needle in PREMISES:
        if needle not in rtl:
            bad.append((tag, what, needle))
    return bad, rtl


def selftest(rtl):
    """⛔ PRICE IT: a bogus needle must be rejected and a real one accepted,
    or this gate cannot tell a missing premise from a present one."""
    rc = 0
    print("  --- must-fire: the anchors are checked, not assumed ---")
    bogus = "if (winner_v && NO_SUCH_SIGNAL_xyz) begin"
    print("    %-44s %s" % ("a premise that is NOT in the RTL",
                            "rejected" if bogus not in rtl
                            else "*** ACCEPTED"))
    if bogus in rtl:
        rc = 1
    real = PREMISES[3][2]
    print("    %-44s %s" % ("the real winner-first premise",
                            "accepted" if real in rtl else "*** REJECTED"))
    if real not in rtl:
        rc = 1
    return rc


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("J=9 PROOF ANCHORS -- are the premises still true of the RTL?")
    print("=" * 78)
    if not os.path.isfile(PROOF):
        print("  *** %s is missing, so there is no proof to check." % PROOF)
        return 1
    bad, rtl = check()
    print("  premises checked : %d" % len(PREMISES))
    for tag, what, _n in PREMISES:
        if not any(t == tag for t, _w, _n2 in bad):
            print("    %-4s ok    %s" % (tag, what))
    for tag, what, needle in bad:
        print("    %-4s *** GONE: %s" % (tag, what))
        print("         the anchor %r is no longer in src/pe_engine.v." % needle)
        print("         Theorem 1 (wait <= %d) rests on it; re-derive before"
              % BOUND_T1)
        print("         anything quotes that bound again.")
        rc = 1

    # ---- the document must still state the bounds the parameters give -----
    with open(PROOF, encoding="utf-8", errors="replace") as fh:
        doc_raw = fh.read()
    # ⛔ WHITESPACE-NORMALISED BEFORE MATCHING. The first version searched the
    # raw text and reported "the verdict must still be a refusal -- 'does not
    # proceed' is gone" on a document that says exactly that, because the
    # phrase WRAPPED ACROSS A LINE. A false red on prose is the same defect as
    # a false red on code: it has to be silenced, and the way it gets silenced
    # is by weakening the check.
    doc = " ".join(doc_raw.split())
    print()
    print("  --- the document's arithmetic vs the parameters ---")
    # ⛔ `BOUND_T2` IS A REFUTED FIGURE, NOT A RESULT. The document states it
    # as the repair that measurement then killed (40 > 21), so the gate
    # requires it to still APPEAR -- a retraction with its number removed
    # stops being checkable.
    for name, val, must in (("Theorem 1 (holds)", BOUND_T1, "= 9"),
                            ("the refuted repair", BOUND_T2, "= 21")):
        ok = must in doc
        print("    %-16s %-4d stated as %-5s %s"
              % (name, val, must, "ok" if ok else "*** NOT IN THE DOCUMENT"))
        if not ok:
            rc = 1
    # ⛔ AND THE VERDICT MUST STILL BE A REFUSAL. This document's conclusion is
    # that the claim as written is FALSE and the reopening does not proceed. If
    # someone edits it into an approval without re-deriving, that is the single
    # most expensive change anyone could make here, so it is asserted.
    for needle, why in (
            ("FALSE", "the document must still state the claim is false"),
            ("does not proceed", "the verdict must still be a refusal"),
            ("40", "the measured counter-example must still appear"),
            ("no fixed `J` is available",
             "the document must still say no constant J exists below D*"),
            # ⛔ Theorem 3 must still be stated, and stated as ZERO. "bounded"
            # would be a materially weaker claim than the published guarantee
            # needs, and the difference is the whole point of §5.
            ("Theorem 3", "the D* theorem must still be in the document"),
            ("is **zero**", "Theorem 3 must still claim ZERO, not bounded"),
            # ⚠ the document writes the Unicode "≥", not ">=" -- the needle
            # has to match the prose as written, not as I would type it
            ("d_min ≥ D*", "its scope must still be stated")):
        if needle not in doc:
            print("    *** %s -- %r is gone from the document" % (why, needle))
            rc = 1

    print()
    if selftest(rtl):
        rc = 1
    print()
    print("=" * 78)
    print("  GATE j-proof-anchors: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ IT CHECKS THE PREMISES, NOT THE REASONING. The inference from")
    print("      P1-P7 to the two theorems is prose and a gate cannot verify")
    print("      it; what this prevents is the prose outliving the RTL it")
    print("      cites.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
