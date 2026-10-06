"""THE GOLDEN MODEL of the self-clocked phase machine. Written BEFORE the RTL.

⛔⛔ WHY THIS FILE EXISTS, as a root cause rather than a preference. The first
self-clocked build went straight to RTL. The retire arithmetic tangled with the
phase register, the clocked SHIFT retired after ONE dispatch instead of
sixteen, and every one of 75 sweep arms passed on it -- because each bench's
success criterion was that pins MOVE, and a program that retires too early
moves pins beautifully. The defect was found by COVERAGE (the COLLECT phase's
branch count was 0 in all twelve benches), then mis-diagnosed by me twice: once
as a hang (it progresses: 359 actions retired), and once from a probe whose
loader was wrong (it showed one register holding two values).
⇒ Every block on this project was built golden-model-first and the RTL made
  bit-exact to it. This one skipped that. This is the model.

THE PHASE MACHINE, per action type:

  SHIFT (transmit), n bits -> 2n dispatches
      LOW   drive the data bit, take the clock LOW, ADVANCE the pointer
      HIGH  release/raise the clock. The bit stays on the wire across the rise.
      ... n times, retire on the last HIGH.

  SHIFTIN (receive), n bits -> 2n + 1 dispatches
      LOW   release the data pin, take the clock LOW
      HIGH  release/raise the clock and ARM the capture
      ... n times, then ONE trailing dispatch to CONSUME the last bit.

⛔⛔ WHAT `COLLECT` IS FOR, stated explicitly because the ruling asked:
It is the trailing CONSUME dispatch, and it is FORCED -- not a tidiness choice.
The bit must be sampled on the OBSERVED clock rise (so a stretching peer is
read when it answers, not when we guessed). That rise lands AFTER the high
phase's writeback, in the idle window following it. So at the instant 2n
dispatches have elapsed the last bit's value DOES NOT EXIST YET, and consuming
it costs one more dispatch.
⭐ For n > 1 the intermediate bits need no extra dispatch each: bit k's sample
is consumed at bit k+1's LOW phase. Only the LAST bit has no successor, which
is why the cost is +1 for the whole action and not +1 per bit.
⚠ 2n for a receive is reachable ONLY by sampling at a TIMED instant, which is
exactly what clock stretching breaks. A transmit never reads a bit back, so
SHIFT stays at 2n. The asymmetry is the price of stretch-safe sampling.

INVARIANTS, asserted on every action this model runs:
  I1  the phase is LOW at every action start
  I2  the pointer advances exactly once per bit
  I3  exactly one retire, on the last dispatch
  I4  dispatches == 2n for SHIFT, 2n + 1 for SHIFTIN
  I5  a receive consumes exactly n bits, each one captured at a rise
  I6  the clock returns LOW at the end of an action, so the next action's LOW
      phase starts from a known level and no program needs a separating
      OP_LEVEL
  I8  a stretch of ANY length loses no bits and does not change the dispatch
      count; it shifts the release TIMES only
  I9  a stretch beyond the programmed timeout halts the lane and raises the
      sticky -- a fault, reported, never a silently short byte
  I7  COLLECT is never released before the HIGH job it follows has COMPLETED
      (the one-slot-per-lane condition, r_i <= t_i). It holds by construction
      -- the sample is captured in the idle window AFTER that writeback -- but
      a condition that holds by construction is exactly the kind that stops
      holding silently when the construction changes, so it is asserted.

⛔⛔ CLOCK STRETCHING IS UNBOUNDED, AND THE FIRST VERSION OF THIS FILE GOT IT
WRONG. It modelled the capture as landing in the idle window and said that a
rise later than ONE LANE PERIOD lost its bit. That contradicts what has been
ruled since A2 Part 4 -- the SCL wait is a HARDWARE CONDITION ON THE LANE,
never engine occupancy -- and N1a and R3 build on it: stretching DELAYS the
high phase and NEVER LOSES DATA. UM10204 puts no upper limit on how long a
target may hold SCL low, so a design that drops bits after one lane period is
not stretch-compliant, however cleanly it reports the loss.
⇒ THE LANE IS PARKED AFTER THE HIGH PHASE, exactly the way `OP_ARM` parks a
  lane on an edge: its next dispatch -- the next LOW, or the COLLECT -- is
  RELEASED BY THE OBSERVED RISE rather than by its timestamp. A stretch of any
  length then shifts the lane's TIMING and loses nothing, and the dispatch
  count is untouched at 2n / 2n+1.
⚠ THE TIMEOUT SURVIVES, BUT AS A BUS-FAULT DETECTOR, not a stretch limit: a
  stretch beyond the programmed timeout halts the lane and sets
  `clk_stretch_err` -- the same "a timeout means ERROR, never success" rule
  `OP_ARM` already follows. The difference matters: "the peer is slow" is
  legal and must work; "the peer is gone" is a fault and must be reported.

⚠ WHAT COLLECT COSTS THE TIMING MODEL, which is NOT this file's claim to make
but is recorded here because the dispatch count is: it is an ordinary job in
the lane's job stream with `C = 3`, released reactively by the observed rise
(so it carries `J = 1`), and it makes NO FETCH-PORT DEMAND. Refill was never
part of the A2 task model -- it lives only in the `D*` theorem and per-lane
`J` -- so no new arm is needed. ⛔ But its release spacing from the HIGH job is
about `L_sync`, FAR shorter than the lane's nominal bit spacing, so A2/pyRTA
must model that true minimum separation and `D*`/`d_min` must count only
REFILL-BEARING dispatches or it will refuse every clocked program over a gap
that never touches the port.
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOW, HIGH, COLL = "LOW", "HIGH", "COLL"
SHIFT, SHIFTIN = "SHIFT", "SHIFTIN"


class Lane:
    """One lane's clocked state. ⛔ THE PHASE IS PER-LANE AND RESET AT EVERY
    ACTION START -- which is the ruled fix for the defect. A per-slot field is
    not needed: a lane runs one action at a time, in order, so the phase is the
    progress of the CURRENT action. The bug was never the ownership, it was
    that a new action INHERITED the previous one's leftover phase."""

    def __init__(self, name="L0"):
        self.name = name
        self.phase = LOW
        self.ptr = 0            # bit pointer within the current byte
        self.clk = 1            # the clock line's level (released high at idle)
        self.data_driven = True
        self.captured = None    # a bit latched at an observed rise, unconsumed
        self.rx = []            # bits consumed
        self.tx_sent = []       # bits put on the wire
        self.halted = False     # a stretch past the timeout: a BUS FAULT
        self.stretch_err = False
        self.cfg_err = False    # a degenerate action: refused, lane halted

    def start_action(self):
        """I1: every action starts in LOW, with no stale capture."""
        self.phase = LOW
        self.ptr = 0
        self.captured = None


