"""BRANCH_BIT's corpus (v2 primitive 1, Wilson 10-26/27): images that exercise
the branch both ways, alone and under contention, and as zero-time CHAINS.

Lane 0 is the TOGGLER: it drives uio pin 0 high and low on odd delays, so the
branchers sample it at every phase. Every other live lane is a BRANCHER on pin
0: taken -> drive its own pin high, not taken -> drive it low; both paths loop.
`chain` k puts k branches back to back (all on pin 0, so the chain's last one
decides), the zero-time shape Wilson flagged (Q6: v1's delay-0 REARM chain was
a real bug). Every image goes through pe_isa (the one encoder) and pe_asm's
static branch refusals.

Usage:  python test/branch_corpus.py <outdir>     (writes br_*.hex, prints them)
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pe_isa as I                                              # noqa: E402

TOGGLE_PIN = 0
#: spacing sets (d_on, d_off, d_act, d_loop). The toggler's two are odd and
#: coprime, so phases walk; d_act is every brancher's drive action, d_loop the
#: loop re-arm (the spacing before each branch AND its successor -- a branch
#: adds 0). "br" is R2's; "bra" is R2b's ADMISSIBLE set (Wilson 10-27 Q1):
#: every spacing >= D* + B = 20 + 4*3 = 32, with margin.
SPACING = {"br": (37, 53, 40, 23), "bra": (41, 53, 40, 40)}
#: R2b's re-run (Wilson 10-27): the branch is TIMED, its wait W per image.
#: R2 and R2b ran a ZERO-time branch; that word no longer encodes (W >= 32),
#: so their images are built at W = BR_W_MIN and R2b's numbers are history.
BR_WAIT = {"br": I.BR_W_MIN, "bra": I.BR_W_MIN,
           "braw32": 32, "braw40": 40}
SPACING["braw32"] = SPACING["braw40"] = SPACING["bra"]


def _toggler(sp):
    d_on, d_off, _d_act, d_loop = sp
    return [I.act(I.OP_LEVEL, TOGGLE_PIN, 1, d_on),
            I.act(I.OP_LEVEL, TOGGLE_PIN, 0, d_off),
            I.act(I.OP_REARM, 0, 1, d_loop)]


def _brancher(base_word, pin, chain, sp, merged=None, wait=None):
    """[words] for one brancher lane at word `base_word`: `chain` branches on
    TOGGLE_PIN, then the not-taken path, then the taken path. `merged` =
    "nt" / "tk" returns that path alone with the branch REMOVED -- the
    branch-merged lane A2 prices (Wilson 10-27 Q3), never a chip image.
    `merged` = "rb_nt" / "rb_tk" keeps that path with the branch REPLACED by
    an ordinary action of delay W (a READBIT of the same pin): the fair
    control once the branch is timed (Wilson 10-27)."""
    _d_on, _d_off, d_act, d_loop = sp
    n_br = chain
    nt = base_word + n_br                 # not-taken path: 2 words
    tk = nt + 2                           # taken path: 2 words
    words = []
    for k in range(n_br):
        # every branch but the last falls through to the next branch when not
        # taken and jumps to the taken path when taken
        words.append(I.act_branch_bit(TOGGLE_PIN, 1, tk, wait))
    nt_w = [I.act(I.OP_LEVEL, pin, 0, d_act), I.act(I.OP_REARM, 0, 1, d_loop)]
    tk_w = [I.act(I.OP_LEVEL, pin, 1, d_act), I.act(I.OP_REARM, 0, 1, d_loop)]
    if merged in ("nt", "tk"):
        return nt_w if merged == "nt" else tk_w
    if merged in ("rb_nt", "rb_tk"):
        return [I.act(I.OP_READBIT, TOGGLE_PIN, 0, wait)] + (nt_w if merged == "rb_nt" else tk_w)
    return words + nt_w + tk_w


def build(n_branchers=1, chain=1, sp="br", merged=None, check=True):
    """One image: the toggler on lane 0, `n_branchers` branchers (lanes 1..),
    the rest parked. `merged` ("nt"/"tk"): every brancher's branch removed,
    one path kept -- A2's branch-merged view, not refused for branches."""
    spc = SPACING[sp]
    wait = BR_WAIT[sp]
    d_on, d_off, d_act, _d_loop = spc
    hdrs, prog = [], []
    pins = [8, 9, 10, 11]
    word = 0
    for ln in range(I.N_LANES):
        base = I.ACT_BASE + word * I.ACT_BYTES
        if ln == 0:
            ws = _toggler(spc)
            hdrs.append(I.hdr(TOGGLE_PIN, I.PIN_NONE, 1, d_on + d_off, 0, 200, 240, base))
        elif ln <= n_branchers:
            ws = _brancher(word, pins[ln - 1], chain, spc, merged, wait)
            hdrs.append(I.hdr(pins[ln - 1], I.PIN_NONE, 1, 2 * d_act, 0, 200, 240, base))
        else:
            ws = [I.act(I.OP_REARM, 0, 0, 500)]
            hdrs.append(I.hdr(I.PIN_NONE, I.PIN_NONE, 1, 500, 0, 200, 240, base))
        prog += ws
        word += len(ws)
    img = I.full_store(I.join_image(hdrs, prog))
    probs = I.branch_problems(img)
    if probs and check:
        raise ValueError("branch corpus image refused: " + "; ".join(probs))
    return img


