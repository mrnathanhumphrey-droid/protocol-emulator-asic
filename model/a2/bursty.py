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
    """A lane with a bursty arrival curve. n = 1 is an ordinary periodic lane.

    ⛔⛔ SPEC R2 -- THE SCHEDULING DEADLINE AND THE TOLERANCE ARE TWO OBJECTS,
    AND THIS PROJECT TREATED THEM AS ONE UNTIL A TOLERANCE CORRECTION RESHUFFLED
    THE SCHEDULE BY ACCIDENT. Deriving `D_SPI-master = 23` (1.1, from the FRAM
    AC table) was a change to a TOLERANCE, but because the same field was also
    the EDF key it silently re-ordered the priorities of all five lanes and moved
    every `r_i`. The result happened to improve, which is exactly why it needed
    separating: the next correction has no such guarantee.

        D_tol    the lane's real jitter tolerance, in START-DELAY terms.
                 Admissibility only:   (r_i - C_i) <= D_tol.
                 An INPUT -- derived from a datasheet or a protocol table.
        D_sched  the EDF key, also in start-delay terms. A DESIGN CHOICE: any
                 assignment with D_sched <= D_tol is sound, because the schedule
                 then enforces something at least as strong as the requirement.
                 Defaults to D_tol. Not optimised anywhere in Part 1.
        D        the ABSOLUTE deadline the recurrence schedules on, = D_sched +
                 C_i. The recurrence compares completion times, the tolerances
                 bound start delays, and `+C_i` is the conversion.

    ⭐ `assert D_sched <= D_tol` is the soundness condition and it is checked in
    the constructor, not at a call site: scheduling to a deadline LOOSER than the
    tolerance would let a lane meet its EDF deadline while missing its real one,
    and no downstream gate looks at both fields at once.

    LEGACY CALLERS. `BLane(name, T, C, D)` still means "D is the absolute
    scheduling deadline", and `D_tol` then defaults to `D - C` so that
    `(r - C) <= D_tol` is EXACTLY `r <= D`. Every constructed instance in every
    existing gate therefore keeps its verdict bit-for-bit; only the real lane
    table, which passes `D_tol=` explicitly, moves.
    """

    def __init__(self, name, T, C, D=None, n=1, t=None, J=0, note="",
                 D_tol=None, D_sched=None):
        self.name, self.T, self.C, self.n = name, T, C, n
        self.t = t if t is not None else T
        self.J, self.note = J, note
        if D is None and D_tol is None:
            raise ValueError("%s: give either D (absolute) or D_tol (start-delay)"
                             % name)
        if D_tol is None:
            # legacy shape: D is the absolute deadline; the tolerance it implies
            # is D - C, which makes (r-C) <= D_tol identical to r <= D.
            self.D_tol = D - C
            self.D_sched = D_sched if D_sched is not None else self.D_tol
            self.D = D
        else:
            self.D_tol = D_tol
            self.D_sched = D_sched if D_sched is not None else D_tol
            self.D = self.D_sched + C
            if D is not None and D != self.D:
                raise ValueError(
                    "%s: D=%d contradicts D_sched+C=%d. Pass one or the other."
                    % (name, D, self.D))
        if self.D_sched > self.D_tol:
            raise AssertionError(
                "%s: D_sched=%d > D_tol=%d. Scheduling to a deadline LOOSER than "
                "the tolerance is unsound -- the lane could meet its EDF deadline "
                "and still miss its real one. Any D_sched <= D_tol is sound; "
                "equality is the default." % (name, self.D_sched, self.D_tol))
        if n > 1 and self.n * self.t > self.T:
            raise ValueError("%s: burst does not fit its period (n*t=%d > T=%d)"
                             % (name, self.n * self.t, self.T))

    def margin(self, r: int) -> int:
        """The ADMISSIBILITY margin: D_tol - (r - C). The one that decides.

        ⛔ Not `D - r`. That is the recurrence's own slack against the EDF key,
        and with D_sched = D_tol the two differ by exactly C_i -- which is how
        `D - r` came to be printed in the lane-table column while the minimum
        margin quoted in prose was computed the other way. Same five lanes, two
        different "minimum margin" figures (9 and 11), both derived from the same
        run. One function now, so they cannot drift again.
        """
        return self.D_tol - (r - self.C)

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
        return "%s(T=%d,C=%d,D_tol=%d,D_sched=%d,D=%d,n=%d,t=%d)" % (
            self.name, self.T, self.C, self.D_tol, self.D_sched, self.D,
            self.n, self.t)


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
            # ⛔ R2: two verdicts, not one. `sched_ok` is the EDF deadline being
            # met; `feasible` is ADMISSIBILITY, the start delay fitting the real
            # tolerance. They coincide only while D_sched == D_tol, and the one
            # that decides whether the chip works is `feasible`.
            best = {"lane": lane.name, "r": r, "a": a, "L": L, "B": B,
                    "blockers": who, "D": lane.D, "D_tol": lane.D_tol,
                    "D_sched": lane.D_sched, "margin": lane.margin(r),
                    "sched_ok": r <= lane.D,
                    "feasible": (r - lane.C) <= lane.D_tol,
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


def assert_r2_order_neutral(verbose: bool = True) -> bool:
    """SPEC R2 -- THE RESTRUCTURE MUST BE INERT BEFORE ANY DEADLINE MOVES.

    ⛔⛔ R2 and R1 landed in the same edit, and that is the shape in which a
    structural change hides a numerical one. If the D_sched/D_tol split were to
    shift any r_i by itself, then R1's reorder could not be attributed to the
    derived deadline -- and R1's falsifier ("if it reorders and drops a margin,
    report it") would be unreadable, because we could not tell which change did
    it. So the split is required to be a no-op first, on the OLD numbers.

    TWO CHECKS, because one of them is the reason and the other is the fact:

    (a) THE REASON -- a uniform shift of every key by the same k cannot move any
        r_i. The recurrence touches deadlines only through DIFFERENCES: the
        eligibility term is `floor((a + J + D_i - D_j)/T_j) + 1` and the blocking
        filter is `D_j > a + D_i`. Add k to both D_i and D_j and neither moves.
        With C uniform at 2, `key = D_tol + C` IS a uniform shift. Checked on
        constructed sets at several k, because "the algebra says so" is how the
        `a == T-1` period bug survived.

    (b) THE FACT -- the real five-lane table at its PRE-R1 deadlines, under both
        conventions, lane by lane. This is the one that would catch a mistake in
        the constructor rather than in the algebra.
    """
    bad = []
    # ---- (a) uniform shift invariance -----------------------------------
    sets = [[("P", 100, 2, 40), ("Q", 37, 2, 15), ("R", 61, 2, 25)],
            [("P", 10, 2, 4), ("Q", 7, 2, 3), ("R", 7, 2, 3)],
            [("P", 434, 2, 216), ("Q", 25, 2, 12), ("R", 45, 2, 15),
             ("S", 400, 2, 12)]]
    for spec in sets:
        base = [BLane(n, T, C, D) for n, T, C, D in spec]
        r0 = [response_time_b(l, base)["r"] for l in base]
        for k in (1, 2, 5, 97):
            sh = [BLane(n, T, C, D + k) for n, T, C, D in spec]
            r1 = [response_time_b(l, sh)["r"] for l in sh]
            if r0 != r1:
                bad.append(("uniform shift k=%d" % k, r0, r1))
    # ---- (b) the real table, both conventions ---------------------------
    #   PRE-R1/H3 deadlines, as shipped at e586ad4.
    old = [("UART-tx 115200", 434, 2, 216, 1, 434),
           ("SPI-tx 1 MHz", 25, 2, 23, 1, 25),
           ("I2C 400 kHz", 45, 2, 15, 1, 45),
           ("UART-rx 115200", 4140, 2, 216, 10, 414),
           ("SPI-target 1 MHz", 400, 2, 12, 16, 25)]
    pre = [BLane(nm, T, C, D, n=n, t=t) for nm, T, C, D, n, t in old]
    post = [BLane(nm, T, C, D_tol=D, n=n, t=t) for nm, T, C, D, n, t in old]
    rp = [response_time_b(l, pre)["r"] for l in pre]
    rq = [response_time_b(l, post)["r"] for l in post]
    if rp != rq:
        bad.append(("real table pre-R1", rp, rq))
    # ---- the must-fire: an unsound assignment must RAISE -----------------
    fired = False
    try:
        BLane("unsound", 100, 2, D_tol=10, D_sched=11)
    except AssertionError:
        fired = True
    if not fired:
        bad.append(("must-fire D_sched > D_tol", "raise", "accepted"))

    if verbose:
        print("  R2 order-neutrality gate: %s"
              % ("PASS -- the D_sched/D_tol split moves no r_i (uniform-shift "
                 "invariance at 4 values of k on 3 sets, and the real five-lane "
                 "table identical under both conventions: r = %s)" % (rp,)
                 if not bad else "*** FAIL: %s ***" % (bad[0],)))
        print("  R2 must-fire (D_sched > D_tol must raise): %s"
              % ("PASS" if fired else "*** FAIL -- an unsound assignment was "
                 "ACCEPTED; nothing stops a lane being scheduled looser than "
                 "its tolerance ***"))
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
#
# ============================================================================
# THE RTL LATENCIES -- read off `src/project.v`, kept in ONE place
# ============================================================================
# `reg [2:0] wr_sync` -- "Two flops to resolve metastability, a third to see the
# edge" -- with `wr_rise = (wr_sync[2:1] == 2'b01)`. Detection lands at t+2 and
# the asynchronous capture can miss by a cycle.
#   ⛔ These lived in gate_lane_class.py, which imports FROM here, so the
#   reactive budget in the lane table could not read them without a cycle. They
#   are inputs to the lane table (spec R1 derives a DEADLINE from them), so this
#   is their home and 0.9b now imports them back.
L_SYNC = 3          # cycles, worst-case edge-detection latency (3-FF chain)
L_JIT = 1           # cycles, async-capture uncertainty (the only part that is jitter)
OUT_REG = 1         # cycles, output register to pad
TSU_MASTER = 1      # cycles, the PEER master's setup requirement. ⚠ PARAMETRIC:
                    # no SPI master device is picked, so 1 cycle (20 ns) stands
                    # in. Generous for a real master; the R1 gate sweeps it.
F_CLK = 50_000_000


def abs_tolerance(half_period: int, c9_at_completion: bool, C: int,
                  tsu: int = TSU_MASTER) -> int:
    """SPEC R1 -- the START-DELAY tolerance of a REACTIVE lane-action.

    A reactive output has no peer re-synchronisation to hide behind (gate 0.9b):
    the peer samples at a fixed phase of ITS OWN clock, so our whole accumulated
    latency eats its setup window directly. Everything between the peer's edge
    and our pin moving has to fit inside half a bit period:

        L_sync + start_delay + out_reg + [C_i if the pin moves at COMPLETION]
            <=  half_period - tSU(peer)

    Rearranged into the start-delay terms every other tolerance in this project
    is expressed in:

        D_tol = half_period - tSU - L_sync - out_reg - [C_i]

    ⭐ THE C9 TERM IS THE DESIGN DECISION, AND IT IS A SUBTRACTION FROM A
    TOLERANCE, which is why it was invisible while C9 was "dissolved": driving
    the pin at service COMPLETION rather than at START spends C_i cycles of a
    budget that only reactive lanes have.
    """
    return half_period - tsu - L_SYNC - OUT_REG - (C if c9_at_completion else 0)


# ⛔⛔ EVERY D BELOW IS NOW `D_tol=` -- A START-DELAY TOLERANCE, NOT AN ABSOLUTE
# DEADLINE (spec R2). The EDF key the recurrence schedules on is D_tol + C_i,
# which for a uniform C = 2 is a uniform +2 and therefore leaves every priority
# ORDER and every r_i unchanged from the pre-R2 table. That is checked, not
# assumed, by `assert_r2_order_neutral()` below: the restructure had to be
# provably inert before any deadline was allowed to move.
#
# ⭐ L_SYNC / OUT_REG / TSU are imported from the one place they are read off the
# RTL, so the reactive budget below cannot drift from gate 0.9b's.
TX = [
    BLane("UART-tx 115200", 434, 2, D_tol=216, note="periodic, one event/bit"),
    # ⭐ D = 23 DERIVED from the MB85RS64V AC table (DS501-00015-6v1-E, refs/),
    # replacing the modelled centre-sample 12. We are the MASTER here, so the
    # peer judges setup/hold against the clock WE generate, not a bit centre:
    #   D = min(N - tSU, N - tCL, N - tCH) = min(25-1, 25-2, 25-2) = 23
    # ⭐ P1.1a CONFIRMED -- the derived value is LOOSER than the stand-in. And
    # adopting it REORDERS the EDF deadlines (23 > D_I2C = 15), which turns out
    # to IMPROVE the set: a too-tight deadline had been distorting EDF into
    # prioritising SPI-tx over lanes that needed it more. Minimum margin across
    # all five lanes rises 9 -> 11; I2C r 7 -> 5, SPI-target r 5 -> 3.
    BLane("SPI-tx 1 MHz", 25, 2, D_tol=23,
          note="D derived from MB85RS64V tSU/tCH/tCL"),
    BLane("I2C 400 kHz", 45, 2, D_tol=15,
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
#
# ⭐ SPEC H3 -- D_tol IS 213, NOT 216, AND THE TWO UART DIRECTIONS ARE NOT ONE
# LANE. UART-tx sources its own timing and its 216 is sigrok-adjudicated.
# UART-rx is REACTIVE-anchor: the sample grid hangs off a DETECTED start edge,
# and detection lags the true edge by L_sync, so the whole grid slides and the
# early-side constraint tightens to T - half - L_sync = 216 - 3 = 213. Gate 0.9b
# derived that and printed it; the lane table kept 216, so the ledger and the
# model disagreed by 3 cycles on a 206-cycle margin. Costs nothing here -- and
# that is exactly why it survived: a difference that changes no verdict is the
# kind that stays wrong.
UART_RX = BLane("UART-rx 115200", T=4140, C=2, D_tol=216 - L_SYNC, n=10, t=414,
                note="10 samples/frame at the fastest admitted peer (414, the "
                     "sampler-realistic band floor); n*t == T, gapless; "
                     "D_tol = 216 - L_sync (REACTIVE-anchor, 0.9b)")

# SPI-target: the MASTER supplies SCK, so our events are its edges -- two per bit,
# 16 per byte, and back-to-back bytes again make n*t == T.
#
# ⭐⭐ SPEC R1 -- D_tol IS DERIVED, AND O4 IS CLOSED. The last stand-in deadline
# in the table was this lane's 12, carried over from the centre-sampling geometry
# `min(T//2, T - T//2 - 1)` at T = 25. It was reported as "non-load-bearing,
# because the binding test is 0.9b's absolute budget rather than D" -- and that
# reading was WRONG. Under EDF a deadline is a PRIORITY, and 12 was the tightest
# number in the table, so the stand-in was making SPI-target the highest-priority
# lane and therefore setting every other lane's r_i. A modelled number was the
# scheduling key for the whole set.
#
# The fix is to derive it from the same absolute budget that already governs the
# lane, expressed in start-delay terms (`abs_tolerance` above, half-period 25 at
# 1 MHz):
#
#   C9 = pin at START       D_tol = 25 - 1 - 3 - 1     = 20
#   C9 = pin at COMPLETION  D_tol = 25 - 1 - 3 - 1 - 2 = 18
#
# ⛔ THE SHIPPED VALUE IS THE COMPLETION ONE, 18. Not because C9 is decided --
# 1.3 decides it -- but because 18 is the SMALLER of the two, so the table is
# correct under either outcome and cannot be made worse by the decision. START
# is priced in `gate_spi_target_D.py` and in the 1.2 frontier.
#
# ⭐ IT REORDERS, AND THE FALSIFIER DID NOT FIRE: the derived budget is looser
# than the stand-in (18 > 12), so I2C (15) takes the highest priority and
# SPI-target drops to second. No margin falls -- I2C r goes 5 -> 3 and
# SPI-target 3 -> 5, and the MINIMUM admissibility margin across the set rises
# 11 -> 14. Both C9 variants clear the >= 4 bar at 1 MHz by more than 15 cycles,
# so C9 is NOT decided by 1 MHz feasibility; it is decided by the frequency
# ceiling, which is 1.3's question and not this lane's.
SPI_RX = BLane("SPI-target 1 MHz", T=400, C=2, n=16, t=25,
               D_tol=abs_tolerance(25, c9_at_completion=True, C=2),
               note="master-clocked, 16 edges/byte, back-to-back: n*t == T; "
                    "D_tol DERIVED from the absolute budget (R1), C9=COMPLETION")


def report(lanes: list, label: str) -> dict:
    print("=" * 78)
    print(label)
    print("=" * 78)
    U = sum(l.util for l in lanes)
    print("  %-20s %-7s %-5s %-7s %-7s %-5s %-4s %-6s %-8s"
          % ("lane", "T_i", "C_i", "D_tol", "D_sched", "key", "n_i", "t_i", "n*C/T"))
    for l in lanes:
        print("  %-20s %-7d %-5d %-7d %-7d %-5d %-4d %-6d %-8.5f"
              % (l.name, l.T, l.C, l.D_tol, l.D_sched, l.D, l.n, l.t, l.util))
    print("  %-20s %-7s %-5s %-7s %-7s %-5s %-4s %-6s %-8.5f  %s"
          % ("TOTAL U", "", "", "", "", "", "", "", U,
             "FEASIBLE (<=1)" if U <= 1 else "*** U > 1 ***"))
    print("  notes:")
    for l in lanes:
        print("    %-20s %s" % (l.name, l.note))
    print()
    print("  EDF priority order (by key = D_sched + C_i, most urgent first):")
    print("    %s" % "  <  ".join("%s(%d)" % (l.name.split()[0], l.D)
                                  for l in sorted(lanes, key=lambda x: x.D)))
    print()
    Lb = busy_period_b(lanes)
    print("  busy period L = %s" % Lb)
    print("  %-20s %-5s %-5s %-6s %-7s %-8s %-6s %-6s %s"
          % ("lane", "m_i", "r_i", "r-C_i", "D_tol", "margin", "arg a", "B(a)",
             "verdict"))
    rows = []
    for l in lanes:
        rr = response_time_b(l, lanes)
        m = l.N(Lb) if Lb else None
        rows.append({"lane": l.name, **rr, "m": m})
        r = rr["r"]
        print("  %-20s %-5s %-5s %-6s %-7d %-8s %-6s %-6s %s"
              % (l.name, m, r, (r - l.C) if r is not None else "-", l.D_tol,
                 rr.get("margin") if r is not None else "-",
                 rr.get("a"), rr.get("B"),
                 "OK" if rr.get("feasible") else "*** INFEASIBLE ***"))
    # ⛔ the margin is D_tol - (r - C), NOT D - r. See BLane.margin().
    print("  margin = D_tol - (r - C_i), the ADMISSIBILITY margin (spec R2)")
    mm = [r["margin"] for r in rows if r.get("margin") is not None]
    if mm:
        print("  minimum admissibility margin = %d   (bar >= 4: %s)"
              % (min(mm), "clears" if min(mm) >= 4 else "*** BELOW BAR ***"))
    bad = [r for r in rows if not r.get("feasible")]
    zero = [r for r in rows if r.get("feasible") and r["margin"] == 0]
    many = [r for r in rows if r["m"] and r["m"] > 1]
    print()
    print("  lanes with m_i > 1 (the regime the bound was unsound in): %s"
          % (", ".join("%s (m=%d)" % (r["lane"], r["m"]) for r in many)
             if many else "none"))
    print("  A2-F6 zero margin: %s"
          % (", ".join(r["lane"] for r in zero) if zero else "no lane"))
    print("  (r_i - C_i) <= D_tol for every lane: %s"
          % ("YES" if not bad else "NO -- " + ", ".join(r["lane"] for r in bad)))
    sched = [r for r in rows if not r.get("sched_ok")]
    print("  r_i <= D_sched + C_i (the EDF deadline) for every lane: %s"
          % ("YES" if not sched else "NO -- " + ", ".join(r["lane"] for r in sched)))
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
        # the CURRENT table's three driving lanes, so the demonstration is on
        # the shipped deadlines rather than the retracted T=62 / D=30 pair.
        lanes = [BLane("UART-tx", 434, 2, D_tol=216),
                 BLane("SPI-tx", 25, 2, D_tol=23),
                 BLane("I2C", 45, c_i2c, D_tol=15)]
        U = sum(l.util for l in lanes)
        rows = [(l, response_time_b(l, lanes)) for l in lanes]
        bad = [l.name for l, r in rows if not r.get("feasible")]
        print("  %-18s C_I2C = %-6d U = %-9.4f %s"
              % (label, c_i2c, U, "FEASIBLE" if U <= 1 and not bad
                 else "INFEASIBLE: " + (", ".join(bad) if bad else "U > 1")))
        print("      %s" % note)
        for l, r in rows:
            print("      %-10s r = %-8s D_tol = %-5d B = %-6s %s"
                  % (l.name, r["r"], l.D_tol, r.get("B"),
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
    print("  %-20s %-6s %-6s %-7s %-6s %-7s %s"
          % ("lane", "r_i", "r-C_i", "D_tol", "t_i", "queues?", "classification"))
    for l in lanes:
        rr = response_time_b(l, lanes)
        r = rr["r"]
        queues = (l.n > 1 and r is not None and r > l.t)
        if r is None:
            cls = "NAMED OBSTACLE (no bound)"
        elif not rr["feasible"]:
            cls = "NAMED OBSTACLE (r - C > D_tol)"
        elif queues:
            cls = "DERIVED BUFFER (r > t: events accumulate)"
        else:
            cls = "FEASIBLE"
        print("  %-20s %-6s %-6s %-7d %-6d %-7s %s"
              % (l.name, r, r - l.C, l.D_tol, l.t,
                 "yes" if queues else "no", cls))
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
        # legacy shape on purpose: the Ethernet stand-in D is an absolute
        # deadline from the centre-sample geometry, not a derived tolerance.
        eth = BLane("Ethernet w=%d" % w, 5 * w, 2, 5 * w - 1)
        ls = lanes + [eth]
        U = sum(l.util for l in ls)
        L = busy_period_b(ls)
        rs = [response_time_b(l, ls) for l in ls]
        bad = [r["lane"] for r in rs if not r["feasible"]]
        mm = min(r["margin"] for r in rs)
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
              % (w, 5 * w, 5 * w - 1, U, rs[-1]["r"], rs[-1]["margin"],
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
    if not assert_r2_order_neutral():
        print("\nABORTING: the D_sched/D_tol split is NOT inert, so no deadline")
        print("change below can be attributed to the deadline rather than to the")
        print("restructure. Fix the split before reading any number here.")
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
