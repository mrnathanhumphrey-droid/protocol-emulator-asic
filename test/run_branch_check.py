#!/usr/bin/env python3
"""BRANCH_BIT's gate (v2 primitive 1; Wilson 10-26/27, R2c).

THE ONE CLAIM: the timed branch (opcode 8, wait W >= D* + B) picks the right
next word, fetches nothing past itself, and costs its lanes nothing an
ordinary action of delay W would not -- and each of those is guarded by a
must-fire that goes red without it.

Bench: test/tb_equiv.v with +BRCHECK=1 (test/branch_check.vh computes the
expected next PC from the word and the pin, and checks every dispatched head
against the image). Images: test/branch_corpus.py, written to scratch.

  B1  baseline, W = 32 and 40, 1 and 4 branchers: pc_bad 0, head_bad 0,
      stall 0; every lane's branch-successor lateness <= the same lane's
      ordinary actions' (the control, same run); every ordinary action
      within A2's bound r - C, A2 pricing the branch as an action of delay W.
  B2  the chain images (branch->branch) are REFUSED by pe_isa (Q2).
  B3  the runtime refusals: W < BR_W_MIN, and a target past the store, packed
      past the encoder -> config_err set and the branching lane halted.
  B4  the must-fires: TGT_OFF1 / ALWAYS / NEVER / LVL_INV red on the PC,
      FETCH_PAST red on the head, W_ZERO (the zero-time branch R2b measured)
      red on stalls.

POSITIVE TOKEN: `GATE branch-check: PASSED`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model"), os.path.join(ROOT, "model", "a2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402
import branch_corpus as B               # noqa: E402

BENCH = "test/tb_equiv.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
NCYC = 30000
STEADY = 1000          # per-dispatch stats from this cycle on (past the start)
GEN = "run_branch_check"
#: image name -> its builder. braw* = BRANCH_BIT (primitive 1); cmp_* =
#: CMP_BRANCH (primitive 2): the bit-order pair and the mask/inv pair.
IMAGES = {
    "braw32_alone": lambda: B.build(1, 1, "braw32"),
    "braw32_contend4": lambda: B.build(4, 1, "braw32"),
    "braw40_alone": lambda: B.build(1, 1, "braw40"),
    "braw40_contend4": lambda: B.build(4, 1, "braw40"),
    "cmp_order": lambda: B.build_cmp("ok", kind="order"),
    "cmp_mask": lambda: B.build_cmp("ok", kind="mask"),
}
BASE = list(IMAGES)
#: mutant -> (BRCHECK counter that must go non-zero, what it breaks, image)
MUTANTS = [
    ("M_BR_TGT_OFF1", "pc_bad", "the taken target one word past its own", "braw32_contend4"),
    ("M_BR_ALWAYS", "pc_bad", "every branch taken", "braw32_contend4"),
    ("M_BR_NEVER", "pc_bad", "no branch taken", "braw32_contend4"),
    ("M_BR_LVL_INV", "pc_bad", "taken on the opposite level", "braw32_contend4"),
    ("M_BR_FETCH_PAST", "head_bad", "the spare fetched past a branch head", "braw32_contend4"),
    ("M_BR_W_ZERO", "stall_cycles", "the zero-time branch (no refill window)", "braw32_contend4"),
    # v2 primitive 2: CMP_BRANCH, each on the image whose pair it breaks
    ("M_CMP_ORDER_IGN", "pc_bad", "no wire-order reversal on an MSB lane", "cmp_order"),
    ("M_CMP_IMM_OFF1", "pc_bad", "the immediate one off", "cmp_order"),
    ("M_CMP_MASK_IGN", "pc_bad", "the mask mode ignored (all 8 bits)", "cmp_mask"),
    ("M_CMP_INV", "pc_bad", "q[0] (taken on mismatch) ignored", "cmp_mask"),
]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_equiv"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def write_hex(path, img):
    I.write_image(path, img)
    sim_run.scratch_image(GEN, path)
    return path


def sim(vvp, img):
    """-> ({BRCHECK counters}, {(kind, lane): (n, max)}, raw)."""
    args = [vvp, "+IMG=%s" % img, "+NBYTES=%d" % I.STORE_BYTES,
            "+NCYC=%d" % NCYC, "+BRCHECK=1", "+BRDBG=1"]
    r = run(sim_run.vvp(args, images=[img]))
    out = r.stdout + r.stderr
    m = re.search(r"^BRCHECK (.*)$", out, re.M)
    cnt = {}
    if m:
        for kv in m.group(1).split():
            k, v = kv.split("=", 1)
            cnt[k] = int(v)
    per = {}
    for mm in re.finditer(r"^BRDBG (ctl|suc) lane (\d+) op \d+ late (\d+) now (\d+)", out, re.M):
        if int(mm.group(4)) <= STEADY:
            continue
        k = (mm.group(1), int(mm.group(2)))
        n, mx = per.get(k, (0, 0))
        per[k] = (n + 1, max(mx, int(mm.group(3))))
    return cnt, per, out


def run_problems(c, per, bound):
    """[problem] for ONE branch run, each `name=value` -- THE judge every
    verdict below goes through (baseline clean, mutant red), so gate_meta's
    always-pass stub of it must turn the gate red."""
    out = ["%s=%d" % (k, c[k]) for k in ("pc_bad", "head_bad", "stall_cycles")
           if c.get(k)]
    if c.get("wb", 0) == 0 or c.get("taken", 0) == 0 or c.get("not", 0) == 0:
        out.append("both_ways=0 (wb %s taken %s not %s)"
                   % (c.get("wb"), c.get("taken"), c.get("not")))
    for (kind, ln), (_n, mx) in sorted(per.items()):
        if kind == "suc":
            _cn, cmx = per.get(("ctl", ln), (0, None))
            if cmx is None or mx > cmx:
                out.append("succ_late=%d lane %d > its control max %s" % (mx, ln, cmx))
        elif bound is None or mx > bound:
            out.append("ctl_late=%d lane %d > A2's r - C = %s" % (mx, ln, bound))
    return out


def a2_dispatch_bound(img):
    """max over lanes of r - C, A2 pricing each branch as an action of delay W."""
    import program_a2 as P
    r = P.lane_responses(img)
    if any(v[0] is None for v in r.values()):
        return None
    return max(v[0] for v in r.values()) - P.C_SHIPPED


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("BRANCH_BIT -- the timed branch (v2 primitive 1)")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_brchk_")
    vvp = os.path.join(tmp, "brchk.vvp")
    build(vvp)

    print("\n  B1 baseline (%d cycles, stats from cycle %d)" % (NCYC, STEADY))
    for name in BASE:
        img = IMAGES[name]()
        p = write_hex(os.path.join(tmp, "brchk_%s.hex" % name), img)
        c, per, raw = sim(vvp, p)
        if not c:
            probs.append("%s: no BRCHECK line (%s)" % (name, raw[-200:]))
            continue
        bound = a2_dispatch_bound(img)
        bad = run_problems(c, per, bound)
        if name.startswith("cmp_") and not c.get("cmp"):
            bad.append("cmp=0 -- no CMP_BRANCH ran, so nothing was compared")
        print("    %-16s wb %4d  stall %d  pc_bad %d  head_bad %d  A2 r-C %s  %s"
              % (name, c["wb"], c["stall_cycles"], c["pc_bad"], c["head_bad"], bound,
                 "ok" if not bad else "*** " + "; ".join(bad)))
        probs += ["%s: %s" % (name, b) for b in bad]

    print("\n  B2 chains refused (Wilson 10-27 Q2)")
    for name, (nb, ch, sp) in B.REFUSED_CHAINS.items():
        pr = I.branch_problems(B.build(nb, ch, sp, check=False))
        ok = any("branch->branch chain" in x for x in pr)
        print("    %-16s %s" % (name, "REFUSED" if ok else "*** NOT REFUSED ***"))
        if not ok:
            probs.append("%s: the chain is not refused" % name)
    # v2 primitive 2: whole bytes only, and something must have arrived
    # (Wilson 10-27 addition 1); q[1] held for LOOP's break-out flag
    for v in B.CMP_REFUSED:
        pr = I.branch_problems(B.build_cmp(v, check=False))
        want = {"bit7": "after 7 bit(s)", "norx": "NOTHING received",
                "q1": "q[1] must be zero"}[v]
        ok = any(want in x for x in pr)
        print("    cmp_%-12s %s" % (v, "REFUSED" if ok else "*** NOT REFUSED ***"))
        if not ok:
            probs.append("cmp_%s: not refused for its own reason" % v)

    print("\n  B3 runtime refusals (packed past the encoder)")
    good = B.build(1, 1, "braw32")
    for name, kw in (("w_below_min", {"wait": I.BR_W_MIN - 1}),
                     ("tgt_past_store", {"target": (I.STORE_BYTES - I.ACT_BASE) // I.ACT_BYTES})):
        img = B.patch_branches(good, **kw)
        static = I.branch_problems(img)
        p = write_hex(os.path.join(tmp, "brchk_%s.hex" % name), img)
        c, _per, raw = sim(vvp, p)
        live = c.get("live1")          # the branching lane (lane 1)
        halted = live == 0
        ok = bool(static) and c.get("cfgerr") == 1 and halted
        print("    %-16s pe_asm %s  cfgerr %s  lane-1 live %s  %s"
              % (name, "refuses" if static else "*** ACCEPTS ***", c.get("cfgerr"),
                 live, "ok" if ok else "*** NOT REFUSED ***"))
        if not ok:
            probs.append("%s: not refused (static %d, cfgerr %s, live %s)"
                         % (name, len(static), c.get("cfgerr"), live))

    print("\n  B4 must-fires")
    mf = {}
    for define, counter, what, imgname in MUTANTS:
        if imgname not in mf:
            mi = IMAGES[imgname]()
            mf[imgname] = (write_hex(os.path.join(tmp, "brchk_mf_%s.hex" % imgname), mi),
                           a2_dispatch_bound(mi))
        mp, mf_bound = mf[imgname]
        mv = os.path.join(tmp, "brchk_%s.vvp" % define.lower())
        try:
            build(mv, [define])
        except RuntimeError as exc:
            print("    %-16s BUILD FAIL -- not a kill" % define)
            probs.append("%s: %s" % (define, exc))
            continue
        c, per, _raw = sim(mv, mp)
        # red FOR ITS OWN REASON: the judge must name the mutant's counter
        red = any(p.startswith(counter + "=") for p in run_problems(c, per, mf_bound))
        print("    %-16s %-42s %s=%s  %s" % (define, what, counter, c.get(counter),
                                           "RED" if red else "*** SURVIVED ***"))
        if not red:
            probs.append("%s survived (%s = %s)" % (define, counter, c.get(counter)))

    print()
    for p_ in probs:
        print("  *** " + p_)
    print("  GATE branch-check: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
