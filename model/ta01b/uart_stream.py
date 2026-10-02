"""TA-01b -- UART conformance over an UNBOUNDED run.

The claim: conformance of a chip transmitting frames FOREVER is decidable by
fixpoint reachability over a bounded, resettable clock -- in bounded work, and
covering every run including the infinite one. Unrolling can only ever certify N
frames at cost proportional to N; a CLOSED reachable set with BAD outside it is a
sound safety proof over all of them at once.

⛔⛔ AND BE PRECISE ABOUT WHAT THIS DOES *NOT* SHOW. A bounded integer clock makes
the product plain FINITE-STATE, so BFS-to-closure proves the infinite-run property
on its own. Zones add nothing here. The run-length axis proves FIXPOINT > UNROLL,
which is a SECONDARY result. What forces the timed automaton is the CLOCK RANGE --
and only the PARAMETRIC row (conformance for every baud in a range, proven once)
is a necessity rather than an optimisation, because enumeration cannot even
PHRASE a symbolic period. That row is the reprogrammable chip's actual
correctness statement.

⭐ THE INTER-FRAME IDLE IS NONDETERMINISTIC, not sampled. The executor may idle
for any number of cycles before the next frame, so unbounded-idle-then-frame is
covered BY CONSTRUCTION. TA-01 sampled idle in {0,1,2,3}; that tests phase
independence but cannot speak for "arbitrary". Nondeterminism is what makes
BFS-to-closure a genuine fixpoint rather than trace enumeration.

⛔ THE DATA CONJUNCT NEEDS A *PERIODIC* EXPECTED STREAM. Over an unbounded run an
arbitrary expected sequence needs unbounded position memory and the finiteness
argument dies. The lazy escape -- drop the byte comparison for the loop and check
framing only -- silently makes the data conjunct non-load-bearing again, which is
exactly the regression M5 was added to stop. So: period P, monitor tracks position
mod P, and the mod-P counter is part of the determinism/totality cross-product.

⛔ FRAMING IS VALUE-INDEPENDENT BY CONSTRUCTION: it checks the start level, the
stop level and the hold windows, never a byte value. The data conjunct carries the
pattern check. Neither hides behind the other.
"""

from __future__ import annotations

import sys
from collections import deque

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

F_CLK = 50_000_000
BAUD_DEFAULT = 115200
# ⭐ bit-order-SENSITIVE bytes -- TA-01's palindrome lesson. 0x00/0xFF/0xA5 all
# equal their own bit-reversal and cannot catch an LSB/MSB swap.
STREAM_DEFAULT = (0x55, 0x0F, 0x01)


def bit_period(baud: int = BAUD_DEFAULT, f_clk: int = F_CLK) -> int:
    return round(f_clk / baud)


# ============================================================================
# EXECUTOR -- loops forever over a periodic byte stream
# ============================================================================
E_IDLE, E_START, E_STOP = "eIDLE", "eSTART", "eSTOP"


class StreamExecutor:
    """Emits IDLE -> START -> D0..D7 -> STOP -> (arbitrary idle) -> repeat.

    State: (phase, clock, index-into-stream).

    Mutation knobs exist so the rejection arms are expressible without a second
    model: `bad_frame` selects which stream position is corrupted, `bad_kind`
    selects how.
    """

    def __init__(self, stream=STREAM_DEFAULT, t_bit: int = None,
                 bad_frame: int | None = None, bad_kind: str | None = None,
                 t_exec: int | None = None):
        self.stream = tuple(stream)
        self.p = len(self.stream)
        self.t = t_bit if t_bit is not None else bit_period()
        self.te = t_exec if t_exec is not None else self.t   # executor's own period
        self.bad_frame = bad_frame
        self.bad_kind = bad_kind

    def initial(self):
        return (E_IDLE, 0, 0)

    def _byte(self, idx: int) -> int:
        b = self.stream[idx % self.p]
        if self.bad_kind == "databit" and idx % self.p == (self.bad_frame or 0):
            b ^= 0x08                      # one data bit, framing untouched
        return b

    def successors(self, st):
        """-> [(next_state, emitted_level), ...]. Nondeterministic only in IDLE."""
        phase, x, idx = st
        te = self.te
        if phase == E_IDLE:
            # ⭐ unbounded idle, by construction: stay idle, or begin a frame
            return [((E_IDLE, 0, idx), 1), ((E_START, 0, idx), 0)]
        if phase == E_START:
            if x + 1 < te:
                return [((E_START, x + 1, idx), 0)]
            return [((f"eD0", 0, idx), 0)]
        if phase == E_STOP:
            lv = 1
            if self.bad_kind == "stoplow" and idx % self.p == (self.bad_frame or 0):
                lv = 0
            elif self.bad_kind == "stopcenterlow" and idx % self.p == (self.bad_frame or 0):
                # ⛔ low from the stop-bit CENTRE onward -- single-point sampling
                # at the centre is glitch-BLIND, so a dip that recovers would not
                # be seen. This drives low THROUGH the sample so it must fire.
                lv = 0 if x >= te // 2 else 1
            if x + 1 < te:
                return [((E_STOP, x + 1, idx), lv)]
            return [((E_IDLE, 0, (idx + 1) % self.p), lv)]
        if phase.startswith("eD"):
            k = int(phase[2:])
            b = self._byte(idx)
            nbits = 7 if (self.bad_kind == "sevenbits"
                          and idx % self.p == (self.bad_frame or 0)) else 8
            lv = (b >> k) & 1
            if x + 1 < te:
                return [((phase, x + 1, idx), lv)]
            return [((f"eD{k+1}" if k + 1 < nbits else E_STOP, 0, idx), lv)]
        raise AssertionError("unknown executor phase %r" % phase)


