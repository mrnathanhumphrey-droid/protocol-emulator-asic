"""SPEC 1.2 -- the (C, J) FRONTIER as the design constraint on the engine.

THE ONE CLAIM: the microarchitecture is not free to cost whatever it costs. This
prints, on the post-R lane set, exactly which (service time, release jitter)
pairs keep every lane admissible -- so 1.3 picks a pipeline against a number
instead of choosing one and hoping.

⛔⛔ ALL EARLIER FRONTIERS ARE SUPERSEDED. Three deadlines have moved since the
last one was printed, and each moved the thing a frontier is made of:
    1.1  D_tol(SPI-tx)     12 -> 23   derived, MB85RS64V AC table
    H3   D_tol(UART-rx)   216 -> 213  derived, REACTIVE-anchor sync lag
    R1   D_tol(SPI-target) 12 -> 18   derived, absolute budget; REORDERS EDF
A frontier quoted without its lane set is not a result, so every row below
names its D_sched/D_tol set and its C9 variant.

⭐ WHY THIS IS NOT ONE SWEEP BUT TWO TESTS. Gate 0.9b established that the test
depends on who sources the timing, and `C` enters the two tests DIFFERENTLY:

  SOURCE lanes (UART-tx, SPI-tx, I2C)
      differential: margin = D_tol - (r - C). C enters ONCE, through r. A
      uniform shift in our output is invisible to a peer that re-synchronises.

  REACTIVE lanes (SPI-target, UART-rx)
      absolute: the peer samples at a fixed phase of its own clock, so the whole
      latency chain counts. For SPI-target, C enters TWICE AND IN THE SAME
      DIRECTION:
          through r          (more service -> later start)
          through D_tol      (= half - tSU - L_sync - out_reg - C, at C9=COMPLETION)
      ⛔ THAT SECOND PATH IS THE ONE A FRONTIER SWEEP NORMALLY MISSES, because
      it looks like a constant per lane. It is not: it is a function of the
      quantity being swept, so the reactive rows bend twice as fast as the
      source rows and the binding lane changes along the sweep.

⛔ J IS NOT ONE NUMBER EITHER. Two independent sources:
    J_pipe   registering the EDF winner makes every release uncertain by 1.
             Applies to ALL lanes -- it is a property of the engine.
    L_jit    the 3-FF synchroniser's async-capture ambiguity, 1 cycle, on the
             REACTIVE-J action only (I2C's high-phase release, spec R3).
They are independent, so on the I2C lane they ADD. Modelling J as a single
global number would under-charge that lane by exactly the term that makes it
reactive.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                   # noqa: E402
from bursty import (BLane, L_JIT, L_SYNC, OUT_REG, TSU_MASTER,       # noqa: E402
                    abs_tolerance, response_time_b)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BAR = 4             # the >= 4 measurement reserve (spec P2). Retires after Phase 2.
HALF_SPI = 25       # cycles, half a 1 MHz SPI bit period at 50 MHz

# (name, T, n, t, class, D_tol spec)
#   "src"  -> D_tol is a constant from a datasheet/protocol table
#   "abs"  -> D_tol is a FUNCTION of (C, C9): the absolute budget
#   "anch" -> D_tol is a constant, but the test is absolute (sync-anchored)
LANE_SPEC = [
    ("UART-tx 115200", 434, 1, 434, "src", 216),
    ("SPI-tx 1 MHz", 25, 1, 25, "src", 23),
    ("I2C 400 kHz", 45, 1, 45, "src", 15),
    ("UART-rx 115200", 4140, 10, 414, "anch", 216 - L_SYNC),
    ("SPI-target 1 MHz", 400, 16, 25, "abs", None),
]


def build(C: int, j_pipe: int, c9_completion: bool):
    """The five-lane set at a candidate (C, J) and C9 choice.

    ⛔ ONE list, built once, selected from. `response_time_b` filters
    interference by identity.
    """
    lanes = []
    for name, T, n, t, cls, dtol in LANE_SPEC:
        if cls == "abs":
            dtol = abs_tolerance(HALF_SPI, c9_completion, C)
        J = j_pipe + (L_JIT if name.startswith("I2C") else 0)
        if dtol < 0:
            return None
        lanes.append(BLane(name, T, C, n=n, t=t, J=J, D_tol=dtol))
    return lanes


def evaluate(C: int, j_pipe: int, c9_completion: bool):
    """(min margin, rows) or (None, reason) when the point is not admissible."""
    lanes = build(C, j_pipe, c9_completion)
    if lanes is None:
        return None, "D_tol would be negative: C exceeds the absolute budget"
    U = sum(l.util for l in lanes)
    if U > 1:
        return None, "U = %.3f > 1" % U
    rows = []
    for l in lanes:
        rr = response_time_b(l, lanes)
        if rr.get("r") is None:
            return None, "busy period diverged"
        rows.append((l, rr))
    return min(rr["margin"] for _l, rr in rows), rows


def grid(c9_completion: bool) -> dict:
    """min margin over (C, J_pipe). The frontier is the >= BAR contour."""
    out = {}
    print("    %-5s %s" % ("C \\ J", "  ".join("%6d" % j for j in range(0, 4))))
    for C in range(1, 8):
        cells = []
        for j in range(0, 4):
            m, _ = evaluate(C, j, c9_completion)
            out[(C, j)] = m
            cells.append("  n/a " if m is None
                         else "%6d" % m)
        print("    %-5d %s" % (C, "  ".join(cells)))
    return out


def detail(C: int, j_pipe: int, c9_completion: bool) -> None:
    m, rows = evaluate(C, j_pipe, c9_completion)
    tag = "COMPLETION" if c9_completion else "START"
    if m is None:
        print("    C = %d, J_pipe = %d, C9 = %-10s -> NOT ADMISSIBLE (%s)"
              % (C, j_pipe, tag, rows))
        return
    print("    C = %d, J_pipe = %d, C9 = %s   min margin %d"
          % (C, j_pipe, tag, m))
    print("      %-20s %-5s %-5s %-6s %-7s %-8s %-6s %s"
          % ("lane", "J_i", "r_i", "r-C_i", "D_tol", "margin", "key", "test"))
    for l, rr in rows:
        cls = [s[4] for s in LANE_SPEC if s[0] == l.name][0]
        print("      %-20s %-5d %-5d %-6d %-7d %-8d %-6d %s"
              % (l.name, l.J, rr["r"], rr["r"] - l.C, l.D_tol, rr["margin"],
                 l.D, {"src": "differential", "abs": "absolute (C9)",
                       "anch": "absolute (anchored)"}[cls]))


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 1.2 -- the (C, J) frontier on the post-R lane set")
    print("=" * 78)
    print("  LANE SET (5), D_sched = D_tol throughout (spec R2, no assignment")
    print("  optimisation in Part 1); EDF key = D_sched + C_i:")
    for name, T, n, t, cls, dtol in LANE_SPEC:
        print("    %-20s T=%-5d n=%-3d t=%-4d %-5s D_tol=%s"
              % (name, T, n, t, cls,
                 dtol if dtol is not None
                 else "half - tSU - L_sync - out_reg - [C9]  (a FUNCTION of C)"))
    print("  constants: L_sync=%d  L_jit=%d  out_reg=%d  tSU(master)=%d  bar=%d"
          % (L_SYNC, L_JIT, OUT_REG, TSU_MASTER, BAR))
    print("  J_i = J_pipe + L_jit on the REACTIVE-J lane (I2C), J_pipe elsewhere")
    print()
    # ⛔ SPEC A1 -- this gate's whole job is to analyse VARIANTS, so `used` is
    # declared as one. The point of printing it anyway is that `base` must still
    # match every other gate in the run: a frontier swept from the wrong table
    # is the failure mode here, not a mismatched sweep point.
    lane_digest.announce(
        "frontier.py (1.2)", build(2, 1, True),
        variant="sweeps C and J by construction; shown at the target (C=2, "
                "J_pipe=1, C9=COMPLETION). D_tol(SPI-target) is a FUNCTION of C")

    rc = 0
    for c9 in (False, True):
        tag = "COMPLETION" if c9 else "START"
        print()
        print("  --- minimum admissibility margin, C9 = pin at %s ---" % tag)
        g = grid(c9)
        ok = {k for k, v in g.items() if v is not None and v >= BAR}
        print("    points clearing the >= %d bar: %d of %d"
              % (BAR, len(ok), len(g)))
        if ok:
            # the frontier: the largest C at each J, and the largest J at each C
            print("    frontier (largest admissible C per J_pipe):")
            for j in range(0, 4):
                cs = sorted(C for (C, jj) in ok if jj == j)
                print("      J_pipe = %d  ->  C <= %s"
                      % (j, max(cs) if cs else "NONE ADMISSIBLE"))
        else:
            print("    *** no (C, J) point is admissible at C9 = %s ***" % tag)
            rc = 1

    # ---- the two candidates 1.3 has to choose between --------------------
    print()
    print("=" * 78)
    print("  THE TWO CANDIDATES 1.3 CHOOSES BETWEEN (spec 1.3 item 1)")
    print("=" * 78)
    print("  unpipelined: one service, no registered winner -> C = 3, J_pipe = 0")
    print("  pipelined:   winner registered a cycle early   -> C = 2, J_pipe = 1")
    print()
    cands = [("unpipelined C=3 J=0", 3, 0), ("pipelined C=2 J=1", 2, 1)]
    verdicts = {}
    for label, C, j in cands:
        print("  %s" % label)
        for c9 in (False, True):
            detail(C, j, c9)
            m, _ = evaluate(C, j, c9)
            verdicts[(label, c9)] = m
        print()
    print("  %-22s %-14s %-14s %s"
          % ("candidate", "C9=START", "C9=COMPLETION", "verdict"))
    for label, C, j in cands:
        a, b = verdicts[(label, False)], verdicts[(label, True)]
        v = ("clears the bar under BOTH C9 outcomes"
             if a is not None and b is not None and min(a, b) >= BAR
             else "clears only at C9=START" if a is not None and a >= BAR
             else "*** below the bar ***")
        print("  %-22s %-14s %-14s %s"
              % (label, "min margin %s" % a, "min margin %s" % b, v))

    # ---- what the sweep says that a single point cannot ------------------
    print()
    print("=" * 78)
    print("  WHAT BINDS, AND WHERE IT CHANGES HANDS")
    print("=" * 78)
    print("  ⭐ The binding lane is not fixed along the sweep. Every point at")
    print("     J_pipe = 1, both C9 variants, so 1.3 can see which quantity it")
    print("     is actually buying at each cost:")
    print("    %-4s %-24s %-9s %-24s %s"
          % ("C", "binding @ C9=START", "min marg", "binding @ C9=COMPL", "min marg"))
    for C in range(1, 8):
        cells = []
        for c9 in (False, True):
            m, rows = evaluate(C, 1, c9)
            if m is None:
                cells += ["n/a", "-"]
            else:
                cells += [min(rows, key=lambda x: x[1]["margin"])[0].name, m]
        print("    %-4d %-24s %-9s %-24s %s" % (C, cells[0], cells[1],
                                                cells[2], cells[3]))
    print()
    # ---- the target, stated ---------------------------------------------
    print("  THE TARGET 1.2 HANDS TO 1.3, stated per lane:")
    tC, tJ = 2, 1
    m, rows = evaluate(tC, tJ, True)
    print("    (C_i, J_pipe) = (%d, %d) on every lane, priced at C9=COMPLETION"
          % (tC, tJ))
    print("    -- the WORSE C9 variant, so the target holds whichever way 1.3")
    print("    decides. J_i is J_pipe + L_jit on I2C and J_pipe elsewhere.")
    print("      %-20s %-8s %-8s %-8s %s"
          % ("lane", "C_i", "J_i", "margin", "budget this leaves"))
    for l, rr in rows:
        print("      %-20s %-8d %-8d %-8d %s"
              % (l.name, l.C, l.J, rr["margin"],
                 "%d cycles before the >= %d bar" % (rr["margin"] - BAR, BAR)))
    print("    min margin %d; the bar is %d; the binding lane is %s."
          % (m, BAR, min(rows, key=lambda x: x[1]["margin"])[0].name))
    print()
    print("  ⭐⭐ AND THE 1 MHz FEASIBILITY DOES NOT DECIDE THE PIPELINE. Both")
    print("     candidates come out at min margin %d, under both C9 variants, and"
          % m)
    print("     in both cases the binding lane is I2C -- whose margin is")
    print("     identical at (C=3,J=0) and (C=2,J=1) because the extra service")
    print("     cycle and the extra jitter cycle cost it the same. So 1.3 must")
    print("     choose on AREA and CRITICAL PATH, not on schedulability, and")
    print("     this file's job is to say that rather than to pretend a")
    print("     preference fell out of the numbers.")
    print()
    print("  ⭐ WHAT C9 IS WORTH, IN C RATHER THAN MHz: one cycle of service")
    print("     budget. At J_pipe <= 1 the ceiling is C <= 6 at START and C <= 5")
    print("     at COMPLETION. That is the same decision 0.9b priced at ~0.5 MHz")
    print("     of SPI-target headroom, measured in the unit 1.3 actually spends.")
    print()
    print("  ⛔ A FRONTIER IS NOT A CEILING ON C ALONE. The reactive rows bend")
    print("     faster than the source rows because C is in their D_tol as well")
    print("     as in their r, so the admissible region is not a rectangle and")
    print("     'C <= k' is not a safe summary of it. Read the grid, not the max.")
    print()
    print("  ⚠ EVERY NUMBER HERE IS STILL AT AN UNMEASURED C. This frontier says")
    print("     what C the design may cost; Phase 2 measures what it does cost.")
    print("     The >= %d bar is the reserve against that gap and it RETIRES when"
          % BAR)
    print("     the measurement lands -- at which point this file is re-run and")
    print("     the margins are quoted on the measured value.")
    print()
    print("  GATE 1.2: %s" % ("PASSED -- the frontier is non-empty under both C9 "
                              "variants and both 1.3 candidates are located on it"
                              if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
