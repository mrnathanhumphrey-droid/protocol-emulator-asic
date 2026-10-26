"""N1 -- every NON-ADMISSIBLE image is declared by name, with what it violates.

⛔⛔ WHY. The bench set runs programs that break the admissibility conditions
on purpose -- stress images that overload the scheduler, reactive-path images
at delays below `D*`, measurement images whose pins collide with the pad
override. That is legitimate, and it was UNDECLARED: `corpus_all5` (U = 1.096)
was discovered to be overloaded only when ruling S tried to bound it. A program
that silently violates a condition the published guarantee rests on reads, to
anyone running the bench set, like a program the guarantee covers.

⇒ Three conditions, each derived from the image itself:

    OVERLOAD  U = sum(C / T) > 1 over the program's own lane set
              (`program_a2.lane_set`): no finite worst-case response exists.
    PORT      the program's REFILL-BEARING d_min is below `D* = k * L_REFILL`
              (`gate_j_program.port_feasible`), so it does not claim J = 1.
    PINMAP    a driving lane collides with `project.v`'s pad override --
              DECLARED in `test/corpus.py PAD_COLLISION` (P5), read from
              there rather than restated.
    QUEUE     condition 1.6a broken PER PROGRAM (ruling DT-A): some lane's
              worst-case response, from its NOMINAL release and with W1's
              jitter on every lane, exceeds its tightest action delay --
              `r_i > t_i`, so a job can still be pending at its successor's
              release (`program_a2.queue_slot`). That is exactly where
              TChecker's `ovr` becomes reachable, so a program outside it is
              one no exact witness can adjudicate. Not judged on an OVERLOAD
              image (no finite r exists to compare).

An image may violate any of them only if `NON_ADMISSIBLE` names it with THOSE
conditions and a reason. Undeclared is RED; a declared condition that no longer
holds (stale) is RED. Refusal images are exempt here because their
non-admissibility is already declared, with the one refusal each exercises, in
`gate_degenerate_fields.DELIBERATE`.

⭐⭐ THE REFILL-BEARING d_min, NOT THE RAW DELAY. Refills follow RETIRES (R5:
zero non-retiring refill-bearing dispatches on every image), so the spacing
that matters is between consecutive retires of a lane. After action i retires
the next release is `d_i` later -- `d_i + L_SYNC + 1` if i is a clocked
open-drain action, which PARKS on the observed rise (the term A2's slack uses;
R5 measured exactly 20 = 16 + 3 + 1 on `ckhold_over`) -- and action i+1 then
needs `m_{i+1}` dispatches to retire (1 unclocked; 2n for a clocked SHIFT,
2n+1 for a SHIFTIN), each at least `d_{i+1}` apart. Taking the raw minimum
delay instead flags every clocked program whose delay sits just above
`SDA_HOLD`, which is the conservative-but-wrong reading §1 already refuted.
⚠ IT IS THE NOMINAL RELEASE SPACING, which is what Theorem 3 reasons about
("by P8/P9 a lane dispatches at most once per d cycles"). A MEASURED dispatch
spacing can sit up to J below it -- one release served late, the next on time
-- and R5 measured exactly that: 69 on `corpus_i2c` against a nominal 70, and
37 against 37 on `ckod`. The two are different quantities, not a disagreement.
"""

from __future__ import annotations

import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    sys.path.insert(0, _p)

import corpus                                                     # noqa: E402
import gate_degenerate_fields as dgf                              # noqa: E402
import gate_j_program as jp                                       # noqa: E402
import pe_isa as I                                                # noqa: E402
import program_a2 as pa                                           # noqa: E402
import zero_spacing as zs                                         # noqa: E402
from bursty import L_SYNC                                         # noqa: E402

# ⭐⭐ THE DECLARATION LIST LIVES IN `model/nonadmissible.py` (Wilson, SP2/P4:
# one registry of declared non-admissible images AND of the timing exemptions
# any of them may take -- `timing_checks=False`, `no_rta_budget`). It moved
# there unchanged; this gate still owns judging it against the images.
import nonadmissible as NA                                        # noqa: E402
from nonadmissible import (NON_ADMISSIBLE, OVERLOAD, PINMAP,      # noqa: E402,F401
                           PORT, QUEUE)


