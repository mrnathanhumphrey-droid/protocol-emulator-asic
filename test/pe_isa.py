"""pe_isa -- THE ONE ENCODER. Field widths, the packers, and the host stream.

Everything that knows how a program byte or a host push is laid out lives here
and nowhere else.

⛔⛔⛔ WHY THIS MODULE EXISTS, FROM FOUR ACTUAL DEFECTS. The two-copies failure
is this project's most reliable bug:

  * `tb_smoke` kept a private `exp_act[23:2]` slice of the action word, and
    broke the moment a queue field used the padding;
  * `run_local.py` kept a third copy of the source list and could not elaborate
    at all, while its comment claimed it matched CI;
  * `periodic_equivalence` certified a lane table nobody used any more, which is
    why `lane_digest` exists;
  * `gate_pyrta`, `gate_rearm` and `gate_pin_subsets` each built their own pyRTA
    task set and all three reported the wrong answer at once.

R1/R2's host model pushes bytes through the `ui_in` nibble channel, and `pe_asm`
emits the image that consumes them. Written separately, those two are the same
defect waiting: the program would say "queue 1" and the host stream would push
to queue 2, and every test would pass on both sides of a mismatch.
⇒ One module owns the encoding AND the push sequence for a transfer.

⚠ WHAT THIS CANNOT COVER: the Verilog side. `src/pe_engine.v` derives the same
widths in its own language, so `model/gate_one_encoder.py` extracts those
localparams and checks they agree with the values here -- a cross-language
check, because a Python module cannot be imported by a testbench.
"""

from __future__ import annotations

import hashlib

# ---------------------------------------------------------------------------
# WIDTHS -- the single source. `gate_one_encoder.py` checks the RTL agrees.
# ---------------------------------------------------------------------------
N_LANES, AW, DLY_W, PINW, CW, D_W = 5, 8, 10, 4, 4, 8
CNT_W = 4                  # the per-action count field
BQW = 2                    # TX queue index, in what used to be zero padding
N_TXQ = 1 << BQW           # TX queues the tag can name

HDR_BITS = PINW * 2 + 1 + DLY_W + CW + D_W + D_W + AW   # +1 = drive mode
HDR_BYTES = (HDR_BITS + 7) // 8
ACT_W = 3 + PINW + 1 + DLY_W + CNT_W + BQW
ACT_BYTES = (ACT_W + 7) // 8
ACT_BASE = N_LANES * HDR_BYTES

OP_LEVEL, OP_SHIFT, OP_SHIFTIN, OP_READBIT = 0, 1, 2, 3
OP_START, OP_STOP, OP_ARM, OP_REARM = 4, 5, 6, 7
OPCODES = {
    "LEVEL": OP_LEVEL, "SHIFT": OP_SHIFT, "SHIFTIN": OP_SHIFTIN,
    "READBIT": OP_READBIT, "START": OP_START, "STOP": OP_STOP,
    "ARM": OP_ARM, "REARM": OP_REARM,
}

# pin indices: 0..7 = uio, 8..11 = uo_out[0..3]
N_UIO = 8
UO0, UO1, UO2, UO3 = 8, 9, 10, 11
PIN_NONE = (1 << PINW) - 1          # the reserved non-driving index

# ---- the field order, declared as data so the digest covers it ------------
HDR_FIELDS = (("pin", PINW), ("clkpin", PINW), ("mode", 1), ("t", DLY_W),
              ("c", CW), ("dsched", D_W), ("dtol", D_W), ("base", AW))
ACT_FIELDS = (("op", 3), ("pin", PINW), ("level", 1), ("delay", DLY_W),
              ("count", CNT_W), ("q", BQW))


def _pack(fields, values, nbytes):
    w = 0
    for (_name, width), val in zip(fields, values):
        w = (w << width) | (int(val) & ((1 << width) - 1))
    total = sum(width for _n, width in fields)
    w <<= (nbytes * 8 - total)          # MSB-align; spare lands at the bottom
    return w.to_bytes(nbytes, "big")


def hdr(pin, clkpin, mode, t, c, dsched, dtol, base) -> bytes:
    """`mode`: 1 = push-pull, 0 = open-drain.

    ⛔ Open-drain is only meaningful on a `uio` pin: `uo_out` has no enable, so
    an open-drain lane there drives low once and sticks. The chip now REFUSES
    such a program (1.6s, `config_err`) -- it is not merely discouraged.
    """
    return _pack(HDR_FIELDS, (pin, clkpin, mode, t, c, dsched, dtol, base),
                 HDR_BYTES)


def act(op, pin, level, delay, count=0, q=0) -> bytes:
    """`q` names the TX QUEUE this action draws its payload from.

    ⭐ It costs no layout: the action word was 22 bits inside 3 bytes, so the
    bottom 2 bits were zero padding. Every image written before the field
    existed is bit-identical to one written with `q = 0`.
    """
    return _pack(ACT_FIELDS, (op, pin, level, delay, count, q), ACT_BYTES)


# ---------------------------------------------------------------------------
# THE HOST STREAM -- the other half, and the reason this module is shared
# ---------------------------------------------------------------------------
def host_pushes(byte, queue):
    """The pushes that deliver one payload byte to one TX queue.

    Returns [(nibble, tag)] in order. Two pushes per byte, **HIGH NIBBLE
    FIRST**, and the tag accompanies BOTH -- the hardware latches it with the
    high nibble, so a host that changed it between pushes would split the byte
    across two queues; repeating it is what makes that impossible from this
    side too.

    ⛔ THE ORDER IS A RULING, NOT A CONVENTION: high-nibble-first matches the
    MSB-first bit order the SPI and I2C lanes shift with, so a byte reads the
    same way on the wire as it was pushed.
    """
    if not 0 <= queue < N_TXQ:
        raise ValueError("TX queue %d outside 0..%d" % (queue, N_TXQ - 1))
    b = int(byte) & 0xFF
    return [((b >> 4) & 0xF, queue), (b & 0xF, queue)]


def host_stream(payload, queue):
    """The push sequence for a whole payload, one queue."""
    out = []
    for b in payload:
        out += host_pushes(b, queue)
    return out


# ---------------------------------------------------------------------------
# THE DIGEST -- printed by every artefact, so a private copy is detectable
# ---------------------------------------------------------------------------
def digest() -> str:
    """A hash over every field width, the packing ORDER, and the push shape.

    ⚠ WHAT IT CATCHES AND WHAT IT DOES NOT. Artefacts that import this module
    cannot disagree, so a matching digest is not the interesting case: the
    digest exists so that an artefact which reintroduces a PRIVATE copy and
    prints a digest computed from it shows up as a mismatch within one run.
    `gate_one_encoder.py` additionally greps for second definitions of the
    packers, because a copy that prints nothing would otherwise be invisible.
    """
    h = hashlib.sha256()
    for name, width in HDR_FIELDS:
        h.update(("H:%s:%d;" % (name, width)).encode())
    for name, width in ACT_FIELDS:
        h.update(("A:%s:%d;" % (name, width)).encode())
    h.update(("B:%d,%d,%d,%d,%d;" % (HDR_BITS, HDR_BYTES, ACT_W, ACT_BYTES,
                                     ACT_BASE)).encode())
    h.update(("P:%s;" % (host_pushes(0xA5, 1),)).encode())
    return h.hexdigest()[:12]