class Dispatch:
    __slots__ = ("lane", "act", "idx", "phase", "ptr", "retire", "clk",
                 "armed", "consumed", "t", "reactive")

    def __init__(self, lane, act, idx, phase, ptr, retire, clk, armed,
                 consumed, t=0, reactive=False):
        self.lane, self.act, self.idx = lane, act, idx
        self.phase, self.ptr, self.retire = phase, ptr, retire
        self.clk, self.armed, self.consumed = clk, armed, consumed
        # ⭐ THE RELEASE TIME, and whether this dispatch was released by the
        # OBSERVED RISE rather than by the lane's timestamp. The second flag is
        # what the A2 modelling needs: every post-HIGH dispatch on a clocked
        # lane is a REACTIVE release and carries the sync jitter, not just the
        # COLLECT one.
        self.t, self.reactive = t, reactive

    def row(self):
        return [self.lane, self.act, self.idx, self.phase, self.ptr,
                int(self.retire), self.clk, int(self.armed),
                -1 if self.consumed is None else int(self.consumed),
                self.t, int(self.reactive)]


#: the lane period, the sync latency of an observed edge, and the programmed
#: timeout. ⚠ These are the MODEL's units of time, not a claim about the
#: shipped parameters -- the `C` re-measurement is what sets those.
D_PERIOD, L_SYNC, TIMEOUT = 20, 3, 4000


