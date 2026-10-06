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

N_PINS = I.UO3 + 1
REFUSED, DEFINED, UNREACHABLE = "REFUSED", "DEFINED", "UNREACHABLE"

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
DELIBERATE = {
    "tx_badclk_image.hex":
        "the 1.6x alias: a SHIFT lane whose clock pin IS its data pin. Built "
        "for `tb_tx +BADCLK=1`, which asserts the lane HALTS with `config_err` "
        "set -- the silicon backstop for the silent-corruption class.",
    "pinnone_image.hex":
        "a receive on PIN_NONE. Built to prove the out-of-range read is "
        "guarded; before `pin_real` it put X into `l_rx`, `rx_data` and the "
        "serial readback, which is what `tb_pinrange +MODE=1` now refuses.",
    "ckdegen_image.hex":
        "a clocked action with a ZERO bit count, by BOTH routes: lane 0 is a "
        "clocked SHIFTIN at count 0, lane 1 a clocked SHIFT at count 15 where "
        "count + 1 wraps to 0 in the 4-bit field. Built for `tb_pinrange "
        "+MODE=3`, which asserts both lanes HALT with `config_err` set and NO "
        "clock edge emitted -- the must-fire for the defined refusal.",
    "ckdegen2_image.hex":
        "the SECOND route to a zero bit count: a clocked SHIFT at `count = 15`, "
        "where `count + 1` wraps to 0 in the 4-bit field. Its own image because "
        "`config_err` gates dispatch ENGINE-WIDE, so the first refusal would "
        "stop the second route from ever being reached -- measured as one "
        "writeback in the whole run when both shared a program.",
    "armnone_image.hex":
        "an ARM on a reserved pin index. Built for `tb_pinrange +MODE=2`, "
        "which counts the armed window and asserts `arm_hit` is never X -- the "
        "third instance of the out-of-range family.",
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
            if a["op"] == I.OP_REARM and a["level"]:
                break
            pc += I.ACT_BYTES


OPNAME = {v: k for k, v in I.OPCODES.items()}


def violations(img):
    """Every REFUSED row a program actually contains."""
    out = []
    for ln, h, a in walk(img):
        op = OPNAME.get(a["op"], "?")
        clk_real = h["clkpin"] < N_PINS
        clocked = clk_real and a["level"] == 1 and a["op"] in (I.OP_SHIFT,
                                                              I.OP_SHIFTIN)
        nbits = (a["count"] + 1) & 0xF if a["op"] == I.OP_SHIFT else a["count"]
        if clocked and nbits == 0:
            out.append((ln, op, "count", "clocked and nbits == 0", a["count"]))
        if a["op"] in (I.OP_SHIFTIN, I.OP_READBIT, I.OP_ARM) \
                and a["pin"] >= N_PINS:
            out.append((ln, op, "pin", "PIN_NONE or >= N_PINS", a["pin"]))
        if a["op"] == I.OP_SHIFT and clk_real and h["clkpin"] == a["pin"]:
            out.append((ln, op, "clkpin", "== the data pin", a["pin"]))
    return out


def selftest():
    """⛔ PRICE IT: a hand-built degenerate action must be caught."""
    print()
    print("  --- must-fire: a hand-built degenerate action is refused ---")
    rc = 0
    base = bytearray(I.ACT_BASE + 4 * I.ACT_BYTES)
    # one lane, real distinct clock pin, program at ACT_BASE
    hdr = I.hdr(2, 1, 0, 9, 2, 18, 27, I.ACT_BASE)
    base[0:I.HDR_BYTES] = hdr
    for ln in range(1, I.N_LANES):
        base[ln * I.HDR_BYTES:(ln + 1) * I.HDR_BYTES] = \
            I.hdr(I.PIN_NONE, I.PIN_NONE, 0, 500, 2, 200, 240, I.ACT_BASE)
    cases = [
        ("a clocked SHIFTIN with count = 0",
         I.act(I.OP_SHIFTIN, 2, 1, 9, count=0), True),
        ("a clocked SHIFT with count = 15 (nbits wraps to 0)",
         I.act(I.OP_SHIFT, 2, 1, 9, count=15), True),
        ("a clocked SHIFTIN with count = 1 (the ACK slot)",
         I.act(I.OP_SHIFTIN, 2, 1, 9, count=1), False),
        ("a clocked SHIFT with count = 7 (a byte)",
         I.act(I.OP_SHIFT, 2, 1, 9, count=7), False),
        ("an UNCLOCKED SHIFTIN with count = 0 (level 0)",
         I.act(I.OP_SHIFTIN, 2, 0, 9, count=0), False),
    ]
    for label, act, want in cases:
        img = bytearray(base)
        img[I.ACT_BASE:I.ACT_BASE + I.ACT_BYTES] = act
        img[I.ACT_BASE + I.ACT_BYTES:I.ACT_BASE + 2 * I.ACT_BYTES] = \
            I.act(I.OP_REARM, 0, 1, 9)
        v = violations(bytes(img))
        got = bool(v)
        ok = (got == want)
        print("    %-52s %s" % (label, "ok" if ok else
                                "*** wanted %s" % ("a refusal" if want
                                                   else "no refusal")))
        if not ok:
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

    imgs = [p for p in sorted(glob.glob(os.path.join(ROOT, "test", "*.hex")))
            if not os.path.basename(p).startswith("probe_")]
    if not imgs:
        print("  *** no images found, so this gate would pass by scanning")
        print("      nothing.")
        return 1
    print()
    print("  --- every shipped image, against the REFUSED rows ---")
    bad, seen_deliberate = 0, set()
    for p in imgs:
        name = os.path.basename(p)
        v = violations(load(p))
        if not v:
            continue
        if name in DELIBERATE:
            seen_deliberate.add(name)
            kinds = sorted({"%s %s" % (op, field) for _l, op, field, _p, _x in v})
            print("    %-24s DELIBERATE (%s) -- %s"
                  % (name, ", ".join(kinds), DELIBERATE[name][:44]))
            continue
        bad += 1
        for ln, op, field, pred, val in v:
            print("    *** %-24s lane %d %s %s = %d (%s)"
                  % (name, ln, op, field, val, pred))
        rc = 1
    print("    %d image(s) scanned, %d declared deliberate, %d UNDECLARED"
          % (len(imgs), len(seen_deliberate), bad))
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
