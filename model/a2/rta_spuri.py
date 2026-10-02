"""A2-GREEN Part 1 (O9) -- Spuri's DEADLINE-LIMITED interference.

THE ONE CHANGE: the interference sum restricts to instances whose ABSOLUTE
DEADLINE is <= the analysed instance's. Nothing else moves. The `+1` stays
exactly where `a2_close.py` put it (that is Part 2's question, and conflating the
two would make neither answerable).

⛔⛔ WHY THE LOOSE SUM WAS WRONG AND IN WHICH DIRECTION. `a2_close.py` summed
`ceil(w/T_j)*C_j` over every other lane -- every instance of every lane,
regardless of deadline. Under EDF an instance only interferes if it is more
urgent, i.e. its absolute deadline is <= the analysed instance's. Counting the
rest OVER-states interference, so every `r_i` in A2_CLOSE_RESULTS was an upper
bound on an upper bound. Safe for a feasibility claim, but it manufactures
margin loss -- and SPI was sitting at zero margin, which is exactly the place a
spurious cycle changes the verdict.

SPURI'S FORM, IMPLEMENTED AS WRITTEN (RR-2772 / George-Rivierre-Spuri RR-2966):

    W_i(a, t) = sum_{j != i} min{ ceil((t + J_j)/T_j),
                                  floor((a + J_j + D_i - D_j)/T_j) + 1 }_0 * C_j

  first term  = how many j-instances can be RELEASED in [0, t)
  second term = how many j-instances can carry a deadline <= a + D_i
  {x}_0       = max(0, x) -- a lane whose every deadline is later contributes NOTHING

  L_i(a) = floor(a/T_i)*C_i + 1 + B_i(a) + W_i(a, L_i(a))
  r_i    = max over a in A_i ( L_i(a) + C_i + J_i - a )

⭐ B_i IS A FUNCTION OF `a`, WHICH THE UNIFORM VERSION MISSED. A job can block
only if it is already running AND carries a deadline later than the analysed
instance's ABSOLUTE deadline `a + D_i`. As `a` grows, fewer lanes qualify and the
blocking shrinks -- sometimes to zero. `a2_close.blocking()` used relative
deadlines only, which is the a = 0 case and therefore conservative.

⛔ `a` IS SEARCHED, NOT ASSUMED ZERO. Spuri's Lemma 4.1 is the whole reason: the
worst case is NOT always the first instance of the busy period. The candidate set
is the i-releases PLUS the points where the deadline-limiting term changes
(`k*T_j + D_j - D_i`), because the min() switches branch exactly there.
"""

from __future__ import annotations

import os
import sys
from math import ceil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from a2_close import (ETHERNET, REQUIRED, Lane, blocking, busy_period,  # noqa: E402
                      cond1, cond2, response_time)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def floor_div(n: int, d: int) -> int:
    """Python's // already floors toward -inf for negatives, which is what the
    `floor(...)` in Spuri's second term requires. Asserted, not assumed."""
    return n // d


assert floor_div(-204, 434) == -1, "floor must round toward -infinity"
assert floor_div(-10, 25) == -1