def run_action(lane, act_index, op, nbits, tx_byte=0, peer_bits=None,
               stretch=0, timeout=TIMEOUT, d=D_PERIOD):
    """Dispatch-by-dispatch expansion of ONE clocked action.

    `peer_bits` is what the peer puts on the data line, consumed in order.
    `stretch` is CYCLES the peer holds the clock low past the high phase.

    ⛔⛔ THE LANE IS PARKED AFTER THE HIGH PHASE, ARM-STYLE. Its next dispatch
    is RELEASED BY THE OBSERVED RISE, not by its timestamp, so a stretch of any
    length shifts the release TIMES and loses NOTHING. The first version of
    this model had the capture race an idle window and drop bits past one lane
    period, which contradicted A2 Part 4 / N1a / R3 and would not have been
    stretch-compliant.
    ⚠ `timeout` is a BUS-FAULT bound, not a stretch limit: past it the lane
    HALTS and the sticky is raised, the same way `OP_ARM`'s timeout means error
    and never success.
    """
    assert op in (SHIFT, SHIFTIN), op
    # ⛔⛔ A ZERO BIT COUNT IS A DEFINED REFUSAL, NOT AN ASSERTION FAILURE.
    # `nbits == 0` has no meaning as a shift, and the silicon's answer is to
    # HALT the lane and set the existing `config_err` sticky -- so the model
    # must say the same thing, or Layer B has no entry to compare against and
    # the RTL's behaviour on it would be unverifiable.
    # ⚠ TWO WAYS TO REACH IT in the ISA, which is why the engine guards the
    # COMPUTED `ck_nbits` and not the raw field: a clocked SHIFTIN with
    # `count = 0`, and a clocked SHIFT with `count = 15`, where `a_cnt + 1`
    # wraps to 0 in the 4-bit field.
    if nbits == 0:
        lane.start_action()
        lane.halted = True
        lane.cfg_err = True
        return []                       # no dispatch, no clock edge, no bits
    assert 1 <= nbits <= 8, nbits
    peer_bits = list(peer_bits or [0] * nbits)
    lane.start_action()
    out = []
    i = 0
    bits_done = 0
    pending = None          # a rise armed; the lane is parked until it arrives
    t = 0                   # the release time of the dispatch about to run
    reactive = False        # was THIS dispatch released by the rise

    while True:
        armed = False
        consumed = None
        retire = False
        # ⛔ RECORD THE PHASE THIS DISPATCH EXECUTES, captured BEFORE the body
        # mutates it. The first version read `lane.phase` afterwards and every
        # row came out "LOW" -- a trace that cannot distinguish the phases is
        # useless as an authority, and it also made the I1 arm unfireable.
        ph_exec = lane.phase

        if lane.phase == LOW:
            # ⭐ THE POINTER ADVANCES ON THE LOW PHASE ONLY (I2). The high
            # phase emits no new bit -- it exists so the bit already on the
            # wire is read across a rise -- so advancing there would consume
            # two payload bits per clock cycle. That is precisely the defect
            # the old corpus idiom had.
            lane.clk = 0
            if op == SHIFT:
                lane.tx_sent.append((tx_byte >> bits_done) & 1)
                lane.data_driven = True
            else:
                lane.data_driven = False      # condition (a): RELEASED
                # consume the bit captured during the previous idle window
                if lane.captured is not None:
                    consumed = lane.captured
                    lane.rx.append(consumed)
                    lane.captured = None
            lane.ptr += 1
            bits_done += 1
            lane.phase = HIGH

        elif lane.phase == HIGH:
            lane.clk = 1                      # released; the peer may hold it
            if op == SHIFTIN:
                armed = True
                pending = peer_bits[bits_done - 1]
            if bits_done >= nbits:
                if op == SHIFT:
                    retire = True             # I4: 2n for a transmit
                    lane.phase = LOW          # I6: clock ends LOW for SHIFT
                    lane.clk = 0
                else:
                    lane.phase = COLL
            else:
                lane.phase = LOW

        else:                                  # COLL -- the trailing consume
            lane.clk = 0                       # I6
            if lane.captured is not None:
                consumed = lane.captured
                lane.rx.append(consumed)
                lane.captured = None
            retire = True                      # I4: 2n + 1 for a receive
            lane.phase = LOW

        out.append(Dispatch(lane.name, act_index, i, ph_exec, lane.ptr,
                            retire, lane.clk, armed, consumed, t, reactive))

        # ---- the gap to the NEXT dispatch -------------------------------
        # ⛔⛔ A PARK, NOT A RACE. If a capture was armed by this high phase,
        # the lane waits for the OBSERVED RISE: the next dispatch is released
        # `stretch + L_SYNC` after this one, however long `stretch` is, and the
        # bit is in hand when it runs. Nothing is lost at any stretch length.
        if pending is not None:
            if stretch > timeout:
                # ⚠ A BUS FAULT, not a slow peer: halt and report. The bits
                # already taken stand; the action does NOT complete.
                lane.halted = True
                lane.stretch_err = True
                break
            t = t + stretch + L_SYNC
            lane.captured = pending
            pending = None
            reactive = True        # released by the rise
        else:
            t = t + d
            reactive = False

        i += 1
        if retire:
            break
        assert i <= 2 * nbits + 2, "runaway action: %s n=%d" % (op, nbits)
    return out


