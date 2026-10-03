"""A2-GREEN Part 4 -- the RECEIVING direction: bursty reactive lanes.

THE ONE CLAIM: every reactive lane is classified -- feasible, feasible-with-a-
derived-buffer, or named obstacle -- with no lane left as "probably fine".

⛔⛔ WHY THIS PART IS THE DANGEROUS ONE. A bursty lane emits `n` events per outer
period, so `m_i > 1` BY CONSTRUCTION -- and `m_i > 1` is the exact regime in
which the recurrence was proved UNSOUND in Part 3 (non-strict eligibility against
a strict release count under-counted interference and UNDER-estimated response
time). Parts 1-3's real tables were safe only because every feasible required
lane is `m_i = 1`. That protection does not exist here. So:

  * the corrected release count is used (`N_j`, below, generalises it);
  * the offset-dependent blocking `B_i(a)` is carried through;
  * and no bursty number is trusted until TChecker has confirmed it on an
    instance in the same regime (`run_bursty.py`).

THE ARRIVAL CURVE (Spuri's bursty model): `n` events per outer period `T`, at
inner spacing `t`, with `n*t <= T`. Events in the closed interval [0, delta]:

    N(delta) = n*floor(delta/T) + min( n, floor((delta mod T)/t) + 1 )

⭐ IT REDUCES TO THE CORRECTED PERIODIC FORM AT n = 1 -- `floor(delta/T) + 1`,
exactly the release count Part 3 had to fix. That is not a remark, it is a
mechanical gate: `assert_reduces_to_periodic()` checks the generalisation against
`rta_spuri.w_contribution` over thousands of points, so a bursty lane with n = 1
cannot silently mean something different from the periodic lane it is.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from a2_close import Lane                                     # noqa: E402
from rta_spuri import blocking_at, floor_div, response_time_spuri, w_contribution  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class BLane:
    """A lane with a bursty arrival curve. n = 1 is an ordinary periodic lane."""

    def __init__(self, name, T, C, D, n=1, t=None, J=0, note=""):
        self.name, self.T, self.C, self.D, self.n = name, T, C, D, n
        self.t = t if t is not None else T
        self.J, self.note = J, note
        if n > 1 and self.n * self.t > self.T:
            raise ValueError("%s: burst does not fit its period (n*t=%d > T=%d)"
                             % (name, self.n * self.t, self.T))

    def N(self, delta: int) -> int:
        """Events arriving in the closed interval [0, delta]. 0 for delta < 0."""
        if delta < 0:
            return 0
        full = delta // self.T
        rem = delta % self.T
        return self.n * full + min(self.n, rem // self.t + 1)

    def arrivals(self, horizon: int) -> list:
        """Every event arrival time in [0, horizon] -- the candidate offsets."""
        out = []
        k = 0
        while k * self.T <= horizon:
            for m in range(self.n):
                a = k * self.T + m * self.t
                if a <= horizon:
                    out.append(a)
            k += 1
        return sorted(set(out))

    @property
    def util(self):
        return self.n * self.C / self.T

    def __repr__(self):
        return "%s(T=%d,C=%d,D=%d,n=%d,t=%d)" % (
            self.name, self.T, self.C, self.D, self.n, self.t)


# ============================================================================
def busy_period_b(lanes: list, cap: int = 2_000_000):
    L = sum(l.C for l in lanes)
    for _ in range(100_000):
        nxt = sum(l.N(L) * l.C for l in lanes)
        if nxt == L:
            return L
        if nxt > cap:
            return None
        L = nxt
    return None


def blocking_at_b(lane: BLane, lanes: list, a: int) -> tuple:
    who = [l for l in lanes if l is not lane and l.D > a + lane.D]
    return (max(l.C - 1 for l in who) if who else 0), [l.name for l in who]


def response_time_b(lane: BLane, lanes: list, horizon: int | None = None) -> dict:
    """r_i for a bursty lane set. The generalisation of `response_time_spuri`.

    ⛔⛔ THE ANALYSED LANE MUST BE AN ELEMENT OF `lanes` BY IDENTITY, AND THIS IS
    ASSERTED BECAUSE I GOT IT WRONG. Interference is filtered with `o is not
    lane`, so passing a lane object that is merely EQUAL to one in the list --
    e.g. from a second call to a lane-set builder -- excludes nothing, the
    analysed lane interferes with itself, and the bound comes out INFLATED
    (SPI-target read 7 instead of 5).

    It is the mirror image of pyRTA's footgun, which `gate_pyrta.py` already
    guards: pyRTA filters by VALUE (`t != excluded`) and so OVER-excludes two
    parameter-identical lanes; this filters by IDENTITY and so UNDER-excludes a
    copy. Both produce a silently wrong number, in opposite directions. Having
    written the guard for theirs and then tripped over ours, the check belongs
    here rather than in each caller.

        L_i(a) = (N_i(a) - 1)*C_i + B_i(a)
                 + sum_{j!=i} min( N_j(L), N_j(a + D_i - D_j) ) * C_j
        r_i    = max over arrivals a ( L_i(a) + C_i + J_i - a )
    """
    if not any(o is lane for o in lanes):
        raise AssertionError(
            "response_time_b: %r is not an element of `lanes` by identity. "
            "Build the lane set ONCE and select from it -- a second builder "
            "call yields equal-but-distinct objects, which `is not` will not "
            "exclude, inflating the bound." % (lane.name,))
    L_busy = busy_period_b(lanes)
    if L_busy is None:
        return {"lane": lane.name, "diverged": True, "r": None}
    if horizon is None:
        horizon = L_busy + max(l.T for l in lanes)
    best = None
    cands = lane.arrivals(horizon)
    for a in cands:
        B, who = blocking_at_b(lane, lanes, a)
        base = (lane.N(a) - 1) * lane.C + B
        L = max(base, 1)
        for _ in range(100_000):
            nxt = base + sum(
                min(o.N(L), o.N(a + lane.D - o.D)) * o.C
                for o in lanes if o is not lane)
            if nxt == L:
                break
            if nxt < L:
                L = nxt
                break
            L = nxt
        else:
            return {"lane": lane.name, "diverged": True, "r": None}
        r = L + lane.C + lane.J - a
        if best is None or r > best["r"]:
            best = {"lane": lane.name, "r": r, "a": a, "L": L, "B": B,
                    "blockers": who, "D": lane.D, "feasible": r <= lane.D,
                    "diverged": False}
    best["n_cands"] = len(cands)
    best["L_busy"] = L_busy
    return best


# ============================================================================
# THE MECHANICAL GATE: the bursty form must BE the periodic form at n = 1
# ============================================================================
def assert_reduces_to_periodic(verbose: bool = True) -> bool:
    """n=1 bursty == corrected periodic, on the curve AND on the full recurrence.

    ⛔ Without this, `n=1` in the bursty path could quietly mean something other
    than the periodic lane it claims to be, and Part 4 would be analysing a
    different task set from Parts 1-3 while reusing their vocabulary.
    """
    bad = []
    # (a) the arrival curve against the corrected release count
    for T in (3, 5, 7, 25, 62, 434):
        bl = BLane("x", T, 2, T // 2, n=1)
        pl = Lane("x", T, C=2, D=T // 2)
        for delta in range(0, 3 * T + 5):
            got = bl.N(delta)
            want = floor_div(delta, T) + 1
            if got != want:
                bad.append(("curve", T, delta, got, want))
            # and against the real interference term, deadline cap and all
            g2 = min(bl.N(delta), bl.N(0 + 50 - bl.D)) * bl.C
            w2 = w_contribution(pl, 0, delta, 50)
            if g2 != w2:
                bad.append(("w_contribution", T, delta, g2, w2))
    # (b) whole-recurrence equality on the real required set
    per = [Lane("UART", 434, C=2, D=216), Lane("SPI", 25, C=2, D=12),
           Lane("I2C", 62, C=2, D=30)]
    bur = [BLane("UART", 434, 2, 216), BLane("SPI", 25, 2, 12),
           BLane("I2C", 62, 2, 30)]
    for i in range(3):
        a = response_time_spuri(per[i], per, plus_one=0)["r"]
        b = response_time_b(bur[i], bur)["r"]
        if a != b:
            bad.append(("recurrence", per[i].name, None, b, a))
    if verbose:
        print("  n=1 reduction gate: %s"
              % ("PASS -- bursty form is the periodic form at n=1 "
                 "(curve, interference term, and whole recurrence)" if not bad
                 else "*** FAIL: %d mismatches, first %s ***" % (len(bad), bad[0])))
    return not bad


# ============================================================================
# THE REACTIVE LANES
# ============================================================================
# ⛔ D_i for every lane below EXCEPT UART is MODELED, not sigrok-derived (O4).
#    The centre-sampling geometry D = min(T//2, T - T//2 - 1) is applied at each
#    lane's inner spacing. TA-03's conformance oracles upgrade these.
# ⛔⛔ I2C IS T=45, D=15 -- CORRECTED, see spec N1 and model/a2/gate_i2c_phase.py.
# It used to be T=62, D=30, and both were wrong:
#   * T=62 came from 125/2 = 62.5 rounded DOWN, which the pre-reg called
#     conservative. It is not: it presumes a SYMMETRIC phase split, and a
#     symmetric 400 kHz low phase is 1.25 us against tLOW(min) = 1.3 us -- a
#     spec violation at NOMINAL (UM10204 Rev 7.0 Table 11). The legal split is
#     asymmetric (N_low=80, N_high=45 on balanced margin) and its minimum
#     inter-event spacing is 45, so the lane is DENSER than modelled.
#   * D=30 was the centre-sampling stand-in. For a lane whose clock we generate
#     the peer judges inter-edge intervals, so D is how much differential jitter
#     a phase can absorb: min(N_low - tLOW, N_high - tHIGH) = min(15, 15) = 15.
#     DERIVED, not modelled -- one of the three O4 labels comes off here.
TX = [
    BLane("UART-tx 115200", 434, 2, 216, note="periodic, one event/bit"),
    BLane("SPI-tx 1 MHz", 25, 2, 12, note="periodic, two events/bit"),
    BLane("I2C 400 kHz", 45, 2, 15,
          note="asymmetric SCL 80/45; D derived from UM10204 T11, not modelled"),
]

# UART-rx: 10 samples per frame (start + 8 data + stop) at one bit period apart;
# back-to-back frames make the outer period exactly 10 bit periods. n*t == T, so
# the burst is GAPLESS -- the densest arrival the protocol permits.
# ⛔⛔ T is 414, not 413 and not 434 -- spec N2 then P1. The admitted peer band is
# the band our receiver is PROVED to decode, BUT the original [413, 458] was
# synthesized with an EXACT sampler and so double-counted the per-bit slack:
# admitting a peer at 413 means the peer's own rate error has already consumed
# the bit window, leaving nothing for our sampler. Re-synthesized in Imitator
# with the sampler displaced by L_sync = 3 (REACTIVE-anchor, 0.9b) and uncertain
# by Dj = 8 (= r - C, gate 0.9), the exact constraint is
#     5*Te > 2067  &  4126 > 9*Te    ->   Te in [414, 458]
# Lower edge up by one; upper edge UNCHANGED, because a late sample is
# indistinguishable from a slower peer and so pushes the band up rather than
# squeezing both ends. Must-fire confirmed: Te = 413 is REJECTED.
# ⭐ D_rx is NO LONGER a separate test -- the band subsumes it. A2's remaining
# job for this lane is to certify r - C <= Dj_assumed, and the reserve lives in
# the BAND WIDTH: the integer band holds at [414,458] for Dj up to 13, so r - C
# can grow by 5 (about five C increments) before the band narrows.
UART_RX = BLane("UART-rx 115200", T=4140, C=2, D=216, n=10, t=414,
                note="10 samples/frame at the fastest admitted peer (414, the "
                     "sampler-realistic band floor); n*t == T, gapless")

# SPI-target: the MASTER supplies SCK, so our events are its edges -- two per bit,
# 16 per byte, and back-to-back bytes again make n*t == T.
SPI_RX = BLane("SPI-target 1 MHz", T=400, C=2, D=12, n=16, t=25,
               note="master-clocked, 16 edges/byte, back-to-back: n*t == T")


def report(lanes: list, label: str) -> dict:
    print("=" * 78)
    print(label)
    print("=" * 78)
    U = sum(l.util for l in lanes)
    print("  %-20s %-7s %-5s %-5s %-4s %-6s %-8s %s"
          % ("lane", "T_i", "C_i", "D_i", "n_i", "t_i", "n*C/T", "note"))
    for l in lanes:
        print("  %-20s %-7d %-5d %-5d %-4d %-6d %-8.5f %s"
              % (l.name, l.T, l.C, l.D, l.n, l.t, l.util, l.note))
    print("  %-20s %-7s %-5s %-5s %-4s %-6s %-8.5f  %s"
          % ("TOTAL U", "", "", "", "", "", U,
             "FEASIBLE (<=1)" if U <= 1 else "*** U > 1 ***"))
    print()
    Lb = busy_period_b(lanes)
    print("  busy period L = %s" % Lb)
    print("  %-20s %-7s %-6s %-6s %-7s %-7s %-6s %s"
          % ("lane", "m_i", "r_i", "D_i", "margin", "arg a", "B(a)", "verdict"))
    rows = []
    for l in lanes:
        rr = response_time_b(l, lanes)
        m = l.N(Lb) if Lb else None
        rows.append({"lane": l.name, **rr, "m": m})
        print("  %-20s %-7s %-6s %-6d %-7s %-7s %-6s %s"
              % (l.name, m, rr["r"], l.D,
                 (l.D - rr["r"]) if rr["r"] is not None else "-",
                 rr.get("a"), rr.get("B"),
                 "OK" if rr.get("feasible") else "*** INFEASIBLE ***"))
    bad = [r for r in rows if not r.get("feasible")]
    zero = [r for r in rows if r.get("feasible") and r["D"] - r["r"] == 0]
    many = [r for r in rows if r["m"] and r["m"] > 1]
    print()
    print("  lanes with m_i > 1 (the regime the bound was unsound in): %s"
          % (", ".join("%s (m=%d)" % (r["lane"], r["m"]) for r in many)
             if many else "none"))
    print("  A2-F6 zero margin: %s"
          % (", ".join(r["lane"] for r in zero) if zero else "no lane"))
    print("  r_i <= D_i for every lane: %s"
          % ("YES" if not bad else "NO -- " + ", ".join(r["lane"] for r in bad)))
    return {"U": U, "rows": rows, "bad": bad, "zero": zero, "many": many}


def clock_stretch() -> dict:
    """I2C clock-stretch: the lane the spec expected to be the honest obstacle.

    ⭐ THE SPEC ASKS THE WRONG QUESTION FIRST, AND THE RIGHT ANSWER FALLS OUT OF
    A DIRECTION ARGUMENT RATHER THAN A SPEC LOOKUP. A2-GREEN says: "check the I2C
    spec for a stretch ceiling first; no ceiling -> honest obstacle." But a
    stretch CEILING bounds how LONG the peer can delay us -- a latency question.
    Schedulability needs a FLOOR on inter-arrival: how CLOSE TOGETHER our events
    can come. Those are different quantities, and the ceiling's absence does not
    make the lane unschedulable.

    THE DIRECTION ARGUMENT: a slave stretches by holding SCL LOW, which LENGTHENS
    the low phase. Consecutive SCL-release events therefore move FURTHER APART,
    never closer. So:

        the densest possible arrival on this lane is the UN-stretched lane,

    which is already in the table at T = 62. Stretching can only reduce the event
    rate. No amount of stretching, bounded or not, can break A2a or A2b.

    ⛔ THE REAL EXPOSURE IS C_i, NOT T_i -- AND THE SPEC DOES NOT ASK ABOUT IT.
    If the engine BUSY-WAITS on SCL, its service time for that event IS the
    stretch duration. Plain I2C (UM10204) permits unbounded stretching in
    standard/fast mode, so a busy-wait makes `C_i` unbounded, which violates P2
    (bounded per-lane service) and takes the whole task set with it -- every other
    lane's blocking term is `max(C_j - 1)`. One busy-wait makes every lane
    infeasible, not just this one. Computed below rather than argued.

    ⚠ UNVERIFIED AGAINST THE DOCUMENT: I have not opened UM10204 in this session
    and will not present a clause number. My understanding is that plain I2C sets
    no maximum stretch for standard/fast mode while SMBus does (T_LOW:SEXT, 25 ms
    cumulative). ⭐ The conclusion does not depend on it: the direction argument
    settles schedulability without any ceiling, and the C_i argument holds for ANY
    ceiling large enough to matter.
    """
    print("=" * 78)
    print("I2C CLOCK-STRETCH -- the two variants, computed")
    print("=" * 78)
    out = {}
    for label, c_i2c, note in (
            ("hardware wait", 2, "the lane blocks on SCL; the engine moves on"),
            ("engine busy-wait", 5000, "engine holds while SCL is low (5000 cyc "
                                       "= 100 us, a SHORT stretch)")):
        lanes = [BLane("UART-tx", 434, 2, 216), BLane("SPI-tx", 25, 2, 12),
                 BLane("I2C", 62, c_i2c, 30)]
        U = sum(l.util for l in lanes)
        rows = [(l, response_time_b(l, lanes)) for l in lanes]
        bad = [l.name for l, r in rows if not r.get("feasible")]
        print("  %-18s C_I2C = %-6d U = %-9.4f %s"
              % (label, c_i2c, U, "FEASIBLE" if U <= 1 and not bad
                 else "INFEASIBLE: " + (", ".join(bad) if bad else "U > 1")))
        print("      %s" % note)
        for l, r in rows:
            print("      %-10s r = %-8s D = %-5d B = %-6s %s"
                  % (l.name, r["r"], l.D, r.get("B"),
                     "OK" if r.get("feasible") else "*** INFEASIBLE ***"))
        out[label] = {"U": U, "bad": bad}
    print()
    print("  ⭐ ONE BUSY-WAIT TAKES EVERY LANE, NOT JUST ITS OWN: the blocking")
    print("     term is max_j(C_j - 1) over later-deadline lanes, so an unbounded")
    print("     C on any lane is an unbounded B on all the others. That is why")
    print("     this is a derived DESIGN REQUIREMENT and not a per-lane caveat.")
    print()
    print("  CLASSIFICATION: FEASIBLE, conditional on a derived design")
    print("  requirement -- the SCL wait must be a hardware condition on the lane,")
    print("  never engine occupancy. Violate it and the classification becomes")
    print("  NAMED OBSTACLE (unbounded C_i, P2 fails).")
    return out


def classify(lanes: list) -> None:
    """feasible / derived-buffer / named-obstacle, per A2-GREEN Part 4.

    ⭐ THE BUFFER TRIGGER FOR A BURSTY LANE IS `r_i > t_i`, NOT `r_i > D_i`. If a
    lane's response exceeds its own INNER SPACING, the next event of the same
    burst arrives before the previous is served and events ACCUMULATE -- that is
    the O5 derived-buffer case, and it is also exactly what sends the foreign
    model to `OVR`. A lane can satisfy `r_i <= D_i` and still need a FIFO.
    """
    print("=" * 78)
    print("CLASSIFICATION -- every reactive lane, no 'probably fine'")
    print("=" * 78)
    print("  %-20s %-6s %-6s %-6s %-7s %s"
          % ("lane", "r_i", "D_i", "t_i", "queues?", "classification"))
    for l in lanes:
        rr = response_time_b(l, lanes)
        r = rr["r"]
        queues = (l.n > 1 and r is not None and r > l.t)
        if r is None:
            cls = "NAMED OBSTACLE (no bound)"
        elif r > l.D:
            cls = "NAMED OBSTACLE (r > D)"
        elif queues:
            cls = "DERIVED BUFFER (r > t: events accumulate)"
        else:
            cls = "FEASIBLE"
        print("  %-20s %-6s %-6d %-6d %-7s %s"
              % (l.name, r, l.D, l.t, "yes" if queues else "no", cls))
    print()
    print("  ⛔ NO reactive lane reaches the derived-buffer rung, so the FIFO-depth")
    print("     derivation is UNEXERCISED and is deliberately not shipped here.")
    print("     Were a lane to queue, the depth is the max backlog over a burst")
    print("     (Joseph & Pandya); writing that formula now would ship an")
    print("     unvalidated bound for a case that does not arise.")


def ethernet_width(lanes: list) -> None:
    """THE AUTHORITATIVE Ethernet shadow-register width, on a NAMED lane set.

    ⛔⛔ THIS EXISTS BECAUSE THE FIRST ANSWER WAS COMPUTED ON THE WRONG TASK SET.
    `a2_close.REQUIRED` is TX-ONLY (3 lanes), so the original w-sweep answered
    "what width works if the chip only transmits" -- and its `w = 1` row was
    relayed as the derived minimum for a design that carries FIVE lanes in both
    directions. The arc was:

        w = 4   from the loose (pre-O9) interference sum
        w = 1   "cheaper" correction -- WRONG LANE SET, and wrong in the UNSAFE
                direction: on the real set it is margin 1 with m_Eth = 4, which
                is inside the regime Part 3 proved the recurrence can
                UNDER-estimate in, and the bursty foreign check only reaches m=2
        w = 2   minimum on the shipped set; w = 4 clears m_i > 1 entirely

    Every row prints its lane set. A buffer width quoted without one is not a
    result -- see the run-condition-in-the-name rule.
    """
    print("=" * 78)
    print("ETHERNET SHADOW-REGISTER WIDTH -- authoritative, on the shipped set")
    print("=" * 78)
    print("  LANE SET (%d): %s" % (len(lanes), ", ".join(l.name for l in lanes)))
    print()
    print("  %-4s %-7s %-6s %-9s %-7s %-7s %-8s %-9s %s"
          % ("w", "T=5w", "D", "U", "r_Eth", "margin", "m_Eth", "min marg", "verdict"))
    for w in (1, 2, 4, 8):
        eth = BLane("Ethernet w=%d" % w, 5 * w, 2, 5 * w - 1)
        ls = lanes + [eth]
        U = sum(l.util for l in ls)
        L = busy_period_b(ls)
        rs = [response_time_b(l, ls) for l in ls]
        bad = [r["lane"] for r in rs if not r["feasible"]]
        mm = min(r["D"] - r["r"] for r in rs)
        m_eth = eth.N(L)
        # ⛔ m_i > 1 ANYWHERE is a caveat, not just infeasibility
        unsafe = [l.name for l in ls if l.N(L) > 1]
        if bad:
            v = "infeasible: " + ",".join(bad)
        elif unsafe:
            v = "feasible BUT m>1: %s" % ",".join(unsafe)
        else:
            v = "CLEAR (all m_i = 1)"
        print("  %-4d %-7d %-6d %-9.5f %-7d %-7d %-8d %-9d %s"
              % (w, 5 * w, 5 * w - 1, U, rs[-1]["r"], eth.D - rs[-1]["r"],
                 m_eth, mm, v))
    print()
    print("  ⭐ w = 2 is the MINIMUM that is both feasible and inside the")
    print("     foreign-validated regime (m_Eth = 2, which run_bursty.py covers).")
    print("     w = 4 is the first width with every lane back at m_i = 1.")
    print("  ⛔ w = 1 is feasible by margin 1 with m_Eth = 4 -- NOT covered by any")
    print("     foreign check, and one cycle of registration latency kills it.")


def main() -> int:
    print()
    print("A2-GREEN PART 4 -- the receiving direction")
    print()
    if not assert_reduces_to_periodic():
        print("\nABORTING: the bursty generalisation does not reproduce the")
        print("periodic recurrence at n=1, so it is not a generalisation.")
        return 1
    print()
    report(TX, "DRIVING DIRECTION ONLY (Parts 1-3, restated as bursty with n=1)")
    print()
    full = TX + [UART_RX, SPI_RX]
    res = report(full, "BOTH DIRECTIONS -- required protocols, tx + rx")
    print()
    print("=" * 78)
    print("⛔ THESE BURSTY NUMBERS ARE NOT YET TRUSTWORTHY")
    print("=" * 78)
    print("  Every lane above with m_i > 1 sits in the regime where Part 3 proved")
    print("  this recurrence can UNDER-estimate. The n=1 reduction gate shows the")
    print("  bursty form agrees with the periodic one where they overlap -- it says")
    print("  nothing about n > 1, which is the whole point of Part 4.")
    print("  Run `python model/a2/zone/run_bursty.py` for the foreign check.")
    print("  (That run: 9/9 lane-instances agree, 3 of them with m_i > 1.)")
    print()
    classify(full)
    print()
    ethernet_width(full)
    print()
    clock_stretch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
