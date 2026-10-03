"""LOAD-MODE PIN SAFETY -- the readback path must not drive attached peripherals.

THE ONE CLAIM: with protocol outputs on `uo_out`, today's readback scheme issues
REAL SPI transactions into an attached FRAM during load and run, and can WRITE
it -- corrupting the rung-5 readback oracle before the test starts. The fix
(protocol outputs held at idle, readback bit-serial on the 3 serial pins) issues
exactly zero.

⛔⛔ THIS BUG IS A DIRECT CONSEQUENCE OF THE PRODUCT CALL, AND IT ARRIVED WITH IT.
Filling `uo_out` to 8/8 put SPI-master's CS, SCLK and MOSI on pins that
`src/project.v` already drives from `mem[]`:

    assign uo_out = prog_mode ? {pad, ptr} : rd_data;

So in PROG mode `uo_out` echoes the write pointer, and in RUN mode it walks
`mem[rd_ptr]` out one byte at a time. Under the new pin map those bytes ARE the
CS/SCLK/MOSI lines. The readback feature was harmless when `uo_out` was
debug-only; it became a peripheral driver the moment the pin map changed.

⭐ AND IT IS NOT MERELY "SPURIOUS SELECT". The hazard is computed below rather
than asserted: the walk is a slow SPI master (one sample of CS/SCLK/MOSI per
readback step), so with enough steps it shifts whole bytes in. A `WREN` (0x06)
followed by a `WRITE` (0x02) is a real write to the MB85RS64V, and the oracle the
demo depends on is the FRAM's contents.

⚠ SCOPE, SAID PLAINLY: this is a BEHAVIOURAL model of the FRAM and of the pin
map, not an RTL simulation. It establishes that the hazard exists, that it can
reach a write, and that the fix removes it. The RTL-level must-fire (a model FRAM
attached in cocotb, zero transactions across load and reset) is a Phase 2 item
and is named at the end.

THE FIX, AND WHY RESET HAS TO BE HIGH:
  * LOAD MODE: the 5 protocol outputs are HELD AT IDLE; readback goes out
    bit-serially on the 3 serial pins only. The serialiser already exists for RX
    -- it gains a load-mode job.
  * RESET: `uo_out` is output-only and CANNOT go high-Z, and pin roles are
    assigned PER PROGRAM, so reset cannot know which pin is CS. So every
    protocol output RESETS HIGH, which is the inactive level for all of them:
    UART TX idles high, CS is inactive high, and SCLK/MOSI edges are IGNORED
    while CS is high.
  * PROGRAM START drives the idle levels and ASSERTS CS LAST, so no edge is
    presented to a selected device.
"""

from __future__ import annotations

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- the ruled uo_out pin map (5 protocol outputs + 3 serial) ------------
# ORIGIN: the product ruling after 133d1ac. uo_out is EXACTLY FULL at 8/8.
PINMAP = {7: "UART-tx TX", 6: "SPI-master SCLK", 5: "SPI-master MOSI",
          4: "SPI-master CS", 3: "SPI-target MISO",
          2: "serial DATA", 1: "serial STROBE", 0: "serial VALID"}
BIT_TX, BIT_SCLK, BIT_MOSI, BIT_CS, BIT_MISO = 7, 6, 5, 4, 3
PROTOCOL_BITS = [BIT_TX, BIT_SCLK, BIT_MOSI, BIT_CS, BIT_MISO]
SERIAL_BITS = [2, 1, 0]

AW = 6
STORE = 2 ** AW

# ---- MB85RS64V opcodes. ORIGIN: the datasheet in refs/ ------------------
WREN, WRITE, READ, WRDI, RDSR, WRSR = 0x06, 0x02, 0x03, 0x04, 0x05, 0x01
WRITE_OPS = {WRITE, WRSR}


