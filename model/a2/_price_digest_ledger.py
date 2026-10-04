"""PRICING ARM for the digest ledger. Mutates the shipped table; must go RED.

⛔⛔ WHY THIS FILE EXISTS. `lane_digest.DIGEST_LEDGER` is a new guard, and the
standing rule here is that a guard which has only ever been seen PASS is an
unmeasured artefact -- this project has already shipped a condition (1.6s) that
printed PASS unconditionally because its failure branch was unreachable. So the
ledger is priced the way the A1 meta-check is priced: by MUTATING THE ARTEFACT
it guards, not by removing a tool.

⭐ THE MUTATION IS THE REALISTIC ONE. It does not invent a nonsense table; it
nudges a single lane's `J` by one -- exactly the shape of the two near-misses
that motivated the ledger: a second builder that drops `J`
(`gate_lane_class.five_lanes`, which reported the OLD digest under the current
table's name) and an in-passing edit to a deadline. The ledger must notice that
the live table is not the authorised one.

`price_gates.sh` requires this to exit NON-ZERO.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import bursty                                                     # noqa: E402
import lane_digest                                                # noqa: E402


def main() -> int:
    before = lane_digest.base_digest()
    ok_before = lane_digest.assert_current(verbose=False)
    print("  shipped digest BEFORE mutation : %s   ledger ok: %s"
          % (before, ok_before))
    if not ok_before:
        print("  *** the ledger is ALREADY failing, so this arm cannot show")
        print("      that the mutation is what breaks it. Fix the ledger first.")
        return 0        # exit 0 => price_gates reports "stayed green (bad)"

    # the mutation: one lane, one field, one cycle.
    bursty.TX[0].J = bursty.TX[0].J + 1
    after = lane_digest.base_digest()
    ok_after = lane_digest.assert_current(verbose=False)
    print("  shipped digest AFTER  mutation : %s   ledger ok: %s"
          % (after, ok_after))

    if after == before:
        print("  *** THE DIGEST DID NOT MOVE. `J` is not inside the hash, so a")
        print("      gate could analyse a different jitter and still MATCH. The")
        print("      ledger cannot guard a field the digest does not cover. ***")
        return 0
    if ok_after:
        print("  *** THE LEDGER ACCEPTED A TABLE THAT IS NOT IN IT. An")
        print("      unauthorised bump would propagate through the whole suite")
        print("      with every gate agreeing with every other. ***")
        return 0

    print()
    print("  ⭐ PRICED: a one-cycle change to one lane's J moves the digest")
    print("     %s -> %s and the ledger REJECTS it." % (before, after))
    print("     That is the failure mode the ledger exists for -- the suite's")
    print("     own cross-check only compares gates to EACH OTHER within a run,")
    print("     so without this a whole run can agree on a table nobody")
    print("     authorised.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
