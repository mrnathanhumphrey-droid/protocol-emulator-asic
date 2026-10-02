"""A2-CLOSE Parts B and C -- feasibility and the response-time bound, against
the `D_i` that Part A finally defined.

THE LINE THAT NEEDED D_i: `r_i <= D_i`. It is now checkable.

D_i comes from `jitter_dmax.py`: D_i = min(T_i//2, T_i - T_i//2 - 1), reproduced
by adversarial search at all four lanes and corroborated at UART by sigrok
flipping verdict at exactly the same cycle.

⛔⛔ SCOPE OF D_i, SAID PLAINLY BECAUSE THE TABLE BELOW LOOKS MORE UNIFORM THAN
IT IS. Part A's conformance product is UART's -- TA-01/01b/01c only ever covered
UART. For UART the number is derived, searched, and sigrok-adjudicated. For SPI,
I2C and Ethernet the SAME centre-sampling geometry is applied at each lane's T,
which is a MODEL ASSUMPTION for those lanes, not a derivation from a proved
monitor. Ethernet is the weakest: 10BASE-T is Manchester-coded into a PLL
receiver, and "sample each bit at its centre" is a stand-in for that. The
Ethernet verdict below does NOT depend on the exact value -- it fails for any
D < 3 -- but the number itself is the stand-in, and a tighter real monitor would
only make it worse.
"""

from __future__ import annotations

import sys
from math import ceil, gcd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

F_CLK = 50_000_000
C_EVENT = 2                      # ARCH_PREREG_01: "engine busy at 2 clk/event"


def D_of(T: int) -> int:
    """Part A's closed form. Centre-sampling jitter tolerance, both sides."""
    half = T // 2
    return min(half, T - half - 1)


class Lane:
    def __init__(self, name, T, C=C_EVENT, J=0, D=None):
        self.name, self.T, self.C, self.J = name, T, C, J
        self.D = D_of(T) if D is None else D

    def __repr__(self):
        return "%s(T=%d,C=%d,D=%d)" % (self.name, self.T, self.C, self.D)


REQUIRED = [Lane("UART 115200", 434), Lane("SPI 1 MHz", 25), Lane("I2C 400 kHz", 62)]
ETHERNET = Lane("10 Mbit Ethernet", 5)


# ============================================================================
# B_i -- DERIVED from the deadline ordering, not inherited as "(k-1)"
# ============================================================================
def blocking(lane: Lane, lanes: list) -> tuple:
    """B_i = max over lanes that can carry a LATER deadline of (C_j - 1).

    Non-preemptive EDF: a job already running cannot be preempted, so lane i is
    delayed by at most the longest single action of a lane whose deadline is
    later (those are the only ones that could have started ahead of it and still
    be running). Discrete time, so the `-1`: if it had one cycle left it would be
    gone before i's release instant mattered.

    ⭐ THIS IS WHY PART A HAD TO COME FIRST. `lp(i)` is defined by DEADLINE, and
    the deadlines are the D_i Part A derived. With D spanning 2..216 the ordering
    is strongly shaped, and B_i is NOT uniform: the latest-deadline lane is
    blocked by nothing at all.
    """
    later = [l for l in lanes if l.D > lane.D]
    if not later:
        return 0, []
    return max(l.C - 1 for l in later), [l.name for l in later]


def busy_period(lanes: list):
    """L = fixpoint of W(t) = sum ceil(t/T_j)*C_j from t = sum C_j (Spuri Eq 1)."""
    L = sum(l.C for l in lanes)
    for _ in range(100_000):
        nxt = sum(ceil(L / l.T) * l.C for l in lanes)
        if nxt == L:
            return L
        L = nxt
    return None


# ============================================================================
# PART B -- A2a FEASIBILITY
# ============================================================================
def cond1(lanes: list) -> tuple:
    U = sum(l.C / l.T for l in lanes)
    return U, U <= 1


def scheduling_points(lanes: list, horizon: int) -> list:
    """Distinct absolute deadlines D_i + k*T_i inside [0, horizon]."""
    pts = set()
    for l in lanes:
        k = 0
        while l.D + k * l.T <= horizon:
            pts.add(l.D + k * l.T)
            k += 1
    return sorted(pts)