def expand(op, nbits):
    """The expected phase sequence, as a list. The single authority."""
    seq = []
    for _b in range(nbits):
        seq += [LOW, HIGH]
    if op == SHIFTIN:
        seq += [COLL]
    return seq


def check_invariants(op, nbits, disp, lane):
    """I1-I6. Returns a list of violations."""
    bad = []
    want = expand(op, nbits)
    # ⛔ THE RECORDED PHASES, not a recomputation. The first version rebuilt the
    # sequence from scratch starting at LOW, which made I1 unfireable: it could
    # not see an action that STARTED in an inherited phase, and that is the one
    # defect this model was written to catch.
    got = [d.phase for d in disp]
    if got != want:
        bad.append("phase sequence %s, expected %s"
                   % ("/".join(got), "/".join(want)))
    if len(disp) != len(want):
        bad.append("I4: %d dispatch(es), expected %d (%s n=%d)"
                   % (len(disp), len(want), op, nbits))
    if got[:1] != [LOW]:
        bad.append("I1: the action did not start in LOW (started %s)" % got[0])
    if lane.ptr != nbits:
        bad.append("I2: pointer advanced %d time(s), expected %d"
                   % (lane.ptr, nbits))
    nret = sum(1 for d in disp if d.retire)
    if nret != 1:
        bad.append("I3: %d retire(s), expected exactly 1" % nret)
    elif not disp[-1].retire:
        bad.append("I3: the retire is not on the last dispatch")
    if op == SHIFTIN:
        if len(lane.rx) != nbits:
            bad.append("I5: consumed %d bit(s), expected %d"
                       % (len(lane.rx), nbits))
        narm = sum(1 for d in disp if d.armed)
        if narm != nbits:
            bad.append("I5: armed %d capture(s), expected %d" % (narm, nbits))
    if disp[-1].clk != 0:
        bad.append("I6: the clock is %d at the end, expected 0"
                   % disp[-1].clk)
    # I7: a COLLECT dispatch must come strictly AFTER the HIGH it follows, and
    # may consume only a bit captured in the window between them. A COLLECT
    # that consumed nothing means the bit was never there to take.
    for i, d in enumerate(disp):
        if d.phase != COLL:
            continue
        if i == 0 or disp[i - 1].phase != HIGH:
            bad.append("I7: a COLLECT at dispatch %d does not follow a HIGH"
                       % i)
        elif d.consumed is None:
            bad.append("I7: the COLLECT at dispatch %d consumed nothing, so "
                       "the sample it exists to take never arrived" % i)
    return bad


# --------------------------------------------------------------------------
# THE PROGRAMS. ⛔ The model runs the REAL ones, not toys: the corpus lanes it
# must reproduce, and the two FRAM transactions the whole clocked scheme exists
# to make fit (a full 4-byte write at 75 bytes, a random read at 90).
# --------------------------------------------------------------------------
def fram_write_actions(nbytes=4):
    """S | dev | A | addrhi | A | addrlo | A | data | A | P -- per wire byte a
    clocked SHIFT of 8 bits then a 1-bit clocked SHIFTIN for the ACK."""
    out = []
    for _b in range(nbytes):
        out += [(SHIFT, 8), (SHIFTIN, 1)]
    return out