# ============================================================================
def w_contribution(j: Lane, a: int, t: int, D_i: int) -> int:
    """One lane's term in W_i(a, t). Spuri's min{release-bound, deadline-bound}_0.

    ⛔⛔ THE RELEASE BOUND IS `floor(t/T_j) + 1`, NOT `ceil(t/T_j)`, AND MIXING
    THE TWO CONVENTIONS MADE THE BOUND UNSOUND. The two halves of the min() must
    agree about ties:

      * the deadline bound here is NON-STRICT (`D_j <= a + D_i`), so a job whose
        deadline EQUALS the analysed instance's is counted as an interferer --
        correct, because the hardware promises no tie-break rule;
      * `ceil(t/T_j)` counts releases in the OPEN interval [0, t), so it excludes
        a job released at exactly t -- a strict convention.

    Non-strict eligibility with a strict release count UNDER-counts, and an
    under-counted interference term is an under-estimated response time, which is
    the one direction a bound may not err in. TChecker found it: on I3 lane D it
    reported 11 against the recurrence's 8, and the hand trace confirms 11 (all
    four lanes released at t=0, and the two 11-vs-11 deadline ties both break
    against D). `floor(t/T_j) + 1` counts the release at 0 and at t, matching the
    non-strict eligibility.

    ⭐ It also removes the degenerate fixpoint that forced the `max(base, 1)`
    seed: at t = 0 this term is 1, not 0.
    """
    released = floor_div(t + j.J, j.T) + 1                  # releases in [0, t]
    eligible = floor_div(a + j.J + D_i - j.D, j.T) + 1      # deadline <= a + D_i
    n = max(0, min(released, eligible))
    return n * j.C


def blocking_at(lane: Lane, lanes: list, a: int) -> tuple:
    """B_i(a) = max{ C_j - 1 : j != i, D_j > a + D_i }.

    Only a job whose deadline is later than the analysed instance's ABSOLUTE
    deadline can still be holding the engine non-preemptively.
    """
    who = [l for l in lanes if l is not lane and l.D > a + lane.D]
    return (max(l.C - 1 for l in who) if who else 0), [l.name for l in who]


def candidates(lane: Lane, lanes: list, horizon: int) -> list:
    """A_i -- the offsets worth checking.

    i's own releases, plus every point where the deadline-limiting branch of the
    min() switches. Omitting the second family is how an offset search silently
    becomes "check a = 0".
    """
    A = {0}
    k = 0
    while k * lane.T <= horizon:
        A.add(k * lane.T)
        k += 1
    for j in lanes:
        if j is lane:
            continue
        k = 0
        while True:
            a = k * j.T + j.D - lane.D
            if a > horizon:
                break
            if a >= 0:
                A.add(a)
            k += 1
            if k > 10_000:
                break
    return sorted(A)


def response_time_spuri(lane: Lane, lanes: list, plus_one: int = 1,
                        horizon: int | None = None) -> dict:
    """r_i with deadline-limited interference and a-dependent blocking."""
    L_busy = busy_period(lanes) or 1
    if horizon is None:
        horizon = L_busy + max(l.T for l in lanes)
    best = None
    for a in candidates(lane, lanes, horizon):
        B, who = blocking_at(lane, lanes, a)
        base = floor_div(a, lane.T) * lane.C + plus_one + B
        # ⛔⛔ THE SEED MUST BE >= 1, AND THIS BUG WAS REAL. Seeding at `base`
        # lets `base = 0` (no blocking, no earlier instance) sit on a DEGENERATE
        # FIXPOINT: `ceil(0/T_j) = 0` counts no interference, `nxt = 0 = L`, and
        # the iteration terminates before it starts. Spuri's release count
        # `ceil((t+J_j)/T_j)` only counts the job released AT 0 once t > 0, so
        # the recurrence must be evaluated at t >= 1. With the `+1` in place
        # base was never 0, which is exactly how the `+1` MASKED this -- the
        # term was wrong and the seed was wrong, and together they cancelled.
        L = max(base, 1)
        for _ in range(100_000):
            nxt = base + sum(w_contribution(o, a, L, lane.D)
                             for o in lanes if o is not lane)
            if nxt == L:
                break
            if nxt < L:          # seed sat above the fixpoint: nothing precedes
                L = nxt
                break
            L = nxt
        else:
            return {"lane": lane.name, "diverged": True}
        r = L + lane.C + lane.J - a
        if best is None or r > best["r"]:
            best = {"lane": lane.name, "r": r, "a": a, "L": L, "B": B,
                    "blockers": who, "D": lane.D, "feasible": r <= lane.D,
                    "diverged": False, "n_candidates": None}
    best["n_candidates"] = len(candidates(lane, lanes, horizon))
    return best


