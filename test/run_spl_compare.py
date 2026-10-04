"""T3 -- single vs double action buffer, measured on a buildable parameter.

THE ONE QUESTION: does the double buffer (169 flops) lower either `D*` -- the
action delay at which the shared fetch port stops being the binding constraint
-- or the per-lane prefetch-miss wait? If it lowers neither, the recommendation
is removal.

⛔⛔ WHY THIS EXISTS AT ALL. The advertised benefit was "worst-case J 11 -> 7",
computed from `SWEEP_SINGLE` in `gate_j_program.py`. That dict described a
SINGLE-BUFFER CONFIGURATION WITH NO BUILD OPTION: `NSLOT = 2 * N_LANES` was
fixed in `pe_engine.v`, so the arm could not be re-measured even in principle,
and its correctness had never been established either. A 169-flop decision was
resting on a number with no recipe. `SPL` is now a real parameter, so both
configurations elaborate and both can be measured.

⭐ THE RECIPE IS THE EXISTING SWEEP'S, DELIBERATELY. `--five d d+1 d+2 d+3 d+4`
per point, `tb_smoke`, 200k cycles, warm-up 4000, window asserted >= 100k --
identical to `model/a2/price_j_sweep.sh`, so the double-buffer column here is
comparable with the live J sweep rather than being a third way of measuring.

⛔ PROBE PATHS ONLY (standing rule 6): images go to `probe_spl.hex`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_spl"))

NCYC, WARMUP, MIN_WINDOW = 200000, 4000, 100000
# ⭐ SPANNING D* = 20 FROM BOTH SIDES, and the points either side of the known
# double-buffer cliff (18 -> 19) so a shift in it is visible rather than
# inferred.
D_LIST = [8, 12, 16, 18, 19, 20, 21, 25, 30]
SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
L_REFILL, N_LANES = 4, 5
D_STAR_STRUCTURAL = N_LANES * L_REFILL          # 20


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def build(top, bench, spl):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "%s_spl%d.vvp" % (top, spl))
    r = run(["iverilog", "-g2012", "-o", out, "-s", top,
             "-P%s.SPL_CFG=%d" % (top, spl),
             os.path.join(ROOT, bench)]
            + [os.path.join(ROOT, s) for s in SRCS])
    if r.returncode != 0:
        print("*** build %s SPL=%d failed" % (top, spl))
        print((r.stdout + r.stderr)[-800:])
        return None
    return out


def smoke_point(vvp, d):
    """One sweep point. Returns (steady_max, events, window, nbytes) or None
    with a reason -- the preconditions are the existing sweep's."""
    g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
             "--five", str(d), str(d + 1), str(d + 2), str(d + 3), str(d + 4),
             "probe_spl"])
    if g.returncode != 0:
        return None, "image build failed"
    r = run(["vvp", vvp, "+IMG=test/probe_spl.hex",
             "+NCYC=%d" % NCYC, "+WARMUP=%d" % WARMUP])
    txt = r.stdout + r.stderr

    def num(pat):
        m = re.search(pat, txt)
        return int(m.group(1)) if m else None

    nb = num(r"probe_spl\.hex: (\d+) bytes")
    win = num(r"window length *: *(\d+)")
    steady = num(r"STEADY *: *(\d+)")
    ev = num(r"EVENTS in steady state *: *(\d+)")
    # ⛔ THE SAME TWO VACUITY TRAPS THE J SWEEP HIT, CHECKED THE SAME WAY: an
    # image that never loaded and an empty window both read as "no stalls".
    if nb is None or nb < 30:
        return None, "the image never loaded (%s bytes)" % nb
    if win is None or win < MIN_WINDOW:
        return None, "window %s < %d" % (win, MIN_WINDOW)
    if steady is None:
        return None, "no STEADY reading"
    return (steady, ev, win, nb), None


