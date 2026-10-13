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

# ⭐ THE HEADER'S LAST SPARE BIT IS THE BIT-ORDER BIT (Wilson's ruling 1).
# The header was 47 bits in 6 bytes with ONE spare at the bottom; `order` takes
# it, so the layout is now exactly 48 of 48 and the word is full.
HDR_BITS = PINW * 2 + 1 + DLY_W + CW + D_W + D_W + AW + 1  # +1 mode, +1 order
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
N_PINS = UO3 + 1                    # 12 real pins: 8 `uio` + 4 `uo_out`
PIN_NONE = (1 << PINW) - 1          # the reserved non-driving index

# ---- the field order, declared as data so the digest covers it ------------
HDR_FIELDS = (("pin", PINW), ("clkpin", PINW), ("mode", 1), ("t", DLY_W),
              ("flags", CW), ("dsched", D_W), ("dtol", D_W), ("base", AW),
              ("order", 1))

# ⛔⛔ BIT ORDER IS A PER-LANE PROPERTY, AND IT HAD BEEN AN UNSTATED GLOBAL.
# `OP_SHIFT` emits `l_tx[0]` first, so the wire order was LSB-FIRST for every
# lane -- while I2C and SPI mode 0 are both MSB-first and UART really is
# LSB-first. One engine-wide order cannot serve both.
# ⭐ A LANE RUNS ONE PROTOCOL, so the setting belongs in the lane header, not
# in each action: per-action it would be 5 x N_ACTIONS bits to say the same
# thing, and there is no spare action bit anyway (ACT_W is 24 of 24).
#     ORDER_LSB = 0   UART: first bit out is the LSB (and the default, so
#                     every image written before this field is unchanged)
#     ORDER_MSB = 1   I2C, SPI mode 0: first bit out is the MSB
# ⚠ THE DOCSTRING BELOW USED TO CLAIM THE LANES SHIFT MSB-FIRST, which was the
# OPPOSITE of what the RTL did, and it went unnoticed because nothing decoded
# the wire against a standard -- and the one byte a bench checked end to end
# (0x5A) is a BIT-REVERSAL PALINDROME that matched either way. sigrok reading
# a pushed 0x05 as 7-bit address 0x50 is what settled it.
ORDER_LSB, ORDER_MSB = 0, 1

# ⛔⛔ RULING CE1 + CE2 (HDR) -- THE 4-BIT FIELD THAT WAS `c` IS NOW `flags`.
# `c` was a stale copy of the inter-dispatch spacing C, written `2` from when
# C measured 2 (it measures 3; that value lives in the analysis, not here).
# The RTL loaded it into `l_c` and NOTHING read it, nor did any tool -- so the
# four bits were free, and they are now per-lane MODE BITS:
#     bit0  FLAG_HALF_HIGH  CE1: a clocked lane's HIGH phase lasts d/2, not d
#                           (I2C Fm up to ~397 kHz; refused when d/2 < D*)
#     bit1  FLAG_CLK_INV    CE2: the clock pin is driven INVERTED (push-pull
#                           only) -- SPI mode 3 -> mode 1, mode 0 -> mode 2
#     bits2-3 RESERVED      must be 0: kept for the 60 MHz branch. `hdr()`
#                           refuses them, as do `pe_asm` and the image audit.
# ⭐ EVERY EXISTING IMAGE WRITES 0, so each runs byte-identically to before
# (the builders' old `c = 2` would now have meant CLK_INV -- they were updated,
# and the lockstep proves nothing moved).
FLAG_HALF_HIGH, FLAG_CLK_INV = 0x1, 0x2
FLAG_RESERVED = 0xC
ACT_FIELDS =(("op", 3), ("pin", PINW), ("level", 1), ("delay", DLY_W),
              ("count", CNT_W), ("q", BQW))