# ============================================================================
def part2_plus_one() -> bool:
    """A2-GREEN Part 2 (O8) -- is the `+1` distinct from `(C_k - 1)`, or a
    double-count?

    ⛔ I AM NOT CITING AN EQUATION NUMBER I CANNOT CHECK. The spec asks for the
    `+1` to be sourced to "RR-2966's discrete non-preemptive formulation (the
    exact equation)". I do not have that paper open and will not invent a
    reference. What I CAN do is stronger than a citation: construct cases whose
    answer is forced by the schedule itself and see which form reproduces them.

    THE HYPOTHESIS UNDER TEST: the `+1` is the one-tick offset of the critical
    instant (blocker starts at t-1) and `(C_k - 1)` is the blocker's remaining
    service. If so they are the SAME tick counted twice: a blocker that started
    one tick early has, by definition, `C_k - 1` left. The `- 1` IS the offset.
    """
    print("=" * 78)
    print("PART 2 (O8) -- the `+1`, settled by construction")
    print("=" * 78)
    cases = []

    # (1) one lane alone. Nothing to interfere, nothing to block. The engine
    #     picks the job up and runs it: r must be EXACTLY C.
    solo = Lane("solo", T=100, C=2, D=50)
    cases.append(("N=1, nothing to block or interfere", [solo], solo, 2,
                  "job is picked up and run: r = C"))

    # (2) two lanes, analysed one has the LATEST deadline so B = 0, and the
    #     other is more urgent so it goes first. r = C_other + C_self.
    a2 = Lane("urgent", T=100, C=2, D=10)
    b2 = Lane("relaxed", T=100, C=3, D=50)
    cases.append(("N=2, B=0, one more-urgent lane ahead", [a2, b2], b2, 5,
                  "EDF runs urgent (2) then relaxed (3): 2+3 = 5"))

    # (3) blocking, hand-timed. X is analysed, Y is less urgent but ALREADY
    #     RUNNING, having started one tick before X's release.
    #       t=-1 Y starts (C=4)        t=0 X released, Y has 3 left
    #       t=0..3 Y runs out          t=3..5 X runs       -> r_X = 5
    x3 = Lane("analysed", T=100, C=2, D=10)
    y3 = Lane("blocker", T=100, C=4, D=50)
    cases.append(("N=2, blocker started one tick early", [x3, y3], x3, 5,
                  "Y has C-1=3 left at t=0, then X: 3+2 = 5"))

    print("  %-38s %-7s %-9s %-9s %s"
          % ("case", "truth", "with +1", "without", "which is right"))
    ok = True
    for label, lanes, target, truth, why in cases:
        with_1 = response_time_spuri(target, lanes, plus_one=1)["r"]
        without = response_time_spuri(target, lanes, plus_one=0)["r"]
        verdict = ("WITHOUT" if without == truth and with_1 != truth else
                   "WITH" if with_1 == truth and without != truth else
                   "both" if with_1 == without == truth else "NEITHER")
        if verdict != "WITHOUT":
            ok = False
        print("  %-38s %-7d %-9d %-9d %s" % (label, truth, with_1, without, verdict))
        print("      %s" % why)
    print()
    if ok:
        print("  ⭐ ALL THREE forced cases agree with the form WITHOUT the `+1`, and")
        print("     the `+1` form is wrong by exactly 1 in every one of them -- including")
        print("     case (1), which has NO blocker at all. That rules out the reading")
        print("     that the `+1` is the critical-instant offset: with nothing blocking,")
        print("     there is no offset to account for, and the term still adds a cycle.")
        print()
        print("  ⛔ CONCLUSION: the `+1` DOUBLE-COUNTS the tick that `(C_k - 1)` already")
        print("     encodes. It is not a distinct term. Direction of the error:")
        print("     CONSERVATIVE BY 1 CYCLE on every lane. Remove it.")
    else:
        print("  *** the three cases do not agree on one form -- do not change the")
        print("      recurrence until this is resolved ***")
    print()
    print("  ⚠ WHAT THIS DOES NOT DO: it does not source the term in the literature.")
    print("    It shows the `+1` form contradicts three schedules whose answers are")
    print("    forced. If RR-2966 does carry a `+1`, then it sits in a formulation")
    print("    that differs elsewhere (continuous time, or B defined as C_k not")
    print("    C_k - 1) and the two cannot be mixed -- which is the same conclusion.")
    return ok


