"""EVERY OPCODE x EVERY ACTION FIELD x ITS DEGENERATE VALUES, ENUMERATED.

⛔⛔ WHY THIS GATE EXISTS: `count = 0` WAS NOT ALONE, and it was not found by
thinking. A clocked `OP_SHIFTIN` with `count = 0` reached the engine while
`tb_fifo` was being built (a corrupted store, from pushing host bytes while
PROG was still high), and `clocked_conform` reported "no model entry for op=2
cnt=0". Writing the guard then turned up a SECOND route to the same state: a
clocked `OP_SHIFT` with `count = 15` computes `a_cnt + 1` = 16, which WRAPS to
0 in the 4-bit field. One degenerate value, found by accident; a second, found
by writing the fix. That is the signature of a CLASS, and this project's rule
for a class is to enumerate it rather than fix instances.

⭐ THE FIELDS ARE SMALL, SO THE TABLE IS FINITE: op 3 bits, pin 4, level 1,
delay 10, count 4, q 2. Enumerating the degenerate values -- zero, the maximum,
and the reserved encodings (`PIN_NONE`, pins 12..14, queue indices at or above
`N_TXQ`) -- gives a bounded table, and every row carries one of three verdicts:

    REFUSED      no shipped image may contain it, and this gate says so
    DEFINED      it has meaning; the model and the RTL agree on what
    UNREACHABLE  it cannot occur, with a written reason

⚠ WHERE THIS SITS, AND A DEVIATION DECLARED. The ruling asked `pe_asm` to
refuse the degenerate count. `pe_asm`'s lane representation is
`(op, pin, level, delay, q)` -- IT DOES NOT CARRY `count` -- so the refusal
cannot live there without changing every caller and every must-fire that
builds those tuples. This gate decodes the ASSEMBLED IMAGES instead, which is
strictly stronger for the purpose: it sees what actually SHIPS, including
images built by generators that never pass through `pe_asm`'s tuple form at
all.

⛔⛔ OWED, AGAINST THE `pe_asm` PROTOCOL FRONT-END. When the judge-usable
assembler lands, its lane descriptions carry `count`, and the refusal moves to
ASSEMBLY TIME as well -- a program is then rejected where it is WRITTEN rather
than audited after it is built. This gate stays either way: it is the only
thing that sees images produced by generators which never pass through the
assembler at all. ⇒ Interim by ruling, not by accident.

⛔ What it does NOT do is reject a program at assembly time, so a new
generator can still emit a degenerate action -- it will fail here, in the gate,
rather than at the call site.
"""
import collections
import glob
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
import pe_isa as I                                              # noqa: E402

sys.path.insert(0, HERE)
import hold_bound                                               # noqa: E402

N_PINS = I.UO3 + 1
REFUSED, DEFINED, UNREACHABLE = "REFUSED", "DEFINED", "UNREACHABLE"

#: ⛔⛔ THE SILICON REFUSAL CLASSES, NAMED (ruling D6). Every one of these halts
#: the engine with `config_err` set, and D6's requirement is ONE PER REFUSAL
#: IMAGE: a program built to exercise one refusal must be LEGAL in every other
#: field, or the arm that "proves" refusal A passes because refusal B fired
#: first and nobody can tell which. ⚠ MEASURED, NOT HYPOTHETICAL -- the halt is
#: ENGINE-WIDE through `ST_IDLE`'s `!config_err`, so the FIRST refusal stops
#: everything and a second one is unreachable in that run. `ckdegen_image` was
#: already split into two images for exactly this reason.
R_CKDEGEN = "ck_degen: a clocked action with a zero bit count"
R_PINRANGE = "pin_real: a receive or arm on an index >= N_PINS"
R_CLKALIAS = "1.6x: an OP_SHIFT whose clock pin IS its data pin"
R_HOLDVIOL = ("D1/U: an open-drain data drive the hold applies to (clocked, or "
              "an unclocked SHIFT taking its own clock low) with d <= SDA_HOLD")
R_OD_ON_UO = "1.6s: an open-drain lane on a push-pull-only `uo_out` pin"

