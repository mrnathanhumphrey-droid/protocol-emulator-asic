"""Build a tiny program image and emit it as a Verilog memory file.

⛔⛔ THIS EXISTS BECAUSE "IT ELABORATES" IS NOT EVIDENCE. This project has
already recorded a gate-level sim passing for weeks on a stub with ZERO
flip-flops -- the flow was broken the whole time and nothing noticed, because
the artefact was too simple to reach the broken path. So the engine gets a
program that makes it DO something, and the test asserts on PIN MOVEMENT.

⭐ The image layout here is the SPEC, hand-assembled, so if the RTL's unpacking
disagrees with the documented layout the simulation says so rather than both
sides drifting together. ⛔ A second implementation by the same author is not an
independent witness -- but a hand-assembled image against a generated unpacker
CAN diverge, which is what makes the check worth running.

HEADER, 47 bits in 6 bytes, MSB-aligned, 1 spare bit at the bottom:
    [47:44] pin        [43:40] clkpin     [39]    mode (1 = push-pull)
    [38:29] t          [28:25] C_i        [24:17] D_sched
    [16:9]  D_tol      [8:1]   base       [0]     spare

⚠ THE `mode` BIT WAS MISSING FROM THIS TABLE, which put every field below it
one bit adrift. A bench that decoded `t` from the prose rather than from
`pe_isa.HDR_FIELDS` echoed the d=12 arm as "518". The authority is
`HDR_FIELDS`; this table is a reading of it and has now been corrected
against it.
ACTION, 3 bytes, MSB-aligned in 24 bits:
    [23:21] opcode     [20:17] pin        [16] level
    [15:6]  delay      [5:2]   count      [1:0] TX queue

⚠ `[1:0]` was spare padding and this docstring still said so after the queue
field took it. A layout comment that disagrees with `pe_isa` is the two-copies
defect in prose form, so it is corrected here: an image written before the
field existed is bit-identical to one written with `q = 0`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ⛔⛔ THE ENCODER IS IMPORTED, NOT DEFINED HERE. Field widths, `hdr`, `act`
# and the host push sequence all live in `pe_isa`, because this file used to own
# them and `tb_smoke` kept a private slice of the same layout that broke the
# moment a field used the padding. R1/R2's host model and `pe_asm` need the
# identical encoding, and three copies of a bit-packer is this project's most
# reliable bug.
from pe_isa import (                      # noqa: F401,E402
    ACT_BASE, ACT_BYTES, ACT_W, AW, BQW, CW, DLY_W, D_W, HDR_BITS, HDR_BYTES,
    N_LANES, OP_ARM, OP_LEVEL, OP_READBIT, OP_REARM, OP_SHIFT, OP_SHIFTIN,
    ORDER_LSB, ORDER_MSB,
    OP_START, OP_STOP, PINW, PIN_NONE, UO0, UO1, UO2, UO3, act, hdr,
)

def build():
    """Lane 0 toggles uo_out[0]; lane 1 toggles uo_out[1] at a different rate.

    ⭐ TWO LIVE LANES ON PURPOSE. `M-PREFETCH-STALE` is VACUOUS with one live
    lane -- the previous winner IS the current winner, so a stale prefetch word
    is coincidentally correct. Two lanes at different rates make the scheduler
    actually alternate, which is the only condition under which a stale
    prefetch produces a wrong pin.
    """
    prog = []
    # lane 0: drive uo_out[0] low, then high, then re-arm. delay in cycles.
    l0 = ACT_BASE
    prog.append(act(OP_LEVEL, UO0, 0, 20))
    prog.append(act(OP_LEVEL, UO0, 1, 20))
    prog.append(act(OP_REARM, 0, 1, 20))        # level=1 => loop to base
    # lane 1: a different period, so the EDF winner changes hands
    l1 = l0 + 3 * ACT_BYTES
    prog.append(act(OP_LEVEL, UO1, 0, 31))
    prog.append(act(OP_LEVEL, UO1, 1, 31))
    prog.append(act(OP_REARM, 0, 1, 31))
    # lanes 2..4 parked on a NON-looping re-arm: live, but never move a pin
    l2 = l1 + 3 * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))

    headers = [
        hdr(UO0, UO0, 1, 20, 2, 40, 60, l0),       # lane 0
        hdr(UO1, UO1, 1, 31, 2, 60, 90, l1),       # lane 1
        hdr(0, 0, 0, 500, 2, 200, 240, l2),
        hdr(1, 1, 0, 500, 2, 200, 240, l2),
        hdr(2, 2, 0, 500, 2, 200, 240, l2),
    ]
    img = b"".join(headers) + b"".join(prog)
    assert len(headers[0]) == HDR_BYTES
    return img


def build_stress(d0: int, d1: int):
    """A program whose inter-action delays are SHORT ENOUGH TO STRESS THE
    REFILL PATH. This exists because the default program cannot measure J.

    ⛔⛔ THE DEFAULT PROGRAM MEASURES NOTHING ABOUT JITTER, AND THAT WAS FOUND
    THE HARD WAY. Its delays are 20 and 31 cycles against a refill latency of
    about 4, so the prefetcher always wins the race -- with ONE buffer or TWO.
    Measured steady-state stall is 0 either way; the `J = 5` the bench has been
    reporting all along is entirely a COLD START, and the `M_BUF_SWAP` mutant
    (which removes the double buffer's swap) SURVIVED against it. A bench that
    cannot distinguish the design from the mutant cannot evidence the design.

    ⭐ WHERE THE DOUBLE BUFFER CAN SHOW UP, derived rather than guessed. With a
    single buffer the slot frees at writeback and the refill must finish before
    the NEXT DISPATCH, a window of `d`. With two buffers the head is already
    valid at the swap, and the refill of the freed slot has until the dispatch
    AFTER next -- about `2d`. So for a refill latency `L`:

        single buffer stalls when   d < L
        double buffer stalls when  2d < L

    The design is therefore distinguishable from its mutant only for
    `L/2 <= d < L`, which for L ~ 6 is `d` in [3, 6). At d = 20 both are clean
    and at d = 1 both stall -- in neither case does the measurement say
    anything about the buffering.
    """
    prog = []
    l0 = ACT_BASE
    prog.append(act(OP_LEVEL, UO0, 0, d0))
    prog.append(act(OP_LEVEL, UO0, 1, d0))
    prog.append(act(OP_REARM, 0, 1, d0))
    l1 = l0 + 3 * ACT_BYTES
    prog.append(act(OP_LEVEL, UO1, 0, d1))
    prog.append(act(OP_LEVEL, UO1, 1, d1))
    prog.append(act(OP_REARM, 0, 1, d1))
    l2 = l1 + 3 * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))
    # ⛔ D_sched/D_tol are scaled with the delay: leaving them at the default
    # 40/60 against a 5-cycle period would make every lane permanently late and
    # the run would be measuring an OVERLOADED system, not a jitter mechanism.
    headers = [
        hdr(UO0, UO0, 1, d0, 2, 2 * d0, 3 * d0, l0),
        hdr(UO1, UO1, 1, d1, 2, 2 * d1, 3 * d1, l1),
        hdr(0, 0, 0, 500, 2, 200, 240, l2),
        hdr(1, 1, 0, 500, 2, 200, 240, l2),
        hdr(2, 2, 0, 500, 2, 200, 240, l2),
    ]
    return b"".join(headers) + b"".join(prog)


# ⛔⛔ ONE RECIPE PER FILENAME. The clean-room check found `five_image.hex`
# reproducing with DIFFERENT CONTENT: `--all` generated it from the shipped
# periods while `run_mutants` regenerated it from a tight stress set, so the
# same filename meant two different programs depending on who ran last. Only
# run_mutants consumes it, so ITS delays are the recipe -- defined here, in the
# generator, and imported by the consumer.
FIVE_STRESS = (12, 13, 14, 15, 16)


def build_five(delays):
    """SCHEDULER STRESS IMAGE -- five active lanes at the shipped inter-action
    delays. Representative of the real design's REFILL DEMAND.

    ⚠ NOT A PIN-MAP-LEGAL PROGRAM, and the distinction matters. It declares
    push-pull on `uio` pins 0..4, which is PHYSICALLY FINE -- a `uio` pin is
    capable of either drive class -- but it is not the ruled PLACEMENT, which
    puts push-pull protocol outputs on `uo_out` (4 of them) and keeps `uio` for
    pins that must be able to stop driving. So this image needs five push-pull
    pins where the ruled placement provides four.
    ⭐ THAT IS WHY THE 1.5 MASK IS RUNTIME AND NOT BUILD-TIME: a compile-time
    mask of the ruled placement would freeze this program dead, and it measures
    something real. It is a scheduler stress program, not a configuration the
    chip would be wired into.
    ⛔ AND IT IS WHY THE DRIVE CLASS CANNOT BE CHECKED AT LOAD TIME FOR `uio`:
    there is no build-time class to check a header against. Only `uo_out` has
    one (output-only, hence push-pull only), which is exactly 1.6s.

    ⛔ THE TWO-LANE PROGRAMS UNDERSTATE REFILL CONTENTION BY A FACTOR OF ~2.5.
    One shared fetch port serves every lane, so the question "does a dispatch
    ever wait on a refill" depends on TOTAL refill demand, and measuring it with
    2 of 5 lanes active answers a different question. The shipped inner action
    spacings are about 25 (SPI 1 MHz at 50 MHz), 45 (I2C 400 kHz), 434
    (UART 115200), 414 (UART-rx inner) and 25 (SPI-target inner).
    """
    prog, headers, base = [], [], []
    off = ACT_BASE
    for n, d in enumerate(delays):
        base.append(off)
        prog.append(act(OP_LEVEL, n, 0, d))
        prog.append(act(OP_LEVEL, n, 1, d))
        prog.append(act(OP_REARM, 0, 1, d))
        off += 3 * ACT_BYTES
    for n, d in enumerate(delays):
        # D_tol capped at the 8-bit field; the shipped lanes' real keys are
        # derived in the A2 model, not here -- this program exists to load the
        # REFILL PORT, and its deadlines only have to keep the set schedulable.
        headers.append(hdr(n, n, 1, min(d, 1023), 2,
                           min(2 * d, 255), min(3 * d, 255), base[n]))
    return b"".join(headers) + b"".join(prog)


# ⚠ LIKE `build_five`, A SCHEDULER STRESS IMAGE AND NOT A PIN-MAP-LEGAL
# PROGRAM: it declares push-pull on `uio` pins, which is physically fine but is
# not the ruled placement. See `build_five`'s docstring.
def build_chain(d_tog: int, d_park: int):
    """Two toggling lanes plus THREE lanes parked on CHAINING re-arms at a
    short delay, so the chaining path is exercised often.

    ⛔ WHY A THIRD PROGRAM. `M_BUF_CHAINFLIP` -- swapping on a chaining re-arm,
    whose PC does not advance -- SURVIVED both other images. It is not a
    correctness defect: the flip makes an unfilled slot the head, the refill
    then loads `l_pc` into it, and `l_pc` still points at the SAME action, so
    the buffer-swap invariant is satisfied and the pin behaviour is right. What
    it costs is a needless refill on every park dispatch, which steals shared
    fetch bandwidth from the lanes that are timing-critical.
    ⭐ So it is a JITTER mutant, not a correctness one, and it can only be
    killed DIFFERENTIALLY on a program where parks are frequent enough to
    compete for the port. A park at delay 500 (the default program) dispatches
    8 times in 4,000 cycles and steals nothing.
    """
    # ⭐ THREE toggling lanes, not two: the port has to be busy enough that the
    # bandwidth the mutant wastes is bandwidth something else needed. With two
    # toggling lanes the steady-state stall is 0 for the design AND the mutant,
    # and a differential test between two zeroes measures nothing.
    prog, headers, base = [], [], []
    off = ACT_BASE
    n_tog = 3
    for n in range(n_tog):
        base.append(off)
        prog.append(act(OP_LEVEL, n, 0, d_tog + n))
        prog.append(act(OP_LEVEL, n, 1, d_tog + n))
        prog.append(act(OP_REARM, 0, 1, d_tog + n))
        off += 3 * ACT_BYTES
    # the parked lanes: a CHAINING re-arm (level 0) at a SHORT delay, so they
    # dispatch often and the needless refill actually competes
    lp = off
    prog.append(act(OP_REARM, 0, 0, d_park))
    for n in range(n_tog):
        headers.append(hdr(n, n, 1, d_tog + n, 2,
                           min(2 * (d_tog + n), 255),
                           min(3 * (d_tog + n), 255), base[n]))
    for n in range(n_tog, N_LANES):
        headers.append(hdr(n, n, 0, d_park, 2, min(2 * d_park, 255),
                           min(3 * d_park, 255), lp))
    return b"".join(headers) + b"".join(prog)


def build_cfgerr(d: int = 20):
    """1.6s MUST-FIRE: an OPEN-DRAIN lane assigned a `uo_out` pin.

    `uo_out` has no output enable, so an open-drain lane there can never
    release -- it drives low once and sticks. The chip must REFUSE to run this,
    not emulate it, and must say why in the status stream (CONFIG_ERR).
    """
    prog = [act(OP_LEVEL, UO0, 0, d), act(OP_LEVEL, UO0, 1, d),
            act(OP_REARM, 0, 1, d)]
    l0 = ACT_BASE
    lp = l0 + 3 * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))
    headers = [hdr(UO0, UO0, 0, d, 2, 2 * d, 3 * d, l0)]   # mode 0 on uo_out!
    for n in range(1, N_LANES):
        headers.append(hdr(n, n, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)


def build_census(d: int = 25):
    """A program that executes ALL EIGHT opcodes on the RTL.

    ⛔⛔ WHY THIS IS NOT THE SAME AS THE GOLDEN MODEL'S COVERAGE.
    `model/gate_reverse_trace.py` runs the S1 census on an executable ISA
    semantics and exercises all 8 opcodes -- which settles "is any opcode
    unneeded by the required protocols". It settles NOTHING about the RTL:
    `gate_cj_bounds` derives C_max for all 8 action types and measures it on
    TWO, because the default smoke program only uses LEVEL and re-arm. A model
    exercising an opcode is not the silicon exercising it.
    ⇒ This image makes the RTL execute every opcode, so the per-opcode C
    measurement covers 8 of 8 instead of 2 of 8.

    ⚠ IT IS A COVERAGE PROGRAM, NOT A PROTOCOL. The opcodes run in an order
    chosen to reach them all, not to speak UART or I2C -- so its pin waveform
    means nothing and only the per-opcode service times should be read from it.
    Claiming otherwise would be the "exact answer to the wrong question" shape.
    """
    prog, headers, base = [], [], []
    off = ACT_BASE
    # lane 0 walks the OUTPUT-side opcodes; lane 1 the INPUT-side ones. Two
    # lanes because a single live lane makes the scheduler degenerate and the
    # dispatch path is part of what C measures.
    seq0 = [(OP_LEVEL, UO0, 0), (OP_LEVEL, UO0, 1), (OP_SHIFT, UO0, 0),
            (OP_START, UO0, 1), (OP_STOP, UO0, 0), (OP_REARM, 0, 1)]
    seq1 = [(OP_SHIFTIN, UO1, 0), (OP_READBIT, UO1, 0), (OP_ARM, UO1, 0),
            (OP_REARM, 0, 1)]
    for seq in (seq0, seq1):
        base.append(off)
        for op, pin, lvl in seq:
            prog.append(act(op, pin, lvl, d, count=8))
            off += ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    # ⛔⛔ LANE 0's CLOCK PIN IS NOT ITS DATA PIN, AND IT USED TO BE. This
    # image runs OP_SHIFT on lane 0, and OP_SHIFT writes the data pin and then
    # the CLOCK pin, clock second -- so with `clkpin == pin` the clock write
    # overwrites the data bit with `a_lvl` and every 1 bit is lost. The engine
    # now REFUSES that combination (1.6x: sticky CONFIG_ERR, lane halted), so
    # this image would not run at all.
    # ⚠ IT WAS HARMLESS UNTIL TWO THINGS CHANGED TOGETHER: nothing had ever
    # fed the host channel, so the shift register was always all-zero and
    # losing the 1 bits changed nothing; and nothing refused the program. The
    # per-opcode C measurement this image exists for was taken in that state.
    # ⭐ LANE 1 KEEPS `clkpin == pin` DELIBERATELY: it runs SHIFTIN, READBIT
    # and ARM, none of which touch the clock pin, so the alias is a don't-care
    # there -- and leaving it is what keeps the 1.6x refusal SCOPED rather than
    # a blanket rule. `build_five` relies on the same scope.
    headers.append(hdr(UO0, UO2, 1, d, 2, 2 * d, 3 * d, base[0]))
    headers.append(hdr(UO1, UO1, 1, d + 1, 2, 2 * d, 3 * d, base[1]))
    for n in range(2, N_LANES):
        headers.append(hdr(n, n, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)


def build_half(d: int = 24):
    """RULING 1's MUST-FIRES: two HALF-DUPLEX lanes, TX and RX on one lane.

    ⛔⛔ THE PROGRAM SHAPE IS THE POINT, AND IT IS NOT THE OBVIOUS ONE.
    `OP_SHIFT` drives the data pin AND the clock pin in one dispatch, and it
    ADVANCES THE TX POINTER. So a bit period built from two SHIFTs -- one per
    clock edge, which is what `corpus.py` does -- consumes TWO payload bits per
    protocol bit, and the byte on the wire is not the byte that was pushed.
    ⭐ THE CLOCK CAN BE DECOUPLED FROM THE SHIFT with the opcodes that already
    exist: `OP_LEVEL` reaches `l_clkpin` NOWHERE -- the clock pin is written in
    the `OP_SHIFT` arm and in no other -- so pointing an `OP_LEVEL` at the
    clock pin as its own `a_pin` moves the clock WITHOUT shifting. One bit is
    then:
        SHIFT(data, level=0)   data bit out, clock LOW   -- advances TX
        LEVEL(clkpin, 1)       clock HIGH                -- no shift
    which is one shift per bit, data changing while the clock is low. That is
    the correct framing for both I2C and SPI mode 0.
    ⚠ IT COSTS TWO ACTIONS PER BIT, so a bit period is 2*d cycles. At d >= D*
    = 20 that is <= 1.25 MHz for SPI and comfortably inside 400 kHz for I2C.
    A THREE-action bit (adding a separate receive sample) needs d = 17 for
    1 MHz, which is BELOW D* and therefore inadmissible -- see the round's
    record for what that closes.

    lane 0 -- I2C-SHAPED WRITE THEN ACK READ (open-drain SDA/SCL on uio):
        8 x [ SHIFT(SDA, lvl=0, clk=SCL, q=0, cnt=7), LEVEL(SCL, 1) ]
        LEVEL(SCL, 0), SHIFTIN(SDA, cnt=8), LEVEL(SCL, 1)   -- release + sample
        REARM
    lane 1 -- SPI-MASTER-SHAPED WRITE THEN READ (push-pull on uo_out):
        8 x [ SHIFT(MOSI, lvl=0, clk=SCLK, q=1, cnt=7), LEVEL(SCLK, 1) ]
        8 x [ LEVEL(SCLK, 0), SHIFTIN(MISO, cnt=8), LEVEL(SCLK, 1) ]
        REARM

    ⭐ THE TWO LANES NAME DIFFERENT QUEUES (0 and 1), so `pe_asm`'s
    queue-ownership rule is satisfied and the two TX streams are separable at
    the pins.
    ⚠ PROTOCOL-SHAPED, NOT A CERTIFIED PROTOCOL. There is no START/STOP
    condition and no addressing: the claims this image supports are about the
    PLUMBING -- that a pushed byte reaches the wire, that a sampled byte
    reaches the host, and that neither direction corrupts the other.
    """
    prog, headers, base = [], [], []
    off = ACT_BASE
    # ---- lane 0: I2C-shaped, SDA = uio[2], SCL = uio[1] ----------------
    base.append(off)
    seq0 = []
    for _b in range(8):
        seq0.append(act(OP_SHIFT, 2, 0, d, count=7, q=0))
        seq0.append(act(OP_LEVEL, 1, 1, d))
    seq0.append(act(OP_LEVEL, 1, 0, d))
    seq0.append(act(OP_SHIFTIN, 2, 0, d, count=8))
    seq0.append(act(OP_LEVEL, 1, 1, d))
    seq0.append(act(OP_REARM, 0, 1, d))
    prog += seq0
    off += len(seq0) * ACT_BYTES
    # ---- lane 1: SPI-master-shaped, MOSI = uo_out[2], SCLK = uo_out[1],
    #      MISO = uio[0] ------------------------------------------------
    base.append(off)
    seq1 = []
    for _b in range(8):
        seq1.append(act(OP_SHIFT, 10, 0, d, count=7, q=1))
        seq1.append(act(OP_LEVEL, 9, 1, d))
    for _b in range(8):
        seq1.append(act(OP_LEVEL, 9, 0, d))
        seq1.append(act(OP_SHIFTIN, 0, 0, d, count=8))
        seq1.append(act(OP_LEVEL, 9, 1, d))
    seq1.append(act(OP_REARM, 0, 1, d))
    prog += seq1
    off += len(seq1) * ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    # lane 0 open-drain on uio (a releasable bank, as the pin map requires);
    # lane 1 push-pull on uo_out. Both name a clock pin DISTINCT from the data
    # pin, which 1.6x requires of any shifting lane.
    headers.append(hdr(2, 1, 0, d, 2, 2 * d, 3 * d, base[0]))
    headers.append(hdr(10, 9, 1, d, 2, 2 * d, 3 * d, base[1]))
    for n in range(2, N_LANES):
        headers.append(hdr(4, 4, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)


def build_i2cframe(d: int = 62, sda: int = 2, scl: int = 1):
    """A FULL I2C WRITE TRANSACTION, for a foreign decoder to adjudicate.

        S | 1010 000 0 | A | data | A | P

    ⛔⛔ WHY A FOREIGN DECODER AND NOT ANOTHER ASSERTION. Every I2C claim this
    project has made is same-hand: our engine against our own peer model
    (`fram_i2c.v` says so in its own header) and our own benches. `sigrok`'s
    `i2c` protocol decoder is code written from the standard by people who have
    never seen this design, so it can disagree in ways nothing here can.

    THE FRAMING, built from the opcodes that exist:
      START   `OP_START(SDA, 0)` pulls SDA low while SCL is still released
              high -- which IS a start condition -- then SCL goes low.
      a bit   `OP_SHIFT(SDA, lvl=0, clk=SCL)` puts the data bit on SDA and
              takes SCL LOW in one dispatch, then `OP_LEVEL(SCL, 1)` releases
              SCL high. Data changes only while SCL is low, as I2C requires.
              ⭐ TWO ACTIONS PER BIT AND ONE SHIFT PER BIT -- the clock is
              decoupled from the shift because `l_clkpin` is written in the
              `OP_SHIFT` arm and nowhere else, so an `OP_LEVEL` aimed at SCL
              moves the clock without consuming a payload bit.
      ACK     SCL low, `OP_SHIFTIN(SDA)` RELEASES SDA so the peer can pull it,
              SCL high (the acknowledge is now on the wire), SCL low.
      STOP    SDA low, SCL high, then `OP_STOP(SDA, 1)` releases SDA so it
              RISES while SCL is high.

    ⚠ THE FIRST TRANSACTION CARRIES ADDRESS 0x00 AND IS EXPECTED TO. `l_tx`
    resets to 0 and the host byte loads only at the end of eight shifts, so the
    first byte out of any lane is the reset byte -- `tb_tx` asserts exactly
    that. ⭐ The host pattern is therefore chosen so that EVERY LATER
    transaction is valid: with a 4-byte cycle of [data, addr, data, addr] the
    loop emits (0x00, data), then (addr, data), (addr, data), ... so from the
    second transaction on the wire carries a well-formed write.

    ⚠ OPEN-DRAIN IS WHAT MAKES THIS LEGAL AT ALL. Both pins are on `uio`,
    declared `MODE_OD`, so a 1 is a RELEASE and the peer may pull low at the
    same time -- which is what an ACK is. A push-pull lane here would fight the
    peer on every acknowledge.
    """
    prog, headers = [], []
    off = ACT_BASE
    base = off
    seq = []
    seq.append(act(OP_START, sda, 0, d))        # SDA low, SCL still high = S
    seq.append(act(OP_LEVEL, scl, 0, d))        # SCL low
    for _byte in range(2):                      # device address, then data
        for _b in range(8):
            seq.append(act(OP_SHIFT, sda, 0, d, count=7, q=0))
            seq.append(act(OP_LEVEL, scl, 1, d))
        seq.append(act(OP_LEVEL, scl, 0, d))    # SCL low before releasing SDA
        seq.append(act(OP_SHIFTIN, sda, 0, d, count=8))   # release + sample
        seq.append(act(OP_LEVEL, scl, 1, d))    # SCL high: the ACK is on air
        seq.append(act(OP_LEVEL, scl, 0, d))    # SCL low
    seq.append(act(OP_LEVEL, sda, 0, d))        # SDA low with SCL low
    seq.append(act(OP_LEVEL, scl, 1, d))        # SCL high
    seq.append(act(OP_STOP, sda, 1, d))         # SDA released = P
    seq.append(act(OP_REARM, 0, 1, d))
    prog += seq
    off += len(seq) * ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    # ⭐ ORDER_MSB (ruling 1): I2C is MSB-first, and the lane now SAYS so in
    # its header rather than relying on the host to pre-reverse every byte.
    # The engine reverses at the load into `l_tx`, so the host pushes the
    # device address 0xA0 AS ITSELF and the wire carries 0xA0 MSB-first.
    # ⚠ BEFORE THIS BIT EXISTED the program had to push 0x05 -- the reversal --
    # and sigrok read the 7-bit address as 0x50 either way, which is exactly
    # how the engine's LSB-first order stayed invisible.
    headers.append(hdr(sda, scl, 0, d, 2, 2 * d, 3 * d, base,
                       order=ORDER_MSB))
    for n in range(1, N_LANES):
        headers.append(hdr(4, 4, 0, 500, 2, 200, 240, lp))
    img = b"".join(headers) + b"".join(prog)
    return img


def build_rxfast(d: int = 24):
    """THE RX-DROP MUST-FIRE: complete a received byte faster than the serial
    link can carry one away.

    ⛔ THE LINK'S PAYLOAD SLOT IS 48 CYCLES: the serialiser shifts one bit per
    TWO cycles, a frame is 12 bits, and `status_turn` forces a status frame
    after every payload frame. `rx_pend` is ONE DEEP, so a second `rx_push`
    inside that window sets `rx_drop_sticky` and the byte is GONE.
    ⭐ `count = 1` MAKES THE RATE ARBITRARY: the RX byte-complete fires at
    `rx_bitp == a_cnt - 1`, so at `a_cnt = 1` it fires on EVERY sample and a
    "byte" completes once per SHIFTIN dispatch -- once per `d` cycles. At
    `d = 24` that is one completion per 24 cycles against a 48-cycle slot, so
    roughly half of them must be lost, and the flag must say so.
    ⚠ THE BYTES ARE NONSENSE BY CONSTRUCTION -- one sample is not a byte. That
    is deliberate and declared: this program exists to exercise the PENDING
    REGISTER's overflow behaviour, not to receive data. What is asserted is
    that the loss is REPORTED and that the surviving payload is intact.
    """
    prog, headers, base = [], [], []
    off = ACT_BASE
    base.append(off)
    seq = []
    for _b in range(8):
        seq.append(act(OP_SHIFTIN, 0, 0, d, count=1))
    seq.append(act(OP_REARM, 0, 1, d))
    prog += seq
    off += len(seq) * ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    # MISO = uio[0] as an input; the lane needs a clock pin distinct from its
    # data pin only if it SHIFTS (1.6x), and this lane only shifts IN.
    headers.append(hdr(0, 1, 1, d, 2, 2 * d, 3 * d, base[0]))
    for n in range(1, N_LANES):
        headers.append(hdr(4, 4, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)


def build_tx_badclk(d: int = 12):
    """1.6x's MUST-FIRE: a SHIFT lane whose clock pin IS its data pin.

    ⛔ The program the engine must refuse. One lane, eight SHIFTs drawing from
    queue 0, with `clkpin == pin` -- so the clock write would overwrite every
    data bit with `a_lvl`. The chip sets sticky CONFIG_ERR and halts the lane
    instead of transmitting corrupted bytes.
    ⚠ A GUARD THAT HAS ONLY EVER BEEN SEEN TO PASS HAS UNKNOWN STRENGTH, which
    is why this image exists rather than a comment: `tb_tx +BADCLK=1` runs it
    and requires the refusal, and `M_SHIFT_CLK_ALIAS` removes the refusal and
    must make that run fail.
    """
    prog, headers, base = [], [], []
    off = ACT_BASE
    base.append(off)
    for _i in range(8):
        prog.append(act(OP_SHIFT, UO0, 0, d, count=7, q=0))
        off += ACT_BYTES
    prog.append(act(OP_REARM, 0, 1, d))
    off += ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    headers.append(hdr(UO0, UO0, 1, d, 2, 2 * d, 3 * d, base[0]))
    for n in range(1, N_LANES):
        headers.append(hdr(n, n, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)


def build_tx(d0: int = 12, d1: int = 13, cnt: int = 7):
    """T5.1 -- TWO TX LANES DRAWING FROM DIFFERENT HOST QUEUES.

    ⛔⛔ THE HOST DATA CHANNEL HAS NEVER BEEN DRIVEN BY ANY BENCH. `pe_isa`
    has carried `host_pushes` since the channel was built, and nothing in
    `test/` calls it -- so every `OP_SHIFT` the suite has ever executed found
    `host_valid = 0` and took the UNDERRUN branch. The census image runs SHIFT,
    which is how `gate_cj_bounds` measures C on 8 of 8 opcodes; it has never
    run SHIFT with a BYTE IN THE QUEUE. The path from a queue to a wire was
    built, encoded in the ISA, and unexercised.
    ⇒ This program is the first one that can carry payload, and the claim it
      exists to test is the ORDERING one: with two TX-consuming lanes active,
      consumption order is the EDF dispatch interleave, so a host cannot
      predict which lane takes the next byte. Per-lane queues are what make
      that safe, and `tb_tx.v` is what shows it.

    THE SHAPE. Each lane loops eight SHIFTs then re-arms, and names its OWN
    queue:
        lane 0:  8 x SHIFT(pin=UO0, count=cnt, q=0), REARM(d0)   clk = UO2
        lane 1:  8 x SHIFT(pin=UO1, count=cnt, q=1), REARM(d1)   clk = UO3

    ⛔⛔ THE CLOCK PIN MUST DIFFER FROM THE DATA PIN, AND THE FIRST VERSION OF
    THIS PROGRAM GOT IT WRONG IN A WAY NOTHING WOULD HAVE FLAGGED. `OP_SHIFT`
    drives BOTH pins in one ST_DRIVE -- `pin_out[a_pin] <= l_data[cur][0]` and
    then `pin_out[l_clkpin[cur]] <= a_lvl` -- and the clock write comes SECOND.
    With `clkpin == pin` (which `build_census` and `build_five` both declare,
    harmlessly, because they only use OP_LEVEL) the clock assignment OVERWRITES
    the data bit with `a_lvl`. At `a_lvl = 0` every 1 bit becomes a 0: exactly
    8 lost bits per lane here, which is exactly the number of 1s in each
    queue's payload.
    ⚠ NOTHING REFUSES SUCH A PROGRAM. The wire carries a well-formed frame of
    the wrong data, which is the silent-corruption class -- and it had never
    been reachable before, because until T5.1 nothing in the suite had ever
    shifted a real byte. ⇒ Reported as a candidate load-time condition; NOT
    fixed here, because adding an admissibility rule is a ruling.

    ⭐ `count = 7`, NOT 8, AND THE OFF-BY-ONE IS THE POINT. The byte load fires
    at `l_bitp[cur] == a_cnt` and resets `l_bitp` to 0, so with `cnt = 7` the
    pointer walks 0..7 -- EIGHT drives -- and the load lands on the eighth. At
    `cnt = 8` it would walk 0..8 and emit a ninth, padding bit per byte, which
    would show up as a byte-alignment failure that looked like a tag bug.

    ⚠ THE FIRST BYTE OUT OF EACH LANE IS ZERO, by construction and not by
    accident: `l_data` resets to 0 and the first load happens at the END of the
    first eight drives. So the stream is `00` then the pushed bytes in order,
    and a bench that expected the pushed bytes immediately would fail for a
    reason that has nothing to do with queues.

    ⚠ `d0 != d1` SO THE LANES INTERLEAVE RATHER THAN RACE. Equal delays would
    keep them phase-locked and dispatching in a fixed index order every time,
    which is the easy case; one cycle of difference makes the interleave drift
    and exercises the ordering claim at many phases in one run.
    """
    prog, headers, base = [], [], []
    off = ACT_BASE
    lanes = ((UO0, UO2, d0, 0), (UO1, UO3, d1, 1))
    for n, (pin, _clk, d, q) in enumerate(lanes):
        base.append(off)
        for _i in range(8):
            prog.append(act(OP_SHIFT, pin, 0, d, count=cnt, q=q))
            off += ACT_BYTES
        prog.append(act(OP_REARM, 0, 1, d))
        off += ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    # mode = 1 (push-pull): `uo_out` has no enable, so open-drain there is the
    # 1.6s violation. UO0..UO3 are `uo_out` pins, so push-pull is the only legal
    # class and this program is pin-map legal -- unlike `build_five`.
    # ⭐ DATA AND CLOCK ON DIFFERENT PINS, which is also how a real SPI lane is
    # configured (MOSI + SCK). See the docstring for what happens otherwise.
    for n, (pin, clk, d, q) in enumerate(lanes):
        headers.append(hdr(pin, clk, 1, d, 2, 2 * d, 3 * d, base[n]))
    for n in range(2, N_LANES):
        headers.append(hdr(n, n, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)


def build_edge(timeout: int, d1: int = 12, arm_pin: int = 0,
               arm_edge: int = 0):
    """A REACTIVE lane: arm on a peer edge, then move a pin.

    lane 0:  ARM(arm_pin, edge=arm_edge, dly=timeout)
             LEVEL(UO0, 1, d1)        <- dispatches AT the edge (see note)
             LEVEL(UO0, 0, d1)        <- at edge + d1
             REARM(level=1, d1)       <- loop, re-arms for the next frame
    lanes 1-4: parked on a chaining re-arm.

    `timeout = 0` encodes NO TIMEOUT (wait indefinitely), which is how UART-rx
    idles between frames.

    ⛔⛔ A SPEC GAP THIS EXPOSES, FLAGGED NOT PAPERED OVER. The rebase sets
    `l_timestamp := now` at the edge, so the FIRST action after ARM dispatches
    AT the edge. UART-rx needs its first sample at `edge + half`, and there is
    nowhere to put that offset: ARM's delay field is the TIMEOUT, and a delay
    only takes effect at an action's WRITEBACK, so it delays the NEXT action
    rather than its own. The ISA has no pure-delay opcode -- the census's
    p_uart_rx lists only (ARM, SHIFTIN, READBIT) and assumed "centred by the
    lane's phase" was free. It is not. Needs a ruling: a pure-delay opcode, a
    no-op LEVEL as the idiom, or a rebase of `now + offset`.
    ⭐ The must-fire below does NOT depend on resolving it: varying the edge's
    phase and requiring `t_out - t_edge` to be CONSTANT proves the anchor is the
    edge, whatever the offset turns out to be.
    """
    prog, headers = [], []
    l0 = ACT_BASE
    prog.append(act(OP_ARM, arm_pin, arm_edge, timeout))
    prog.append(act(OP_LEVEL, UO0, 1, d1))
    prog.append(act(OP_LEVEL, UO0, 0, d1))
    prog.append(act(OP_REARM, 0, 1, d1))
    lp = l0 + 4 * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))
    headers.append(hdr(UO0, UO0, 1, d1, 2, 2 * d1, 3 * d1, l0))
    for n in range(1, N_LANES):
        headers.append(hdr(n, n, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)




def build_noop(timeout: int, half: int, d1: int = 12, arm_pin: int = 0,
               noop_pin: int = PIN_NONE):
    """The HALF-BIT OFFSET IDIOM: ARM -> no-op(delay=half) -> first sample.

    ⭐ WHY IT IS EXACT. The edge rebase sets `l_timestamp := now`, so the first
    action after ARM dispatches AT the edge -- but a UART receiver needs its
    first sample at `edge + half`. ARM's delay field is the TIMEOUT, and a delay
    only takes effect at an action's WRITEBACK (so it delays the NEXT action,
    not its own). Hence a no-op carrying `half`.
    ⭐⭐ And Ruling 2 is what makes the landing exact: writeback adds to the
    STORED timestamp, so the sample lands at `t_edge + half` HOWEVER LATE the
    no-op itself is serviced. The no-op's own service jitter never reaches the
    grid.

    `noop_pin` exists to build the BAD program: a no-op that names the lane's
    ARM pin -- a real INPUT -- instead of the reserved index. That one drives
    against the peer and must show up as X on the resolved bus, which is the
    contention class 1.6r closed on MISO.
    """
    prog, headers = [], []
    l0 = ACT_BASE
    prog.append(act(OP_ARM, arm_pin, 0, timeout))        # arm on FALL
    prog.append(act(OP_LEVEL, noop_pin, 0, half))        # the NO-OP: half a bit
    prog.append(act(OP_LEVEL, UO0, 0, d1))               # "first sample"
    prog.append(act(OP_LEVEL, UO0, 1, d1))
    prog.append(act(OP_REARM, 0, 1, d1))
    lp = l0 + 5 * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))
    headers.append(hdr(UO0, UO0, 1, d1, 2, 2 * d1, 3 * d1, l0))
    for n in range(1, N_LANES):
        headers.append(hdr(n, n, 0, 500, 2, 200, 240, lp))
    return b"".join(headers) + b"".join(prog)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    if "--all" in sys.argv:
        # ⛔⛔ EVERY IMAGE THE SUITE LOADS, WITH ITS ARGUMENTS RECORDED HERE.
        # `tb_edge` reads `noop_image_h19.hex` and NO COMMAND IN THE REPO
        # PRODUCED IT -- it was made by hand and then gitignored, so the suite
        # depended on an artefact with no recipe. Regenerating the images after
        # an encoder change duly broke must-fire 5b, because the half values are
        # a DIFFERENTIAL (19 - 7 = 12) and nothing said so.
        # ⇒ One target rebuilds all of them, and the arguments are the record.
        specs = [
            ([], "default smoke", "smoke_image.hex"),
            (["--census"], "all 8 opcodes", "census_image.hex"),
            (["--cfgerr"], "1.6s violation", "cfgerr_image.hex"),
            (["--five"] + [str(x) for x in FIVE_STRESS],
             "5-lane refill load (the run_mutants stress set)",
             "five_image.hex"),
            (["--chain", "12", "40"], "chaining re-arm", "chain_image.hex"),
            (["--stress", "25", "31"], "single-buffer stress", "stress_image.hex"),
            (["--edge", "200", "0", "edge_image"], "timeout 200, FALL", "edge_image.hex"),
            (["--edge", "0", "0", "edge_image_noto"], "no timeout, FALL", "edge_image_noto.hex"),
            (["--edge", "0", "1", "edge_image_rise"], "no timeout, RISE", "edge_image_rise.hex"),
            (["--noop", "0", "7", "noop_image"], "half = 7", "noop_image.hex"),
            (["--noop", "0", "19", "noop_image_h19"],
             "half = 19 (5b pairs with 7: difference 12)",
             "noop_image_h19.hex"),
            (["--noop", "0", "7", "bad"], "no-op on a real input pin", "noop_image_bad.hex"),
            # ⭐ T5.1: the first image in the suite that can carry HOST PAYLOAD.
            (["--tx", "12", "13"], "two TX lanes on queues 0 and 1",
             "tx_image.hex"),
            (["--txbadclk"], "1.6x violation: SHIFT with clkpin == pin",
             "tx_badclk_image.hex"),
            (["--half", "24"], "two half-duplex lanes: TX then RX on one lane",
             "half_image.hex"),
            (["--rxfast", "24"], "RX faster than the payload slot",
             "rxfast_image.hex"),
            (["--i2cframe", "62"], "a full I2C write: S | addr | A | data | A | P",
             "i2cframe_image.hex"),
        ]
        import hashlib
        import subprocess
        rc = 0
        manifest = []
        for args, why, _out in specs:
            r = subprocess.run([sys.executable, __file__] + args,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            ok = r.returncode == 0
            rc |= 0 if ok else 1
            print("  %-46s %-44s %s"
                  % (" ".join(args) or "(default)", why,
                     "ok" if ok else "*** FAILED"))
        # ⭐⭐ THE MANIFEST. Each reserved artefact is pinned by hash NEXT TO THE
        # RECIPE THAT MAKES IT, and the file is TRACKED -- so a recipe change
        # shows up as a diff in review, and an artefact that comes out
        # differently on another machine or tool version is visible too.
        # ⛔ WHY IT REPLACES COMPARING AGAINST THE OLD COPY ON DISK: the clean
        # room first compared regenerated content with the file it had just
        # quarantined, and "found" a difference that was the OLD copy's fault --
        # the stale file was only a valid reference if it was authoritative,
        # which is exactly what was in question. A tracked hash has provenance;
        # a file sitting in the tree does not.
        # ⛔ BUILT FROM THE SPEC LIST, NOT A DIRECTORY SCAN. A scan has to
        # GUESS which recipe made which file, and guessed wrong for most of
        # them -- eleven of seventeen lines read "# ?", which is the half of
        # the manifest that matters. Each spec already knows its output.
        def _sha(fn):
            with open(os.path.join(here, fn), "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()

        for args, _why, outfn in specs:
            if os.path.isfile(os.path.join(here, outfn)):
                manifest.append("%s  %s  # make_smoke_image.py %s"
                                % (_sha(outfn), outfn,
                                   " ".join(args) or "(default)"))
        # the corpus images have their own generator, named as theirs
        for fn in sorted(os.listdir(here)):
            if fn.startswith("corpus_") and fn.endswith(".hex"):
                manifest.append("%s  %s  # corpus.py" % (_sha(fn), fn))
        # ⭐⭐ THE TOOLCHAIN HEADER. A hash that disagrees on another machine
        # is either a recipe change (the finding) or a different tool building
        # the same recipe (not one), and the hashes alone cannot tell those
        # apart -- which makes "re-pin the hash" the cheap way out of a red
        # gate, and launders a real recipe change through a toolchain excuse.
        # Recording the versions next to the hashes is what separates them;
        # `clean_room.py` prints stored vs live on any mismatch.
        import toolchain
        tc = toolchain.header_lines()
        mpath = os.path.join(here, "artefacts.sha256")
        with open(mpath, "w", encoding="ascii", newline=chr(10)) as fh:
            fh.write("# GENERATED by make_smoke_image.py --all. Tracked on"
                     + chr(10))
            fh.write("# purpose: a recipe change must show as a diff here, in"
                     + chr(10))
            fh.write("# the same commit. sha256  artefact  # recipe" + chr(10))
            fh.write("# the toolchain that built these hashes:" + chr(10))
            for ln in tc:
                fh.write(ln + chr(10))
            for ln in manifest:
                fh.write(ln + chr(10))
        print()
        print("  manifest: %d artefacts pinned -> %s" % (len(manifest), mpath))
        for ln in tc:
            print("    %s" % ln)
        if any(ln.endswith(toolchain.MISSING) for ln in tc):
            print("    ⚠ a tool probed as MISSING -- the header records that"
                  " reading rather than omitting the line, so a manifest")
            print("      written without the full toolchain cannot read as"
                  " though it had one.")
        return rc
    if "--noop" in sys.argv:
        # --noop <timeout> <half> [bad] -- `bad` points the no-op at the arm pin
        k = sys.argv.index("--noop")
        to, half = int(sys.argv[k + 1]), int(sys.argv[k + 2])
        arg4 = sys.argv[k + 3] if len(sys.argv) > k + 3 else ""
        bad = arg4 == "bad"
        img = build_noop(to, half, noop_pin=(0 if bad else PIN_NONE))
        # ⭐ an explicit BASENAME, so `noop_image_h19.hex` has a command
        name = ("noop_image_bad" if bad
                else (arg4 if arg4 else "noop_image"))
        out = os.path.join(here, name + ".hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("%s (timeout=%d half=%d noop_pin=%d), %d bytes -> %s"
              % (name, to, half, 0 if bad else PIN_NONE, len(img), out))
        return 0
    if "--edge" in sys.argv:
        # --edge <timeout> [edge_polarity] [basename]
        # ⭐ THREE VARIANTS, because the four must-fires need different stimuli:
        #   edge_image       timeout=200, arm on FALL  -> rebase + timeout
        #   edge_image_noto  timeout=0,   arm on FALL  -> no edge, no release
        #   edge_image_rise  timeout=0,   arm on RISE  -> I2C clock stretch
        k = sys.argv.index("--edge")
        to = int(sys.argv[k + 1])
        pol = int(sys.argv[k + 2]) if len(sys.argv) > k + 2 else 0
        name = sys.argv[k + 3] if len(sys.argv) > k + 3 else "edge_image"
        img = build_edge(to, arm_edge=pol)
        out = os.path.join(here, name + ".hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("edge image (timeout=%d), %d bytes -> %s" % (to, len(img), out))
        return 0
    if "--cfgerr" in sys.argv:
        img = build_cfgerr()
        out = os.path.join(here, "cfgerr_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x" % b + chr(10))
        print("cfgerr image (1.6s violation), %d bytes -> %s" % (len(img), out))
        return 0
    if "--census" in sys.argv:
        img = build_census()
        out = os.path.join(here, "census_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("census image (all 8 opcodes), %d bytes -> %s" % (len(img), out))
        return 0
    if "--chain" in sys.argv:
        k = sys.argv.index("--chain")
        img = build_chain(int(sys.argv[k + 1]), int(sys.argv[k + 2]))
        out = os.path.join(here, "chain_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("chain image, %d bytes -> %s" % (len(img), out))
        return 0
    if "--five" in sys.argv:
        k = sys.argv.index("--five")
        delays = [int(x) for x in sys.argv[k + 1:k + 6]]
        img = build_five(delays)
        # ⛔⛔ AN OPTIONAL BASENAME, SO PROBES CANNOT WRITE A RESERVED NAME.
        # The J investigation swept dozens of delay sets through this flag and
        # every one landed on `five_image.hex` -- the name the suite's own
        # recipe owns -- so the tree was left holding arm C's program under the
        # stress image's name, and the clean room caught it only afterwards.
        # Same root as the earlier `cj_measured.txt` clobber.
        # ⭐ Experiments pass `probe_*`, which `.gitignore` covers; reserved
        # names belong to generators and the manifest.
        base = (sys.argv[k + 6] if len(sys.argv) > k + 6
                and not sys.argv[k + 6].startswith("-") else "five_image")
        out = os.path.join(here, base + ".hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("five-lane image %s, %d bytes -> %s" % (delays, len(img), out))
        return 0
    if "--i2cframe" in sys.argv:
        k = sys.argv.index("--i2cframe")
        dd = int(sys.argv[k + 1]) if len(sys.argv) > k + 1 else 62
        img = build_i2cframe(dd)
        out = os.path.join(here, "i2cframe_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("i2c frame image d=%d, %d bytes -> %s"
              % (dd, len(img), out))
        return 0
    if "--rxfast" in sys.argv:
        k = sys.argv.index("--rxfast")
        dd = int(sys.argv[k + 1]) if len(sys.argv) > k + 1 else 24
        img = build_rxfast(dd)
        out = os.path.join(here, "rxfast_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("rxfast image d=%d, %d bytes -> %s" % (dd, len(img), out))
        return 0
    if "--half" in sys.argv:
        k = sys.argv.index("--half")
        dd = int(sys.argv[k + 1]) if len(sys.argv) > k + 1 else 24
        img = build_half(dd)
        out = os.path.join(here, "half_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("half-duplex image d=%d, %d bytes -> %s"
              % (dd, len(img), out))
        return 0
    if "--txbadclk" in sys.argv:
        img = build_tx_badclk()
        out = os.path.join(here, "tx_badclk_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("tx badclk image, %d bytes -> %s" % (len(img), out))
        return 0
    if "--tx" in sys.argv:
        k = sys.argv.index("--tx")
        d0 = int(sys.argv[k + 1]) if len(sys.argv) > k + 1 else 12
        d1 = int(sys.argv[k + 2]) if len(sys.argv) > k + 2 else 13
        img = build_tx(d0, d1)
        out = os.path.join(here, "tx_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("tx image d0=%d d1=%d, %d bytes -> %s" % (d0, d1, len(img), out))
        return 0
    if "--stress" in sys.argv:
        k = sys.argv.index("--stress")
        d0 = int(sys.argv[k + 1])
        d1 = int(sys.argv[k + 2])
        img = build_stress(d0, d1)
        out = os.path.join(here, "stress_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("stress image d0=%d d1=%d, %d bytes -> %s"
              % (d0, d1, len(img), out))
        return 0
    img = build()
    out = os.path.join(here, "smoke_image.hex")
    with open(out, "w", encoding="ascii") as fh:
        for b in img:
            fh.write("%02x\n" % b)
    print("HDR_BITS=%d HDR_BYTES=%d ACT_W=%d ACT_BYTES=%d ACT_BASE=%d"
          % (HDR_BITS, HDR_BYTES, ACT_W, ACT_BYTES, ACT_BASE))
    print("image is %d bytes -> %s" % (len(img), out))
    if len(img) > (1 << AW):
        print("*** image does not fit 2**AW = %d" % (1 << AW))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