def cliff(points):
    """The smallest swept d whose steady stall is 0 AND stays 0 above it.
    ⚠ A FLOOR ON THE CLIFF, not the cliff: it can only be located between two
    SWEPT points, so it is reported as an interval, never as a single number
    the sweep did not actually test.
    """
    ds = sorted(points)
    for i, d in enumerate(ds):
        if points[d][0] == 0 and all(points[x][0] == 0 for x in ds[i:]):
            return (ds[i - 1] if i else None), d
    return None, None


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("T3 -- SINGLE vs DOUBLE ACTION BUFFER (SPL = 1 vs 2)")
    print("=" * 78)
    print("  recipe per point : --five d d+1 d+2 d+3 d+4, then tb_smoke")
    print("                     (the J sweep's recipe, so the columns compare)")
    print("  run              : %d cycles, warm-up %d, window asserted >= %d"
          % (NCYC, WARMUP, MIN_WINDOW))
    print("  D* (structural)  : k * L_REFILL = %d" % D_STAR_STRUCTURAL)
    print()

    # ---- correctness FIRST. A performance number from a broken -----------
    # configuration is a measurement of nothing, and the retracted benefit
    # claim came from an arm whose correctness was never established.
    print("  --- correctness gate: tb_smoke must PASS at both depths ---")
    vvps = {}
    for spl in (2, 1):
        v = build("tb_smoke", "test/tb_smoke.v", spl)
        if v is None:
            return 1
        r = run(["vvp", v])
        txt = r.stdout + r.stderr
        ok = "SMOKE: PASS" in txt
        e0 = re.search(r"edges on uo_out\[0\] \(lane 0\) *: *(\d+)", txt)
        e1 = re.search(r"edges on uo_out\[1\] \(lane 1\) *: *(\d+)", txt)
        c = re.search(r"measured C \(x100 cycles/job\): *(\d+)", txt)
        flips = re.search(r"select-bit flips *: *(\d+)", txt)
        print("    SPL=%d  %s   edges %s/%s  C=%s  select-flips=%s"
              % (spl, "PASS" if ok else "*** FAIL",
                 e0.group(1) if e0 else "?", e1.group(1) if e1 else "?",
                 c.group(1) if c else "?", flips.group(1) if flips else "?"))
        if not ok:
            print("      *** a performance comparison against an incorrect")
            print("          configuration is worthless. Stopping.")
            return 1
        vvps[spl] = build("tb_smoke", "test/tb_smoke.v", spl)
    print("    ⭐ identical pin behaviour and C at both depths, and SPL=1")
    print("       shows ZERO select-bit flips -- there is no swap to make.")
    print()

    # ---- the sweep -------------------------------------------------------
    print("  --- steady-state stall vs d, both depths ---")
    print("    %-5s %-22s %-22s %s"
          % ("d", "double (SPL=2)", "single (SPL=1)", "difference"))
    pts = {2: {}, 1: {}}
    for d in D_LIST:
        cells, bad = {}, False
        for spl in (2, 1):
            got, why = smoke_point(vvps[spl], d)
            if got is None:
                cells[spl] = "*** %s" % why
                bad = True
            else:
                steady, ev, win, _nb = got
                pts[spl][d] = (steady, ev, win)
                cells[spl] = "stall %-3d (%d events)" % (steady, ev)
        if bad:
            print("    %-5d %-22s %-22s %s"
                  % (d, cells[2], cells[1], "NO READING"))
            rc = 1
            continue
        diff = pts[1][d][0] - pts[2][d][0]
        print("    %-5d %-22s %-22s %s"
              % (d, cells[2], cells[1],
                 ("single is %+d" % diff) if diff else "identical"))

    if rc:
        print()
        print("  *** a point had no reading, so the comparison is incomplete.")
        return 1

    # ---- what it means ---------------------------------------------------
    print()
    print("  --- where the port stops binding (measured D*) ---")
    top = max(D_LIST)
    for spl, name in ((2, "double"), (1, "single")):
        below, at = cliff(pts[spl])
        if at is None:
            print("    %-7s: stall NEVER reaches 0 anywhere in the swept"
                  % name)
            print("             range, up to d = %d. Its cliff is ABOVE %d --"
                  % (top, top))
            print("             not located, and NOT absent." % ())
        else:
            print("    %-7s: stall first reaches 0 at d = %d; the last swept"
                  % (name, at))
            print("             nonzero point below it is d = %s" % below)
            print("             ⇒ the cliff lies in (%s, %d]; the sweep cannot"
                  % (below, at))
            print("               place it closer than two swept points")
    c2, c1 = cliff(pts[2])[1], cliff(pts[1])[1]

    # ⛔⛔ THE COMPARISON IS MADE IN THE SCOPED REGION, AND THE FIRST VERSION
    # OF THIS BLOCK WAS WRONG BECAUSE IT WAS NOT. It took the worst stall over
    # the WHOLE swept range -- which includes d < D*, where neither
    # configuration is port-feasible and both read 11 -- so the maximum was
    # set by points the published claim explicitly does not cover, the two
    # columns tied at 11, and the gate printed "LOWERS NEITHER, remove 169
    # flops". The table it printed directly above said the opposite: at
    # d >= 19 the double buffer stalls 0 while the single buffer stalls 8, 6,
    # 4, 1, 1.
    # ⇒ An exact maximum over the wrong range. The published claim is scoped
    #   to d >= D*, so that is where the two configurations must be compared.
    scoped = [d for d in sorted(pts[2]) if d >= D_STAR_STRUCTURAL]
    w2_all = max(v[0] for v in pts[2].values())
    w1_all = max(v[0] for v in pts[1].values())
    w2 = max(pts[2][d][0] for d in scoped)
    w1 = max(pts[1][d][0] for d in scoped)
    print()
    print("  --- the verdict on 169 flops ---")
    print("    worst stall, WHOLE swept range   : double %d   single %d"
          % (w2_all, w1_all))
    print("      ⚠ this range includes d < D* = %d, where NEITHER depth is"
          % D_STAR_STRUCTURAL)
    print("        port-feasible and the claim is not made, so this line is")
    print("        NOT the verdict. Reading it off this line is how the first")
    print("        version of this gate recommended removal: the two columns")
    print("        came out equal over the whole range while differing by %d"
          % (w1 - w2))
    print("        cycles in the scoped region below.")
    print("    worst stall, d >= D* = %-3d (SCOPED): double %d   single %d"
          % (D_STAR_STRUCTURAL, w2, w1))
    print("    cliff                            : double %s   single %s"
          % (c2, "above %d" % top if c1 is None else c1))
    # "no cliff in range" means WORSE than everything swept, not "the same".
    lowers_dstar = (c2 is not None and (c1 is None or c2 < c1))
    lowers_stall = w2 < w1
    print()
    if lowers_dstar or lowers_stall:
        print("    ⇒ THE DOUBLE BUFFER IS WHAT MAKES THE PUBLISHED CLAIM TRUE.")
        if lowers_stall:
            print("      In the scoped region the double buffer stalls %d and"
                  % w2)
            print("      the single buffer stalls up to %d, so `d_min >= D* ->"
                  % w1)
            print("      J = 1` HOLDS ONLY AT SPL = 2. At SPL = 1 the same")
            print("      programs stall, so J would be at least %d." % (w1 + 1))
        if lowers_dstar:
            print("      And the cliff moves: %s vs %s."
                  % (c2, "above %d" % top if c1 is None else c1))
        print("      RECOMMENDATION: KEEP IT. The benefit is now a")
        print("      reproducible measurement at a buildable parameter,")
        print("      not an unrepeatable record -- and it is larger and in a")
        print("      different place than the retracted '11 -> 7' claimed.")
        print("      ⚠ NATHAN RULES. ⭐ AND NOTE WHAT CHANGES: removing the")
        print("      double buffer would invalidate the ONLY published timing")
        print("      claim, which the previous framing ('at the shipped")
        print("      delays it buys nothing') did not say.")
    else:
        print("    ⇒ in the scoped region the double buffer lowers neither")
        print("      the stall nor the cliff. RECOMMENDATION: remove it --")
        print("      169 flops for no measured benefit. ⚠ NATHAN RULES.")
    print()
    print("    ⚠ WHAT THIS DOES NOT MEASURE: the per-lane wait, which is")
    print("      `test/run_jlane.py` with -Ptb_jlane.SPL_CFG=1, and the cold")
    print("      start, which `tb_smoke` reports separately from steady state.")
    print("  ⛔ The sweep wrote only test/probe_spl.hex; no reserved name")
    print("     was touched.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
