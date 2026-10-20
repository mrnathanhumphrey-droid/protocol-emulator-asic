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
import lane_digest                                            # noqa: E402
from rta_spuri import blocking_at, floor_div, response_time_spuri, w_contribution  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ⛔ SET ONLY BY `price_gates.sh`, to revert the jitter fix and require the
# must-fire to go red. Read once at import so it cannot be flipped mid-run and
# leave half a table computed each way.
_NOMINAL_ONLY = os.environ.get("BURSTY_NOMINAL_INTERFERENCE") == "1"
if _NOMINAL_ONLY:
    print("  ⚠⚠ BURSTY_NOMINAL_INTERFERENCE=1 -- the jitter interference term "
          "is REVERTED to the unsound nominal curve. This is the pricing arm; "
          "every number below is the OLD, WRONG one by construction.")


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
        """NOMINAL events arriving in the closed interval [0, delta]. 0 if < 0.

        ⛔⛔ THIS IS THE JITTER-FREE CURVE AND IT MUST NOT BE USED FOR
        INTERFERENCE. Use `N_J`. See its docstring for the bug this caused.
        """
        if delta < 0:
            return 0
        full = delta // self.T
        rem = delta % self.T
        return self.n * full + min(self.n, rem // self.t + 1)

    def N_J(self, delta: int) -> int:
        """JITTER-INFLATED arrival count -- the one the interference sum needs.

        ⛔⛔⛔ THE BUG THIS REPLACES, AND ITS DIRECTION. `response_time_b` summed
        `min(o.N(L), o.N(a + D_i - D_j)) * o.C` -- the NOMINAL curve, with no
        `J` anywhere. So release jitter entered the subject's own response
        (`r = L + C + J - a`) and entered NOTHING in the interference that a
        jittery lane imposes on the others. A lane whose releases can bunch up
        by `J` can deliver more jobs into a window than its period allows, so
        dropping the term UNDER-counts interference and UNDER-estimates `r_i`.
        That is the one direction a bound may not err in.

        ⭐ IT WAS NOT A GENERALISATION GAP -- THE PERIODIC FORM IT WAS GATED
        AGAINST ALREADY HAD THE TERM. `rta_spuri.w_contribution` reads
        `floor((t + J_j)/T_j) + 1` and `floor((a + J_j + D_i - D_j)/T_j) + 1`.
        The bursty rewrite dropped both while keeping the vocabulary, and
        `assert_reduces_to_periodic` -- the mechanical gate whose entire job is
        to catch exactly this -- passed, because EVERY lane it constructs takes
        the default `J = 0`. At J = 0 the two curves are identically equal, so
        the gate compared them on the one slice where no disagreement can
        exist. An identity filter, in the soundness checker. The gate is now
        required to run a non-zero J (see `assert_reduces_to_periodic`).

        THE DERIVATION. A job's release may be delayed by up to `J` after its
        nominal release, so an event nominally at time `s` can be observed
        anywhere in `[s, s + J]`. The observed events in `[0, delta]` are
        therefore a subset of the events NOMINALLY in `[-J, delta]`, and by
        periodicity that window has the same count as `[0, delta + J]`:

            N_J(delta) = N(delta + J)

        ⭐ AT n = 1 THIS IS EXACTLY SPURI'S TERM: `floor((delta + J)/T) + 1`.
        That identity is what `assert_reduces_to_periodic` now checks at J > 0,
        so the two implementations can no longer drift apart in silence.
        """
        if _NOMINAL_ONLY:
            # ⛔ THE PRICING ARM, AND IT IS NOT A DEBUG SWITCH. `price_gates.sh`
            # sets BURSTY_NOMINAL_INTERFERENCE=1 to REVERT the fix and then
            # REQUIRES the must-fire to fail. A must-fire that has only ever
            # been seen pass has unknown strength -- it would read PASS just the
            # same if the jitter term were deleted and its three faces ended up
            # comparing one number against itself. This is how the fix is shown
            # to be load-bearing rather than merely present.
            return self.N(delta)
        return self.N(delta + self.J)

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
    """L = the synchronous busy period, on the JITTER-INFLATED curve.

    ⛔ `N` HERE WOULD BE WRONG FOR A SECOND, QUIETER REASON than the
    interference sum. `L_busy` is only used as a HORIZON -- it sets how far
    `arrivals()` is searched for the offset `a`. Understating it does not
    understate any single `r_i` directly; it drops CANDIDATE OFFSETS, and
    Spuri's Lemma 4.1 is precisely the statement that the worst `a` need not be
    the first one. So the error would surface as a `max` taken over too small a
    set -- an under-estimate with no term visibly missing from the recurrence.
    Inflating the curve can only lengthen the horizon, which is safe.
    """
    L = sum(l.C for l in lanes)
    for _ in range(100_000):
        nxt = sum(l.N_J(L) * l.C for l in lanes)
        if nxt == L:
            return L
        if nxt > cap:
            return None
        L = nxt
    return None


def blocking_at_b(lane: BLane, lanes: list, a: int) -> tuple:
    """B_i(a) = max{C_j - 1 : j != i, D_j > a + D_i}.

    ⭐ WHY THERE IS NO `J` IN THIS FILTER, DERIVED RATHER THAN INHERITED. The
    ruling asked for jitter in the blocking eligibility as well as in the
    interference. Worked through, the term is ALREADY the conservative one, and
    adding `J` here would move it in the wrong direction:

      * deadlines in this project are relative to the NOMINAL release -- that is
        what makes `r = L + C + J - a` a response measured from `a`, and
        `(r - C) <= D_tol` a start delay the datasheet can bound;
      * a job of lane j with nominal release `s` therefore has absolute deadline
        `s + D_j` NO MATTER how late its actual release lands;
      * to block, it must already be executing at the analysed release, so its
        actual release precedes it, which under jitter admits nominal releases
        as early as `s = -J_j`;
      * those jobs carry deadlines in `[D_j - J_j, D_j]`, and the filter
        qualifies a blocker when its deadline EXCEEDS `a + D_i`. The largest
        deadline in that range is `D_j`, at `s = 0` -- which is the un-inflated
        value already tested.

    So jitter widens the set of j-jobs that can be mid-execution, but every one
    it adds carries an EARLIER deadline than the one already admitted, and a
    `max` over a set cannot grow by adding members that fail its filter.
    Inflating by `+J_j` here would admit blockers whose deadlines are too early
    to invert priority -- conservative, but by an amount with no derivation, and
    `price_jitter_blocking()` measures it rather than arguing it.
    """
    who = [l for l in lanes if l is not lane and l.D > a + lane.D]
    return (max(l.C - 1 for l in who) if who else 0), [l.name for l in who]


def blocking_at_b_from_jitter_model(lane: BLane, lanes: list, a: int) -> tuple:
    """The blocking filter rebuilt FROM the jitter model, to check the shipped one.

    ⛔⛔ THE FIRST VERSION OF THIS WAS A STRAWMAN AND IT FIRED FALSELY. It tested
    `D_j + J_j > a + D_i` and reported that 184 of 432 swept instances changed
    their blocking term -- which read as "the derivation is wrong, escalate".
    It was the PROBE that was wrong. `D_j` is a RELATIVE deadline; `D_j + J_j`
    is not the absolute deadline of any job in the model, under jitter or
    without it. Adding a release delay to a relative deadline does not delay the
    deadline at all -- a job released late has LESS time left, not more. So the
    strawman admitted blockers that cannot exist, and its 184 disagreements
    measured nothing but its own construction. A dramatic number out of my own
    helper, again.

    THE DERIVED FORM. Enumerate what jitter actually admits. A j-job can block
    the analysed instance only if it is already executing when that instance
    arrives, so its ACTUAL release precedes the arrival; with a delay of up to
    `J_j`, the nominal releases that can land at or before the busy-period start
    are `s in [-J_j, 0]`. Deadlines are relative to the NOMINAL release, so such
    a job's absolute deadline is `s + D_j`, and it inverts priority only when
    that exceeds `a + D_i`:

        qualifies  <=>  max_{s in [-J_j, 0]} (s + D_j) > a + D_i
                   <=>  D_j > a + D_i                  (the max is at s = 0)

    ⭐ SO THE SHIPPED FILTER IS THE WIDEST CASE ALREADY, and jitter adds only
    j-jobs whose deadlines are EARLIER -- members that fail the filter, which a
    `max` cannot grow by. This function computes the max explicitly instead of
    asserting the algebra, so a sign slip in either place shows up as a
    disagreement rather than as agreement by construction.
    """
    who = []
    for l in lanes:
        if l is lane:
            continue
        latest = max(s + l.D for s in range(-l.J, 1))     # the max, enumerated
        if latest > a + lane.D:
            who.append(l)
    return (max(l.C - 1 for l in who) if who else 0), [l.name for l in who]


def spuri_candidate_set(lane: BLane, lanes: list, horizon: int) -> list:
    """Every subject offset `a` in [0, horizon] where a term of r(a) steps.

    The subject's own release offsets, plus, for every other lane j, the
    offsets where `N_J(a + D_i - D_j)` steps: `N(x)` steps at x = kT + m*t, and
    `N_J(x) = N(x + J)`, so a = kT_j + m*t_j - J_j + D_j - D_i. See the Z1
    comment in `response_time_b` for the source and the bug it closes.
    """
    out = set(lane.arrivals(horizon))
    out.add(0)
    for o in lanes:
        if o is lane:
            continue
        k = 0
        while k * o.T - o.J + o.D - lane.D <= horizon:
            for m in range(o.n):
                a = k * o.T + m * o.t - o.J + o.D - lane.D
                if 0 <= a <= horizon:
                    out.add(a)
            k += 1
    return sorted(out)


def response_time_b(lane: BLane, lanes: list, horizon: int | None = None,
                    jitter_in_interference: bool = True,
                    spuri_candidates: bool = True) -> dict:
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
                 + sum_{j!=i} min( N_J_j(L), N_J_j(a + D_i - D_j) ) * C_j
        r_i    = max over arrivals a ( L_i(a) + C_i + J_i - a )

    where `N_J_j(x) = N_j(x + J_j)` is the jitter-inflated arrival count. ⛔ Both
    branches of the min() carry it; see `BLane.N_J` for why using the nominal
    `N_j` here was UNSOUND and how the reduction gate failed to catch it.

    `jitter_in_interference=False` reproduces the OLD, unsound sum. It exists so
    the must-fire can show the old form under-reporting on a constructed
    instance -- a fix with no failing case is a fix on no evidence -- and is used
    nowhere else.
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
    # ⛔⛔ RULING Z1 -- SPURI'S CANDIDATE SET, NOT THE SUBJECT'S RELEASES ALONE.
    # Spuri, "Analysis of Deadline Scheduled Real-Time Systems", INRIA RR-2772
    # (1996), the EDF response-time analysis for arbitrary release: r(a) is
    # piecewise in the subject's offset `a` and its maxima sit at the LEFT end
    # of each piece, i.e. wherever any term of the recurrence steps:
    #   * the subject's own count N(a)          -> its own release offsets
    #   * each interferer's N_J(a + D_i - D_j)  -> a = kT_j + m*t_j + D_j
    #                                                  - J_j - D_i
    # This used to read `cands = lane.arrivals(horizon)` -- the first set only
    # -- which misses every offset where an interferer's deadline lines up
    # with the subject's. MEASURED: below TChecker's exact worst case on 7 of
    # 8 queue-depth-one instances, and below the full set on 184 of 6,601
    # lane-instances with NO jitter at all. `spuri_candidates=False` keeps the
    # old search ONLY so `gate_spuri_candidates` can show it failing.
    cands = (spuri_candidate_set(lane, lanes, horizon) if spuri_candidates
             else lane.arrivals(horizon))
    cnt = (lambda o, x: o.N_J(x)) if jitter_in_interference else (lambda o, x: o.N(x))
    for a in cands:
        B, who = blocking_at_b(lane, lanes, a)
        # ⭐ THE SUBJECT'S OWN EARLIER-INSTANCE TERM IS DELIBERATELY *NOT*
        # JITTER-INFLATED, matching `rta_spuri`'s `floor(a/T_i)*C_i`. `a` is the
        # subject's own NOMINAL offset, so its predecessors in the busy period
        # are exactly the nominal releases in [0, a) -- a set jitter cannot add
        # to from the future, because a release can only be delayed, never
        # advanced. The subject's own delay is accounted once, in `+ lane.J`
        # below; inflating here as well would charge the same uncertainty twice
        # on the lanes that already pay it. `price_subject_inflation()` measures
        # the variant rather than leaving the choice as a remark.
        base = (lane.N(a) - 1) * lane.C + B
        L = max(base, 1)
        for _ in range(100_000):
            nxt = base + sum(
                min(cnt(o, L), cnt(o, a + lane.D - o.D)) * o.C
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

    ⛔⛔⛔ THIS GATE PASSED WHILE THE BUG IT EXISTS TO CATCH WAS PRESENT, AND THE
    REASON IS THE REASON, NOT AN ACCIDENT. Every lane it built took the default
    `J = 0`. The bursty interference sum had dropped BOTH jitter terms that
    `w_contribution` carries -- and at `J = 0` the two expressions are
    identically equal, for every T, every delta, and every deadline. So the gate
    sampled thousands of points, all of them inside the subspace where no
    disagreement can exist, and reported PASS on a sound-looking comparison of
    one correct function against one unsound one. An IDENTITY FILTER sitting in
    the soundness checker itself.

    ⭐ THE FIX IS A SWEEP OVER `J`, NOT ONE MORE CASE. `J = 0` is retained (the
    old behaviour must not move) and every positive J in range is added, with
    the J > 0 cell count asserted NON-ZERO -- so a future refactor that drops
    the jitter arm fails here instead of passing vacuously. That assertion is
    the part a "add a J=2 test" fix would have left out, and it is the part that
    makes this gate unable to repeat its own failure.
    """
    bad = []
    n_j_pos = 0           # cells actually exercised at J > 0 -- asserted below
    # (a) the arrival curve against the corrected release count, SWEPT OVER J
    # ⛔ ENUMERATED WHERE THE SPACE IS SMALL (ruling 3). The arrival curve is
    # arithmetic in T and J, so every small period is swept exhaustively; the
    # three large ones are kept as NAMED REPRESENTATIVES because the inner
    # `delta` loop is O(T) and 434 alone would dominate the run.
    # ⭐ THE SAMPLING RATIONALE, stated because the ruling requires one where
    # enumeration stops: 25, 62 and 434 are the SHIPPED periods (SPI, I2C,
    # UART), so the unenumerated part of the space is covered by the exact
    # values the design uses rather than by arbitrary large numbers.
    for T in list(range(2, 17)) + [25, 62, 434]:
        for J in range(0, 13):
            bl = BLane("x", T, 2, T // 2, n=1, J=J)
            pl = Lane("x", T, C=2, J=J, D=T // 2)
            for delta in range(0, 3 * T + 5):
                # the NOMINAL curve is jitter-free by definition
                got = bl.N(delta)
                want = floor_div(delta, T) + 1
                if got != want:
                    bad.append(("curve", (T, J), delta, got, want))
                # the INFLATED curve is Spuri's release count, J and all
                gotJ = bl.N_J(delta)
                wantJ = floor_div(delta + J, T) + 1
                if gotJ != wantJ:
                    bad.append(("curve_J", (T, J), delta, gotJ, wantJ))
                # and the real interference term, deadline cap and all
                g2 = min(bl.N_J(delta), bl.N_J(0 + 50 - bl.D)) * bl.C
                w2 = w_contribution(pl, 0, delta, 50)
                if g2 != w2:
                    bad.append(("w_contribution", (T, J), delta, g2, w2))
                if J > 0:
                    n_j_pos += 1
    # (b) whole-recurrence equality on the real required set, AT J > 0 TOO
    for J in (0, 1, 4):
        per = [Lane("UART", 434, C=2, J=J, D=216), Lane("SPI", 25, C=2, J=J, D=12),
               Lane("I2C", 62, C=2, J=J, D=30)]
        bur = [BLane("UART", 434, 2, 216, J=J), BLane("SPI", 25, 2, 12, J=J),
               BLane("I2C", 62, 2, 30, J=J)]
        for i in range(3):
            a = response_time_spuri(per[i], per, plus_one=0)["r"]
            b = response_time_b(bur[i], bur)["r"]
            if a != b:
                bad.append(("recurrence", (per[i].name, J), None, b, a))
    # ⛔ THE ANTI-VACUITY ASSERTION. Without it this gate can go back to being
    # green-by-construction the moment the J arm is dropped or short-circuited.
    if n_j_pos == 0:
        bad.append(("VACUOUS", "no J>0 cell was exercised -- this gate is the "
                    "identity filter again", None, 0, 1))
    if verbose:
        print("  n=1 reduction gate: %s"
              % ("PASS -- bursty form is the periodic form at n=1 "
                 "(curve, inflated curve, interference term, and whole "
                 "recurrence), over T in 2..16 + {25,62,434} and J in 0..12 "
                 "EXHAUSTIVELY: %d cells at J>0"
                 % n_j_pos if not bad
                 else "*** FAIL: %d mismatches, first %s ***" % (len(bad), bad[0])))
    return not bad


def assert_jitter_reaches_interference(verbose: bool = True) -> bool:
    """MUST-FIRE: one lane's jitter has to be able to move ANOTHER lane's r.

    ⛔⛔ THE FACE THAT MATTERS IS THE SECOND ONE. It is not enough that the fixed
    recurrence produces a larger number -- a bound that is merely bigger proves
    nothing, since multiplying every `r` by two would also pass. What has to be
    shown is that the OLD form was BLIND: that with the nominal curve in the
    interference sum, lane j's jitter changed lane i's response by exactly
    nothing, so the term was not understated but ABSENT.

    THE CONSTRUCTION. The subject carries `J_i = 0` and the interferer carries
    all the jitter. That isolates the direction under test: `r_i = L + C_i +
    J_i - a` cannot move through `J_i`, so any change in `r_i` is attributable
    to the interference lane j imposes, which is the only thing the fix touched.

    THREE FACES:
      (1) jitter must MATTER         r_new(J_j>0) >  r(J_j=0)
      (2) the old form must be BLIND r_old(J_j>0) == r(J_j=0)
      (3) the direction must be the UNSAFE one  r_old < r_new
    """
    # T_i=8, T_j=7, C=2, D_i=4, D_j=5, J_j=1 -- smallest instance found by a
    # sweep of 181 such cases, so this is a representative and not a curiosity.
    def build(J_j):
        li = BLane("subject", 8, 2, 4, J=0)
        lj = BLane("jittery", 7, 2, 5, J=J_j)
        return li, [li, lj]

    li1, set1 = build(1)
    li0, set0 = build(0)
    r_nojit = response_time_b(li0, set0)["r"]
    r_old = response_time_b(li1, set1, jitter_in_interference=False)["r"]
    r_new = response_time_b(li1, set1, jitter_in_interference=True)["r"]

    f1 = r_new > r_nojit
    f2 = r_old == r_nojit
    f3 = r_old < r_new
    ok = f1 and f2 and f3
    if verbose:
        print("  jitter-reaches-interference MUST-FIRE  "
              "(subject J=0, interferer J=1, T=8/7, C=2, D=4/5)")
        print("      r with J_j = 0                  %d" % r_nojit)
        print("      r with J_j = 1, OLD nominal sum  %d   %s"
              % (r_old, "BLIND -- identical to J=0" if f2 else "(moved)"))
        print("      r with J_j = 1, jitter-inflated  %d" % r_new)
        print("      face 1 jitter matters      %s" % ("PASS" if f1 else "FAIL"))
        print("      face 2 old form was blind  %s" % ("PASS" if f2 else "FAIL"))
        print("      face 3 error was UNSAFE    %s" % ("PASS" if f3 else "FAIL"))
        if ok:
            print("      ⛔ the old sum under-reported by %d cycles = %d whole "
                  "j-jobs. Not a rounding gap: an absent term."
                  % (r_new - r_old, (r_new - r_old) // 2))
        print("      ⚠ EXACT TRUTH IS NOT CLAIMED HERE. This shows the old form "
              "unsound and the new form larger; that the new form is CORRECT is "
              "TChecker's to say (zone/run_jitter.py), not this gate's.")
    return ok


def price_jitter_blocking(verbose: bool = True) -> dict:
    """Does the blocking filter need jitter? Checked against the jitter model.

    ⛔ WHAT THIS CAN AND CANNOT SETTLE. It checks the shipped filter against the
    SAME jitter model re-expressed -- which catches a sign slip or an off-by-one
    between the algebra and the code, and nothing more. It is a same-author
    re-derivation and is labelled as one. Whether the blocking TERM itself is a
    sound bound under jitter is TChecker's question, because non-preemption is
    emergent in that model and B is not encoded at all: if B were wrong under
    jitter, the foreign checker would disagree on a constructed instance.
    """
    # ⛔⛔ EXHAUSTIVE OVER A DECLARED RANGE, NOT A HAND-PICKED GRID
    # (Wilson's ruling 3). This read
    #     T_i in (4,5,8,11), T_j in (3,5,7,13), D_i in (3,5,9),
    #     D_j in (4,6,11),   J_j in (1,3,8)
    # -- 432 points chosen by hand. The project has now had a must-fire's
    # witness slide between hand-chosen constants THREE times: two constants,
    # then a list of constants, then `T = 13` falling between 2.0 and 1.5 MHz
    # in `gate_lane_class`. A disagreement between two expressions of one
    # formula is an ARITHMETIC fact over small integers, and small integers
    # are enumerable.
    # ⭐ THE RANGE IS THE RATIONALE: periods 2..12 and deadlines 2..12 cover
    # every ordering of the five quantities that the blocking term branches
    # on, and a disagreement that needs a period above 12 to appear would be
    # a disagreement about overflow, not about the algebra -- a different
    # claim, and one this must-fire does not make.
    # ⚠ 11 x 11 x 11 x 11 x 8 is 117k instances before the arrival loop, so
    # the bound is kept modest on purpose; it is still 270x the hand grid.
    moved = []
    n = 0
    for T_i in range(2, 13):
        for T_j in range(2, 13):
            for D_i in range(2, 13):
                for D_j in range(2, 13):
                    for J_j in range(0, 8):
                        li = BLane("i", T_i, 2, D_i, J=0)
                        lj = BLane("j", T_j, 3, D_j, J=J_j)
                        ls = [li, lj]
                        n += 1
                        for a in li.arrivals(2 * max(T_i, T_j)):
                            b0 = blocking_at_b(li, ls, a)[0]
                            b1 = blocking_at_b_from_jitter_model(li, ls, a)[0]
                            if b0 != b1:
                                moved.append((T_i, T_j, D_i, D_j, J_j, a, b0, b1))
                                break
    out = {"n": n, "moved": moved}
    if verbose:
        print("  blocking filter vs the jitter model: %d instances swept, "
              "%d disagree" % (n, len(moved)))
        if moved:
            print("      *** the shipped filter and the model-derived filter "
                  "DISAGREE, first %s -- one of the two is wrong ***"
                  % (moved[0],))
        else:
            print("      the shipped `D_j > a + D_i` IS the widest case the "
                  "jitter model admits (the max over s in [-J_j,0] is at s=0),")
            print("      so jitter adds only blockers with EARLIER deadlines, "
                  "which the filter rejects. ⚠ same-author check: soundness of")
            print("      the B term under jitter is TChecker's to confirm.")
        print("      ⛔ RETRACTED: the first version of this probe tested "
              "`D_j + J_j > a + D_i` and reported 184 of 432 instances moved")
        print("         -- 432 being the HAND-PICKED grid this sweep replaced;"
              " it is exhaustive now (ruling 3).")
        print("         That is not a jittered deadline -- a late release has "
              "LESS slack, not a later deadline. The probe was the bug.")
    return out


def price_subject_inflation(verbose: bool = True) -> dict:
    """Would inflating the SUBJECT's own earlier-instance count change r?

    The recurrence deliberately leaves `(N_i(a) - 1)*C_i` un-inflated. This
    reports what the alternative would cost, so "not inflated" is a priced
    decision rather than an unexamined one.
    """
    rows = []
    for J in (1, 3, 8):
        for T_i in (5, 8, 25):
            li = BLane("i", T_i, 2, 6, J=J)
            lj = BLane("j", 7, 2, 9, J=J)
            ls = [li, lj]
            r = response_time_b(li, ls)["r"]
            # the inflated-subject variant, computed inline so the production
            # path keeps ONE recurrence and no mode flag it could be run in.
            best = None
            L_busy = busy_period_b(ls)
            for a in li.arrivals(L_busy + max(l.T for l in ls)):
                B = blocking_at_b(li, ls, a)[0]
                base = (li.N_J(a) - 1) * li.C + B        # <- the variant
                L = max(base, 1)
                for _ in range(100_000):
                    nxt = base + sum(min(o.N_J(L), o.N_J(a + li.D - o.D)) * o.C
                                     for o in ls if o is not li)
                    if nxt == L:
                        break
                    if nxt < L:
                        L = nxt
                        break
                    L = nxt
                rr = L + li.C + li.J - a
                if best is None or rr > best:
                    best = rr
            rows.append((J, T_i, r, best, best - r))
    if verbose:
        print("  subject-own-inflation pricing (NOT applied):")
        print("      %-5s %-6s %-9s %-11s %s"
              % ("J", "T_i", "r shipped", "r inflated", "cost"))
        for J, T_i, r, b, d in rows:
            print("      %-5d %-6d %-9d %-11d %+d" % (J, T_i, r, b, d))
        print("      ⭐ the gap is the SAME uncertainty charged twice: once as an"
              " extra own-instance, once in `+ lane.J`. Recorded, not applied;")
        print("      TChecker decides it on the constructed instances.")
    return {"rows": rows}


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

# ⛔⛔ J_PIPE -- DERIVED AND *NOT APPLIED*. READ THIS BEFORE QUOTING ANY r_i.
# =============================================================================
# THE SHIPPED LANES BELOW CARRY NO `J` AT ALL, SO EVERY PUBLISHED r_i AND THE
# "min margin 14" ARE A J = 0 ANALYSIS -- while the stated design point has
# always been "(C = 2, J_pipe = 1)" (frontier.py: "registering the EDF winner
# makes every release uncertain by 1"). So the published numbers match NEITHER
# 1.3 candidate. Logged as an ERROR, not a footnote.
#
# ⭐ S3 then MEASURED the engine and DERIVED the real bound from
# src/pe_engine.v's structure (decomposed in gate_cj_bounds.py):
#     winner registration                1   (frontier.py's original J_pipe)
#     prefetch scan notice               1
#     own refill  (P_REQ/P_WAIT/P_CAP)   3
#     in-flight refill for another lane  3
#     header load                        0   (dispatch is gated on hdr_done)
#                                       ---
#     J_PIPE_DERIVED                      8
# with I2C alone carrying J_PIPE + L_JIT, as the REACTIVE-J lane.
# At that bound the set is still FEASIBLE: r = {18, 15, 12, 17, 13}, MIN MARGIN
# 5, which still clears the margin >= 4 bar. Digest would move to 10b327701c7c.
#
# ⛔⛔ BOTH BLOCKERS ARE NOW RESOLVED, AND THE ANSWER REVERSED THE VERDICT.
#
#   1. RETRACTED -- pyRTA DOES have jitter. The claim "pyRTA's task model has no
#      jitter parameter" was FALSE. It ships `PeriodicWithJitter(period, jitter)`
#      with `max_arrivals(d) = ceil((d + jitter)/period)`, which is Spuri's
#      inflated release count exactly. I read the TASK constructor, saw four
#      fields, and claimed an absence about the MODULE -- the jitter lives in a
#      sibling arrival model, one import away. Same error as the two "full-tree
#      reads" that were truncation artefacts: an ABSENCE claimed from a partial
#      read of the place it would have been. See gate_pyrta_jitter.py.
#
#   2. CONFIRMED AND FIXED -- the recurrence really was unsound. The old sum
#      used the NOMINAL arrival curve in the interference term, so a jittery
#      lane's bunching was invisible to every other lane. TChecker: on the
#      must-fire instance the old sum returns 3 where the true worst case is 4.
#      Not conservative -- wrong, in the forbidden direction. `BLane.N_J` is the
#      fix; `assert_jitter_reaches_interference` is the must-fire; three engines
#      agree on 11 lane-instances (zone/run_jitter.py, gate_pyrta_jitter.py).
#
# ⛔⛔⛔ AND THE NUMBER ABOVE IS WRONG BECAUSE OF (2). "r = {18,15,12,17,13},
# MIN MARGIN 5, still clears the margin >= 4 bar" was computed with the UNSOUND
# sum. With jitter in the interference term:
#
#     J_pipe = 8   r = {18, 15, 16, 19, 15}   MIN MARGIN 1   ⛔ FAILS the bar
#     J_pipe = 7   r = {17, 14, 13, 18, 14}   min margin 4   (passes, exactly)
#     J_pipe = 2   r = {12,  9,  6, 11,  7}   min margin 11
#
# So the design sits ONE cycle outside its own pre-registered margin >= 4 bar at
# the derived J, and the only reason J = 8 ever looked acceptable was the bug.
# The tightest lane is I2C throughout -- it is the one carrying J_PIPE + L_JIT.
# ⭐ THE DROP FROM 4 TO 1 BETWEEN J=7 AND J=8 IS A WHOLE INTERFERER JOB crossing
# into I2C's window, not a rounding effect, which is why no amount of tightening
# elsewhere recovers it.
#
# ⇒ J_PIPE_DERIVED = 8 IS NOT PUBLISHABLE, and not because it is unverified --
#   because verifying it refuted it. The remedy is to reduce J, which is what
#   the double buffer does (DOUBLE_BUFFER_PREREG below).
J_PIPE_DERIVED = 8

# ⭐⭐ DOUBLE BUFFER -- PRE-REGISTERED BEFORE THE RTL IS WRITTEN.
# =============================================================================
# Nathan's call (yes), Wilson's lean (yes), and the sequencing is Wilson's: the
# jitter-sound analysis came FIRST because it is needed at any J. It is now done,
# and it is what turned the double buffer from an optimisation into a
# REQUIREMENT -- at the derived J = 8 the sound recurrence gives min margin 1
# against a pre-registered bar of 4.
#
# THE PREDICTION, WRITTEN DOWN BEFORE THE MEASUREMENT (the whole point):
#   With a second action buffer per lane, the two refill terms disappear from
#   the J decomposition in gate_cj_bounds.py, because a lane's next action is
#   already resident when its current one is dispatched:
#       winner registration                1   stays -- the EDF key is registered
#       prefetch scan notice               1   stays -- the scan is still a cycle
#       own refill  (P_REQ/P_WAIT/P_CAP)   3 -> 0   absorbed by the spare buffer
#       in-flight refill for another lane  3 -> 0   the shared port is no longer
#                                                   on the dispatch path
#       header load                        0   unchanged
#                                         ---
#       J_PIPE_PREDICTED                    2
#
# ⛔ FALSIFIER: if the derivation after the RTL lands comes out ABOVE 2, the
# double buffer did not buy what it was costed for and the ~110 flops are not
# justified by this argument. Report it, do not re-argue the decomposition to
# reach 2 -- that is the same-author re-derivation this project keeps catching.
#
# ⛔ AND IT IS NOT FREE IN VERIFICATION, which is the part a flop count hides:
#   * a buffer-swap invariant (exactly one buffer is the live one per lane, and
#     the swap happens at dispatch, not at refill completion);
#   * a STALE-BUFFER MUTANT -- dispatch from the buffer that was NOT refilled.
#     If the suite stays green with that mutation, the double buffer is
#     untested and its J reduction is unevidenced.
J_PIPE_PREDICTED = 2
DOUBLE_BUFFER_PREREG = {
    "predicted_J_pipe": 2,
    "falsifier": "derived J_pipe > 2 after the RTL lands",
    "owes": ["buffer-swap invariant", "stale-buffer mutant"],
    "cost_flops_estimate": 110,
    "margin_at_predicted_J": 11,      # from the J sweep, bar is >= 4
}

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
# ⭐⭐⭐ THE RE-BASELINE: EVERY LANE NOW CARRIES ITS DERIVED J. Until now the
# shipped table carried J = 0 on all five lanes while the stated design point
# was "(C = 2, J_pipe = 1)" -- so every published r_i was a J = 0 analysis that
# matched NEITHER 1.3 candidate. That is fixed here, and the fix is a DERIVATION
# rather than a measurement:
#
#   J_SHIPPED = gate_j_program.j_of(d_min = 25) = 1
#
# from the refill structure given the shipped program's tightest inner action
# spacing (25 cycles -- SPI and SPI-target at 1 MHz on a 50 MHz clock). The
# shortfall term is max(0, N*L_REFILL - (d_min + C)) = max(0, 20 - 27) = 0, so
# only the winner-registration cycle survives. ⭐ The measurement AGREES: steady
# -state prefetch stall 0 over 3,700 cycles, cold start 0 after
# prime-before-release.
#
# ⛔ J IS A PROGRAM PROPERTY, NOT A CHIP PROPERTY, which is why this is 1 and
# not 8. The UNIVERSAL worst case over every admissible program is 8 (attained
# at the tightest admissible d_min = 8, where U = 1.0), and it is published
# alongside this table rather than inside it -- see `gate_j_program.py`. Putting
# the universal bound in the shipped table would overstate the thing we ship;
# putting the shipped value in the universal claim would understate the things
# we have not written. Both numbers, both labelled.
#
# ⭐ I2C IS THE ONE EXCEPTION AND IT IS NOT AN EXCEPTION TO THE RULE: it carries
# J_SHIPPED + L_JIT, because it is the lane whose release is captured
# asynchronously. An earlier estimate that forgot this was wrong by exactly one.
J_SHIPPED = 1
# ⛔⛔⛔ C = 3, MEASURED, AND IT WAS 2 FOR THE LIFE OF THE PROJECT.
# `docs/PREREG_C_SAT.md` pre-registered the minimum inter-dispatch spacing at 2
# and named 3 as the falsifier; `test/run_csat.py` measured 3 on four arms over
# 32,677 spacings in which a successor was ALREADY ELIGIBLE during the
# predecessor's writeback, and not one of them was 2. The dispatch FSM is a
# THREE-state cycle (ST_IDLE -> ST_DRIVE -> ST_WB -> ST_IDLE) and `ST_WB`
# returns to ST_IDLE unconditionally, so the next dispatch decision cannot be
# taken until the cycle after writeback.
#
# WHY THE OLD FIGURE WAS WRONG ABOUT THE RIGHT NUMBER. `svc_cycles/svc_jobs`
# = 688/344 = 2.00 counts cycles with `st != ST_IDLE`: the engine's OCCUPANCY
# per job. Occupancy is 2 and spacing is 3, both exactly. `C` in a
# response-time analysis is the resource time a job denies to every OTHER job,
# and that is the spacing.
# ⚠ AND IT SURVIVED BECAUSE TWO READINGS AGREED -- a structural derivation
# ("two states, so C = 2") and a simulation mean (2.00), both about occupancy.
# Agreement between two measurements of the same wrong quantity is not
# corroboration.
#
# ⛔ IT IS A NAME, NOT A LITERAL, BECAUSE A DEADLINE CARRIES `C` TOO.
# `SPI_RX`'s `D_tol` is DERIVED by `abs_tolerance(..., C=...)`, which SUBTRACTS
# C -- a reactive lane whose pin moves at service completion spends its whole
# service time out of the peer's setup window. Writing `3` in the lane rows and
# leaving `C=2` in that call would have left the table internally inconsistent,
# which is the "a scope assumption is threaded through the constant too" shape.
# `gate_lane_class` asserts `D_tol == abs_tolerance(25, True, sp.C)` and would
# have caught it -- the guard working is not a reason to rely on it.
C_SHIPPED = 3

TX = [
    BLane("UART-tx 115200", 434, C_SHIPPED, D_tol=216, J=J_SHIPPED,
          note="periodic, one event/bit"),
    # ⭐ D = 23 DERIVED from the MB85RS64V AC table (DS501-00015-6v1-E, refs/),
    # replacing the modelled centre-sample 12. We are the MASTER here, so the
    # peer judges setup/hold against the clock WE generate, not a bit centre:
    #   D = min(N - tSU, N - tCL, N - tCH) = min(25-1, 25-2, 25-2) = 23
    # ⭐ P1.1a CONFIRMED -- the derived value is LOOSER than the stand-in. And
    # adopting it REORDERS the EDF deadlines (23 > D_I2C = 15), which turns out
    # to IMPROVE the set: a too-tight deadline had been distorting EDF into
    # prioritising SPI-tx over lanes that needed it more. Minimum margin across
    # all five lanes rises 9 -> 11; I2C r 7 -> 5, SPI-target r 5 -> 3.
    BLane("SPI-tx 1 MHz", 25, C_SHIPPED, D_tol=23, J=J_SHIPPED,
          note="D derived from MB85RS64V tSU/tCH/tCL"),
    # ⭐ J_SHIPPED + L_JIT -- the only lane with an ASYNCHRONOUSLY captured
    # release, so it pays the async-capture cycle on top of the pipeline term.
    BLane("I2C 400 kHz", 45, C_SHIPPED, D_tol=15, J=J_SHIPPED + L_JIT,
          note="asymmetric SCL 80/45; D derived from UM10204 T11, not modelled; "
               "J = J_SHIPPED + L_JIT (async capture)"),
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
UART_RX = BLane("UART-rx 115200", T=4140, C=C_SHIPPED, D_tol=216 - L_SYNC,
                n=10, t=414,
                J=J_SHIPPED,
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
# ⛔ THE SHIPPED VALUE IS 18 AND IT STAYS 18 EVEN THOUGH C9 = START IS NOW RULED
# AND WOULD ALLOW 20. The label is "CONSERVATIVE, C9-INDEPENDENT": 18 is correct
# under either C9 outcome, so the number does not depend on a decision the RTL
# has not yet honoured. It lifts to 20 only when Phase 2 MEASURES the pin moving
# at service start -- measure first, then widen. Taking the 2 cycles now would
# be billing the schedule for a property of a design that does not exist.
#
# ⭐ IT REORDERS, AND THE FALSIFIER DID NOT FIRE: the derived budget is looser
# than the stand-in (18 > 12), so I2C (15) takes the highest priority and
# SPI-target drops to second. No margin falls -- I2C r goes 5 -> 3 and
# SPI-target 3 -> 5, and the MINIMUM admissibility margin across the set rises
# 11 -> 14. Both C9 variants clear the >= 4 bar at 1 MHz by more than 15 cycles,
# so C9 is NOT decided by 1 MHz feasibility; it is decided by the frequency
# ceiling, which is 1.3's question and not this lane's.
# ⛔⛔ ONE EVENT PER BIT, NOT PER EDGE (Wilson 10-18 ruling 3, built 10-20).
# This lane was modelled as 16 events per byte at t = 25 -- an event on EVERY
# SCK edge. The program that ships (pe_proto.SPITarget, MISO out) answers ONE
# edge per bit: ARM(change-edge) ; SHIFT(MISO). So the real demand is 8 events
# per byte at the SCK period, t = T_ext = 50 at 1 MHz -- the master's claimed
# maximum clock, not anything inside the program. D_tol is unchanged: the
# half-period is still 25. Computed before the change (probe_reports/
# spi_target_b2_prediction.txt, ours and pinned pyRTA): every lane's r and the
# min margin 11 are UNCHANGED; U falls 0.32083 -> 0.26083. The MOSI-capture
# variant (16 events per byte) is witnessed at <= 500 kHz, i.e. t >= 50 too.
SPI_RX = BLane("SPI-target 1 MHz", T=400, C=C_SHIPPED, n=8, t=50,
               J=J_SHIPPED,
               D_tol=abs_tolerance(25, c9_at_completion=True, C=C_SHIPPED),
               note="master-clocked, ONE event per bit (the change-edge), "
                    "8/byte back-to-back: n*t == T; t = T_ext at 1 MHz; "
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
    # ---- the jitter-sound recurrence: the fix, and the evidence it needed ----
    print("JITTER IN THE INTERFERENCE TERM (the W-1 recurrence fix)")
    if not assert_jitter_reaches_interference():
        print("\nABORTING: the must-fire for the jitter fix does not fire. Either")
        print("the fix is not in the interference sum, or the constructed")
        print("instance no longer distinguishes the two forms -- and in both")
        print("cases the fix is unevidenced. Do not read any J > 0 number.")
        return 1
    price_jitter_blocking()
    price_subject_inflation()
    print()
    report(TX, "DRIVING DIRECTION ONLY (Parts 1-3, restated as bursty with n=1)")
    print()
    full = TX + [UART_RX, SPI_RX]
    lane_digest.announce("bursty.py (A2 Part 4, both directions)", full)
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
