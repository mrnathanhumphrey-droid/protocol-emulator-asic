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
D_ON, D_OFF = 37, 53          # the toggler: odd, coprime, so phases walk
D_ACT = 40                    # every brancher's drive actions
D_LOOP = 23                   # the loop re-arm


def _toggler():
    return [I.act(I.OP_LEVEL, TOGGLE_PIN, 1, D_ON),
            I.act(I.OP_LEVEL, TOGGLE_PIN, 0, D_OFF),
            I.act(I.OP_REARM, 0, 1, D_LOOP)]


def _brancher(base_word, pin, chain=1):
    """[words] for one brancher lane at word `base_word`: `chain` branches on
    TOGGLE_PIN, then the not-taken path, then the taken path."""
    n_br = chain
    nt = base_word + n_br                 # not-taken path: 2 words
    tk = nt + 2                           # taken path: 2 words
    words = []
    for k in range(n_br):
        # every branch but the last falls through to the next branch when not
        # taken and jumps to the taken path when taken
        words.append(I.act_branch_bit(TOGGLE_PIN, 1, tk))
    words += [I.act(I.OP_LEVEL, pin, 0, D_ACT), I.act(I.OP_REARM, 0, 1, D_LOOP)]
    words += [I.act(I.OP_LEVEL, pin, 1, D_ACT), I.act(I.OP_REARM, 0, 1, D_LOOP)]
    return words


def build(n_branchers=1, chain=1):
    """One image: the toggler on lane 0, `n_branchers` branchers (lanes 1..),
    the rest parked."""
    hdrs, prog = [], []
    pins = [8, 9, 10, 11]
    word = 0
    for ln in range(I.N_LANES):
        base = I.ACT_BASE + word * I.ACT_BYTES
        if ln == 0:
            ws = _toggler()
            hdrs.append(I.hdr(TOGGLE_PIN, I.PIN_NONE, 1, D_ON + D_OFF, 0, 200, 240, base))
        elif ln <= n_branchers:
            ws = _brancher(word, pins[ln - 1], chain)
            hdrs.append(I.hdr(pins[ln - 1], I.PIN_NONE, 1, 2 * D_ACT, 0, 200, 240, base))
        else:
            ws = [I.act(I.OP_REARM, 0, 0, 500)]
            hdrs.append(I.hdr(I.PIN_NONE, I.PIN_NONE, 1, 500, 0, 200, 240, base))
        prog += ws
        word += len(ws)
    img = I.full_store(I.join_image(hdrs, prog))
    probs = I.branch_problems(img)
    if probs:
        raise ValueError("branch corpus image refused: " + "; ".join(probs))
    return img


#: name -> (branchers, chain length)
CORPUS = {
    "br_alone": (1, 1),
    "br_contend4": (4, 1),
    "br_chain2": (4, 2),
    "br_chain3": (4, 3),
}


def main(argv) -> int:
    out = argv[1] if len(argv) > 1 else os.path.join(HERE, "..", "probe_branch")
    os.makedirs(out, exist_ok=True)
    for name, (nb, ch) in CORPUS.items():
        p = os.path.join(out, name + ".hex")
        I.write_image(p, build(nb, ch))
        print("  %-14s %d brancher lane(s), chain %d -> %s" % (name, nb, ch, p))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