#: the CHAINS (Wilson 10-27 Q2): refused by pe_isa.branch_problems, so they
#: are refusal tests now -- build(check=False) and the refusal must name them
REFUSED_CHAINS = {
    "br_chain2": (4, 2, "br"),
    "br_chain3": (4, 3, "br"),
}


def patch_branches(img, wait=None, target=None):
    """`img` with every BRANCH_BIT's W and/or target overwritten PAST the
    encoder -- the runtime refusal's arms (a corrupted store reaches the
    engine whatever pe_asm refuses)."""
    out = bytearray(img)
    nwords = (I.STORE_BYTES - I.ACT_BASE) // I.ACT_BYTES
    for w in range(nwords):
        a = I.ACT_BASE + w * I.ACT_BYTES
        x = I._unpack(I.ACT_FIELDS, out[a:a + I.ACT_BYTES], I.ACT_BYTES)
        if x["op"] != I.OP_BRANCH_BIT:
            continue
        wt = I.branch_wait(x) if wait is None else int(wait)
        tg = x["delay"] if target is None else int(target)
        out[a:a + I.ACT_BYTES] = I.act(I.OP_BRANCH_BIT, x["pin"], x["level"], tg,
                                       count=wt >> I.PINB_W, pinb=wt & ((1 << I.PINB_W) - 1))
    return bytes(out)


#: name -> (branchers, chain length, spacing set)
CORPUS = {
    "br_alone": (1, 1, "br"),
    "br_contend4": (4, 1, "br"),
    "bra_alone": (1, 1, "bra"),          # R2b: the admissible corpus
    "bra_contend4": (4, 1, "bra"),
    "braw32_alone": (1, 1, "braw32"),    # R2b re-run: the TIMED branch
    "braw32_contend4": (4, 1, "braw32"),
    "braw40_alone": (1, 1, "braw40"),
    "braw40_contend4": (4, 1, "braw40"),
}


# ---------------------------------------------------------------------------
# v2 PRIMITIVE 2: THE CMP_BRANCH CORPUS (Wilson 10-27; Nate 10-28 option 1)
# ---------------------------------------------------------------------------
#: the two bytes the senders send, alternately. ⭐ 0xB4 is NOT a bit-palindrome
#: (reversed it is 0x2D), so a lane that skipped the order reversal compares
#: the wrong byte -- M_CMP_ORDER_IGN must be visible.
CMP_A, CMP_B = 0xB4, 0x3C
CMP_BIT_T = 40          # sender bit slot; the receivers sample 20 into it
CMP_W = 40              # the CMP's wait W
CMP_RX_LOOP = 540       # receiver re-arm: period 20 + 8*40 + 40 + 40 + 540 = 960