def fram_random_read_actions():
    """S | dev+W | A | addrhi | A | addrlo | A | Sr | dev+R | A | data | A- | P"""
    out = []
    for _b in range(3):                      # dev+W, addrhi, addrlo
        out += [(SHIFT, 8), (SHIFTIN, 1)]
    out += [(SHIFT, 8), (SHIFTIN, 1)]        # dev+R after the repeated START
    out += [(SHIFTIN, 8)]                    # the data byte read IN
    out += [(SHIFT, 1)]                      # the master's NACK
    return out


PROGRAMS = {
    "corpus_i2c lane0":      [(SHIFT, 8), (SHIFTIN, 1)],
    "corpus_spim lane0":     [(SHIFT, 8), (SHIFTIN, 8)],
    "corpus_all5 lane0":     [(SHIFT, 8), (SHIFTIN, 1)],
    "corpus_all5 lane2":     [(SHIFT, 8), (SHIFTIN, 8)],
    "FRAM write n=4":        fram_write_actions(4),
    "FRAM random read":      fram_random_read_actions(),
}


def run_program(name, actions, stretch=0):
    lane = Lane("L0")
    trace, rc = [], 0
    print("  %s" % name)
    for ai, (op, n) in enumerate(actions):
        disp = run_action(lane, ai, op, n,
                          tx_byte=0xA5, peer_bits=[0] * n, stretch=stretch)
        # ⛔ `start_action` ALREADY ZEROED THE POINTER, so the per-action count
        # IS `lane.ptr`. The first version subtracted a "pre" value and read
        # 7-of-8 on every action after the first -- an off-by-one invented by
        # the harness, which would have been read as an RTL defect.
        lane_view = Lane("tmp")
        lane_view.ptr = lane.ptr
        lane_view.rx = lane.rx[-n:] if op == SHIFTIN else []
        bad = check_invariants(op, n, disp, lane_view)
        trace += [d.row() for d in disp]
        print("    %-8s n=%-2d %2d dispatch(es)  %-28s %s"
              % (op, n, len(disp), "/".join(d.phase for d in disp)[:28],
                 "ok" if not bad else "*** " + bad[0]))
        for b in bad[1:]:
            print("        *** %s" % b)
        if bad:
            rc = 1
    return rc, trace


