"""S1 -- THE PROGRAM-SIZE CENSUS. The store is sized from the programs that
must actually run, not from a guess.

THE ONE CLAIM: `AW` is chosen by ENCODING the real submission + rung-5 demo
programs in the F1 format and taking the largest, plus headroom -- so the store
size is a measurement with an audit trail, not a round number.

⛔⛔ WHY THIS GATE EXISTS. Two previous attempts to size the store were both
wrong, in opposite directions, and neither was a census:
  * `AW >= 8, 9 for headroom` -- WITHDRAWN. It treated a symptom: the old
    action word put PAYLOAD in the program, so size grew with MESSAGE LENGTH.
  * `AW = 6 fits, 62 of 64 bytes` -- TRUE but DANGEROUS as a shipping decision.
    It was measured on ONE transaction per protocol. The rung-5 demo needs
    SEVERAL transaction shapes on the same chip, and 2 spare bytes is 0 further
    actions.
⭐ So the question was never "is 64 enough" in the abstract. It is "enough for
WHAT", and the census is the what.

⭐⭐ AND EVERY ACTION COUNT BELOW IS ENUMERATED, NOT ASSERTED. Each program is a
written-out list of actions. A reader can disagree with a line; nobody has to
trust a total. That is the difference between a census and an estimate, and this
project has already shipped one asserted count that was wrong -- see the I2C
correction below.

⛔⛔ A CORRECTION TO F1, FOUND BY DOING THIS. F1's transaction table costs an
I2C write transaction at 8 actions, described as "START, SHIFT 8 addr, ACK read,
SHIFT 8 data, ACK read, STOP (+2 setup)". That is a ONE-BYTE-ADDRESS device.
⭐ OUR PART IS NOT ONE. Primary, MB85RC256V (RAMXEED), its own protocol section:
"the master outputs 8 bits x 2 memory address to the slave. When the each memory
address input ends, the slave again outputs the acknowledge", and its waveform
reads `S 1 0 1 0 A2 A1 A0 0 A | Address A | Address A | Write A | ... P` -- TWO
address bytes, each with its own ACK. So the real transaction is 4 actions longer
than F1 costed it.
⭐ Same for SPI. Primary, MB85RS64V: "WRITE op-code, arbitrary 16 bits of address
and 8 bits of writing data are input to SI. The 3-bit upper address bit is
invalid", waveform `SI  OP-CODE | 16-bit Address | Data In`. So a WRITE carries
TWO address bytes, not the one an 8 KB part might suggest.
⇒ ⛔ THE LESSON IS THE SHAPE OF THE EARLIER ERROR REPEATING: a transaction count
taken from a protocol in general rather than from THE PART WE SHIP.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from gate_encoding_f1 import (action_word, bits_for, budget,       # noqa: E402
                              store_cost, N_PINS, N_LANES)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LANES = lane_digest.shipped()
DELAY_BITS = 10                 # F1's fit
HEADROOM = 1.25                 # Wilson's S1 rule: largest program + 25%

# ---------------------------------------------------------------------------
# THE ACTION VOCABULARY. ⭐ One line per opcode, so a program is a list of
# these and the cost of a program is len(list) * action_bytes.
# ORIGIN: F1's shift/repeat encoding -- opcode, pin, level/dir, delay/period,
# clock pin, bit count.
# ---------------------------------------------------------------------------
LEVEL = "LEVEL"      # drive one pin to a level after a delay
SHIFT = "SHIFT"      # emit N bits from the lane's data register at period T
SHIFTIN = "SHIFTIN"  # sample N bits into the lane's data register
READBIT = "READBIT"  # sample ONE bit (I2C ACK, on the observed SCL rise -- R3)
START = "START"      # I2C START / repeated START
STOP = "STOP"        # I2C STOP
ARM = "ARM"          # arm an edge-triggered RX lane (UART start-bit detect)
WAIT = "WAIT"        # a no-op re-arm: adds to the STORED timestamp (Ruling 2)

# ---------------------------------------------------------------------------
# THE PROGRAMS. Each is (name, lane, [actions], why each action is there).
# ⛔ `D_tol` is NOT here -- F3 put it in the image as loader metadata, so it
# costs header bytes, not actions.
# ---------------------------------------------------------------------------
def p_uart_tx():
    return [(LEVEL, "start bit: TX low"),
            (SHIFT, "8 data bits at T = one bit period, LSB first"),
            (LEVEL, "stop bit: TX high")]


def p_uart_rx():
    return [(ARM, "wait for the START edge (REACTIVE lane)"),
            (SHIFTIN, "sample 8 bits at T, centred by the lane's phase"),
            (READBIT, "sample the stop bit -- framing check, sets sticky ovr")]


def p_spi_wren():
    # MB85RS64V: WREN is opcode-only, no address, no data.
    return [(LEVEL, "CS low -- select"),
            (SHIFT, "8 bits: WREN opcode 0x06, with the clock pin"),
            (LEVEL, "CS high -- deselect latches WEL")]


def p_spi_write():
    # ORIGIN MB85RS64V: "WRITE op-code, arbitrary 16 bits of address and 8 bits
    # of writing data are input to SI."
    return [(LEVEL, "CS low"),
            (SHIFT, "8 bits: WRITE opcode 0x02"),
            (SHIFT, "8 bits: address high  <- 16-bit address, byte 1 of 2"),
            (SHIFT, "8 bits: address low   <- byte 2 of 2"),
            (SHIFT, "8 bits: data"),
            (LEVEL, "CS high -- ends the transaction")]


def p_spi_read():
    return [(LEVEL, "CS low"),
            (SHIFT, "8 bits: READ opcode 0x03"),
            (SHIFT, "8 bits: address high"),
            (SHIFT, "8 bits: address low"),
            (SHIFTIN, "8 bits: data out of SO -- this is the ORACLE read"),
            (LEVEL, "CS high")]


def p_i2c_write():
    # ORIGIN MB85RC256V: S | dev+W A | Address A | Address A | Write A | ... P
    return [(START, "START condition"),
            (SHIFT, "8 bits: device address word, R/W = 0"),
            (READBIT, "ACK from the slave, on the observed SCL rise (R3)"),
            (SHIFT, "8 bits: memory address high <- 8 bits x 2, byte 1"),
            (READBIT, "ACK"),
            (SHIFT, "8 bits: memory address low  <- byte 2"),
            (READBIT, "ACK"),
            (SHIFT, "8 bits: data"),
            (READBIT, "ACK"),
            (STOP, "STOP condition")]


def p_i2c_read():
    # ORIGIN MB85RC256V: "specifying the address in the same way as for a
    # write, and then issuing another start condition and sending the Device
    # Address Word (R/W '1' input)."
    return [(START, "START"),
            (SHIFT, "8 bits: device address word, R/W = 0"),
            (READBIT, "ACK"),
            (SHIFT, "8 bits: memory address high"),
            (READBIT, "ACK"),
            (SHIFT, "8 bits: memory address low"),
            (READBIT, "ACK"),
            (START, "REPEATED START -- the part's own documented sequence"),
            (SHIFT, "8 bits: device address word, R/W = 1"),
            (READBIT, "ACK"),
            (SHIFTIN, "8 bits: read data -- the ORACLE read"),
            (LEVEL, "NACK: master releases SDA high on the 9th clock"),
            (STOP, "STOP")]


def p_spi_target():
    # We are the TARGET: the master clocks us. The program only has to present
    # data and release. ⭐ The RELEASE is not an action -- 1.6r made it an
    # async-clear on uio_oe, i.e. HARDWARE, which is why it costs 0 bytes here.
    return [(ARM, "arm on CS falling (REACTIVE lane)"),
            (SHIFT, "8 bits out on MISO, clocked by the observed SCK")]


PROGRAMS = [
    ("UART tx frame", "UART-tx", p_uart_tx),
    ("UART rx frame", "UART-rx", p_uart_rx),
    ("SPI WREN + WRITE (FRAM)", "SPI-tx", lambda: p_spi_wren() + p_spi_write()),
    ("SPI READ (FRAM oracle)", "SPI-tx", p_spi_read),
    ("I2C write (FRAM)", "I2C", p_i2c_write),
    ("I2C addressed read, rSTART", "I2C", p_i2c_read),
    ("SPI-target respond", "SPI-target", p_spi_target),
]


def header_bytes() -> tuple:
    """Per-lane header, from F1's image layout.

    ⛔ D_tol is image metadata (F3), so it IS in the header -- the loader's 5.3
    screen reads it. It costs header bytes and zero flops in the datapath.
    """
    f = [("pin", bits_for(N_PINS - 1)),
         ("clock pin", bits_for(N_PINS - 1)),
         ("t (inner period)", DELAY_BITS),
         ("C_i", bits_for(8)),
         ("D_sched", bits_for(max(l.D for l in LANES))),
         ("D_tol", bits_for(max(l.D_tol for l in LANES)))]
    bits = sum(b for _n, b in f)
    return f, bits, -(-bits // 8) * N_LANES


def main() -> int:
    print()
    print("=" * 78)
    print("S1 -- PROGRAM-SIZE CENSUS: the store sized from the real programs")
    print("=" * 78)
    lane_digest.announce("gate_program_census.py (S1)", LANES)
    rc = 0

    aw = action_word(DELAY_BITS, with_clock_pin=False, with_count=True)
    hdr_f, hdr_bits, hdr_bytes = header_bytes()

    print()
    print("  --- the action word and the image header ---")
    print("    action word: %d bits = %d bytes" % (aw["bits"], aw["bytes"]))
    for n, b in aw["fields"]:
        print("      %-18s %d bits" % (n, b))
    print("    per-lane header: %d bits; x %d lanes = %d bytes"
          % (hdr_bits, N_LANES, hdr_bytes))
    for n, b in hdr_f:
        print("      %-18s %d bits" % (n, b))

    # ---- the census -----------------------------------------------------
    print()
    print("  --- the census: every action ENUMERATED ---")
    sizes = {}
    for name, lane, fn in PROGRAMS:
        acts = fn()
        nb = len(acts) * aw["bytes"]
        sizes[name] = (lane, len(acts), nb)
        print()
        print("    %s   [lane %s]" % (name, lane))
        for i, (op, why) in enumerate(acts, 1):
            print("      %2d  %-8s %s" % (i, op, why))
        print("      => %d actions x %d B = %d bytes of program"
              % (len(acts), aw["bytes"], nb))

    # ---- the demo: all five lanes at once -------------------------------
    print()
    print("  --- ⭐ THE ONE THAT SIZES THE STORE: the all-five-lanes demo ---")
    print("    ⛔ This is the program the submission's headline claim needs, so")
    print("    it is the one the store must hold -- not the largest SINGLE")
    print("    transaction. One FIFO, one action stream, all lanes live (F1:")
    print("    the shift action names its lane, so there is no lane-select")
    print("    field and no second stream).")
    demo = [("UART tx frame", p_uart_tx()),
            ("UART rx frame", p_uart_rx()),
            ("SPI WREN + WRITE (FRAM)", p_spi_wren() + p_spi_write()),
            ("SPI READ (FRAM oracle)", p_spi_read()),
            ("I2C write (FRAM)", p_i2c_write()),
            ("I2C addressed read, rSTART", p_i2c_read()),
            ("SPI-target respond", p_spi_target())]
    print()
    print("    %-32s %s" % ("component", "actions"))
    tot_acts = 0
    for n, a in demo:
        print("    %-32s %d" % (n, len(a)))
        tot_acts += len(a)
    # ⭐ the re-arm: a periodic demo must re-arm, and Ruling 2 made that a
    # chained no-op that adds to the STORED timestamp. One per lane that repeats.
    rearms = N_LANES
    print("    %-32s %d  (one per lane, Ruling 2 chained no-op)"
          % ("+ re-arm WAIT actions", rearms))
    tot_acts += rearms
    prog_bytes = tot_acts * aw["bytes"]
    total = prog_bytes + hdr_bytes
    print("    %-32s %d actions" % ("TOTAL", tot_acts))
    print("    program %d B + header %d B = %d BYTES"
          % (prog_bytes, hdr_bytes, total))

    # ---- choose AW ------------------------------------------------------
    need = total * HEADROOM
    print()
    print("  --- choosing AW: largest program + %.0f%% headroom = %.0f bytes ---"
          % ((HEADROOM - 1) * 100, need))
    sc = store_cost()
    bg = budget()
    print("    %-5s %-9s %-10s %-12s %-9s %s"
          % ("AW", "bytes", "bits", "cells", "% budget", "holds it?"))
    chosen = None
    for a in range(6, 11):
        by = 2 ** a
        bits = by * 8
        cells = bits * sc["per_bit_itemised"]
        pct = 100.0 * cells / bg["cells_practical"]
        ok = by >= need
        if ok and chosen is None:
            chosen = (a, by, cells, pct)
        print("    %-5d %-9d %-10d %-12.0f %-9.1f %s"
              % (a, by, bits, cells, pct, "YES" if ok else "no"))
    print("    (cells at the ITEMISED %.2f cells/bit; budget = %.0f practical"
          % (sc["per_bit_itemised"], bg["cells_practical"]))
    print("     cells, i.e. 65%% of %.0f at 100%% density)"
          % bg["cells_at_100pct"])

    if chosen is None:
        print("    *** no AW in 6..10 holds the demo -- the encoding needs")
        print("        another pass, not a bigger store")
        return 1
    a, by, cells, pct = chosen
    print()
    print("  --- ⭐ RESULT ---")
    print("    AW = %d  (%d bytes), %.0f cells, %.1f%% of the practical budget"
          % (a, by, cells, pct))
    print("    the demo needs %d B; %d B leaves %d B = %d spare actions"
          % (total, by, by - total, (by - total) // aw["bytes"]))
    print()
    print("    ⚠⚠ READ THAT %.1f%% CORRECTLY: IT IS THE STORE ALONE." % pct)
    print("    The ENGINE is not built, so it is not priced, so this is NOT")
    print("    'the chip is %.0f%% full'. ⛔ Quoting a store fraction as a chip"
          % pct)
    print("    fraction is the shape of the error that produced 'area is free")
    print("    at 6.28 percent' -- that was die-area UTILISATION including")
    print("    68,161 filler instances, read as headroom.")
    print("    ⇒ what IS known: the store takes %.0f of %.0f practical cells,"
          % (cells, bg["cells_practical"]))
    print("      leaving %.0f for the engine, and the engine's cost becomes a"
          % (bg["cells_practical"] - cells))
    print("      MEASUREMENT in S3, not an estimate here.")

    # ---- the pre-registered prediction, scored --------------------------
    print()
    print("  --- the PRE-REGISTERED prediction, scored ---")
    print("    Wilson predicted AW = 7 suffices; falsifier: AW = 8 needed.")
    if a == 7:
        print("    ⇒ PREDICTION HELD: AW = 7.")
    elif a == 8:
        print("    ⇒ ⛔ FALSIFIER FIRED: AW = 8 is needed, not 7. Reported as")
        print("      the prediction required, not quietly adopted.")
        # ⭐⭐ AND THE RESULT DOES NOT DEPEND ON THE HEADROOM CONVENTION, which
        # is the obvious way to rig this. State it, because a sizing rule that
        # only produces its answer at one chosen margin is not a measurement.
        raw_fits_7 = total <= 128
        print()
        print("    ⭐⭐ AND IT IS NOT THE HEADROOM RULE DOING THE WORK. The demo")
        print("    is %d B against AW=7's 128 B, so AW=7 fails at ZERO" % total)
        print("    headroom: %s. ⛔ A sizing rule that only yields its answer at"
              % ("it FITS -- check this" if raw_fits_7 else "it does not fit"))
        print("    one chosen margin is not a measurement, so the %.0f%%"
              % ((HEADROOM - 1) * 100))
        print("    is reported as a SEPARATE cushion rather than as the reason.")
        if raw_fits_7:
            print("    *** AW=7 holds the demo unpadded -- then the headroom IS")
            print("        the deciding term and must be argued, not assumed")
            rc_local = 1
        else:
            print("    ⇒ AW = 8 is forced by the PROGRAMS, and the headroom is")
            print("      then free: %d B of the 256 remain." % (256 - total))
    else:
        print("    ⇒ ⛔ NEITHER: AW = %d. Outside the pre-registered pair, so" % a)
        print("      the prediction AND its falsifier both miss -- which is")
        print("      itself a finding about how the estimate was formed.")

    # ---- what died, and what did not ------------------------------------
    print()
    print("  --- ⛔ what this does and does NOT revive ---")
    print("    AW = 9 stays DEAD: %.0f cells = %.0f%% of budget."
          % (8 * 2 ** 9 * sc["per_bit_itemised"],
             100.0 * 8 * 2 ** 9 * sc["per_bit_itemised"] / bg["cells_practical"]))
    print("    ⭐ And the reason AW = %d is affordable where 9 was not is NOT" % a)
    print("    that the budget moved -- it is that F1 took the PAYLOAD out of")
    print("    the program, so the store now scales with the number of")
    print("    TRANSACTIONS and not with message length.")
    print("    ⛔ The registered readback (F2) is what makes a deeper store")
    print("    safe: store depth was on the 18.44-of-20 ns combinational pad")
    print("    feedthrough, and F2 took it off. Growing AW BEFORE F2 would")
    print("    have deepened the critical path. ⇒ the two rulings compose, and")
    print("    the order mattered.")

    print()
    print("=" * 78)
    print("  GATE program-census: PASSED -- AW = %d from an enumerated census"
          % a)
    print("    * %d programs, every action listed" % len(PROGRAMS))
    print("    * demo = %d actions = %d B program + %d B header = %d B"
          % (tot_acts, prog_bytes, hdr_bytes, total))
    print("    * ⛔ F1's I2C count corrected: our part needs 8 bits x 2 memory")
    print("      address bytes, so +4 actions over F1's one-byte-address figure")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