def _pack(fields, values, nbytes):
    w = 0
    for (name, width), val in zip(fields, values):
        # ⛔⛔ A VALUE THAT DOES NOT FIT ITS FIELD IS REFUSED, NEVER MASKED
        # (WF2, found by N1). This used to `& ((1 << width) - 1)` silently: a
        # UART-tx header asking for D_sched 434 / D_tol 868 in 8-bit fields was
        # encoded as 178 / 100 -- an image saying different numbers than its
        # program, with D_sched > D_tol, and pe_asm none the wiser.
        if not 0 <= int(val) < (1 << width):
            raise ValueError("field %s = %d does not fit its %d-bit field "
                             "(0..%d) -- the encoder refuses rather than "
                             "truncating" % (name, int(val), width,
                                             (1 << width) - 1))
        w = (w << width) | int(val)
    total = sum(width for _n, width in fields)
    w <<= (nbytes * 8 - total)          # MSB-align; spare lands at the bottom
    return w.to_bytes(nbytes, "big")


def hdr(pin, clkpin, mode, t, flags, dsched, dtol, base,
        order=ORDER_LSB) -> bytes:
    """`mode`: 1 = push-pull, 0 = open-drain.
    `flags`: FLAG_HALF_HIGH | FLAG_CLK_INV, or 0 (see FLAG_* above). The
    reserved bits are REFUSED here, at the one encoder.
    `order`: ORDER_LSB (0) or ORDER_MSB (1) -- which end of the byte goes out
    first. See ORDER_LSB above for why it is per LANE.

    ⛔ Open-drain is only meaningful on a `uio` pin: `uo_out` has no enable, so
    an open-drain lane there drives low once and sticks. The chip now REFUSES
    such a program (1.6s, `config_err`) -- it is not merely discouraged.
    ⭐ `order` DEFAULTS TO LSB, which is what the engine did before the field
    existed, so every image written without it is bit-identical to one written
    with `order = ORDER_LSB` -- the same property the `q` field has.
    """
    if int(flags) & ~(FLAG_HALF_HIGH | FLAG_CLK_INV):
        raise ValueError("header flags 0x%X set a RESERVED bit (only "
                         "HALF_HIGH = 1 and CLK_INV = 2 exist)" % int(flags))
    return _pack(HDR_FIELDS,
                 (pin, clkpin, mode, t, flags, dsched, dtol, base, order),
                 HDR_BYTES)


def bitrev8(b: int) -> int:
    """Reverse the bits of a byte.

    ⭐ SHARED, because the host needs the same function the RTL implements: a
    test that wants 0xA0 on an MSB-first wire has to know what to push, and a
    second private copy of a bit reversal is the kind of thing that disagrees
    in one place only.
    """
    return int("{:08b}".format(int(b) & 0xFF)[::-1], 2)


def act(op, pin, level, delay, count=0, q=0) -> bytes:
    """`q` names the TX QUEUE this action draws its payload from.

    ⭐ It costs no layout: the action word was 22 bits inside 3 bytes, so the
    bottom 2 bits were zero padding. Every image written before the field
    existed is bit-identical to one written with `q = 0`.
    """
    return _pack(ACT_FIELDS, (op, pin, level, delay, count, q), ACT_BYTES)


# ---------------------------------------------------------------------------
# THE SELF-CLOCKED SHIFTS -- named constructors, because the field is overloaded
# ---------------------------------------------------------------------------
# ⛔⛔ `level = 1` ON A SHIFT OR SHIFTIN WHOSE LANE HAS A REAL CLOCK PIN MEANS
# "SELF-CLOCKED": the action drives BOTH clock phases itself and carries a whole
# byte, instead of one bit per action. 20 actions per I2C wire byte become 2.
#
# WHY AN OVERLOADED FIELD AT ALL -- there was nothing else. Measured: ACT_FIELDS
# is 24 of 24 bits, HDR_FIELDS is 48 of 48, and all 8 opcodes are used. And
# `level` is the RIGHT field to overload rather than merely the available one:
# on a self-clocked shift "the clock level to write this dispatch" is vacuous,
# because the action writes both levels.
#
# ⛔ THE UART CASE IS DEFINED AND UNCHANGED: with NO real clock pin
# (`clkpin = PIN_NONE`), `level` keeps its exact old meaning. Self-clocking
# requires `clk_real` AND `level = 1`. A UART lane has no clock pin, so nothing
# a UART program can write is reinterpreted.
#
# ⚠ SUPPORTED PHASE ORDER, and the limitation stated rather than omitted: the
# self-clocked order is DATA WITH THE CLOCK LOW, THEN CLOCK HIGH -- data settles
# while the clock is low and is read on the rise. That is I2C, and SPI MODES 0
# AND 3, which covers both FRAM parts. SPI MODES 1 AND 2 change data on the
# RISING edge and need the reverse order: they are NOT expressible as a
# self-clocked shift and stay on the unclocked idiom (`level = 0` plus
# `OP_LEVEL` for the clock), which is untouched and still available.
#
# ⇒ These constructors exist so no caller has to write the bare `1`. `pe_asm`
#   refuses a raw `level = 1` SHIFT on a real-clock lane that did not come
#   through them, so the overload stays visible in the toolchain.
SELF_CLOCKED = 1        # the `level` value that means "self-clocked"