#: (opcode, field, predicate-name) -> (verdict, reason)
#: ⛔ KEYED BY OPCODE, because the same field value means different things per
#: opcode -- `PIN_NONE` is a REFUSAL on a receive and a REQUIREMENT on an SPI
#: target's clock pin. A table keyed only by field would have to pick one.
TABLE = {
    # ---- count ---------------------------------------------------------
    ("SHIFT", "count", "clocked and nbits == 0"): (
        REFUSED,
        "A clocked SHIFT's bit count is `count + 1`, so `count = 15` wraps to "
        "ZERO in the 4-bit field and the action has no meaning. ⛔ The engine "
        "guards the COMPUTED `ck_nbits`, not the raw field, which is why this "
        "row exists at all -- guarding `count != 0` would have missed it "
        "entirely. Silicon halts the lane and sets `config_err`; the golden "
        "model returns no dispatch, no clock edge and no bits."),
    ("SHIFTIN", "count", "clocked and nbits == 0"): (
        REFUSED,
        "A clocked SHIFTIN's bit count IS `count`, so `count = 0` is a receive "
        "of nothing. ⭐ THIS IS THE ONE THAT ACTUALLY HAPPENED: it reached the "
        "engine from a store corrupted by pushing host bytes while PROG was "
        "high, and `clocked_conform` reported `no model entry for op=2 cnt=0`. "
        "Silicon halts the lane and sets `config_err` rather than leaving it "
        "undefined, because a corrupted store reaches the engine whatever the "
        "toolchain refuses."),
    ("SHIFT", "count", "unclocked, any value"): (
        DEFINED,
        "On an UNCLOCKED SHIFT `count` is the host-byte-load threshold, "
        "compared against the pre-increment `tx_bitp`. Any value is meaningful: "
        "a threshold the pointer never reaches simply means the lane never "
        "reloads, which is a starved lane and reported by `lane_underrun` "
        "rather than an illegal action."),
    ("SHIFTIN", "count", "unclocked, 0"): (
        DEFINED,
        "On an UNCLOCKED SHIFTIN the byte-complete test is `rx_bitp == "
        "count - 1`, so `count = 0` underflows the comparison to all-ones and "
        "the byte never completes. ⚠ DEFINED BUT USELESS, and it is tabled as "
        "DEFINED rather than REFUSED deliberately: no shipped image uses it, "
        "and refusing it would be a new rule about the UNCLOCKED path, which "
        "this arc has no mandate to change."),
    # ---- pin -----------------------------------------------------------
    ("SHIFTIN", "pin", "PIN_NONE or >= N_PINS"): (
        REFUSED,
        "A receive with nothing to sample. Already refused statically by "
        "`pe_asm.check_receive_pin` and guarded in silicon by `pin_real`; "
        "measured as X in `l_rx`, `rx_data` and the serial readback before the "
        "guard existed (`pinnone_image.hex`)."),
    ("READBIT", "pin", "PIN_NONE or >= N_PINS"): (
        REFUSED,
        "The single-bit receive, same refusal and same mechanism as "
        "`OP_SHIFTIN` -- it is the same read of `pin_in` through the same "
        "guard."),
    ("ARM", "pin", "PIN_NONE or >= N_PINS"): (
        REFUSED,
        "An edge on a pin that does not exist can never fire, so the lane can "
        "only ever time out. `pin_rise`/`pin_fall` are [N_PINS-1:0]; measured "
        "`arm_hit` X for all 198 armed cycles before `arm_real` existed."),
    ("LEVEL", "pin", "PIN_NONE or >= N_PINS"): (
        DEFINED,
        "A NO-OP, and a shipped mechanism: the half-bit offset idiom is built "
        "on `OP_LEVEL` naming a non-real pin (`build_noop`), which is precisely "
        "how a no-op moves nothing. Guarded by `pin_real` so it writes no pin."),
    ("REARM", "pin", "PIN_NONE or >= N_PINS"): (
        DEFINED,
        "`OP_REARM` does not use its pin field as an arm pin -- it reuses the "
        "lane's existing `l_armpin` -- and every program in the suite ends its "
        "loop with `act(OP_REARM, 0, 1, d)`. Refusing on this field would "
        "reject every shipped program."),
    # ---- the lane's CLOCK pin, which is a header field but belongs here --
    ("SHIFT", "clkpin", "PIN_NONE"): (
        DEFINED,
        "REQUIRED, not merely tolerated: an SPI TARGET declares PIN_NONE as "
        "its clock pin because the master supplies SCK, and `build_spi_target` "
        "ships that way. `clk_real` is what makes it drive no clock -- and it "
        "is also what keeps `level = 1` meaning the OLD thing on such a lane, "
        "which is why every UART program is untouched by the clocked scheme."),
    ("SHIFT", "clkpin", "== the data pin"): (
        REFUSED,
        "1.6x: the clock write would overwrite the data bit, emitting a "
        "well-formed frame of WRONG DATA -- silent corruption, one class above "
        "a wrong number. Refused statically by `pe_asm.check_shift_clock_alias` "
        "and in silicon at dispatch, where the refusal must suppress BOTH "
        "writes (the first version suppressed only the data one)."),
    # ---- q -------------------------------------------------------------
    ("SHIFT", "q", ">= N_TXQ"): (
        UNREACHABLE,
        "The queue field is 2 bits and `N_TXQ` is 4, so every encoding names a "
        "real queue and there is no reserved value to reach. ⚠ This row exists "
        "so the audit is COMPLETE rather than silent about the field: if "
        "`N_TXQ` is ever reduced, this becomes reachable and the row must "
        "change verdict."),
    # ---- delay ---------------------------------------------------------
    ("ARM", "delay", "0"): (
        DEFINED,
        "`delay = 0` on an ARM means NO TIMEOUT -- an encoding choice in an "
        "existing field, and how a lane that must wait indefinitely (UART-rx "
        "between frames) is expressed. `l_notmo` carries it."),
    ("REARM", "delay", "0"): (
        DEFINED,
        "A chaining re-arm with zero delay re-dispatches the same action at "
        "the same timestamp. It is the long-delay mechanism's degenerate end "
        "and costs a dispatch without advancing the PC, which the liveness "
        "watchdog exempts by design."),
}


