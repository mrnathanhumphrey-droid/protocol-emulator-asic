"""gate_spi_premise -- the SPI target's arming check and its premise (Wilson 11-15, call 4).

  P1 TODAY: premises.PICO_SPI_SCK is `assumed` (firmware-set; its hardware witness -- a
     logic-analyser capture of CS and SCK -- is OWED), so spi_premise.check never refuses; it
     reports each SPI-target image's margins. The witness is listed as OWED (hw).
  P2 THE REFUSAL PATH, ready for the witness: with the premise made `measured` in-process and the
     SCK period shortened to 40 cycles, sptgt_m1 (item 1b two words deep, drain 18 -- margin 15
     at 60, -5 at 40) is refused by name
Must-fire: M_SP_NOT_APPLIED (the check skipped when usable -> P2 compiles -> red).
POSITIVE TOKEN: `GATE spi_premise: PASSED`.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test"),
           os.path.join(ROOT, "host", "poset")):
    if _p not in sys.path:
        sys.path.append(_p)
import spi_premise as SP  # noqa: E402

#: the P2 case: item 1b's depth, the drain at which m1 certifies, and the faster SCK period
P2_DEPTH, P2_DRAIN, P2_T = 2, 18, 40


def _m1_case():
    import gen_branch_budget as GB
    import lane_cert as LC
    import proof_constants as PC
    import drain_table as DT
    I = LC._isa()
    img = dict(GB.corpus())["sptgt_m1_image.hex"]
    g, _p, _g = LC.build(img, 0, LC.premises(PC.load()), I)
    arms = [w for w in g if g[w][0]["op"] == I.OP_ARM]
    rs = {s for a in arms for s in g[a][1]}
    for _ in range(P2_DEPTH - 1):
        rs |= {t for s in rs for t in g[s][1]}
    for a in arms:
        for s in g[a][1]:
            img = DT._patch(img, s, P2_DRAIN, I)
    return img, rs, SP.declared_t_ext(dict(GB.corpus())["sptgt_m1_image.hex"])


def judge():
    import gen_branch_budget as GB
    import premises as PM
    probs, rows = [], []
    for name, img in GB.corpus():
        if not SP.declared_t_ext(img):
            continue
        p, info = SP.check(img)
        if p:
            probs.append("P1 %s refused while the premise is assumed: %s" % (name, p))
        rows.append("  %-24s %s" % (name, info["lanes"]))
    img, rs, decl = _m1_case()
    saved = dict(PM.REGISTRY["PICO_SPI_SCK"])
    try:
        PM.REGISTRY["PICO_SPI_SCK"] = dict(saved, label="measured (gate scratch)")
        p_ok, i_ok = SP.check(img, ready=rs, declared=decl)
        p_fast, i_fast = SP.check(img, ready=rs, t_ext=P2_T, declared=decl)
    finally:
        PM.REGISTRY["PICO_SPI_SCK"] = saved
    if p_ok:
        probs.append("P2 refused at the declared rate: %s" % p_ok)
    if not p_fast or "SCK ARM margin" not in p_fast[0]:
        probs.append("P2 a negative margin at SCK period %d not refused: %s" % (P2_T, i_fast))
    return probs, rows, (i_ok, i_fast)


def main():
    import premises as PM
    probs, rows, (i_ok, i_fast) = judge()
    print("P1 the premise %s is %r -- the check reports, never refuses:"
          % ("PICO_SPI_SCK", PM.REGISTRY["PICO_SPI_SCK"]["label"]))
    for r in rows:
        print(r)
    print("   OWED (hw): %s" % PM.REGISTRY["PICO_SPI_SCK"]["owed"])
    print("P2 measured (scratch): m1 at the declared rate %s; at SCK period %d %s"
          % (i_ok["lanes"], P2_T, i_fast["lanes"]))
    for p in probs:
        print("  ***", p)
    SP.NOT_APPLIED_MUT = True
    try:
        mp, _r, _i = judge()
    finally:
        SP.NOT_APPLIED_MUT = False
    red = any(m.startswith("P2") for m in mp)
    print("  must-fire M_SP_NOT_APPLIED %s" % ("RED (killed)" if red else "*** SURVIVED"))
    if not red:
        probs.append("mutant M_SP_NOT_APPLIED survived")
    print("GATE spi_premise: %s" % ("PASSED" if not probs else "FAILED (%d)" % len(probs)))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