def act_shift_clocked(pin, delay, nbits=8, q=0) -> bytes:
    """A self-clocked transmit of `nbits` bits (a whole byte by default).

    ⛔ `count = nbits - 1` BECAUSE THAT IS THE EXISTING `OP_SHIFT` CONVENTION,
    not an off-by-one: the engine compares the PRE-increment `tx_bitp` against
    `a_cnt`, which is also the comparison the host-byte load uses -- so the
    load and the retire coincide, which is what makes a clocked byte reload the
    next payload exactly when it finishes the current one.
    """
    if not 1 <= int(nbits) <= 8:
        raise ValueError("nbits %r outside 1..8" % (nbits,))
    return act(OP_SHIFT, pin, SELF_CLOCKED, delay, count=int(nbits) - 1, q=q)


def act_shiftin_clocked(pin, delay, nbits=8) -> bytes:
    """A self-clocked receive of `nbits` bits. `nbits = 1` is an I2C ACK slot.

    ⛔ `count = nbits` HERE, against `nbits - 1` for the transmit, because the
    two opcodes already counted differently before this existed: `OP_SHIFTIN`
    compares against `a_cnt - 1`. The asymmetry is PRE-EXISTING SEMANTICS
    PRESERVED, and these constructors are where it stops being a trap.

    ⚠ A clocked receive of `n` bits takes `2n + 1` dispatches, not `2n`. The bit
    is captured on the OBSERVED clock rise, which lands in the idle window after
    the high phase, so a trailing COLLECT phase retires the action with the last
    bit in hand. Store cost is unchanged -- it is still ONE action.
    """
    if not 1 <= int(nbits) <= 8:
        raise ValueError("nbits %r outside 1..8" % (nbits,))
    return act(OP_SHIFTIN, pin, SELF_CLOCKED, delay, count=int(nbits))


# ---------------------------------------------------------------------------
# RULING M -- THE STORE IS WRITTEN WHOLE, AND WHAT FILLS IT IS DEFINED
# ---------------------------------------------------------------------------
# ⛔⛔ THE STORE HAS NO RESET, AND THAT REACHES SILICON. A 51-byte image left 205
# of 256 store bytes NEVER WRITTEN, holding whatever powered up. If any lane's
# PC reaches past its program -- a lane with no terminating REARM, a header
# `base` outside the image, or the 8-bit PC wrapping into the header area --
# the engine executes RANDOM ACTIONS ON REAL PINS: the silent class. Found as a
# bench symptom (the readback seeds disagreeing past byte 51), but the defect is
# the chip's.
# ⇒ Every image is written to all 2^AW bytes, and the bytes past the program
#   hold ONE defined word, chosen for what it does if it is ever executed:
#
#     a CHAINING REARM (level 0) on PIN_NONE, maximum delay.
#
#   * NON-DRIVING: OP_REARM moves no pin (`OP_ARM, OP_REARM: ;` in the dispatch
#     arm), and PIN_NONE is the reserved non-driving index besides.
#   * IT TERMINATES THE RUN-OFF: a chaining REARM does not retire
#     (`act_retire` excludes `OP_REARM` at level 0), so the PC never advances --
#     a lane that falls off its program PARKS at the first filler word instead
#     of walking on into the next lane's code or wrapping into the headers.
#   * IT IS ALREADY THE PARKED-LANE IDIOM (`act(OP_REARM, 0, 0, 500)`) and is
#     classified DEFINED in `model/gate_degenerate_fields.py`.
#   * MAXIMUM DELAY so a parked-off lane costs one dispatch per 1023 cycles.
#   * DISTINCTIVE by PIN_NONE + delay 1023, which no shipped program uses:
#     `test/clocked_conform.vh` asserts the prefetch never captures it.
#   ⛔ count = 0 AND q = 0, as in every REARM the suite already ships. The count
#     is unread on OP_REARM, but `q` is NOT inert: `host_q = a_q` steers the TX
#     queue mux in `project.v` for as long as the action is current. Nothing
#     pops on a REARM, but a filler that moved that mux would be a word that
#     "drives nothing" except a select line -- so it does not.
# ⚠ NOT A REFUSAL, AND THAT IS A DECLARED LIMIT: no encoding in the current ISA
# is refused for every lane (each refusal depends on the lane's header), so a
# run-off is SAFE but SILENT. The audit (`model/gate_store_full.py`) refuses
# such a program statically instead.
STORE_BYTES = 1 << AW
STORE_FILLER = act(OP_REARM, PIN_NONE, 0, (1 << DLY_W) - 1)


