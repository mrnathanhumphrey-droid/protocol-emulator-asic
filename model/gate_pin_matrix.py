"""RULING PN4 -- EVERY PIN-TAKING OPCODE IS RUN WITH ITS ACTION PIN != THE
LANE's HEADER DATA PIN (and != its clock pin where that is legal).

⛔⛔ WHY. Silicon fix #3: a clocked SHIFTIN sampled the lane HEADER's pin, not
the action's, and the assembler validated the action's. Every clocked receive
ever run had action pin == header pin (I2C), where the two readings agree, so
nothing could tell them apart -- and the same blind spot sat in `pe_asm`'s
alias check and in Layer V2. A pin-source defect is invisible to any program
that names one pin per lane. This gate makes that a coverage fact, checked:
for each class below, some program that a bench actually RUNS must have an
action whose pin differs from its lane's header pin (and from the clock).

THE PROGRAMS: every tracked image a `benchset` arm runs, plus the arms built
in scratch by the CI runners that declare them (`run_cktx.pindiv_image`).
MUST-FIRES: without `pindiv` the matrix has holes (red); a class whose only
diverse action names the CLOCK pin does not count.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
import pe_isa as I                                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CLASSES = ["LEVEL", "START", "STOP", "SHIFT clocked", "SHIFT unclocked",
           "SHIFTIN clocked open-drain", "SHIFTIN clocked push-pull",
           "SHIFTIN unclocked", "READBIT", "ARM"]


def classify(h, a):
    """The class of action `a` in a lane with header `h`, or None."""
    clocked = (h["clkpin"] != I.PIN_NONE and h["clkpin"] != h["pin"]
               and a["level"] == 1)
    op = a["op"]
    if op == I.OP_LEVEL:
        return "LEVEL"
    if op == I.OP_START:
        return "START"
    if op == I.OP_STOP:
        return "STOP"
    if op == I.OP_SHIFT:
        return "SHIFT clocked" if clocked else "SHIFT unclocked"
    if op == I.OP_SHIFTIN:
        if not clocked:
            return "SHIFTIN unclocked"
        return ("SHIFTIN clocked push-pull" if h["mode"]
                else "SHIFTIN clocked open-drain")
    if op == I.OP_READBIT:
        return "READBIT"
    if op == I.OP_ARM:
        return "ARM"
    return None


def matrix(named):
    """named: [(name, image)] -> {class: [name, ...] with a diverse action}"""
    out = {c: [] for c in CLASSES}
    for name, img in named:
        for _ln, (h, acts) in I.lane_programs(img).items():
            for a in acts:
                c = classify(h, a)
                if c is None or a["pin"] >= 12:
                    continue
                if a["pin"] != h["pin"] and a["pin"] != h["clkpin"]:
                    if name not in out[c]:
                        out[c].append(name)
    return out


def swept():
    import benchset
    recs, _probs = benchset.plan()        # the arms the sweep really runs
    imgs = set()
    for r in recs:
        for p in r["args"]:
            if p.startswith("+IMG=test/") and p.endswith(".hex"):
                imgs.add(p[len("+IMG="):])
    out = []
    for rel in sorted(imgs):
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            with open(p, encoding="ascii") as fh:
                out.append((os.path.basename(rel),
                            bytes(int(t, 16) for t in fh.read().split())))
    return out


def runner_images():
    import run_cktx
    return [("run_cktx.pindiv", run_cktx.pindiv_image())]


def main() -> int:
    print()
    print("=" * 78)
    print("  PN4 -- EVERY PIN-TAKING OPCODE RUN WITH ACTION PIN != HEADER PIN")
    print("=" * 78)
    # ⭐ pindiv is now SWEPT too (benchset tb_cktx `gen`, for coverage), so the
    # runner's copy is added only if the sweep lost it; the must-fire below
    # removes it from BOTH routes, or "without pindiv" would still contain it
    sw = swept()
    named = sw + ([] if any("pindiv" in n for n, _i in sw)
                  else runner_images())
    m = matrix(named)
    rc = 0
    print("  %d programs (%d swept images, %d from the CI runners)"
          % (len(named), len(sw), len(named) - len(sw)))
    for c in CLASSES:
        print("    %-28s %s" % (c, ", ".join(m[c][:4]) if m[c]
                               else "*** ONLY SAME-PIN COVERAGE"))
        if not m[c]:
            rc = 1
    print("  --- must-fires ---")
    holes = [c for c, v in matrix([x for x in sw if "pindiv" not in x[0]])
             .items() if not v]
    ok1 = bool(holes)
    print("    without pindiv the matrix has holes (%d)            %s"
          % (len(holes), "red  ok" if ok1 else "*** WRONG"))
    # a planted IMAGE whose only "diverse" SHIFTIN names its lane's CLOCK pin
    # must leave that class empty -- through `matrix`, not a restatement
    acts = [I.act_shiftin_clocked(1, 70, nbits=8), I.act(I.OP_REARM, 0, 1, 70)]
    park = I.ACT_BASE + len(acts) * I.ACT_BYTES
    # v2: through the ONE assembler (pe_isa.join_image) -- it adds the magic
    plant = I.full_store(I.join_image(
        [I.hdr(2, 1, 0, 70, 0, 140, 210, I.ACT_BASE)]
        + [I.hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 3, 4, 5)],
        acts + [I.act(I.OP_REARM, 0, 0, 500)]))
    ok2 = not matrix([("plant", plant)])["SHIFTIN clocked open-drain"]
    print("    an action on the CLOCK pin is not diversity          %s"
          % ("ok" if ok2 else "*** WRONG"))
    if not (ok1 and ok2):
        rc = 1
    print()
    print("  GATE pin-matrix: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