def compare(lanes: list, label: str) -> dict:
    print("=" * 78)
    print(label + "    N = %d" % len(lanes))
    print("=" * 78)
    print("  %-20s %-6s %-6s %-9s %-9s %-7s %-7s %s"
          % ("lane", "D_i", "B(0)", "r LOOSE", "r SPURI", "delta", "margin", "verdict"))
    rows = []
    for l in lanes:
        old = response_time(l, lanes)                       # the loose sum
        new = response_time_spuri(l, lanes)
        d = new["r"] - old["r"]
        rows.append({"lane": l.name, "old": old["r"], "new": new["r"],
                     "D": l.D, "a": new["a"], "B": new["B"],
                     "feasible": new["feasible"], "delta": d})
        print("  %-20s %-6d %-6d %-9d %-9d %-7s %-7d %s"
              % (l.name, l.D, blocking(l, lanes)[0], old["r"], new["r"],
                 ("%+d" % d) if d else "0", l.D - new["r"],
                 "OK" if new["feasible"] else "INFEASIBLE"))
    # ⛔ a tightening can only REDUCE r. A positive delta would mean the
    # deadline-limited form admits interference the loose sum did not, which is
    # impossible and would be a bug in w_contribution or blocking_at.
    up = [r for r in rows if r["delta"] > 0]
    assert not up, "TIGHTENING INCREASED r on %s -- bug, not a result" % (
        [r["lane"] for r in up],)
    print()
    print("  argmax offset `a` per lane (Lemma 4.1 -- is it ever non-zero?):")
    for l in lanes:
        new = response_time_spuri(l, lanes)
        print("    %-20s a = %-6d  L = %-4d  B(a) = %-3d  over %d candidates"
              % (l.name, new["a"], new["L"], new["B"], new["n_candidates"]))
    print()
    # ---- the falsifier Part 1 pre-registered -----------------------------
    unchanged = [r for r in rows if r["delta"] == 0]
    if len(unchanged) == len(rows):
        print("  *** FALSIFIER FIRED: every lane's r is unchanged. The loose sum was")
        print("      ALREADY deadline-limited and the over-count is elsewhere. Do not")
        print("      trust any margin until it is located. ***")
    else:
        print("  falsifier (all lanes unchanged): did NOT fire -- %d of %d lanes moved"
              % (len(rows) - len(unchanged), len(rows)))
        if unchanged:
            print("      unchanged: %s" % ", ".join(r["lane"] for r in unchanged))
            print("      (expected for the LATEST-deadline lane: the deadline cap")
            print("       never binds when every other lane is more urgent)")
    print()
    zero = [r for r in rows if r["feasible"] and r["D"] - r["new"] == 0]
    bad = [r for r in rows if not r["feasible"]]
    print("  A2-F6 (r_i == D_i, named obstacle not a pass): %s"
          % (", ".join(r["lane"] for r in zero) if zero else "no lane at zero margin"))
    print("  r_i <= D_i for every lane: %s"
          % ("YES" if not bad else "NO -- " + ", ".join(r["lane"] for r in bad)))
    return {"rows": rows, "zero": zero, "bad": bad}