class FramModel:
    """A behavioural SPI FRAM that COUNTS what was done to it.

    ⛔ It counts SELECTIONS and completed OPCODES separately, because "CS went
    low" and "a write happened" are different severities and conflating them
    would overstate or understate the bug.
    """

    def __init__(self):
        self.selected = False
        self.transactions = 0        # CS falling edges
        self.opcodes = []            # completed first-bytes
        self.wren_latch = False
        self.writes = 0              # WRITE seen while the latch was set
        self._sh = 0
        self._n = 0
        self._prev_sclk = 1

    def step(self, cs: int, sclk: int, mosi: int) -> None:
        if self.selected and cs == 1:                 # CS rising: end
            self.selected = False
        elif not self.selected and cs == 0:           # CS falling: start
            self.selected = True
            self.transactions += 1
            self._sh = 0
            self._n = 0
        if self.selected and sclk == 1 and self._prev_sclk == 0:
            self._sh = ((self._sh << 1) | (mosi & 1)) & 0xFF
            self._n += 1
            if self._n == 8:
                op = self._sh
                self.opcodes.append(op)
                if op == WREN:
                    self.wren_latch = True
                elif op in WRITE_OPS:
                    if self.wren_latch:
                        self.writes += 1
                    self.wren_latch = False
        self._prev_sclk = sclk


def drive_from_byte(fram: FramModel, byte: int) -> None:
    """One readback step: the byte appears on uo_out, so its bits ARE the pins."""
    fram.step((byte >> BIT_CS) & 1, (byte >> BIT_SCLK) & 1,
              (byte >> BIT_MOSI) & 1)


def build_write_image() -> list:
    """A 64-byte image whose READBACK WALK clocks WREN then WRITE into the FRAM.

    ⛔ This is the point the random sweep cannot make. Each readback step
    presents one byte, so to clock a bit we need two consecutive bytes: one with
    SCLK low and one with SCLK high carrying the MOSI value -- both with CS held
    LOW. Random bytes break CS almost immediately; an encoded field that keeps
    one bit constant across a run does not.

    ⭐ Nothing here is exotic: bit 4 (CS) is simply held at 0 for the run, which
    is what any program field occupying the low nibble would do.
    """
    def pair(bit: int) -> list:
        lo = 0                                    # CS=0, SCLK=0
        hi = (1 << BIT_SCLK) | (bit << BIT_MOSI)  # CS=0, SCLK=1, MOSI=bit
        return [lo, hi]

    out = []
    for op in (WREN, WRITE):
        out.append(1 << BIT_CS)                   # CS high: end any transaction
        for i in range(7, -1, -1):                # MSB first
            out += pair((op >> i) & 1)
    out.append(1 << BIT_CS)                       # leave it deselected
    # pad to the store size with CS HIGH so the wrap does nothing
    out += [1 << BIT_CS] * (STORE - len(out))
    return out[:STORE]


def scenario_today(image: list, wraps: int = 40) -> FramModel:
    """TODAY'S DESIGN: prog-mode pointer echo, then the run-mode mem walk."""
    f = FramModel()
    # prog mode: uo_out = {2'b00, ptr}. Every byte written advances ptr.
    for ptr in range(STORE):
        drive_from_byte(f, ptr & 0x3F)
    # run mode: uo_out = mem[rd_ptr], walking and wrapping forever
    for _ in range(wraps):
        for b in image:
            drive_from_byte(f, b)
    return f


def scenario_fixed(image: list, wraps: int = 40) -> FramModel:
    """THE FIX: protocol outputs held at IDLE (high); readback on serial pins."""
    f = FramModel()
    idle = sum(1 << b for b in PROTOCOL_BITS)        # all protocol outs HIGH
    for ptr in range(STORE):
        # the readback value goes to the serial pins; protocol bits never move
        ser = (ptr & 0x7) << 0
        drive_from_byte(f, idle | ser)
    for _ in range(wraps):
        for b in image:
            ser = b & 0x7
            drive_from_byte(f, idle | ser)
    return f


def scenario_reset() -> FramModel:
    """RESET: all protocol outputs HIGH, then program start asserts CS LAST."""
    f = FramModel()
    idle = sum(1 << b for b in PROTOCOL_BITS)
    for _ in range(8):
        drive_from_byte(f, idle)
    # program start: drive the idle levels of each role, CS asserted LAST
    seq = [idle,                                   # all high
           idle & ~(1 << BIT_SCLK),                # SCLK to its idle (low, mode 0)
           idle & ~(1 << BIT_SCLK) & ~(1 << BIT_MOSI)]
    for v in seq:
        drive_from_byte(f, v)
    cs_low = seq[-1] & ~(1 << BIT_CS)              # ...CS last
    drive_from_byte(f, cs_low)
    return f