def cond2(lanes: list, horizon: int | None = None) -> dict:
    """Processor-demand + non-preemptive blocking, at every scheduling point.

        forall d:  sum_{D_i <= d} (1 + floor((d - D_i)/T_i)) * C_i  +  B  <=  d
    """
    H = 1
    for l in lanes:
        H = H * l.T // gcd(H, l.T)
    if horizon is None:
        horizon = min(H, max(l.D for l in lanes) + max(l.T for l in lanes))
    B = max((l.C - 1 for l in lanes), default=0)
    pts = scheduling_points(lanes, horizon)
    worst, failures = None, []
    for d in pts:
        demand = sum((1 + (d - l.D) // l.T) * l.C for l in lanes if l.D <= d)
        total = demand + B
        slack = d - total
        if worst is None or slack < worst[0]:
            worst = (slack, d, demand, total)
        if total > d:
            failures.append((d, demand, B, total))
    return {"H": H, "horizon": horizon, "B": B, "points": len(pts),
            "worst": worst, "failures": failures, "passes": not failures}


# ============================================================================
# PART C -- A2b THE BOUND
# ============================================================================
def response_time(lane: Lane, lanes: list, m_cap: int = 2000) -> dict:
    """Spuri/RR-2966 non-preemptive EDF recurrence, offset-searched over q.

        w_i(q) = q*C_i + 1 + sum_{j != i} ceil((w_i(q) + J_j)/T_j)*C_j + B_i
        r_i    = max_q ( w_i(q) + C_i + J_i - q*T_i )

    ⛔ The interference sum is NOT deadline-limited here. Proper EDF analysis
    caps lane j's contribution by how many of its instances can carry a deadline
    <= the analysed instance's; omitting that cap OVER-counts interference, so
    this is an upper bound on an upper bound -- safe for a feasibility claim,
    pessimistic if it ever becomes binding. It is not binding for any lane below;
    if it ever is, tighten it before concluding anything.
    """
    B, blockers = blocking(lane, lanes)
    L = busy_period(lanes)
    m = max(1, ceil(L / lane.T)) if L else 1
    others = [l for l in lanes if l is not lane]
    worst_r, worst_q, trace = None, None, []
    for q in range(min(m, m_cap)):
        w = q * lane.C + 1 + B
        for _ in range(100_000):
            nxt = q * lane.C + 1 + B + sum(ceil((w + o.J) / o.T) * o.C for o in others)
            if nxt == w:
                break
            w = nxt
        else:
            return {"lane": lane.name, "diverged": True, "B": B, "m": m}
        r = w + lane.C + lane.J - q * lane.T
        trace.append((q, w, r))
        if worst_r is None or r > worst_r:
            worst_r, worst_q = r, q
    return {"lane": lane.name, "B": B, "blockers": blockers, "L": L, "m": m,
            "r": worst_r, "q": worst_q, "D": lane.D,
            "feasible": worst_r <= lane.D, "trace": trace[:4], "diverged": False}


def closed_form(lane: Lane, lanes: list) -> int:
    """L_i <= sum_{j != i} C_j + max_lp(C_j - 1). Valid ONLY when every m_i == 1."""
    B, _ = blocking(lane, lanes)
    return sum(l.C for l in lanes if l is not lane) + B


# ============================================================================
def report(lanes: list, label: str) -> dict:
    print("=" * 78)
    print(label + "    N = %d lanes" % len(lanes))
    print("=" * 78)
    print("  %-20s %-8s %-6s %-6s %-6s %s"
          % ("lane", "T_i", "C_i", "D_i", "B_i", "blocked by (later deadline)"))
    for l in lanes:
        B, who = blocking(l, lanes)
        print("  %-20s %-8d %-6d %-6d %-6d %s"
              % (l.name, l.T, l.C, l.D, B, ", ".join(who) if who else "-- nothing"))
    print()

    U, ok1 = cond1(lanes)
    print("  A2a condition (1)  U = sum C_i/T_i = %.5f   %s"
          % (U, "PASS (<= 1)" if ok1 else "*** FAIL: oversubscribed (A2-F3) ***"))

    c2 = cond2(lanes)
    print("  A2a condition (2)  processor demand + blocking B = %d" % c2["B"])
    print("     hyperperiod H = %d, horizon %d, %d scheduling points"
          % (c2["H"], c2["horizon"], c2["points"]))
    sl, d, dem, tot = c2["worst"]
    print("     tightest point: d = %d, demand %d + B %d = %d, slack %d"
          % (d, dem, c2["B"], tot, sl))
    if c2["passes"]:
        print("     %s" % "PASS at every scheduling point")
    else:
        print("     *** FAIL (A2-F4: non-preemption binding) at %d points ***"
              % len(c2["failures"]))
        for d, dem, B, tot in c2["failures"][:4]:
            print("        d = %-5d demand %d + B %d = %d  >  %d" % (d, dem, B, tot, d))
    print()

    L = busy_period(lanes)
    print("  A2b bound -- busy period L = %s cycles" % L)
    print("  %-20s %-6s %-6s %-6s %-7s %-10s %-9s %s"
          % ("lane", "m_i", "r_i", "D_i", "margin", "verdict", "L_i bound", "m_i==1?"))
    rows = []
    for l in lanes:
        rr = response_time(l, lanes)
        rows.append(rr)
        cf = closed_form(l, lanes)
        print("  %-20s %-6d %-6s %-6d %-7s %-10s %-9d %s"
              % (l.name, rr["m"], rr["r"], rr["D"], rr["D"] - rr["r"],
                 "OK" if rr["feasible"] else "INFEASIBLE", cf,
                 "yes" if rr["m"] == 1 else "NO (m>1)"))
        rows[-1]["cf"] = cf
        rows[-1]["cf_valid"] = rr["m"] == 1
    print("     ⛔ `L_i bound` is sum_{j!=i} C_j + B. It bounds the BUSY PERIOD L_i,")
    print("        NOT r_i -- it omits C_i and the +1 entirely. It is printed here")
    print("        only to be checked against L; it can never be the quantity")
    print("        compared against D_i. (L = %s above.)" % L)
    print()
    bad = [r for r in rows if not r["feasible"]]
    tight = [r for r in rows if r["feasible"] and r["D"] - r["r"] <= 0]
    gate = ok1 and c2["passes"] and not bad
    print("  r_i <= D_i for every lane: %s"
          % ("YES" if not bad else "NO -- " + ", ".join(r["lane"] for r in bad)))
    if tight:
        print("  ⚠ ZERO MARGIN on: %s  (feasible, but r_i == D_i exactly -- any"
              % ", ".join(r["lane"] for r in tight))
        print("    increase in C_i, B_i or lane count breaks it immediately)")
    print("  >>> A2 GATE on this lane set: %s" % ("GREEN" if gate else "RED"))
    return {"U": U, "c2": c2, "rows": rows, "gate": gate}


def main() -> int:
    print()
    print("A2-CLOSE -- feasibility and bound against the derived D_i")
    print("D_i = min(T//2, T - T//2 - 1) from Part A (search + sigrok at UART)")
    print()
    r3 = report(REQUIRED, "THE THREE REQUIRED PROTOCOLS")
    print()
    r4 = report(REQUIRED + [ETHERNET], "WITH THE ETHERNET STRETCH GOAL")

    print()
    print("=" * 78)
    print("THE ETHERNET VERDICT -- why it fails, and what the failure is made of")
    print("=" * 78)
    e = ETHERNET
    B, who = blocking(e, REQUIRED + [ETHERNET])
    print("  D_Ethernet            = %d cycles   (T = %d, centre-sample geometry)"
          % (e.D, e.T))
    print("  one service action C  = %d cycles" % e.C)
    print("  blocking B            = %d cycle   (longest other-lane action - 1)" % B)
    print("  C + B                 = %d cycles  > D = %d  -> INFEASIBLE"
          % (e.C + B, e.D))
    print()
    print("  ⭐ THE FAILURE IS STRUCTURAL, NOT NUMERICAL. Ethernet is infeasible for")
    print("     ANY D < %d, because C + B is a floor on the response time that no" % (e.C + B))
    print("     scheduling policy can go under: one indivisible service action plus")
    print("     one non-preemptive blocking action. Tightening D_Ethernet, changing")
    print("     the sampling geometry, or re-deriving against a real Manchester")
    print("     monitor cannot rescue it -- they can only make it worse.")
    print("     Interference from the other three lanes never even gets consulted.")
    print()

    # ---- the escape, computed rather than asserted -------------------------
    print("=" * 78)
    print("THE ESCAPE -- a shift register turns the rate down by its width")
    print("=" * 78)
    # ⛔⛔ RUN CONDITION IN THE OUTPUT, BECAUSE THIS TABLE WAS QUOTED OFF THE
    # WRONG LANE SET. `REQUIRED` is TX-ONLY (3 lanes). The sweep below therefore
    # answers "what width works if the chip only ever transmits" -- and its
    # `w = 1` row was relayed as the derived minimum for the real design, which
    # carries five lanes in both directions. On the five-lane set `w = 1` has
    # margin 1 AND m_Eth = 4, i.e. it sits inside the regime Part 3 proved this
    # recurrence can UNDER-estimate in. The authoritative sweep is
    # `model/a2/bursty.py::ethernet_width()`, on the shipped five-lane set,
    # which gives w = 2 as the minimum and w = 4 as fully clear.
    print("  ⛔ LANE SET FOR THIS SWEEP: %s" % ", ".join(l.name for l in REQUIRED))
    print("     This is the TX-ONLY set. SUPERSEDED for the shipped design --")
    print("     see model/a2/bursty.py (five lanes, both directions): w = 2 min.")
    print("  If the Ethernet lane owns a w-bit shift register clocked at the bit")
    print("  rate, the ENGINE's event is no longer 'emit one bit' but 'refill w")
    print("  bits'. T becomes w*5 cycles. With ping-pong buffering the engine has a")
    print("  full outer period to refill, so D = w*5 - 1.")
    print()
    # ⛔ EVERY lane is re-checked at each w, not just Ethernet. Widening the
    # Ethernet buffer changes the interference every OTHER lane sees, and SPI
    # already runs at zero margin once Ethernet is present -- a table that
    # reported only Ethernet's own deadline would call a set feasible while SPI
    # was the lane that had actually broken.
    print("  %-4s %-7s %-7s %-7s %-9s %-34s %s"
          % ("w", "T=5w", "D=5w-1", "U", "cond(2)", "r_i/D_i per lane", "verdict"))
    for w in (1, 2, 4, 8, 16):
        eth = Lane("Ethernet w=%d" % w, 5 * w, D=5 * w - 1)
        ls = REQUIRED + [eth]
        U, ok1w = cond1(ls)
        c2w = cond2(ls)
        rs = [response_time(l, ls) for l in ls]
        bad = [r for r in rs if not r["feasible"]]
        detail = " ".join("%s %d/%d" % (l.name.split()[0][:4], r["r"], r["D"])
                          for l, r in zip(ls, rs))
        if bad:
            verdict = "infeasible: " + ",".join(r["lane"].split()[0] for r in bad)
        elif not c2w["passes"]:
            verdict = "infeasible: cond(2)"
        elif not ok1w:
            verdict = "infeasible: U>1"
        else:
            verdict = "FEASIBLE"
        print("  %-4d %-7d %-7d %-7.4f %-9s %-34s %s"
              % (w, 5 * w, 5 * w - 1, U, "pass" if c2w["passes"] else "FAIL",
                 detail, verdict))
    print()
    print("  ⛔ DO NOT QUOTE A MINIMUM w FROM THIS TABLE. It is the TX-only set.")
    print("     The shipped answer is in bursty.py: w = 2 minimum, w = 4 clear.")
    print()
    print("  ⛔ THIS IS P1's BUFFER RUNG, APPLIED WHERE THE SPEC DOES NOT PUT IT.")
    print("     A2-CLOSE scopes the 'derive the FIFO depth' escape to REACTIVE INPUT")
    print("     lanes (UART-rx, I2C clock-stretch). The same buffer is the escape for")
    print("     a HIGH-RATE OUTPUT lane, and Ethernet is where it stops being optional:")
    print("     the smallest w that closes the gate is the DERIVED shift-register")
    print("     width, exactly as Joseph & Pandya derive a FIFO depth. A2-F2's")
    print("     'buffer it or say measured-not-proved' applies verbatim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
