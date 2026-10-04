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

HEADER, 6 bytes, MSB-aligned in 48 bits:
    [47:44] pin        [43:40] clkpin     [39:30] t
    [29:26] C_i        [25:18] D_sched    [17:10] D_tol
    [9:2]   base       [1:0]   spare
ACTION, 3 bytes, MSB-aligned in 24 bits:
    [23:21] opcode     [20:17] pin        [16] level
    [15:6]  delay      [5:2]   count      [1:0] spare
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
    headers.append(hdr(UO0, UO0, 1, d, 2, 2 * d, 3 * d, base[0]))
    headers.append(hdr(UO1, UO1, 1, d + 1, 2, 2 * d, 3 * d, base[1]))
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
            ([], "default smoke"),
            (["--census"], "all 8 opcodes"),
            (["--cfgerr"], "1.6s violation"),
            (["--five"] + [str(x) for x in FIVE_STRESS],
             "5-lane refill load (the run_mutants stress set)"),
            (["--chain", "12", "40"], "chaining re-arm"),
            (["--stress", "25", "31"], "single-buffer stress"),
            (["--edge", "200", "0", "edge_image"], "timeout 200, FALL"),
            (["--edge", "0", "0", "edge_image_noto"], "no timeout, FALL"),
            (["--edge", "0", "1", "edge_image_rise"], "no timeout, RISE"),
            (["--noop", "0", "7", "noop_image"], "half = 7"),
            (["--noop", "0", "19", "noop_image_h19"], "half = 19 (5b pairs with 7: difference 12)"),
            (["--noop", "0", "7", "bad"], "no-op on a real input pin"),
        ]
        import subprocess
        rc = 0
        for args, why in specs:
            r = subprocess.run([sys.executable, __file__] + args,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            ok = r.returncode == 0
            rc |= 0 if ok else 1
            print("  %-46s %-44s %s"
                  % (" ".join(args) or "(default)", why,
                     "ok" if ok else "*** FAILED"))
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
        out = os.path.join(here, "five_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("five-lane image %s, %d bytes -> %s" % (delays, len(img), out))
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