def refill_dmin(img):
    """The minimum spacing between consecutive retires, over every lane."""
    best = None
    for ln, h, acts in pa.lanes_of(img):
        # ⛔⛔ DELAY-0 REARM RULING: a delay-0 action (other than an ARM's "no
        # timeout", `model/zero_spacing.py`) IS a spacing between retires, of
        # 0. Dropping it with `delay > 0` below is what hid the chain.
        if zs.find([(ln, i, a["op"], a["delay"]) for i, a in enumerate(acts)]):
            return 0
        seq = [a for a in acts if a["delay"] > 0]
        if not seq:
            continue

        def m(a):                         # dispatches the action needs
            if not pa.is_clocked(h, a):
                return 1
            if a["op"] == I.OP_SHIFT:
                return 2 * ((a["count"] + 1) & 0xF)
            return 2 * a["count"] + 1

        def gap(a):                       # release gap after `a` retires
            park = pa.is_clocked(h, a) and h["mode"] == 0
            return a["delay"] + ((L_SYNC + 1) if park else 0)

        cyc = seq + seq[:1]               # the lane loops back to its base
        for prv, cur in zip(cyc, cyc[1:]):
            sp = gap(prv) + (m(cur) - 1) * cur["delay"]
            best = sp if best is None or sp < best else best
    return best


def conditions(name, img):
    ls, _d, k, _j = pa.lane_set(img)
    out = set()
    if pa.utilisation(ls) > 1.0:
        out.add(OVERLOAD)
    dm = refill_dmin(img)
    if dm is not None and not jp.port_feasible(dm, k):
        out.add(PORT)
    if corpus.pad_collisions(img):
        out.add(PINMAP)
    # ⛔ DT-A, our recurrence only (pyRTA is not in CI): after Z1 ours is >=
    # pyRTA on every admissible lane (DT-F), so this can only be STRICTER
    # than the published number -- the safe side for a refusal.
    if OVERLOAD not in out:
        q = pa.queue_slot(img)
        # ⛔ A LANE WITH NO BOUND BREAKS 1.6a TOO (WF2 round 2): `r is not
        # None and ...` used to skip it, so an image whose lanes had no
        # response bound read as ADMISSIBLE. Overload is declared above; any
        # other missing bound is QUEUE -- the condition it cannot show.
        if any(v["r"] is None or not v["ok"] for v in q.values()):
            out.add(QUEUE)
    return out, dm, pa.utilisation(ls)


def audit(images, declared, pad_declared, deliberate):
    """Problems for this set of (name, img). Pure, so the must-fire can price it."""
    probs, rows = [], []
    for name, img in images:
        if name in deliberate:
            continue
        # ⛔ DELAY-0 REARM RULING: a zero release spacing is not a condition an
        # image may DECLARE (Wilson: the delay-0 build is retired, not
        # registered), so it is red here whatever the registry says.
        try:
            got, dm, u = conditions(name, img)
        except zs.ZeroSpacingError as exc:
            probs.append("%s has a ZERO release spacing and cannot be "
                         "declared: %s" % (name, exc))
            continue
        rows.append((name, got, dm, u))
        want = set(declared.get(name, (set(), ""))[0])
        if name in pad_declared:
            want |= {PINMAP}
        for c in sorted(got - want):
            probs.append("%s violates %s and does not declare it" % (name, c))
        for c in sorted(want - got):
            probs.append("%s declares %s but no longer violates it -- stale"
                         % (name, c))
    for name in sorted(set(declared) - {n for n, _ in images}):
        probs.append("%s is declared but no such image exists" % name)
    return probs, rows


def images():
    """The shared image universe (`model/image_universe.py`, Wilson 10-18):
    this scanned test/*.hex only, missing fpga/images/ and the bench arms."""
    import image_universe
    return image_universe.images()


