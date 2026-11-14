#!/usr/bin/env python3
"""BRANCH_BIT's gate (v2 primitive 1; Wilson 10-26/27, R2c).

THE ONE CLAIM: the timed branch (opcode 8, wait W >= D* + B) picks the right
next word, fetches nothing past itself, and costs its lanes nothing an
ordinary action of delay W would not -- and each of those is guarded by a
must-fire that goes red without it.

Bench: test/tb_equiv.v with +BRCHECK=1 (test/branch_check.vh computes the
expected next PC from the word and the pin, and checks every dispatched head
against the image). Images: test/branch_corpus.py, written to scratch.

  B1  baseline, W = 33 and 40, 1 and 4 branchers: pc_bad 0, head_bad 0,
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
NCYC = 60000          # LOOP n = 255 needs ~25k cycles per entry
STEADY = 1000          # per-dispatch stats from this cycle on (past the start)
GEN = "run_branch_check"
#: image name -> its builder. braw* = BRANCH_BIT (primitive 1); cmp_* =
#: CMP_BRANCH (primitive 2): the bit-order pair and the mask/inv pair.
IMAGES = {
    "braw33_alone": lambda: B.build(1, 1, "braw33"),
    "braw33_contend4": lambda: B.build(4, 1, "braw33"),
    "braw40_alone": lambda: B.build(1, 1, "braw40"),
    "braw40_contend4": lambda: B.build(4, 1, "braw40"),
    "cmp_order": lambda: B.build_cmp("ok", kind="order"),
    "cmp_mask": lambda: B.build_cmp("ok", kind="mask"),
    "cmp_lo": lambda: B.build_cmp("ok", kind="lo"),
    # v2 primitive 2 bundle 2: LOOP -- one lane n = 7, and five contending (n = 1 2 3 7 255)
    "loop_alone": lambda: B.build_loop("alone"),
    "loop_mix": lambda: B.build_loop("mix"),
}
BASE = list(IMAGES)
#: mutant -> (BRCHECK counter that must go non-zero, what it breaks, image)
MUTANTS = [
    ("M_BR_TGT_OFF1", "pc_bad", "the taken target one word past its own", "braw33_contend4"),
    ("M_BR_ALWAYS", "pc_bad", "every branch taken", "braw33_contend4"),
    ("M_BR_NEVER", "pc_bad", "no branch taken", "braw33_contend4"),
    ("M_BR_LVL_INV", "pc_bad", "taken on the opposite level", "braw33_contend4"),
    ("M_BR_FETCH_PAST", "head_bad", "the spare fetched past a branch head", "braw33_contend4"),
    ("M_BR_W_ZERO", "stall_cycles", "the zero-time branch (no refill window)", "braw33_contend4"),
    # v2 primitive 2: CMP_BRANCH, each on the image whose pair it breaks
    ("M_CMP_ORDER_IGN", "pc_bad", "no wire-order reversal on an MSB lane", "cmp_order"),
    ("M_CMP_IMM_OFF1", "pc_bad", "the immediate one off", "cmp_order"),
    ("M_CMP_MASK_IGN", "pc_bad", "the mask mode ignored (all 8 bits)", "cmp_mask"),
    ("M_CMP_INV", "pc_bad", "q[0] (taken on mismatch) ignored", "cmp_mask"),
    # LOOP
    ("M_LOOP_OFF1", "pc_bad", "n + 1 iterations", "loop_mix"),
    ("M_LOOP_NOEXIT", "pc_bad", "the loop never exits", "loop_mix"),
    ("M_LOOP_NORESET", "pc_bad", "the counter survives the exit", "loop_mix"),
    # the pre-decoder (Wilson 10-29): class bits never written at the capture
    ("M_PREDECODE_STALE", "pc_bad", "the opcode-class bits never written", "braw33_contend4"),
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
    out = ["%s=%d" % (k, c[k]) for k in ("pc_bad", "head_bad", "stall_cycles", "loop_bad")
           if c.get(k)]
    if c.get("wb", 0) == 0 or c.get("taken", 0) == 0 or c.get("not", 0) == 0:
        out.append("both_ways=0 (wb %s taken %s not %s)"
                   % (c.get("wb"), c.get("taken"), c.get("not")))
    for (kind, ln), (_n, mx) in sorted(per.items()):
        if kind == "suc":
            _cn, cmx = per.get(("ctl", ln), (0, None))
            if cmx is None or mx > cmx:
                out.append("succ_late=%d lane %d > its control max %s" % (mx, ln, cmx))
        elif bound == NOT_JUDGED:
            continue        # declared outside the admissible set: reported, not bounded
        elif bound is None or mx > bound:
            out.append("ctl_late=%d lane %d > A2's r - C = %s" % (mx, ln, bound))
    return out


#: the control-lane lateness of an image DECLARED outside the admissible set is
#: reported but judged against no bound (every other check still applies)
NOT_JUDGED = "not-judged"
#: the MEASURED-BRIDGE record (Wilson 11-14): written by `--record-bridge`
BRIDGE_JSON = os.path.join(HERE, "branch_bridge.json")


def branch_premises(img):
    """[violated premise] for an image's branch lanes, against agent 2's
    head_late_br premises at B = br1_budget (lean/JLane/JLane/BrRefine.lean;
    every constant from model/proof_constants.py, never typed):
      hd   D* + B <= d                        (throughput)
      hFc  R + head_slack + D* + 2B <= W + d  (condition F: 46 + 2B at R = 14)
    d = the lane's smallest action delay with each branch priced at its wait
    W (program_a2.lanes_of), W = the lane's smallest branch wait. (hNc needs
    agent 2's Y and is not checked here.)"""
    import gate_degenerate_fields as dgf
    import program_a2 as P
    import proof_constants as PC
    k = PC.load()
    B, ds, R, hs = k["br1_budget"], k["dstar"], k["R_base"], k["head_slack"]
    lanes = {ln: acts for ln, _h, acts in P.lanes_of(img)}
    waits = {}
    for ln, _h, a in dgf.walk(img):
        if a["op"] in I.BRANCH_OPS:
            waits[ln] = min(waits.get(ln, 1 << 30), I.branch_wait(a))
    out = []
    for ln, W in sorted(waits.items()):
        d = min((a["delay"] for a in lanes.get(ln, []) if a["delay"] > 0), default=0)
        if d < ds + B:
            out.append("lane %d: hd d=%d < D*+B=%d" % (ln, d, ds + B))
        if R + hs + ds + 2 * B > W + d:
            out.append("lane %d: hFc W+d=%d < R+head_slack+D*+2B=%d" % (ln, W + d, R + hs + ds + 2 * B))
    return out


