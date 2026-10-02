"""TA-01 -- UART conformance as a decidable reachability query.

The one claim this probe tests: "does this UART-TX program conform to UART?"
can be ANSWERED, not argued -- as reachability of a BAD state in the product
(executor || deterministic monitor).

⛔⛔ WHY SAFETY AND NOT LANGUAGE INCLUSION. L(E) subset L(S) is UNDECIDABLE for
timed automata in general (the Alur-Dill universality trap). Reachability is
decidable. The two coincide EXACTLY when the monitor is deterministic AND TOTAL:
every behaviour of E then induces exactly one run of S, so "BAD unreachable" is
precisely "every behaviour conforms". ⛔ Both halves are load-bearing and both
are gated mechanically below -- and TOTALITY is the dangerous half, because a
state with NO enabled transition silently DROPS the behaviour, never reaches
BAD, and reads as CONFORMING. That is the empty-reads-as-pass bug in a new
costume.

⭐ THE MONITOR IS DECODE-THEN-COMPARE AS TWO SEPARATE CONJUNCTS. `UartReceiver`
is a pure model receiver that knows nothing about the intended byte; the equality
against B is a separate stage. Tangled, a receiver bug hides behind the
comparison, and "don't encode the executor's internals in the spec" stops being
checkable.

⛔ AND THIS FILE ALONE PROVES NOTHING ABOUT UART. Both the executor and the
monitor are models written by the same hand from the same understanding; a shared
misconception passes every gate here. GATE 0 -- an independent external decoder
(sigrok) reading our waveform -- is what makes this conformance to UART rather
than internal consistency. Nothing downstream is trustworthy until gate 0 holds.
"""

from __future__ import annotations

# ---- the competition's fixed clock, and integer time --------------------
# Integer cycles keep the automaton finite here and dodge dense-clock issues.
F_CLK = 50_000_000
BAUD_DEFAULT = 115200


def bit_period(baud: int = BAUD_DEFAULT, f_clk: int = F_CLK) -> int:
    """Cycles per bit. 50e6/115200 = 434.027... -> 434."""
    return round(f_clk / baud)


# ============================================================================
# THE EXECUTOR UNDER TEST -- a UART-TX program, modelled as the TA its
# transition table induces.
# ============================================================================
class UartExecutor:
    """Drives TX through idle -> start -> 8 data (LSB first) -> stop.

    `t_bit` is the executor's OWN bit period. Making it a parameter is what lets
    the baud-drift mutants exist: the monitor samples at the NOMINAL period while
    the executor emits at this one.

    `data_bits` likewise exists so a wrong-width mutant is expressible.
    """

    def __init__(self, byte: int, t_bit: int, data_bits: int = 8,
                 stop_level: int = 1, idle_level: int = 1, start_level: int = 0,
                 invert: bool = False):
        assert 0 <= byte <= 0xFF
        self.byte = byte
        self.t_bit = t_bit
        self.data_bits = data_bits
        self.stop_level = stop_level
        self.idle_level = idle_level
        self.start_level = start_level
        self.invert = invert

    def _lvl(self, v: int) -> int:
        return (1 - v) if self.invert else v

    def levels(self, idle_cycles: int) -> list[int]:
        """The full waveform as one level per cycle."""
        out = [self._lvl(self.idle_level)] * idle_cycles
        out += [self._lvl(self.start_level)] * self.t_bit
        for k in range(self.data_bits):
            out += [self._lvl((self.byte >> k) & 1)] * self.t_bit
        out += [self._lvl(self.stop_level)] * self.t_bit
        # return to idle, long enough for the monitor to finish and settle
        out += [self._lvl(self.idle_level)] * (2 * self.t_bit)
        return out


# ============================================================================
# THE SPEC -- a deterministic, TOTAL model receiver. Knows NOTHING about B.
# ============================================================================
IDLE, START, STOP, DONE, BAD_FRAME = "IDLE", "START", "STOP", "DONE", "BAD_FRAME"