def full_store(img: bytes) -> bytes:
    """`img` padded to all STORE_BYTES with the filler word, ALIGNED.

    The filler starts at the image's end, which is an action boundary (headers
    then whole actions), so a run-off PC lands on a whole filler word. 2^AW is
    not a multiple of ACT_BYTES, so the last partial word gets the filler's
    leading bytes -- written, and unreachable by any PC that a whole filler word
    before it has already parked.
    """
    img = bytes(img)
    # ⭐ IDEMPOTENT on an image that is already the whole store -- every
    # tracked image now is, so a reader that pads defensively must not refuse
    # one. Whether its tail really is the filler is `gate_store_full`'s check.
    if len(img) == STORE_BYTES:
        return img
    if len(img) > STORE_BYTES:
        raise ValueError("image is %d bytes, over the %d-byte store"
                         % (len(img), STORE_BYTES))
    if len(img) < ACT_BASE or (len(img) - ACT_BASE) % ACT_BYTES:
        raise ValueError("image ends mid-action (%d bytes), so the filler "
                         "would be misaligned" % len(img))
    pad = STORE_BYTES - len(img)
    reps = (STORE_FILLER * (pad // ACT_BYTES + 1))[:pad]
    return img + reps


def write_image(path, img) -> bytes:
    """THE ONE WRITER of a `.hex` image: always the full store (ruling M1).

    ⛔ Every image writer goes through here so no path can emit a short image;
    `model/gate_store_full.py` refuses any tracked image under STORE_BYTES.
    Returns the bytes written.
    """
    full = full_store(img)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("".join("%02x\n" % b for b in full))
    return full


def _unpack(fields, raw, nbytes):
    """The inverse of `_pack`: {name: value}."""
    w = int.from_bytes(raw, "big") >> (nbytes * 8 - sum(x for _n, x in fields))
    out = {}
    for name, width in reversed(fields):
        out[name] = w & ((1 << width) - 1)
        w >>= width
    return out


def lane_programs(img):
    """{lane: (header dict, [action dict, ...])}: each lane's actions from its
    header's base through its first OP_REARM, which is how every builder here
    ends a lane (a loop, or the parked lane's chaining wait)."""
    out = {}
    for ln in range(N_LANES):
        h = _unpack(HDR_FIELDS, img[ln * HDR_BYTES:(ln + 1) * HDR_BYTES],
                    HDR_BYTES)
        acts, a = [], h["base"]
        while a + ACT_BYTES <= len(img) and len(acts) <= STORE_BYTES:
            x = _unpack(ACT_FIELDS, img[a:a + ACT_BYTES], ACT_BYTES)
            acts.append(x)
            if x["op"] == OP_REARM:
                break
            a += ACT_BYTES
        out[ln] = (h, acts)
    return out


# ⛔⛔ RULING RC4 -- AN I2C LANE IS MSB-FIRST, AND THE ORDER IS DERIVED, NOT
# DEFAULTED. `hdr()`'s default is LSB (UART's order, and every image written
# before the field existed), and every I2C builder inherited it: SIX clocked
# images framed I2C on an LSB-first lane, so `5B` went out as `DA` -- correct
# silicon faithfully sending the wrong byte, found on the first foreign decode
# (sigrok). ⇒ A lane whose program uses START/STOP framing is I2C, so its
# order is MSB; builders take the order from `order_for`, and `i2c_order_
# problems` refuses an image where the two disagree.
I2C_ORDER = ORDER_MSB


def order_for(ops):
    """The bit order a lane's program requires: MSB-first if it frames with
    START/STOP (I2C), else the LSB default."""
    return I2C_ORDER if any(o in (OP_START, OP_STOP) for o in ops) else ORDER_LSB


def i2c_order_problems(img, exempt=()):
    """-> [str]: every lane whose program uses OP_START/OP_STOP but whose
    header is LSB-first. `exempt` names lanes excused BY NAME by the caller."""
    probs = []
    for ln, (h, acts) in sorted(lane_programs(img).items()):
        ops = [x["op"] for x in acts]
        if ln in exempt or order_for(ops) == h["order"]:
            continue
        if order_for(ops) == I2C_ORDER:
            probs.append("lane %d frames with START/STOP (I2C) but its header "
                         "is LSB-first: every byte would go out bit-reversed "
                         "(I2C is MSB-first, UM10204 3.1.5)" % ln)
    return probs


def flag_problems(img, d_star):
    """-> [str]: every header whose mode bits the chip must not be given
    (ruling HDR, CE1, CE2). ONE implementation, called by `pe_asm` on the
    image it assembles and by the image audit on every tracked image.

      * a RESERVED bit (2-3) set -- they are kept for the 60 MHz branch;
      * CLK_INV on an open-drain lane (an I2C clock is released, not driven:
        there is no level to invert), on a lane with no distinct real clock,
        or on a `uio` clock (the XOR would land after the last flop -- F2);
      * HALF_HIGH on a lane with a clocked action whose d/2 < `d_star`: the
        HIGH phase is a dispatch gap, and J = 1 holds only for gaps >= D*.
    `d_star` is passed in, because D* belongs to the analysis, not here."""
    probs = []
    for ln, (h, acts) in sorted(lane_programs(img).items()):
        f = h["flags"]
        if f & FLAG_RESERVED:
            probs.append("lane %d sets RESERVED header flag bit(s) 0x%X"
                         % (ln, f & FLAG_RESERVED))
        clocked = h["clkpin"] < N_PINS and h["clkpin"] != h["pin"]
        if f & FLAG_CLK_INV:
            if h["mode"] != 1:
                probs.append("lane %d: CLK_INV on an OPEN-DRAIN lane -- a "
                             "released clock has no level to invert" % ln)
            elif not clocked:
                probs.append("lane %d: CLK_INV with no distinct real clock "
                             "pin" % ln)
            elif h["clkpin"] < N_UIO:
                probs.append("lane %d: CLK_INV on a `uio` clock (pin %d) -- "
                             "only a `uo_out` clock can be inverted before a "
                             "flop (F2)" % (ln, h["clkpin"]))
        if f & FLAG_HALF_HIGH:
            for x in acts:
                if (x["op"] in (OP_SHIFT, OP_SHIFTIN) and x["level"] == 1
                        and clocked and x["delay"] // 2 < d_star):
                    probs.append("lane %d: HALF_HIGH with a clocked action at "
                                 "d = %d: its HIGH phase d/2 = %d is under "
                                 "D* = %d, so J = 1 would not hold for that "
                                 "gap" % (ln, x["delay"], x["delay"] // 2,
                                          d_star))
                    break
    return probs


def filler_vh() -> str:
    """The filler word for the bench, GENERATED so it is never typed twice."""
    word = int.from_bytes(STORE_FILLER, "big") >> (ACT_BYTES * 8 - ACT_W)
    return ("/* store_filler.vh -- GENERATED by test/pe_isa.py. DO NOT EDIT.\n"
            " * The word every image's unused store bytes hold (ruling M): a\n"
            " * chaining OP_REARM on PIN_NONE at maximum delay. A correctly\n"
            " * terminated program never FETCHES it.\n */\n"
            "localparam [%d:0] PE_STORE_FILLER = %d'h%0*x;\n"
            % (ACT_W - 1, ACT_W, (ACT_W + 3) // 4, word))


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
    bit order the lane's `order` header bit selects, so a byte reads the
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