# ============================================================================
# MONITOR -- re-arming receiver, tracks position mod P
# ============================================================================
# ⛔ BAD IS SPLIT BY CONJUNCT. In TA-01b the rejection arms were only checked for
# "reaches BAD" -- which is a colour, not a reason. R3 (one data bit flipped,
# framing perfect) is supposed to die by the DATA conjunct; if it died by framing
# the data conjunct would still be untested and M5's lesson would have rotted in
# the loop's blind spot, invisible to the zone model which cannot see data at all.
M_IDLE, M_START, M_STOP = "IDLE", "START", "STOP"
M_BAD_FRAME, M_BAD_DATA = "BAD_FRAME", "BAD_DATA"
BAD_STATES = (M_BAD_FRAME, M_BAD_DATA)


def mD(k: int) -> str:
    return "D%d" % k


class StreamReceiver:
    """Deterministic, TOTAL, re-arming model receiver.

    Config: (state, clock, bits, pos). `pos` is the position in the PERIODIC
    expected stream -- without it the data conjunct cannot survive an unbounded
    run, and dropping the data conjunct is the M5 regression.

    ⛔ Every state carries a catch-all so the relation is TOTAL BY CONSTRUCTION.
    A state with no enabled transition DROPS the behaviour, never reaches BAD, and
    reads as CONFORMING -- the silent-drop hole, now on two new axes (the re-arm
    and the arbitrary-idle wait).
    """

    def __init__(self, stream=STREAM_DEFAULT, t_bit: int = None, n: int = 8):
        self.expected = tuple(stream)
        self.p = len(self.expected)
        self.t = t_bit if t_bit is not None else bit_period()
        self.half = self.t // 2
        self.n = n

    def initial(self):
        return (M_IDLE, 0, (), 0)

    def states(self):
        return [M_IDLE, M_START] + [mD(k) for k in range(self.n)] + [M_STOP] + list(BAD_STATES)

    def step(self, cfg, level: int):
        st, x, bits, pos = cfg
        if st in BAD_STATES:
            return (st, 0, bits, pos)

        if st == M_IDLE:
            # arbitrary-length wait; a falling edge opens the frame
            return (M_START, 0, (), pos) if level == 0 else (M_IDLE, 0, (), pos)

        if st == M_START:
            if x < self.half:
                return (M_START, x + 1, bits, pos)
            if x == self.half:
                # FRAMING conjunct -- value-independent
                return (mD(0), 0, (), pos) if level == 0 else (M_BAD_FRAME, 0, bits, pos)
            return (M_BAD_FRAME, 0, bits, pos)                      # catch-all

        for k in range(self.n):
            if st == mD(k):
                if x < self.t:
                    return (st, x + 1, bits, pos)
                if x == self.t:
                    nxt = mD(k + 1) if k + 1 < self.n else M_STOP
                    return (nxt, 0, bits + (level,), pos)
                return (M_BAD_FRAME, 0, bits, pos)                  # catch-all

        if st == M_STOP:
            if x < self.t:
                return (M_STOP, x + 1, bits, pos)
            if x == self.t:
                if level != 1:
                    return (M_BAD_FRAME, 0, bits, pos)        # FRAMING conjunct
                got = self.decode(bits)
                if got is None or got != self.expected[pos]:
                    return (M_BAD_DATA, 0, bits, pos)         # DATA conjunct
                # ⭐ THE RE-ARM: back to IDLE, advance the expected position
                return (M_IDLE, 0, (), (pos + 1) % self.p)
            return (M_BAD_FRAME, 0, bits, pos)                      # catch-all

        return (M_BAD_FRAME, 0, bits, pos)

    @staticmethod
    def decode(bits):
        """LSB-first. Kept as a separate conjunct from the comparison above."""
        if len(bits) != 8:
            return None
        return sum(b << i for i, b in enumerate(bits))