def selftest():
    """⛔ MUTATE THE MODEL: each broken variant must trip a NAMED invariant.
    A model that cannot fail is not a specification, it is a description."""
    print()
    print("  --- must-fire: a broken phase machine trips a named invariant ---")
    rc = 0
    cases = []

    # (a) no phase reset at action start -- THE ACTUAL DEFECT
    def no_reset():
        lane = Lane()
        lane.phase = COLL                    # inherited from a previous action
        lane.ptr = 3
        out, i, bits = [], 0, 0
        # a machine that trusts the inherited phase retires immediately
        out.append(Dispatch("L0", 0, 0, COLL, lane.ptr, True, 0, False, None))
        return check_invariants(SHIFT, 8, out, lane)

    # (b) pointer advances on both phases
    def ptr_twice():
        lane = Lane()
        disp = run_action(lane, 0, SHIFT, 8)
        lane.ptr = 16                        # two per bit
        return check_invariants(SHIFT, 8, disp, lane)

    # (c) a receive with no trailing consume -- 2n instead of 2n+1
    def no_collect():
        lane = Lane()
        disp = run_action(lane, 0, SHIFTIN, 1)
        return check_invariants(SHIFTIN, 1, disp[:-1], lane)

    # (d) two retires
    def two_retires():
        lane = Lane()
        disp = run_action(lane, 0, SHIFT, 2)
        disp[0].retire = True
        return check_invariants(SHIFT, 2, disp, lane)

    cases = [("no phase reset at action start", no_reset, "I1"),
             ("the pointer advances twice per bit", ptr_twice, "I2"),
             ("a receive with no trailing consume", no_collect, "I4"),
             ("two retires in one action", two_retires, "I3")]
    for label, fn, want in cases:
        bad = fn()
        hit = [b for b in bad if b.startswith(want)]
        ok = bool(hit)
        print("    %-40s %s" % (label,
              ("ok -- %s" % hit[0][:40]) if ok
              else "*** wanted %s, got %s" % (want, bad or "a PASS")))
        if not ok:
            rc = 1

    # ⛔ AND THE UNMUTATED MODEL MUST BE SILENT, or the arms above prove nothing.
    lane = Lane()
    d = run_action(lane, 0, SHIFTIN, 8)
    lane2 = Lane("tmp"); lane2.ptr = lane.ptr; lane2.rx = lane.rx
    clean = check_invariants(SHIFTIN, 8, d, lane2)
    print("    %-40s %s" % ("the unmutated model is silent",
                            "ok" if not clean else "*** %s" % clean[0]))
    if clean:
        rc = 1

    # ⛔ THE DEGENERATE BIT COUNT: refused, lane halted, nothing emitted.
    print("    a clocked action with ZERO bits is REFUSED, not undefined")
    for op, n in ((SHIFT, 0), (SHIFTIN, 0)):
        lane = Lane()
        d = run_action(lane, 0, op, n)
        ok = (d == [] and lane.halted and lane.cfg_err)
        print("      %-8s nbits=0  dispatches=%d halted=%-5s cfg_err=%-5s  %s"
              % (op, len(d), lane.halted, lane.cfg_err,
                 "ok" if ok else "*** expected no dispatch + halt + cfg_err"))
        if not ok:
            rc = 1

    # ⛔⛔ I8 -- A STRETCH OF ANY LENGTH LOSES NOTHING. This arm REPLACES one
    # that asserted the opposite: the first model had the capture race an idle
    # window and said a rise later than one lane period dropped its bit. That
    # contradicted A2 Part 4 / N1a / R3 and UM10204, which sets no upper limit
    # on how long a target may hold SCL low. ⇒ The lane PARKS on the rise,
    # ARM-style, so the stretch shifts release TIMES and never data.
    # ⭐ THE OLD ARM PASSED. It was green against the wrong contract, which is
    # why the walk-back came from the RULING and not from a failing test --
    # a test can only check the specification it was given.
    print("    I8: a stretch of ANY length loses no bits (the lane parks)")
    for st in (0, 1, 3, 20, 200, 3999):
        lane = Lane()
        d = run_action(lane, 0, SHIFTIN, 2, peer_bits=[1, 0], stretch=st)
        ok = (len(d) == 5 and lane.rx == [1, 0] and not lane.halted)
        print("      stretch=%-5d %d dispatch(es), bits %s, last release t=%-5d %s"
              % (st, len(d), lane.rx, d[-1].t, "ok" if ok else "*** expected 5 and [1, 0]"))
        if not ok:
            rc = 1

    # ⛔ I9 -- PAST THE TIMEOUT IT IS A BUS FAULT, NOT A SLOW PEER. The lane
    # halts and the sticky is raised: the same "a timeout means ERROR, never
    # success" rule `OP_ARM` follows. ⚠ The distinction is the whole point --
    # "the peer is slow" is legal and must work; "the peer is gone" must be
    # reported, never completed as a short byte.
    print("    I9: a stretch past the timeout halts the lane and reports it")
    for st, want_halt in ((3999, False), (4001, True), (40000, True)):
        lane = Lane()
        d = run_action(lane, 0, SHIFTIN, 2, peer_bits=[1, 0], stretch=st,
                       timeout=4000)
        ok = (lane.halted == want_halt and lane.stretch_err == want_halt)
        print("      stretch=%-6d halted=%-5s sticky=%-5s   %s"
              % (st, lane.halted, lane.stretch_err,
                 "ok" if ok else "*** expected halted=%s" % want_halt))
        if not ok:
            rc = 1

    # ⭐ AND THE REACTIVE RELEASE IS NOW VISIBLE PER DISPATCH, which is what the
    # A2 modelling needs: EVERY post-HIGH dispatch on a clocked lane is
    # released by the observed rise, not just the COLLECT one, so they all
    # carry the sync jitter and a minimum separation of ~L_SYNC.
    lane = Lane()
    d = run_action(lane, 0, SHIFTIN, 8, peer_bits=[0] * 8)
    nreact = sum(1 for x in d if x.reactive)
    ok = (nreact == 8)
    print("    %-52s %s"
          % ("every post-HIGH dispatch is a REACTIVE release (8 of 17)",
             "ok (%d)" % nreact if ok else "*** %d, expected 8" % nreact))
    if not ok:
        rc = 1
    return rc


