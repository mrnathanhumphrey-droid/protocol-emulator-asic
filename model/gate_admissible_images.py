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
from bursty import L_SYNC                                         # noqa: E402

OVERLOAD, PORT, PINMAP, QUEUE = "OVERLOAD", "PORT", "PINMAP", "QUEUE"

#: ⛔ DECLARED BY NAME, each with the conditions it breaks and why that is
#: intended. PINMAP is NOT listed here -- it lives in corpus.PAD_COLLISION.
NON_ADMISSIBLE = {
    "corpus_all5.hex": ({OVERLOAD, PORT},
        "the scheduler stress image: four lanes at d = 9..13 beside a clocked "
        "lane at 70 (D5 raised only lane 0), deliberately oversubscribed. "
        "Ruling S reports its clocked lane UNBOUNDED for this reason."),
    # ⛔ MECHANISM ONLY (ruling Q3), and the first version of this entry said
    # otherwise: it called the tracked file "the measurement base for T1's
    # per-lane J and Theorem 3's port-feasible cells". Those claims were
    # measured with the BUILDER at OTHER delays -- Theorem 3's 35 cells are
    # `run_dstar_check` at d = 20..60, every point admissible -- not with this
    # file at 12..16. Conflating the builder with the file is how a
    # non-admissible image starts to read as evidence.
    "five_image.hex": ({OVERLOAD, PORT},
        "MECHANISM ONLY. The tracked FIVE_STRESS image (d = 12..16, "
        "U = 1.083). Used by tb_witness's stall-chain trace (a floor, sub-D* "
        "regime), run_mutants' M_BUF_SWAP kill (needs stalls to discriminate), "
        "and gate_cj_bounds' sub-D* double-buffer number (that gate is "
        "RETIRED under CJ; the figure is history). No "
        "claim scoped to admissible programs was measured on it (Q3)."),
    "corpus_spim.hex": ({PORT, QUEUE},
        "the SPI-master TRACE image at d = 7, below D*: it exists to move the "
        "uo_out bank for the corpus witness, not as the shipped 1 MHz SPI "
        "lane (25 cycles)."),
    "corpus_sptgt.hex": ({PORT, QUEUE},
        "the SPI-target trace image at d = 6, below D*: it exists to exercise "
        "the target's async MISO release for the corpus witness."),
    "corpus_uartrx.hex": ({PORT, QUEUE},
        "the UART-rx trace image at d = 11, below D*: it exercises the ARM "
        "and edge-capture path at a seeded phase."),
    "chain_image.hex": ({PORT, QUEUE},
        "`build_chain`, the chaining re-arm mechanism at d = 12: a mechanism "
        "test, not a schedulable program."),
    "edge_image.hex": ({PORT},
        "`tb_edge`'s reactive-release image at d = 12, below D*, because the "
        "edge-capture must-fires need tight spacing to discriminate."),
    "edge_image_noto.hex": ({PORT},
        "the no-timeout variant of the tb_edge image (d = 12)."),
    "edge_image_rise.hex": ({PORT},
        "the rising-edge variant of the tb_edge image (d = 12)."),
    "noop_image.hex": ({PORT, QUEUE},
        "the half-bit no-op idiom at d = 7: the no-op exists to offset a lane "
        "by less than one period, which is below D* by construction."),
    "noop_image_bad.hex": ({PORT, QUEUE},
        "the no-op idiom's must-fire image (d = 7)."),
    "noop_image_h19.hex": ({PORT},
        "the no-op idiom at the measured half value h = 19 (d = 12)."),
    # ⛔ RULING DT-B. ckdense's PINMAP is declared in corpus.PAD_COLLISION;
    # QUEUE is new: after W1 its clocked lanes reach r = 28/27/29/31 against
    # T = 20/21/22/23 (pyRTA), the regime where TChecker's `ovr` is reachable
    # and neither our recurrence nor pyRTA can be adjudicated. A STRESS image,
    # no longer Ruling S's must-fire subject.
    "ckdense_image.hex": ({QUEUE},
        "the A2 scheduler stress image (four dense clocked lanes, d = 20..23). "
        "Fails 1.6a under W1's jitter (DT-B), so no claim rests on it; kept "
        "because it is where W1 binds hardest and where W6's term is priced."),
    "ckhold_over_image.hex": ({QUEUE},
        "D4's 'must RUN' boundary point at d = SDA_HOLD + 1 = 16, below every "
        "mode floor: under W1 its lane's r = 18 > t = 16 (DT-A). It exists to "
        "show the silicon RUNS one cycle above the hold, not to be scheduled."),
    "tx_image.hex": ({PORT, QUEUE},
        "`tb_tx`'s TX-queue ownership image at d = 12-13, below D*: it tests "
        "routing of host bytes, not schedulability."),
}


def refill_dmin(img):
    """The minimum spacing between consecutive retires, over every lane."""
    best = None
    for ln, h, acts in pa.lanes_of(img):
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
        if any(v["r"] is not None and not v["ok"] for v in q.values()):
            out.add(QUEUE)
    return out, dm, pa.utilisation(ls)


def audit(images, declared, pad_declared, deliberate):
    """Problems for this set of (name, img). Pure, so the must-fire can price it."""
    probs, rows = [], []
    for name, img in images:
        if name in deliberate:
            continue
        got, dm, u = conditions(name, img)
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
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "test", "*.hex"))):
        n = os.path.basename(p)
        if not n.startswith("probe_"):
            out.append((n, dgf.load(p)))
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("  N1 -- NON-ADMISSIBLE IMAGES, DECLARED BY NAME")
    print("=" * 78)
    imgs = images()
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

    print()
    print("=" * 78)
    print("  GATE admissible-images: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