def main() -> int:
    print()
    print("=" * 78)
    print("LOAD-MODE PIN SAFETY -- readback must not drive the peripherals")
    print("=" * 78)
    lane_digest.announce(
        "gate_load_pin_safety.py", lane_digest.shipped(),
        variant="a pin-map and peripheral model; the lane table is context, "
                "not the subject")
    rc = 0
    print()
    print("  the ruled uo_out map (EXACTLY FULL at 8/8):")
    for b in sorted(PINMAP, reverse=True):
        print("    uo_out[%d]  %s%s" % (b, PINMAP[b],
                                        "   <- protocol" if b in PROTOCOL_BITS
                                        else ""))
    print()
    print("  src/project.v drives: uo_out = prog_mode ? {pad, ptr} : mem[rd_ptr]")
    print("  ⛔ so those bytes ARE the CS/SCLK/MOSI lines under this map.")

    # ---- the hazard, measured over many images -------------------------
    print()
    print("  --- MUST-FIRE: today's readback, against a model FRAM ---")
    rnd = random.Random(20261003)
    n_img = 200
    sel = wr = opc = 0
    worst = None
    for _ in range(n_img):
        img = [rnd.randrange(256) for _ in range(STORE)]
        f = scenario_today(img)
        sel += 1 if f.transactions else 0
        opc += 1 if f.opcodes else 0
        wr += 1 if f.writes else 0
        if worst is None or f.writes > worst[0].writes:
            worst = (f, img)
    print("    %d random 64-byte images, 40 readback wraps each:" % n_img)
    print("      images that SELECT the device (CS low)      : %d of %d"
          % (sel, n_img))
    print("      images that complete at least one OPCODE    : %d of %d"
          % (opc, n_img))
    print("      images that reach a WRITE (WREN then WRITE) : %d of %d"
          % (wr, n_img))
    if worst and worst[0].transactions:
        f = worst[0]
        print("      worst image: %d selections, %d opcodes, %d writes"
              % (f.transactions, len(f.opcodes), f.writes))
        print("      first opcodes seen: %s"
              % ", ".join("0x%02X" % o for o in f.opcodes[:10]))
    fired = sel > 0
    print("    must-fire: %s"
          % ("PASS -- the readback path DOES drive the peripheral"
             if fired else "*** FAIL -- the hazard did not reproduce ***"))
    if not fired:
        rc = 1
    print()
    if wr:
        print("    ⛔⛔ AND IT REACHES A WRITE IN %d OF %d RANDOM IMAGES." % (wr, n_img))
    else:
        print("    ⚠ ZERO completed opcodes on random bytes, and the REASON")
        print("    matters more than the count: CS and SCLK are re-derived from")
        print("    the SAME byte each readback step, so they move together. A")
        print("    CS-low run of random bytes has expected length 2 steps, and")
        print("    clocking one opcode needs CS held low across EIGHT SCLK")
        print("    rising edges. Random bytes essentially cannot do it.")
        print("    ⛔ BUT A REAL PROGRAM IMAGE IS NOT RANDOM -- it has fields in")
        print("    fixed bit positions, so one bit can stay constant across a")
        print("    long run of consecutive bytes. Constructed next, because")
        print("    'I did not observe a write' is not 'a write is unreachable'.")

    # ---- CONSTRUCTIVE: a structured image that reaches a WRITE ----------
    print()
    print("  --- CONSTRUCTED: a 64-byte image that WRITES the FRAM ---")
    adv = build_write_image()
    fa = FramModel()
    for _ in range(4):
        for b in adv:
            drive_from_byte(fa, b)
    print("    image length %d bytes (fits the %d-byte store)" % (len(adv), STORE))
    print("    selections %d, opcodes %s, WRITES %d"
          % (fa.transactions,
             ", ".join("0x%02X" % o for o in fa.opcodes[:6]) or "none",
             fa.writes))
    reached = fa.writes > 0
    print("    => %s"
          % ("⛔⛔ A WRITE IS REACHABLE. The rung-5 oracle IS the FRAM's "
             "contents, so this corrupts the thing the demo measures, before "
             "the demo runs." if reached else
             "*** the construction did not reach a write -- re-check it ***"))
    if not reached:
        rc = 1
    else:
        print("    ⭐ AND THIS IS THE HONEST FORM OF THE CLAIM: the hazard is")
        print("    not 'likely on a random image' (it is not) -- it is")
        print("    'constructible, and a real image has exactly the kind of")
        print("    structure that constructs it'. A bit held constant across a")
        print("    run of bytes is what an encoded field looks like.")

    # ---- the fix --------------------------------------------------------
    print()
    print("  --- THE FIX: protocol outputs held at idle, readback on serial ---")
    allf = []
    rnd2 = random.Random(7)
    for _ in range(n_img):
        img = [rnd2.randrange(256) for _ in range(STORE)]
        allf.append(scenario_fixed(img))
    tot = sum(f.transactions for f in allf)
    print("    %d images, 40 wraps each: %d selections, %d opcodes, %d writes"
          % (n_img, tot, sum(len(f.opcodes) for f in allf),
             sum(f.writes for f in allf)))
    if tot:
        print("    *** FAIL: the fix still selects the device")
        rc = 1
    else:
        print("    => ZERO transactions. The protocol bits never leave their")
        print("       idle level, so no CS edge is ever presented.")

    # ---- reset + program start -----------------------------------------
    print()
    print("  --- RESET AND PROGRAM START: CS asserted LAST ---")
    f = scenario_reset()
    print("    reset holds all %d protocol outputs HIGH" % len(PROTOCOL_BITS))
    print("    then program start drives idle levels and asserts CS last")
    print("    selections: %d (the ONE intended transaction), opcodes: %d"
          % (f.transactions, len(f.opcodes)))
    if f.transactions != 1:
        print("    *** FAIL: expected exactly one intended selection")
        rc = 1
    else:
        print("    => the only CS fall is the program's own, after every other")
        print("       level is already correct. No edge reaches a selected")
        print("       device before the program intends it.")
    print()
    print("    ⛔ WHY RESET-HIGH IS FORCED, NOT CHOSEN: `uo_out` is output-only")
    print("    so it cannot go high-Z, and pin ROLES are assigned per program,")
    print("    so reset cannot know which pin is CS. HIGH is the inactive level")
    print("    for every role on this map at once -- UART TX idles high, CS is")
    print("    inactive high, and SCLK/MOSI edges are ignored while CS is high.")
    print("    ⭐ That is the only constant that is safe for all of them, which")
    print("    is what makes it a convention rather than a preference.")

    # ---- the mutant the ruling names ------------------------------------
    print()
    print("  --- MUTANT: readback left on the protocol pins ---")
    rnd3 = random.Random(99)
    img = [rnd3.randrange(256) for _ in range(STORE)]
    m = scenario_today(img)
    killed = m.transactions > 0
    print("    readback on protocol pins -> %d selections, %d opcodes"
          % (m.transactions, len(m.opcodes)))
    print("    mutant: %s"
          % ("KILLED -- a non-zero transaction count is the failure signal"
             if killed else "*** SURVIVED ***"))
    if not killed:
        rc = 1

    print()
    print("=" * 78)
    print("  GATE load-pin-safety: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * the hazard reproduces: today's readback drives CS/SCLK/MOSI")
    print("    * the fix issues ZERO transactions across load and reset")
    print("    * reset-HIGH is forced by output-only pins + per-program roles")
    print("    * CS is asserted LAST at program start")
    print("  ⚠ BEHAVIOURAL MODEL, not RTL. The Phase 2 must-fire is: attach a")
    print("    model FRAM in cocotb, run load + reset + a program, and require")
    print("    CS never low except where the program asserts it. A mutant with")
    print("    readback on the protocol pins must fail that test.")
    print("  -> 1.5 field: a load-mode job for the RX serialiser")
    print("  -> 1.6 condition: the pin-role reset/idle convention")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