def data_state(k: int) -> str:
    return f"D{k}"


class UartReceiver:
    """Deterministic, total model receiver. States IDLE->START->D0..D7->STOP->DONE,
    plus absorbing BAD_FRAME.

    Sampling: the clock resets on the falling edge that starts the frame, the
    start bit is sampled at T/2, and every subsequent bit one full T later. That
    is the textbook bit-centre scheme and it is what makes baud drift accumulate
    over the frame rather than cancel.

    ⛔ EVERY STATE HAS A CATCH-ALL. Clock regions that are unreachable in correct
    operation still get an explicit transition (to BAD_FRAME) so the relation is
    TOTAL BY CONSTRUCTION. Without it those regions have no enabled transition,
    the behaviour is dropped, and a non-conforming run reads as conforming.
    """

    def __init__(self, t_bit: int, data_bits: int = 8):
        self.t = t_bit
        self.half = t_bit // 2
        self.n = data_bits

    def initial(self):
        # (state, clock, bits_so_far)
        return (IDLE, 0, ())

    def step(self, cfg, level: int):
        """One cycle. Returns the single successor configuration.

        Deterministic and total by construction -- `determinism_totality_report`
        verifies that mechanically rather than taking this docstring's word.
        """
        state, x, bits = cfg

        if state in (DONE, BAD_FRAME):
            return (state, 0, bits)                      # absorbing

        if state == IDLE:
            # idle high; a falling edge opens the frame and resets the clock
            return (START, 0, ()) if level == 0 else (IDLE, 0, ())

        if state == START:
            if x < self.half:
                return (START, x + 1, bits)
            if x == self.half:
                # sample the start bit: must be low
                return (data_state(0), 0, ()) if level == 0 else (BAD_FRAME, 0, bits)
            return (BAD_FRAME, 0, bits)                  # catch-all: totality

        for k in range(self.n):
            if state == data_state(k):
                if x < self.t:
                    return (state, x + 1, bits)
                if x == self.t:
                    nxt = data_state(k + 1) if k + 1 < self.n else STOP
                    return (nxt, 0, bits + (level,))
                return (BAD_FRAME, 0, bits)              # catch-all

        if state == STOP:
            if x < self.t:
                return (STOP, x + 1, bits)
            if x == self.t:
                # sample the stop bit: must be high
                return (DONE, 0, bits) if level == 1 else (BAD_FRAME, 0, bits)
            return (BAD_FRAME, 0, bits)                  # catch-all

        return (BAD_FRAME, 0, bits)                      # unknown state

    # ---- conjunct 2, kept SEPARATE from the receiver above ----------------
    @staticmethod
    def decoded_byte(bits) -> int | None:
        """LSB-first reconstruction. None if the frame did not complete."""
        if len(bits) != 8:
            return None
        return sum(b << i for i, b in enumerate(bits))

    def states(self) -> list[str]:
        return [IDLE, START] + [data_state(k) for k in range(self.n)] + [STOP, DONE, BAD_FRAME]


# ============================================================================
# GATE 1 -- DETERMINISM and TOTALITY, as two separate mechanical checks
# ============================================================================
def determinism_totality_report(rx: UartReceiver, clock_max: int | None = None) -> dict:
    """Enumerate the full (state x clock x level) cross-product.

    ⛔ The two failures are NOT symmetric. Two enabled transitions breaks the
    safety<->conformance equivalence. ZERO enabled transitions silently drops a
    behaviour so it can never reach BAD -- which reads as CONFORMING. The second
    is the one that flatters.
    """
    if clock_max is None:
        clock_max = rx.t + 2
    multi, none = [], []
    for st in rx.states():
        for x in range(clock_max + 1):
            for lv in (0, 1):
                succs = _enabled(rx, (st, x, ()), lv)
                if len(succs) > 1:
                    multi.append((st, x, lv, succs))
                elif len(succs) == 0:
                    none.append((st, x, lv))
    return {
        "states": len(rx.states()),
        "clock_values": clock_max + 1,
        "checked": len(rx.states()) * (clock_max + 1) * 2,
        "nondeterministic": multi,
        "incomplete": none,
        "deterministic": not multi,
        "total": not none,
    }