def main():
    print()
    print("=" * 78)
    print("CLOCKED PHASE -- THE GOLDEN MODEL (written before the RTL)")
    print("=" * 78)
    print("  SHIFT   = 2n dispatches      (LOW drive+clk low, HIGH clk high)")
    print("  SHIFTIN = 2n + 1 dispatches  (+ one trailing CONSUME, forced by")
    print("            sampling on the OBSERVED rise -- see this file's header)")
    print()
    rc = 0
    trace = []
    for name, actions in PROGRAMS.items():
        r, t = run_program(name, actions)
        rc |= r
        trace += t
    rc |= selftest()

    # ⛔⛔ THE BOUNDS GO OUT AS A GENERATED VERILOG TABLE OF **MEASURED** COUNTS,
    # not as a formula the bench re-derives. "2n+1" written a second time in
    # Verilog is the duplicated-constant shape that has cost this project a
    # published column before; and the table is keyed on the RAW `a_cnt` field
    # so the bench does no arithmetic at all -- not even the SHIFT/SHIFTIN
    # off-by-one, which is exactly the kind of detail a second implementation
    # gets subtly wrong.
    root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir))
    vh = os.path.join(root, "test", "clocked_bounds.vh")
    rows = []
    for cnt in range(0, 16):
        for opname, opnum in ((SHIFT, 1), (SHIFTIN, 2)):
            n = cnt + 1 if opname == SHIFT else cnt
            if not 1 <= n <= 8:
                continue
            lane = Lane()
            d = run_action(lane, 0, opname, n)
            rows.append((opnum, cnt, len(d), opname, n))
    with open(vh, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("/* clocked_bounds.vh -- GENERATED by model/clocked_phase.py."
                 " DO NOT EDIT.\n *\n")
        fh.write(" * The expected dispatch count per clocked action, MEASURED"
                 " by running the\n * golden model -- not a formula restated"
                 " in Verilog. Keyed on the RAW\n * `a_cnt` field, so the"
                 " bench performs no arithmetic and cannot reintroduce\n"
                 " * the SHIFT/SHIFTIN off-by-one (`OP_SHIFT` counts"
                 " `a_cnt + 1` bits,\n * `OP_SHIFTIN` counts `a_cnt`).\n"
                 " * -1 means \"not a clocked action\" and the caller must not"
                 " check it.\n */\n")
        fh.write("function integer ck_expect;\n"
                 "  input integer op;\n  input integer cnt;\n  begin\n"
                 "    ck_expect = -1;\n")
        for opnum, cnt, ndisp, opname, n in rows:
            fh.write("    if (op == %d && cnt == %-2d) ck_expect = %-3d;"
                     "  // %s, %d bit(s)\n" % (opnum, cnt, ndisp, opname, n))
        fh.write("  end\nendfunction\n")
    print()
    print("  bounds table -> %s (%d entries, measured)" % (vh, len(rows)))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                       "test", "clocked_trace.json")
    out = os.path.normpath(out)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"columns": ["lane", "act", "idx", "phase", "ptr", "retire",
                               "clk", "armed", "consumed"],
                   "bounds": {"SHIFT": "2n", "SHIFTIN": "2n+1"},
                   "rows": trace}, fh, indent=1)
    print()
    print("  expected trace -> %s (%d dispatch rows)" % (out, len(trace)))
    print("  ⛔ THE MODEL IS THE SINGLE AUTHORITY FOR THE EXACT COUNTS. Layer B")
    print("     of the bench watchdog checks the RTL against THIS, so no bound")
    print("     is recomputed in Verilog -- a constant written twice is this")
    print("     project's most expensive recurring defect.")
    print()
    print("=" * 78)
    print("  MODEL clocked-phase: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