#: ⛔⛔ IMAGES THAT ARE DELIBERATELY DEGENERATE, declared BY NAME with the
#: refusal each one exists to exercise. These are the must-fire programs: the
#: refusals they trip are the POINT of them, and a gate that failed on them
#: would be refusing the tests that prove the refusals work.
#: ⚠ DECLARED, NOT PATTERN-MATCHED. A rule like "anything with `bad` or `none`
#: in the name is exempt" is how a real defect slips in behind a filename --
#: this project's own coverage measure started over-reporting itself exactly
#: that way. Each entry is a claim that the image's degeneracy is intended,
#: and an image carrying a refused field that is NOT listed fails the gate.
#: ⭐ AND THE LIST IS CHECKED FOR STALENESS: an entry whose image no longer
#: carries any refused field is reported, because then either the image or the
#: refusal changed and nobody noticed.
#: ⭐⭐ EACH ENTRY NAMES **ONE** REFUSAL CLASS (ruling D6), and that is the
#: teeth: the gate now requires the image to trip EXACTLY that class and
#: nothing else. A refusal image that trips a second refusal is RED, because
#: `config_err` halts dispatch ENGINE-WIDE -- whichever fires first is the only
#: one that ever runs, so the arm would be certifying a refusal it never
#: reached. ⚠ THIS CAUGHT SOMETHING THE MOMENT IT WAS WRITTEN: with the
#: clocked images still at `d = 9`, `ckdegen_image` and `ckdegen2_image` tripped
#: BOTH `ck_degen` and D1's hold refusal, so the degenerate-count arm could
#: have been passing on the delay instead.
DELIBERATE = {
    "tx_badclk_image.hex": (R_CLKALIAS,
        "the 1.6x alias: a SHIFT lane whose clock pin IS its data pin. Built "
        "for `tb_tx +BADCLK=1`, which asserts the lane HALTS with `config_err` "
        "set -- the silicon backstop for the silent-corruption class."),
    "pinnone_image.hex": (R_PINRANGE,
        "a receive on PIN_NONE. Built to prove the out-of-range read is "
        "guarded; before `pin_real` it put X into `l_rx`, `rx_data` and the "
        "serial readback, which is what `tb_pinrange +MODE=1` now refuses."),
    "ckdegen_image.hex": (R_CKDEGEN,
        "a clocked action with a ZERO bit count, by BOTH routes: lane 0 is a "
        "clocked SHIFTIN at count 0, lane 1 a clocked SHIFT at count 15 where "
        "count + 1 wraps to 0 in the 4-bit field. Built for `tb_pinrange "
        "+MODE=3`, which asserts both lanes HALT with `config_err` set and NO "
        "clock edge emitted -- the must-fire for the defined refusal."),
    "ckdegen2_image.hex": (R_CKDEGEN,
        "the SECOND route to a zero bit count: a clocked SHIFT at `count = 15`, "
        "where `count + 1` wraps to 0 in the 4-bit field. Its own image because "
        "`config_err` gates dispatch ENGINE-WIDE, so the first refusal would "
        "stop the second route from ever being reached -- measured as one "
        "writeback in the whole run when both shared a program."),
    "armnone_image.hex": (R_PINRANGE,
        "an ARM on a reserved pin index. Built for `tb_pinrange +MODE=2`, "
        "which counts the armed window and asserts `arm_hit` is never X -- the "
        "third instance of the out-of-range family."),
    # ⭐⭐ FOUND BY WRITING D6, NOT BY REVIEW. This image has existed and been
    # run (`tb_pinrange +MODE=0`, and the cocotb suite before that) the whole
    # time, and it was UNDECLARED here for a boring reason: until D6 added the
    # 1.6s predicate, `violations()` could not see the refusal it exists to
    # exercise, so the image tripped nothing and the gate had nothing to ask
    # about. ⚠ AN AUDIT CAN ONLY MISS WHAT IT CANNOT DECODE -- the same shape
    # as the three checks-that-could-not-fire already in the ledger.
    # ⭐⭐ D4's TWO REFUSED POINTS. The THIRD image, `ckhold_over_image.hex` at
    # `SDA_HOLD + 1`, is deliberately ABSENT from this table: it must RUN, so
    # it trips nothing, and listing it would make the stale-exemption check
    # red. ⇒ The boundary is covered from both sides -- two entries that must
    # appear here and one image that must not.
    "ckhold_at_image.hex": (R_HOLDVIOL,
        "a clocked open-drain byte at `d = SDA_HOLD` exactly. ⛔ THE EQUAL "
        "CASE IS REFUSED, not accepted: the held value reaches the pin on the "
        "same cycle the next phase dispatches, so the hold fits and `t_SU;DAT` "
        "is ZERO. Built for `tb_pinrange +MODE=4`, which asserts the lane "
        "halts with `config_err` set and NO clock edge is emitted."),
    "ckhold_under_image.hex": (R_HOLDVIOL,
        "the same program one cycle BELOW the boundary, `d = SDA_HOLD - 1`. "
        "Its pair at `SDA_HOLD + 1` must RUN, which is what makes this a "
        "boundary test rather than a direction test -- a guard written "
        "`d < SDA_HOLD` would pass the `under` arm and the `at` arm would "
        "catch it."),
    "cfgerr_image.hex": (R_OD_ON_UO,
        "an OPEN-DRAIN lane on `uo_out` pin 8. `uo_out` has no tri-state, so "
        "the lane physically cannot release the line it declared releasable, "
        "and the chip REFUSES TO RUN rather than emulating open-drain "
        "incorrectly. Built for `tb_pinrange +MODE=0`, which asserts no pin "
        "moves at all."),
}