def main() -> int:
    print()
    print("=" * 78)
    print("  N1 -- NON-ADMISSIBLE IMAGES, DECLARED BY NAME")
    print("=" * 78)
    import image_universe
    imgs, board = image_universe.board_as_v2(images())   # v2: board images, translated
    probs, rows = audit(imgs, NON_ADMISSIBLE, corpus.PAD_COLLISION,
                        dgf.DELIBERATE)
    print("  QUEUE (1.6a) reads OUR recurrence here (no pyRTA in CI) -- intended "
          "for a refusal threshold:")
    print("  ours >= pyRTA on every admissible lane (gate_a2_program §1b), so "
          "it can only refuse MORE (ruling A7)")
    print("  %d image(s); %d refusal image(s) exempt (declared in DELIBERATE)"
          % (len(imgs), len(imgs) - len(rows)))
    print()
    print("  %-24s %-6s %-7s %-26s %s" % ("image", "U", "refill", "violates",
                                         "status"))
    for name, got, dm, u in rows:
        if not got:
            continue
        print("  %-24s %-6.3f %-7s %-26s %s"
              % (name, u, dm, ",".join(sorted(got)),
                 "declared" if not any(p.startswith(name + " ") for p in probs)
                 else "*** SEE BELOW"))
    rc = 0
    for p in probs:
        print("  *** %s" % p)
        rc = 1
    if not probs:
        print("  every non-admissible image is declared, with its conditions")

    # ---- must-fire ----------------------------------------------------------
    # ⛔ PRICED ON A REAL OVERLOADED IMAGE under a name nothing declares, and on
    # a declaration whose condition no longer holds.
    print()
    print("  --- must-fire ---")
    five = next(img for n, img in imgs if n == "five_image.hex")
    p1, _ = audit([("undeclared_overload.hex", five)], {}, {}, {})
    hit = any("OVERLOAD" in x for x in p1)
    print("    an undeclared U > 1 image is reported        %s"
          % ("ok" if hit else "*** MISSED"))
    i2c = next(img for n, img in imgs if n == "corpus_i2c.hex")
    p2, _ = audit([("corpus_i2c.hex", i2c)],
                  {"corpus_i2c.hex": ({OVERLOAD}, "fixture")}, {}, {})
    hit2 = any("stale" in x for x in p2)
    print("    a stale declaration is reported              %s"
          % ("ok" if hit2 else "*** MISSED"))
    # ---- DT-D: D_sched <= D_tol on every image ----------------------------
    # ⛔ `program_a2.lane_set` PATCHES a header whose EDF key is looser than
    # its tolerance (`if ds > dt: dt = ds`) so the model can run at all; that
    # patch must never be what a tracked image relies on. Not declarable: a
    # header that schedules a lane later than it tolerates is simply wrong.
    print()
    print("  --- DT-D: D_sched <= D_tol on every lane of every image ---")
    def dsched_bad(img):
        return [(ln, h["dsched"], h["dtol"]) for ln, h, _a in pa.lanes_of(img)
                if h["dsched"] > h["dtol"]]
    viol = [(n, b) for n, img in imgs for b in dsched_bad(img)]
    for n, (ln, ds, dt) in viol:
        print("    *** %s lane %d: D_sched %d > D_tol %d" % (n, ln, ds, dt))
        rc = 1
    print("    %d image(s): %s" % (len(imgs), "every lane D_sched <= D_tol"
                                   if not viol else "VIOLATIONS above"))
    import pe_isa as _isa
    planted = bytearray(next(img for n, img in imgs if n == "corpus_i2c.hex"))
    h0 = dgf.unpack(_isa.HDR_FIELDS, planted[:_isa.HDR_BYTES], _isa.HDR_BYTES)
    h0["dsched"], h0["dtol"] = 200, 100
    planted[:_isa.HDR_BYTES] = _isa._pack(
        _isa.HDR_FIELDS, [h0[nm] for nm, _w in _isa.HDR_FIELDS],
        _isa.HDR_BYTES)
    fired = bool(dsched_bad(bytes(planted)))
    print("    must-fire: a planted D_sched 200 > D_tol 100 header is caught  %s"
          % ("ok" if fired else "*** MISSED"))
    if not fired:
        rc = 1

    # ---- RULING HDR: the header mode bits on every image -----------------
    # ⛔ Not declarable, like DT-D: a reserved bit, CLK_INV on an open-drain or
    # `uio` clock, or HALF_HIGH with d/2 under D* is simply wrong. The SAME
    # function `pe_asm` refuses with (`pe_isa.flag_problems`).
    print()
    print("  --- HDR: header mode bits (reserved / CLK_INV / HALF_HIGH) ---")
    fviol = [(n, p) for n, img in imgs
             for p in _isa.flag_problems(img, jp.D_STAR)]
    for n, p in fviol:
        print("    *** %s: %s" % (n, p))
        rc = 1
    print("    %d image(s): %s" % (len(imgs), "no forbidden mode bit"
                                   if not fviol else "VIOLATIONS above"))
    for what, flags, want in (("a planted RESERVED bit", 0x8, "RESERVED"),
                              ("a planted CLK_INV on an open-drain lane",
                               _isa.FLAG_CLK_INV, "OPEN-DRAIN")):
        pl = bytearray(next(img for n, img in imgs if n == "corpus_i2c.hex"))
        h0 = dgf.unpack(_isa.HDR_FIELDS, pl[:_isa.HDR_BYTES], _isa.HDR_BYTES)
        h0["flags"] = flags
        pl[:_isa.HDR_BYTES] = _isa._pack(
            _isa.HDR_FIELDS, [h0[nm] for nm, _w in _isa.HDR_FIELDS],
            _isa.HDR_BYTES)
        got = any(want in p for p in _isa.flag_problems(bytes(pl), jp.D_STAR))
        print("    must-fire: %-42s %s" % (what + " is caught",
                                          "ok" if got else "*** MISSED"))
        rc |= 0 if got else 1

    # ⛔ DT-A's must-fire: ckdense under a name nothing declares must be
    # reported for QUEUE -- the condition is derived, not read off the list.
    dense = next(img for n, img in imgs if n == "ckdense_image.hex")
    p3, _ = audit([("undeclared_queue.hex", dense)], {}, {}, {})
    hit3 = any("QUEUE" in x for x in p3)
    print("    an undeclared 1.6a (QUEUE) image is reported  %s"
          % ("ok" if hit3 else "*** MISSED"))
    if not (hit and hit2 and hit3):
        rc = 1

    # ---- SP2/P4: THE TIMING-EXEMPTION REGISTRY (Wilson) ------------------
    # ⛔ `timing_checks=False` and `no_rta_budget` are accepted only through
    # `model/nonadmissible.py` TIMING_EXEMPT, whose tracked entries must be N1
    # entries above that declare QUEUE (and N1's audit already reds a stale
    # QUEUE, so the exempt image really does fail 1.6a).
    print()
    print("  --- SP2/P4: timing exemptions only through the registry ---")
    import program_a2 as _pa2
    import pe_asm as _asm
    import pe_proto as _pp
    rp = NA.registry_problems() + NA.no_rta_problems(_pa2.NO_RTA_BUDGET)
    for p in rp:
        print("    *** %s" % p)
        rc = 1
    print("    registry: %s; NO_RTA_BUDGET membership == registry: %s"
          % (", ".join("%s(%s)" % (n, "/".join(sorted(e["permits"])))
                       for n, e in sorted(NA.TIMING_EXEMPT.items())),
             "yes" if not rp else "*** NO"))
    tracked = {n for n, _i in imgs}
    for n, e in sorted(NA.TIMING_EXEMPT.items()):
        if e["of"] is None and n not in tracked:
            print("    *** %s is a tracked registry entry with no image" % n)
            rc = 1
    # must-fires, each needing POSITIVE red
    sl, sh, spark = _pp.spi_fram()
    try:
        _asm.assemble(sl, sh, park_pins=spark, timing_checks=False,
                      exempt_as="undeclared_spim.hex")
        mf1 = False
    except _asm.Reject as e:
        mf1 = "TIMING_EXEMPT" in str(e)
    print("    must-fire: an UNREGISTERED image with timing_checks=False is "
          "refused  %s" % ("ok" if mf1 else "*** MISSED"))
    planted = dict(_pa2.NO_RTA_BUDGET)
    planted["corpus_i2c.hex"] = {"why": "planted", "measured_widest": {},
                                 "margin": 0}
    mf2 = any("corpus_i2c.hex" in p for p in NA.no_rta_problems(planted))
    print("    must-fire: an unregistered NO_RTA_BUDGET key is reported      "
          "  %s" % ("ok" if mf2 else "*** MISSED"))
    try:
        NA.require("corpus_i2c.hex", NA.NO_RTA)
        mf3 = False
    except NA.ExemptionError:
        mf3 = True
    print("    must-fire: budgets()' per-use registry check refuses it        "
          "  %s" % ("ok" if mf3 else "*** MISSED"))
    reg = dict(NA.TIMING_EXEMPT)
    reg["i2caddr_image.hex"] = {"permits": {NA.TIMING_OFF}, "of": None,
                                "why": "planted"}
    mf4 = any("i2caddr_image.hex" in p for p in NA.registry_problems(reg))
    print("    must-fire: an exemption with no N1 (QUEUE) declaration is red  "
          "  %s" % ("ok" if mf4 else "*** MISSED"))
    reg5 = dict(NA.TIMING_EXEMPT)
    e5 = dict(reg5["ckdense_image.hex"])
    e5.pop("budget_origin", None)
    reg5["ckdense_image.hex"] = e5
    mf5 = any("budget_origin" in p for p in NA.registry_problems(reg5))
    print("    must-fire: an empirical budget with no stated origin is red    "
          "  %s" % ("ok" if mf5 else "*** MISSED"))
    print("    ckdense budget origin: %s"
          % NA.TIMING_EXEMPT["ckdense_image.hex"]["budget_origin"][:72])
    if not (mf1 and mf2 and mf3 and mf4 and mf5):
        rc = 1

    print()
    print("=" * 78)
    if rc == 0 and board:
        v, why = image_universe.board_stale_verdict(
            "model/gate_admissible_images.py", board)
        print("  stale_records: %s -- %s" % (v, why))
        if v == "STALE":
            import stale_records as SR
            print(SR.token("admissible-images", why))
            return 0
        if v == "FAIL":
            rc = 1
    print("  GATE admissible-images: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