def _sender(pin, msb_first, pair=(CMP_A, CMP_B)):
    """`pair` (CMP_A, CMP_B by default), one bit per CMP_BIT_T slot, period 640."""
    bits = []
    for byte in pair:
        order = range(7, -1, -1) if msb_first else range(8)
        bits += [(byte >> i) & 1 for i in order]
    ws = [I.act(I.OP_LEVEL, pin, b, CMP_BIT_T) for b in bits[:-1]]
    ws.append(I.act(I.OP_LEVEL, pin, bits[-1], CMP_BIT_T // 2))
    ws.append(I.act(I.OP_REARM, 0, 1, CMP_BIT_T // 2))
    return ws


def _receiver(base_word, in_pin, out_pin, byte, mask, inv, variant):
    """offset no-op, 8 READBITs of `in_pin`, the CMP, then the two paths.
    Period 960 = 1.5 sender periods, so passes alternate CMP_A / CMP_B and the
    compare both matches and mismatches. `variant` builds the refusal arms."""
    nrx = {"bit7": 7, "norx": 0}.get(variant, 8)
    ws = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, CMP_BIT_T // 2)]
    ws += [I.act(I.OP_READBIT, in_pin, 0, CMP_BIT_T) for _ in range(nrx)]
    ws += [I.act(I.OP_LEVEL, I.PIN_NONE, 0, CMP_BIT_T) for _ in range(8 - nrx)]
    cmpw = base_word + len(ws)
    nt, tk = cmpw + 1, cmpw + 3
    w = I.act_cmp_branch(byte, tk, CMP_W, mask=mask, inv=inv)
    if variant == "q1":
        x = I._unpack(I.ACT_FIELDS, w, I.ACT_BYTES)
        w = I.act(I.OP_CMP_BRANCH, x["pin"], x["level"], x["delay"], count=x["count"],
                  q=x["q"] | 2, pinb=x["pinb"], mod=x["mod"])
    ws.append(w)
    ws += [I.act(I.OP_LEVEL, out_pin, 0, CMP_BIT_T), I.act(I.OP_REARM, 0, 1, CMP_RX_LOOP)]
    ws += [I.act(I.OP_LEVEL, out_pin, 1, CMP_BIT_T), I.act(I.OP_REARM, 0, 1, CMP_RX_LOOP)]
    return ws


def build_cmp(variant="ok", check=True, kind="order"):
    """Two sender -> receiver PAIRS, one sender pin per receiver.
    ⛔ ONE RECEIVER PER SENDER PIN: a SHIFTIN / READBIT RELEASES the pin it
    samples (v1 semantics -- the I2C ACK read lets SDA go), so a second
    receiver on the same pin reads it released (MEASURED on the first build:
    the later receiver read the bench's default 1 every bit). And uo_out has
    no readback (project.v ties pin_in[11:8] to 0), so the senders are uio.
      kind "order": an LSB-first pair (uio0 -> lane 2) and an MSB-first pair
        (uio1 -> lane 3); the SAME byte (CMP_A) must match on both lanes.
      kind "mask": uio0 sends CMP_A / CMP_B to lane 2 (high-nibble mask, imm
        CMP_A & 0xF0, inverted); uio1 sends CMP_A ^ 1 / CMP_B to lane 3
        (ignore-bit-0 mask, imm CMP_A) -- each matches ONLY under its mask."""
    if kind == "order":
        lanes = [("send", 0, False, (CMP_A, CMP_B)),
                 ("send", 1, True, (CMP_A, CMP_B)),
                 ("recv", 0, 2, CMP_A, I.CMP_MASK_ALL, False, I.ORDER_LSB),
                 ("recv", 1, 3, CMP_A, I.CMP_MASK_ALL, False, I.ORDER_MSB)]
    elif kind == "lo":
        # the low-nibble mode: CMP_A & 0x0F = 0x4 matches CMP_A, not CMP_B (0xC)
        lanes = [("send", 0, False, (CMP_A, CMP_B)),
                 ("recv", 0, 2, CMP_A & 0x0F, I.CMP_MASK_LO, False, I.ORDER_LSB)]
    else:
        lanes = [("send", 0, False, (CMP_A, CMP_B)),
                 ("send", 1, False, (CMP_A ^ 1, CMP_B)),
                 ("recv", 0, 2, CMP_A & 0xF0, I.CMP_MASK_HI, True, I.ORDER_LSB),
                 ("recv", 1, 3, CMP_A, I.CMP_MASK_NO_BIT0, False, I.ORDER_LSB)]
    hdrs, prog, word = [], [], 0
    for ln in range(I.N_LANES):
        base = I.ACT_BASE + word * I.ACT_BYTES
        spec = lanes[ln] if ln < len(lanes) else None
        if spec is None:
            ws = [I.act(I.OP_REARM, 0, 0, 500)]
            hdrs.append(I.hdr(I.PIN_NONE, I.PIN_NONE, 1, 500, 0, 200, 240, base))
        elif spec[0] == "send":
            _k, pin, msb, pair = spec
            ws = _sender(pin, msb, pair)
            hdrs.append(I.hdr(pin, I.PIN_NONE, 1, 16 * CMP_BIT_T, 0, 200, 240, base))
        else:
            _k, inp, outp, byte, mask, inv, order = spec
            ws = _receiver(word, inp, outp, byte, mask, inv, variant)
            hdrs.append(I.hdr(outp, I.PIN_NONE, 1, 960, 0, 200, 240, base, order=order))
        prog += ws
        word += len(ws)
    img = I.full_store(I.join_image(hdrs, prog))
    probs = I.branch_problems(img)
    if probs and check:
        raise ValueError("CMP corpus image refused: " + "; ".join(probs))
    return img


#: the CMP refusal arms: each must be refused by pe_isa.branch_problems
CMP_REFUSED = ("bit7", "norx", "q1")


# ---------------------------------------------------------------------------
# v2 PRIMITIVE 2, BUNDLE 2: THE LOOP CORPUS
# ---------------------------------------------------------------------------
LOOP_D = 32             # every spacing at D* + B: n = 255 fits a 60k-cycle run
LOOP_REARM = 300


def _loop_lane(base_word, pin, n, variant="ok"):
    """head: LEVEL hi, LEVEL lo, then LOOP(n -> head); after the exit a marker
    LEVEL and the re-arm. `variant` builds the refusal arms."""
    head = base_word
    body = [I.act(I.OP_LEVEL, pin, 1, LOOP_D), I.act(I.OP_LEVEL, pin, 0, LOOP_D)]
    # nested / breakout: the offending word sits MID-body, away from the LOOP
    # word, so it is refused for ITS reason, not as a branch->branch chain
    if variant == "nested":
        body = [body[0], I.act_loop(2, head, LOOP_D), body[1]]
    elif variant == "breakout":
        body = [body[0], I.act_branch_bit(0, 1, base_word + 5, LOOP_D), body[1]]
    elif variant == "rearm":
        body[1] = I.act(I.OP_REARM, 0, 1, LOOP_D)
    w = I.act_loop(max(n, 1), head if variant != "fwd" else base_word + len(body) + 1, LOOP_D)
    if variant == "n0":
        x = I._unpack(I.ACT_FIELDS, w, I.ACT_BYTES)
        w = I.act(I.OP_LOOP, 0, 0, x["delay"] & 0x7F, count=x["count"], pinb=x["pinb"])
    return body + [w, I.act(I.OP_LEVEL, pin, 1, LOOP_D), I.act(I.OP_REARM, 0, 1, LOOP_REARM)]


#: kind -> the n of each looping lane (the rest parked)
LOOP_KINDS = {"alone": (7,), "mix": (1, 2, 3, 7, 255)}
LOOP_REFUSED = ("n0", "fwd", "nested", "breakout", "rearm")


def build_loop(kind="mix", variant="ok", check=True):
    ns = LOOP_KINDS[kind]
    hdrs, prog, word = [], [], 0
    for ln in range(I.N_LANES):
        base = I.ACT_BASE + word * I.ACT_BYTES
        if ln < len(ns):
            ws = _loop_lane(word, ln, ns[ln], variant if ln == 0 else "ok")
            hdrs.append(I.hdr(ln, I.PIN_NONE, 1, 2 * LOOP_D, 0, 200, 240, base))
        else:
            ws = [I.act(I.OP_REARM, 0, 0, 500)]
            hdrs.append(I.hdr(I.PIN_NONE, I.PIN_NONE, 1, 500, 0, 200, 240, base))
        prog += ws
        word += len(ws)
    img = I.full_store(I.join_image(hdrs, prog))
    probs = I.branch_problems(img)
    if probs and check:
        raise ValueError("LOOP corpus image refused: " + "; ".join(probs))
    return img


def main(argv) -> int:
    out = argv[1] if len(argv) > 1 else os.path.join(HERE, "..", "probe_branch")
    os.makedirs(out, exist_ok=True)
    for name, (nb, ch, sp) in CORPUS.items():
        p = os.path.join(out, name + ".hex")
        I.write_image(p, build(nb, ch, sp))
        print("  %-14s %d brancher lane(s), chain %d -> %s" % (name, nb, ch, p))
    for kind in ("order", "mask", "lo"):
        p = os.path.join(out, "cmp_%s.hex" % kind)
        I.write_image(p, build_cmp("ok", kind=kind))
        print("  %-14s 2 sender -> CMP receiver pairs -> %s" % ("cmp_" + kind, p))
    for v in CMP_REFUSED:
        probs = I.branch_problems(build_cmp(v, check=False))
        print("  cmp_%-10s REFUSED (%d problem(s)): %s" % (v, len(probs), probs[0][:70] if probs else "*** NONE ***"))
    for name, (nb, ch, sp) in REFUSED_CHAINS.items():
        probs = I.branch_problems(build(nb, ch, sp, check=False))
        print("  %-14s REFUSED (%d problem(s)): %s" % (name, len(probs), probs[0][:70]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