def unpack(fields, raw, nbytes):
    w = int.from_bytes(raw, "big")
    total = sum(x for _n, x in fields)
    w >>= (nbytes * 8 - total)
    out, acc = {}, w
    for name, width in reversed(fields):
        out[name] = acc & ((1 << width) - 1)
        acc >>= width
    return out


def load(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return bytes(int(ln, 16) for ln in fh if ln.strip())


def walk(img):
    """Yield (lane, header, action) for every action a lane can reach."""
    if len(img) < I.ACT_BASE:
        return
    for ln in range(I.N_LANES):
        h = unpack(I.HDR_FIELDS,
                   img[ln * I.HDR_BYTES:(ln + 1) * I.HDR_BYTES], I.HDR_BYTES)
        pc, seen = h["base"], 0
        while pc + I.ACT_BYTES <= len(img) and seen < 200:
            a = unpack(I.ACT_FIELDS, img[pc:pc + I.ACT_BYTES], I.ACT_BYTES)
            yield ln, h, a
            seen += 1
            # ⛔ ANY REARM ENDS THE LANE, not only a looping one (ruling M).
            # The RTL never moves a PC past a REARM: level 1 loops to `l_base`,
            # level 0 does not retire at all (`act_retire`). This walk used to
            # stop only at level 1 and so ran on past a chaining REARM into
            # whatever followed -- harmless while every parked lane's REARM was
            # the image's last word, and 60-70 phantom actions per parked lane
            # once images are written whole with the store filler. MEASURED on
            # every tracked image before the change: identical walks unpadded.
            if a["op"] == I.OP_REARM:
                break
            pc += I.ACT_BYTES


OPNAME = {v: k for k, v in I.OPCODES.items()}


def violations(img, sda_hold=None):
    """Every REFUSED row a program actually contains, each with its CLASS.

    ⭐ THE CLASS IS RETURNED, not just the field (ruling D6). Without it the
    audit can say "this image trips something the engine refuses" but not
    "this image trips exactly the refusal it was built for", and the second is
    the claim a refusal arm actually rests on.
    ⇒ `sda_hold` defaults to the RTL's own `SDA_HOLD` via
      `model/hold_bound.py`. It is a PARAMETER here so the gate can audit the
      `-GSDA_HOLD_NS=<n>` builds against their own boundary rather than against
      the default one -- the `hold0` arm legalises every delay, and reporting
      it against 15 would invent refusals that build cannot have.
    """
    if sda_hold is None:
        sda_hold = hold_bound.bound()
    out = []
    for ln, h, a in walk(img):
        op = OPNAME.get(a["op"], "?")
        clk_real = h["clkpin"] < N_PINS
        clocked = clk_real and a["level"] == 1 and a["op"] in (I.OP_SHIFT,
                                                              I.OP_SHIFTIN)
        nbits = (a["count"] + 1) & 0xF if a["op"] == I.OP_SHIFT else a["count"]
        if clocked and nbits == 0:
            out.append((R_CKDEGEN, ln, op, "count",
                        "clocked and nbits == 0", a["count"]))
        if a["op"] in (I.OP_SHIFTIN, I.OP_READBIT, I.OP_ARM) \
                and a["pin"] >= N_PINS:
            out.append((R_PINRANGE, ln, op, "pin",
                        "PIN_NONE or >= N_PINS", a["pin"]))
        if a["op"] == I.OP_SHIFT and clk_real and h["clkpin"] == a["pin"]:
            out.append((R_CLKALIAS, ln, op, "clkpin",
                        "== the data pin", a["pin"]))
        # ⛔⛔ D1. `~l_mode` in silicon is `mode == 0`, which the header calls
        # OPEN-DRAIN. A push-pull clocked lane is SPI and has no `t_HD;DAT`
        # requirement to miss, so it is NOT refused -- the asymmetry is in the
        # RTL and is reproduced here rather than widened into a blanket rule.
        # ⚠ AT `SDA_HOLD == 0` NOTHING IS REFUSED, matching the RTL's own
        # `(SDA_HOLD != 0)` term: a build with no hold has no hold to not fit.
        # ⛔⛔ RULING U WIDENED IT, and this mirror follows the RTL's
        # `(ck_act | uc_hold)`: the UNCLOCKED open-drain SHIFT that takes its
        # own clock low (`clk_real & level == 0`) is held by the same pipeline,
        # so it is refused at the same delay.
        uc_hold = (a["op"] == I.OP_SHIFT and clk_real and a["level"] == 0)
        if (clocked or uc_hold) and h["mode"] == 0 and sda_hold != 0 \
                and a["delay"] <= sda_hold:
            out.append((R_HOLDVIOL, ln, op, "delay",
                        "%s open-drain and delay <= SDA_HOLD (%d)"
                        % ("clocked" if clocked else "unclocked clock-low",
                           sda_hold), a["delay"]))
        # ⛔ 1.6s, THE HEADER-LOAD REFUSAL. It is per LANE rather than per
        # action, so it would be reported once per action the lane can reach;
        # the dedupe in the caller's `kinds` set collapses that, and the detail
        # rows name the lane.
        if h["mode"] == 0 and I.N_UIO <= h["pin"] < N_PINS:
            out.append((R_OD_ON_UO, ln, op, "pin",
                        "open-drain lane on a `uo_out` pin", h["pin"]))
    return out


def selftest():
    """⛔ PRICE IT: a hand-built degenerate action must be caught."""
    print()
    print("  --- must-fire: a hand-built degenerate action is refused ---")
    rc = 0
    hold = hold_bound.bound()
    # ⛔⛔ THE PROBE DELAY MOVED FROM 9 TO `hold + 1` AND THAT IS NOT COSMETIC.
    # Every case below declares mode 0 (open-drain) with a real clock pin, so
    # under D1 a delay of 9 makes ALL FIVE trip the hold refusal -- including
    # the three that assert NO refusal, which would have gone red, and the two
    # that assert one, which would have passed for the WRONG REASON. ⭐ IT IS
    # `hold + 1` RATHER THAN A LITERAL 16: the boundary lives in the RTL, and a
    # selftest carrying its own copy is how the probe stops tracking the design.
    legal = hold + 1
    base = bytearray(I.ACT_BASE + 4 * I.ACT_BYTES)
    # one lane, real distinct clock pin, program at ACT_BASE
    hdr = I.hdr(2, 1, 0, legal, 0, 2 * legal, 3 * legal, I.ACT_BASE)
    base[0:I.HDR_BYTES] = hdr
    for ln in range(1, I.N_LANES):
        base[ln * I.HDR_BYTES:(ln + 1) * I.HDR_BYTES] = \
            I.hdr(I.PIN_NONE, I.PIN_NONE, 0, 500, 0, 200, 240, I.ACT_BASE)
    cases = [
        ("a clocked SHIFTIN with count = 0",
         I.act(I.OP_SHIFTIN, 2, 1, legal, count=0), R_CKDEGEN),
        ("a clocked SHIFT with count = 15 (nbits wraps to 0)",
         I.act(I.OP_SHIFT, 2, 1, legal, count=15), R_CKDEGEN),
        ("a clocked SHIFTIN with count = 1 (the ACK slot)",
         I.act(I.OP_SHIFTIN, 2, 1, legal, count=1), None),
        ("a clocked SHIFT with count = 7 (a byte)",
         I.act(I.OP_SHIFT, 2, 1, legal, count=7), None),
        ("an UNCLOCKED SHIFTIN with count = 0 (level 0)",
         I.act(I.OP_SHIFTIN, 2, 0, legal, count=0), None),
        # ⭐⭐ D1'S OWN MUST-FIRE, AND BOTH EDGES OF IT. The action is legal in
        # every other field -- a clocked byte on a real distinct clock pin --
        # so the only thing that can refuse it is the delay. ⛔ `hold` REFUSES
        # and `hold + 1` RUNS: a one-sided probe would pass against a guard
        # written `d < SDA_HOLD`, which leaves zero setup before the rise.
        ("a clocked open-drain byte at d = SDA_HOLD",
         I.act(I.OP_SHIFT, 2, 1, hold, count=7), R_HOLDVIOL),
        ("a clocked open-drain byte at d = SDA_HOLD - 1",
         I.act(I.OP_SHIFT, 2, 1, hold - 1, count=7), R_HOLDVIOL),
        ("a clocked open-drain byte at d = SDA_HOLD + 1",
         I.act(I.OP_SHIFT, 2, 1, hold + 1, count=7), None),
    ]
    for label, act, want in cases:
        img = bytearray(base)
        img[I.ACT_BASE:I.ACT_BASE + I.ACT_BYTES] = act
        img[I.ACT_BASE + I.ACT_BYTES:I.ACT_BASE + 2 * I.ACT_BYTES] = \
            I.act(I.OP_REARM, 0, 1, legal)
        v = violations(bytes(img), sda_hold=hold)
        kinds = sorted({k for k, _l, _o, _f, _p, _x in v})
        # ⛔ THE CLASS IS CHECKED, NOT JUST "SOMETHING FIRED". The old probe
        # compared `bool(v)`, which cannot tell the refusal it names from a
        # different one firing in its place -- exactly the confusion D6 exists
        # to remove.
        ok = (kinds == ([] if want is None else [want]))
        print("    %-52s %s"
              % (label, "ok" if ok else
                 "*** wanted %s, got %s"
                 % ("no refusal" if want is None else want,
                    ", ".join(kinds) or "none")))
        if not ok:
            rc = 1
    # ⭐ AND THE `-GSDA_HOLD_NS=0` BUILD LEGALISES ALL OF IT, which is the
    # parameter arm's own premise: `test/phases_run.sh`'s `hold0` arm must be
    # able to RUN the program it measures, so a gate that refused it against
    # the default boundary would be adjudicating the wrong build.
    img0 = bytearray(base)
    img0[I.ACT_BASE:I.ACT_BASE + I.ACT_BYTES] = \
        I.act(I.OP_SHIFT, 2, 1, 1, count=7)
    img0[I.ACT_BASE + I.ACT_BYTES:I.ACT_BASE + 2 * I.ACT_BYTES] = \
        I.act(I.OP_REARM, 0, 1, legal)
    v0 = violations(bytes(img0), sda_hold=0)
    ok0 = not v0
    print("    %-52s %s" % ("d = 1 against SDA_HOLD = 0 (the hold0 build)",
                            "ok" if ok0 else "*** refused with no hold to fit"))
    if not ok0:
        rc = 1
    return rc


def main():
    print()
    print("=" * 78)
    print("DEGENERATE FIELDS -- every opcode x field x degenerate value")
    print("=" * 78)
    rc = 0
    by = collections.Counter(v for v, _r in TABLE.values())
    print("  table: %d row(s) -- %d REFUSED, %d DEFINED, %d UNREACHABLE"
          % (len(TABLE), by[REFUSED], by[DEFINED], by[UNREACHABLE]))
    short = [k for k, (_v, r) in TABLE.items() if len((r or "").strip()) < 60]
    for k in short:
        print("    *** %s has a one-line reason" % (k,))
        rc = 1
    if not short:
        print("  every row carries a substantive reason")

    # the shared image universe (`model/image_universe.py`, Wilson 10-18);
    # this scanned test/*.hex only
    import image_universe
    imgs = [p for _n, p in image_universe.items()]
    if not imgs:
        print("  *** no images found, so this gate would pass by scanning")
        print("      nothing.")
        return 1
    hold = hold_bound.bound()
    print()
    print("  --- every shipped image, against the REFUSED rows ---")
    print("    SDA_HOLD = %d cycles, read from src/pe_engine.v via" % hold)
    print("    model/hold_bound.py -- the boundary is stated ONCE, there.")
    bad, seen_deliberate, multi = 0, set(), 0
    for p in imgs:
        name = os.path.basename(p)
        v = violations(load(p), sda_hold=hold)
        if not v:
            continue
        kinds = sorted({k for k, _l, _o, _f, _p, _x in v})
        if name in DELIBERATE:
            seen_deliberate.add(name)
            want, why = DELIBERATE[name]
            # ⛔⛔ D6: ONE IMAGE, ONE REFUSAL. An extra class here means the
            # arm that certifies `want` may never have reached it.
            extra = [k for k in kinds if k != want]
            if extra:
                multi += 1
                rc = 1
                print("    *** %-24s is declared for ONE refusal but trips %d"
                      % (name, len(kinds)))
                print("        declared : %s" % want)
                for k in extra:
                    print("        ALSO     : %s" % k)
                for k, ln, op, field, pred, val in v:
                    if k != want:
                        print("          lane %d %s %s = %d (%s)"
                              % (ln, op, field, val, pred))
                print("        ⇒ `config_err` halts the engine, so whichever")
                print("          fires first is the only one that runs. Give")
                print("          the image LEGAL values in every other field.")
                continue
            if want not in kinds:
                rc = 1
                print("    *** %-24s is declared for `%s` but does not trip it"
                      % (name, want))
                continue
            print("    %-24s DELIBERATE -- %s" % (name, want))
            print("        %s" % why[:68])
            continue
        bad += 1
        # ⛔ DEDUPED PER (class, lane): the 1.6s refusal is a HEADER property,
        # so it would otherwise print once per action the lane can reach and a
        # one-lane finding would read like three.
        for k, ln in sorted({(k, l) for k, l, _o, _f, _p, _x in v}):
            det = next(d for d in v if d[0] == k and d[1] == ln)
            print("    *** %-24s lane %d %s %s = %d (%s)"
                  % (name, ln, det[2], det[3], det[5], det[4]))
            print("        refusal class: %s" % k)
        rc = 1
    print("    %d image(s) scanned, %d declared deliberate, %d UNDECLARED, "
          "%d tripping MORE THAN ONE refusal"
          % (len(imgs), len(seen_deliberate), bad, multi))
    # ⛔ A STALE EXEMPTION IS A FINDING: if a declared image no longer trips
    # anything, either it stopped being degenerate or the refusal stopped
    # firing, and both matter.
    for name in sorted(set(DELIBERATE) - seen_deliberate):
        print("    *** %s is declared DELIBERATE but carries no refused" % name)
        print("        field -- either the image or the refusal changed")
        rc = 1

    rc |= selftest()
    print()
    print("=" * 78)
    print("  GATE degenerate-fields: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ IT SCANS ASSEMBLED IMAGES, not generator calls: it sees what")
    print("      SHIPS, including images built outside `pe_asm`'s tuple form --")
    print("      but it does not reject a program at assembly time.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