# ============================================================================
# GATE 1 -- determinism + totality, now INCLUDING the mod-P axis
# ============================================================================
def determinism_totality(rx: StreamReceiver) -> dict:
    """Full (state x clock x level x pos) cross-product.

    ⛔ `pos` is in the cross-product deliberately: forgetting the new counter
    reopens the totality hole on a fresh axis, which is how the trap recurs.
    """
    cmax = rx.t + 2
    multi, none = [], []
    for st in rx.states():
        for x in range(cmax + 1):
            for pos in range(rx.p):
                for lv in (0, 1):
                    succ = rx.step((st, x, (0,) * 8, pos), lv)
                    n = 1 if succ is not None else 0
                    if n == 0:
                        none.append((st, x, pos, lv))
    return {
        "checked": len(rx.states()) * (cmax + 1) * rx.p * 2,
        "states": len(rx.states()), "clock_values": cmax + 1, "positions": rx.p,
        "nondeterministic": multi, "incomplete": none,
        "deterministic": not multi, "total": not none,
    }


# ============================================================================
# THE FIXPOINT -- BFS to closure over (executor || monitor)
# ============================================================================
def fixpoint(ex: StreamExecutor, rx: StreamReceiver, cap: int = 4_000_000) -> dict:
    """Reachability to CLOSURE. Closed set + BAD outside it = safety over EVERY
    run, including the infinite one.

    ⛔ THE RESET DIAGNOSTICS ARE TERMINATION AND MAX CLOCK -- not "flat in frame
    count", which is trivially true of a fixpoint and tests nothing. A clock that
    fails to reset makes the state space unbounded, so BFS simply will not
    terminate.
    """
    start = (ex.initial(), rx.initial())
    seen = {start}
    q = deque([start])
    bad_witness = None
    reasons = set()
    max_clock = 0
    frontier_steps = 0
    while q:
        e, m = q.popleft()
        frontier_steps += 1
        if frontier_steps > cap:
            return {"closed": False, "reason": "cap exceeded", "states": len(seen),
                    "max_clock": max_clock, "bad": bad_witness}
        for ne, lv in ex.successors(e):
            nm = rx.step(m, lv)
            max_clock = max(max_clock, nm[1])
            if nm[0] in BAD_STATES:
                reasons.add(nm[0])
                if bad_witness is None:
                    bad_witness = {"exec": e, "mon": m, "level": lv, "why": nm[0]}
            nxt = (ne, nm)
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return {"closed": True, "states": len(seen), "max_clock": max_clock,
            "bad_reachable": bad_witness is not None, "bad": bad_witness,
            "reasons": sorted(reasons), "steps": frontier_steps}


# ============================================================================
# GATE 0 support -- a MULTI-FRAME waveform for the foreign decoder
# ============================================================================
def stream_waveform(ex: StreamExecutor, n_frames: int, idle_cycles: int = 3) -> list:
    """A concrete run: `idle_cycles` of idle before each frame, n_frames total.

    ⭐ A STREAM, not one frame, is what sigrok is actually built to decode -- so
    the foreign authority gets stronger as the stack grows rather than weaker.
    """
    # ⛔ FRAMES ARE COUNTED ON *COMPLETION*, NOT ON START. Counting at the start
    # truncates the final frame mid-flight; sigrok then reports "Frame error" on
    # an otherwise-valid stream and gate 0 fails for a BENCH reason. That is
    # exactly what happened on the first run of this function.
    levels, st = [], ex.initial()
    started = done = 0
    idle_left = idle_cycles
    while done < n_frames:
        succs = ex.successors(st)
        if len(succs) > 1:                       # IDLE: choose deterministically
            if idle_left > 0 or started >= n_frames:
                nxt, lv = succs[0]
                idle_left = max(0, idle_left - 1)
            else:
                nxt, lv = succs[1]; idle_left = idle_cycles; started += 1
        else:
            nxt, lv = succs[0]
            if st[0] == E_STOP and nxt[0] == E_IDLE:
                done += 1                        # the frame has FINISHED
        levels.append(lv)
        st = nxt
    levels += [1] * (2 * ex.te)                  # trailing idle
    return levels


def dump_stream(ex: StreamExecutor, path: str, n_frames: int,
                idle_cycles: int = 3) -> int:
    w = stream_waveform(ex, n_frames, idle_cycles)
    with open(path, "wb") as fh:
        fh.write(bytes(l & 1 for l in w))
    return len(w)