def _bridge():
    import json
    if not os.path.isfile(BRIDGE_JSON):
        return {}
    with open(BRIDGE_JSON, encoding="utf-8") as fh:
        return json.load(fh)


#: image -> how its control-lane bound was obtained (printed beside it)
BOUND_KIND = {}


def a2_dispatch_bound(img, name="image"):
    """max over lanes of r - C, A2 pricing each branch as an action of delay W.

    ⛔⛔ INTERIM, UNTIL THE DISPATCHER-STALL FIX LANDS (Wilson 11-13; agent 2,
    0aed169). With a branch lane the shipped dispatcher can stall EVERY lane
    past A2's J = 1, so that bound is known wrong and could pass falsely:
      * ONE branch lane (and no branch->branch chain, which pe_isa refuses):
        A2 re-run at the PROVED J = j_interim_head_late_optA
        (= 1 + br_succ_late + br1_budget, model/proof_constants.py -- quoted,
        never typed), labelled "interim";
      * TWO OR MORE branch lanes: the stalls can feed each other and the proof
        gives NO bound under the shipped scheduler -- so NO bound is quoted
        (None), and the judge reads that as red: never a pass on a bound we
        know is wrong. Back to the A2 value when STALL_FIX_PENDING goes False."""
    import program_a2 as P
    import proof_constants as PC
    bl = P.branch_lanes(img) if P.STALL_FIX_PENDING else []
    if len(bl) >= 2:
        # ⛔ Wilson 11-14: FIRST the admissible set -- an image whose branch
        # lanes break the theorem's premises is declared outside it, NOT budgeted
        bad = branch_premises(img)
        if bad:
            BOUND_KIND[name] = "NON-ADMISSIBLE (%s)" % "; ".join(bad)
            return NOT_JUDGED
        # inside the premises, no k-lane bound proved yet: the MEASURED-BRIDGE
        # budget (uncertified) -- measured worst + a stated margin, from the
        # record `--record-bridge` writes; owner: agent 2's k-lane bound (DEBT)
        rec = _bridge().get(name)
        if rec is None or rec.get("sha") != P.image_sha(img):
            BOUND_KIND[name] = ("NO PROVED BOUND and no current MEASURED-BRIDGE record "
                                "(run --record-bridge)")
            return None
        BOUND_KIND[name] = ("MEASURED-BRIDGE (uncertified): measured %d + margin %d"
                            % (rec["ctl_late_max"], rec["margin"]))
        return rec["ctl_late_max"] + rec["margin"]
    j = None
    if bl:
        j = PC.load()["j_interim_head_late_optA"]
        BOUND_KIND[name] = "interim J=%d (dispatcher-stall fix pending)" % j
    else:
        BOUND_KIND[name] = "A2"
    r = P.lane_responses(img, j=j)
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
        bound = a2_dispatch_bound(img, name)
        bad = run_problems(c, per, bound)
        if name.startswith("cmp_") and not c.get("cmp"):
            bad.append("cmp=0 -- no CMP_BRANCH ran, so nothing was compared")
        if name.startswith("loop_") and not c.get("loops"):
            bad.append("loops=0 -- no LOOP exited, so no count was checked")
        print("    %-16s wb %4d  stall %d  pc_bad %d  head_bad %d  r-C %s [%s]  %s"
              % (name, c["wb"], c["stall_cycles"], c["pc_bad"], c["head_bad"], bound,
                 BOUND_KIND.get(name, "?"), "ok" if not bad else "*** " + "; ".join(bad)))
        probs += ["%s: %s" % (name, b) for b in bad]

    print("\n  B2 chains refused (Wilson 10-27 Q2)")
    for name, (nb, ch, sp) in B.REFUSED_CHAINS.items():
        pr = I.branch_problems(B.build(nb, ch, sp, check=False))
        ok = any("branch->branch chain" in x for x in pr)
        print("    %-16s %s" % (name, "REFUSED" if ok else "*** NOT REFUSED ***"))
        if not ok:
            probs.append("%s: the chain is not refused" % name)
    # v2 primitive 2: whole bytes only, and something must have arrived
    # (Wilson 10-27 addition 1); q[1] = the USB lane's latched PID since bundle 6
    # (Wilson 11-09), so off the live USB lane it is refused
    # LOOP: n = 0, forward head, nested, break-out by a branch, by a REARM
    for v in B.LOOP_REFUSED:
        pr = I.branch_problems(B.build_loop("alone", v, check=False))
        want = {"n0": "count n = 0", "fwd": "not BACKWARD", "nested": "LOOP inside LOOP",
                "breakout": "jumps OUT of LOOP", "rearm": "REARM inside LOOP"}[v]
        ok = any(want in x for x in pr)
        print("    loop_%-11s %s" % (v, "REFUSED" if ok else "*** NOT REFUSED ***"))
        if not ok:
            probs.append("loop_%s: not refused for its own reason" % v)
    for v in B.CMP_REFUSED:
        pr = I.branch_problems(B.build_cmp(v, check=False))
        want = {"bit7": "after 7 bit(s)", "norx": "NOTHING received",
                "q1": "latched PID (q[1]) off the live USB lane"}[v]   # bundle 6: q[1] is the PID compare
        ok = any(want in x for x in pr)
        print("    cmp_%-12s %s" % (v, "REFUSED" if ok else "*** NOT REFUSED ***"))
        if not ok:
            probs.append("cmp_%s: not refused for its own reason" % v)

    print("\n  B3 runtime refusals (packed past the encoder)")
    good = B.build(1, 1, "braw33")
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