def _enabled(rx: UartReceiver, cfg, level: int) -> list:
    """The successors enabled from cfg on `level`.

    `step` is written to return exactly one; this wrapper exists so the gate
    MEASURES that rather than assuming it. A gate that calls the same function it
    is checking would be proving the implementation against itself -- so this
    re-derives enablement from the guard structure instead.
    """
    state, x, bits = cfg
    out = []
    if state in (DONE, BAD_FRAME):
        out.append((state, 0, bits))
    elif state == IDLE:
        out.append((START, 0, ()) if level == 0 else (IDLE, 0, ()))
    elif state == START:
        if x < rx.half:
            out.append((START, x + 1, bits))
        elif x == rx.half:
            out.append((data_state(0), 0, ()) if level == 0 else (BAD_FRAME, 0, bits))
        else:
            out.append((BAD_FRAME, 0, bits))
    elif state == STOP:
        if x < rx.t:
            out.append((STOP, x + 1, bits))
        elif x == rx.t:
            out.append((DONE, 0, bits) if level == 1 else (BAD_FRAME, 0, bits))
        else:
            out.append((BAD_FRAME, 0, bits))
    else:
        for k in range(rx.n):
            if state == data_state(k):
                if x < rx.t:
                    out.append((state, x + 1, bits))
                elif x == rx.t:
                    nxt = data_state(k + 1) if k + 1 < rx.n else STOP
                    out.append((nxt, 0, bits + (level,)))
                else:
                    out.append((BAD_FRAME, 0, bits))
                break
    return out


# ============================================================================
# THE QUERY -- reachability of BAD in (executor || monitor)
# ============================================================================
def conformance(ex: UartExecutor, rx: UartReceiver, expected_byte: int,
                idle_choices=(0, 1, 2, 3)) -> dict:
    """A[] not BAD over the product, with the executor's idle length
    nondeterministic.

    ⭐ The idle nondeterminism is not decoration: it is what proves the monitor
    is PHASE-INDEPENDENT -- that it locks to the falling edge rather than to an
    absolute cycle. A monitor that only works when the frame starts at cycle 0
    would pass a single-trace check and fail on real silicon.
    """
    explored = 0
    for idle in idle_choices:
        wave = ex.levels(idle)
        cfg = rx.initial()
        for cyc, lv in enumerate(wave):
            cfg = rx.step(cfg, lv)
            explored += 1
            if cfg[0] == BAD_FRAME:
                return {"conforms": False, "reason": "framing", "idle": idle,
                        "cycle": cyc, "state_at_bad": cfg, "explored": explored}
        state, _, bits = cfg
        if state != DONE:
            return {"conforms": False, "reason": "frame never completed",
                    "idle": idle, "final_state": state, "bits": bits,
                    "explored": explored}
        got = rx.decoded_byte(bits)                 # conjunct 1: decode
        if got != expected_byte:                    # conjunct 2: compare
            return {"conforms": False, "reason": "byte mismatch", "idle": idle,
                    "decoded": got, "expected": expected_byte, "explored": explored}
    return {"conforms": True, "explored": explored}


# ============================================================================
# GATE 0 support -- the waveform an INDEPENDENT decoder will read
# ============================================================================
def dump_binary(ex: UartExecutor, path: str, idle_cycles: int = 2) -> int:
    """One byte per cycle, bit0 = the TX line. sigrok's `binary` input eats this.

    ⛔ This is the artifact gate 0 turns on: if a foreign decoder cannot read the
    intended byte off this file, our two models agree with each other and not
    with UART.
    """
    wave = ex.levels(idle_cycles)
    with open(path, "wb") as fh:
        fh.write(bytes(lv & 1 for lv in wave))
    return len(wave)