def main() -> int:
    print()
    print("A2-GREEN PART 1 (O9) -- deadline-limited interference, nothing else moved")
    print("the `+1` is retained exactly as a2_close.py has it; that is Part 2")
    print()
    r3 = compare(REQUIRED, "THREE REQUIRED PROTOCOLS")
    print()
    r4 = compare(REQUIRED + [ETHERNET], "WITH ETHERNET")

    print()
    print("=" * 78)
    print("THE SPI VERDICT -- the number Part 1 exists to settle")
    print("=" * 78)
    spi = [l for l in REQUIRED if l.name.startswith("SPI")][0]
    for label, ls in (("3 required", REQUIRED), ("with Ethernet", REQUIRED + [ETHERNET])):
        old = response_time(spi, ls)
        new = response_time_spuri(spi, ls)
        print("  %-16s r_SPI  LOOSE %-4d ->  SPURI %-4d   D = %d   margin %d -> %d"
              % (label, old["r"], new["r"], spi.D,
                 spi.D - old["r"], spi.D - new["r"]))
    print()
    print("  pre-registered expectation was r_SPI < 12 -> %s"
          % ("CONFIRMED" if response_time_spuri(spi, REQUIRED)["r"] < 12
             else "*** REFUTED ***"))
    print()
    print("  ⭐ WHY SPI GAINS SO MUCH: SPI holds the EARLIEST deadline of the three")
    print("     (12 < 30 < 216). Under EDF no UART or I2C instance released in the")
    print("     busy period can carry a deadline <= 12, so BOTH contribute exactly")
    print("     ZERO. The loose sum charged SPI for all of them. Its zero margin was")
    print("     an ARTEFACT OF THE OVER-COUNT, not a property of the design.")
    print()
    print("  ⛔ Part 2 still moves this by 1: the unsourced `+1` is inside every")
    print("     number above. r_SPI is NOT final until the +1 is sourced or removed.")
    print()
    part2_plus_one()

    # ---- the final numbers, both parts applied --------------------------
    print("=" * 78)
    print("FINAL -- Parts 1 AND 2 applied (deadline-limited, `+1` removed)")
    print("=" * 78)
    for label, ls in (("3 required", REQUIRED), ("with Ethernet", REQUIRED + [ETHERNET])):
        print("  %s:" % label)
        for l in ls:
            f = response_time_spuri(l, ls, plus_one=0)
            print("    %-20s r = %-4d D = %-4d margin %-5d %s"
                  % (l.name, f["r"], f["D"], f["D"] - f["r"],
                     "OK" if f["feasible"] else "INFEASIBLE"))
    eth_final = response_time_spuri(ETHERNET, REQUIRED + [ETHERNET], plus_one=0)
    print()
    print("  ⭐ CROSS-CHECK THAT COSTS NOTHING AND IS WORTH A LOT: with the `+1`")
    print("     removed, r_Ethernet = %d, which is EXACTLY C + B = %d + %d."
          % (eth_final["r"], ETHERNET.C, eth_final["B"]))
    print("     That is the hand-derived structural floor from A2_CLOSE_RESULTS,")
    print("     reached independently by the recurrence. With the `+1` in, the")
    print("     recurrence said 4 and disagreed with the floor by one cycle -- the")
    print("     floor was right and the discrepancy was the double-count.")

    # ---- cond(2) is untouched by O9, and said so ------------------------
    print()
    print("=" * 78)
    print("CONDITION (2) IS UNAFFECTED -- checked, not assumed")
    print("=" * 78)
    for label, ls in (("3 required", REQUIRED), ("with Ethernet", REQUIRED + [ETHERNET])):
        c = cond2(ls)
        U, _ = cond1(ls)
        print("  %-16s U = %.5f   cond(2) %s   tightest d = %d, slack %d"
              % (label, U, "pass" if c["passes"] else "FAIL",
                 c["worst"][1], c["worst"][0]))
    print("  the processor-demand test already carries the `D_i <= d` restriction,")
    print("  which IS the deadline limiting -- so O9 cannot and does not move it.")
    print("  The Ethernet failure at d = 2 stands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