def record_bridge() -> int:
    """`--record-bridge`: measure every image that takes the MEASURED-BRIDGE
    budget (two or more branch lanes, inside the premises) and write its worst
    control-lane lateness + the stated margin to BRIDGE_JSON. The margin is ONE
    refill (proof_constants l_refill): the smallest unit the port can add to a
    word's lateness, stated, never fitted to the data."""
    import json
    import program_a2 as P
    import proof_constants as PC
    margin = PC.load()["l_refill"]
    tmp = tempfile.mkdtemp(prefix="pe_brbridge_")
    vvp = os.path.join(tmp, "brchk.vvp")
    build(vvp)
    out = {}
    for name in BASE:
        img = IMAGES[name]()
        if len(P.branch_lanes(img)) < 2 or branch_premises(img):
            continue
        p = write_hex(os.path.join(tmp, "brchk_%s.hex" % name), img)
        c, per, raw = sim(vvp, p)
        mx = max((m for (kind, _ln), (_n, m) in per.items() if kind == "ctl"), default=None)
        if mx is None:
            print("  *** %s: no control-lane lateness measured" % name)
            return 1
        out[name] = {"ctl_late_max": mx, "margin": margin, "sha": P.image_sha(img),
                     "label": "MEASURED-BRIDGE (uncertified)",
                     "owner": "agent 2's k-lane bound under (b') (Wilson 11-14)"}
        print("  %-16s measured ctl_late max %d + margin %d" % (name, mx, margin))
    with open(BRIDGE_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("  -> %s (%d image(s))" % (os.path.relpath(BRIDGE_JSON, ROOT), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(record_bridge() if "--record-bridge" in sys.argv else main())
