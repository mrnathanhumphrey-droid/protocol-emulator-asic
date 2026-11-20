"""run_flags -- the inter-lane event flags (Wilson 11-19, the 11-09 semantics) on
the RTL: POST counts, WAIT is an ENABLE that consumes one count.

Lane 1 POSTS: a no-op wait, POST on flag 1 (the WRONG flag: it must release
nothing), uio[1] high, POST on flag 5 (40 cycles later), ..., uio[1] low, POST on
flag 5 again. Lane 0 WAITS: WAIT on flag 5, uio[0] high, WAIT on flag 5, uio[0] low.
Flag 5 uses the third index bit (pinb[2]).

Judged on tb_pair's uio[1:0] change events: uio[1] rises, then uio[0] rises
POST_LAG..POST_LAG+SLACK after it (the POST is 40 cycles after the rise, plus the
pick / dispatch), then uio[1] falls, then uio[0] falls the same lag after that.
Must-fires: M_FLAG_NOGATE (WAIT does not hold the lane: uio[0] rises first) and
M_FLAG_NOCONSUME (WAIT never consumes: the second WAIT passes on the first count,
uio[0] falls before uio[1]). pe_isa refuses a flag word with pinb[3] set.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BENCH = "test/tb_pair.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_flags"
PA, PB = 0, 1                 # uio[0] (the waiter's pin), uio[1] (the poster's)
D = 40                        # every word's delay: above D* = 20
F_WRONG, F = 1, 5             # the flag posted first (wrong), the flag waited on
POST_LAG = D                  # the POST follows the poster's edge by one word
SLACK = 12                    # pick + dispatch + pin register, cycles
NCYC = 2000
MUTANTS = [("M_FLAG_NOGATE", "WAIT does not hold the lane"),
           ("M_FLAG_NOCONSUME", "WAIT never consumes its count")]


def image(bad_index=False):
    l0 = I.ACT_BASE
    p0 = [I.act_wait(F, D), I.act(I.OP_LEVEL, PA, 1, D), I.act_wait(F, D),
          I.act(I.OP_LEVEL, PA, 0, D), I.act(I.OP_REARM, 0, 0, 500)]
    l1 = l0 + len(p0) * I.ACT_BYTES
    p1 = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 300), I.act_post(F_WRONG, D),
          I.act(I.OP_LEVEL, PB, 1, D), I.act_post(F, 300),
          I.act(I.OP_LEVEL, PB, 0, D), I.act_post(F, D), I.act(I.OP_REARM, 0, 0, 500)]
    lp = l1 + len(p1) * I.ACT_BYTES
    park = [I.act(I.OP_REARM, 0, 0, 500)]
    prog = p0 + p1 + park
    if bad_index:
        w = bytearray(I.act(I.OP_FLAG_SET, 0, 0, D, pinb=8))
        prog[l1 // I.ACT_BYTES - l0 // I.ACT_BYTES + 1] = bytes(w)
    hdrs = [I.hdr(PA, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0),
            I.hdr(PB, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l1)]
    for n in range(2, I.N_LANES):
        hdrs.append(I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, lp))
    return I.join_image(hdrs, prog)


F_OBS = 3                     # the flag OBSERVE reads


def observe_image(rx_clobber=False):
    """OBSERVE (Wilson 11-19): lane 1 POSTs flag 3 twice; lane 0 waits, OBSERVEs it
    TWICE (no consume: still 2), CMP_BRANCH on 2 -> taken drives uio[0] high, not
    taken drives uio[1] high. `rx_clobber`: a self-timed receive, then the OBSERVE,
    then the CMP -- the RX-liveness refusal's planted case (pe_isa only, not run)."""
    l0 = I.ACT_BASE
    taken = 6
    p0 = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 400),
          I.act_observe(F_OBS, D), I.act_observe(F_OBS, D),
          I.act_cmp_branch(2, taken, I.BR_W_MIN),
          I.act(I.OP_LEVEL, PB, 1, D), I.act(I.OP_REARM, 0, 0, 500),
          I.act(I.OP_LEVEL, PA, 1, D), I.act(I.OP_REARM, 0, 0, 500)]
    if rx_clobber:
        p0[0] = I.act_shiftin_timed(PB, D, 8)
    l1 = l0 + len(p0) * I.ACT_BYTES
    p1 = [I.act_post(F_OBS, D), I.act_post(F_OBS, D), I.act(I.OP_REARM, 0, 0, 500)]
    park = l0 + 5 * I.ACT_BYTES
    hdrs = [I.hdr(PA, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0),
            I.hdr(I.PIN_NONE, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l1)]
    for n in range(2, I.N_LANES):
        hdrs.append(I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, park))
    return I.join_image(hdrs, p0 + p1)


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_pair"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def edges(vvp, img):
    """{(pin, level): first cycle uio[pin] went to level while driven}, and the faults"""
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img, "+NCYC=%d" % NCYC], images=[img]))
    out = r.stdout + r.stderr
    ev = [(int(c), oe, o) for c, oe, o in re.findall(r"^EV (\d+) (\d\d) (\d\d)$", out, re.M)]
    first, prev = {}, {0: None, 1: None}
    for c, oe, o in ev:
        for pin in (0, 1):
            if oe[1 - pin] != "1":
                continue
            v = int(o[1 - pin])
            # the first driven level counts as an edge (the pin was released before)
            if v != prev[pin]:
                first.setdefault((pin, v), c)
            prev[pin] = v
    m = re.search(r"^FLT cfg=(\d) ovr=(\d)$", out, re.M)
    return first, (m.group(0) if m else "no FLT line"), ("END" in out)


def problems(first):
    r1, f1 = first.get((PB, 1)), first.get((PB, 0))
    r0, f0 = first.get((PA, 1)), first.get((PA, 0))
    if None in (r1, f1, r0, f0):
        return ["an edge is missing: uio1 rise %s fall %s, uio0 rise %s fall %s"
                % (r1, f1, r0, f0)]
    p = []
    if not (r1 < r0 < f1 < f0):
        p.append("order: uio1 rise %d, uio0 rise %d, uio1 fall %d, uio0 fall %d -- want "
                 "rise1 < rise0 < fall1 < fall0" % (r1, r0, f1, f0))
    for what, a, b in (("rise", r1, r0), ("fall", f1, f0)):
        if not POST_LAG <= b - a <= POST_LAG + SLACK:
            p.append("%s: uio0 %d cycles after uio1 (want %d..%d: the POST, then the pick)"
                     % (what, b - a, POST_LAG, POST_LAG + SLACK))
    return p


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("FLAGS -- POST / WAIT (ENABLE, consumes one) on the RTL")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_flags_")
    img = image()
    p = os.path.join(tmp, "flags_pw.hex")
    I.write_image(p, img)
    sim_run.scratch_image(GEN, p)
    vvp = os.path.join(tmp, "flags.vvp")
    build(vvp)
    first, flt, ended = edges(vvp, p)
    print("    edges: %s   %s" % ({"%s%d" % ("uio1" if k[0] else "uio0", k[1]): v
                                  for k, v in sorted(first.items())}, flt))
    pr = problems(first) + ([] if flt == "FLT cfg=0 ovr=0" else ["faults: " + flt]) \
        + ([] if ended else ["the bench did not finish"])
    print("    %s" % ("POST / WAIT in order, each wait released by its POST" if not pr
                      else "*** " + "; ".join(pr)))
    probs += pr
    sp = I.flag_word_problems(image(bad_index=True))
    ok = bool(sp) and not I.flag_word_problems(img)
    print("    pe_isa: a POST with pinb[3] set %s; the valid image %s"
          % ("refused" if sp else "*** ACCEPTED",
             "accepted" if not I.flag_word_problems(img) else "*** REFUSED"))
    if not ok:
        probs.append("pe_isa's flag index refusal")
    print("\n  OBSERVE (Wilson 11-19): two POSTs, two OBSERVEs, CMP_BRANCH on 2")
    po = os.path.join(tmp, "flags_obs.hex")
    oimg = observe_image()
    I.write_image(po, oimg)
    sim_run.scratch_image(GEN, po)
    ofirst, oflt, _oe = edges(vvp, po)
    ook = (PA, 1) in ofirst and (PB, 1) not in ofirst and oflt == "FLT cfg=0 ovr=0"
    print("    %s  (edges %s, %s)" % ("taken: the count is 2 after two looks" if ook
                                     else "*** NOT TAKEN", sorted(ofirst), oflt))
    if not ook:
        probs.append("OBSERVE: CMP_BRANCH on 2 not taken after two POSTs and two OBSERVEs")
    mv = os.path.join(tmp, "flags_M_OBSERVE_CONSUMES.vvp")
    build(mv, ["M_OBSERVE_CONSUMES"])
    mfirst, _f, _e = edges(mv, po)
    mred = (PA, 1) not in mfirst
    print("    must-fire M_OBSERVE_CONSUMES (OBSERVE consumes): %s"
          % ("RED (not taken: the second look saw 1)" if mred else "*** SURVIVED"))
    if not mred:
        probs.append("M_OBSERVE_CONSUMES survived")
    rp = I.observe_rx_problems(observe_image(rx_clobber=True))
    cp = I.observe_rx_problems(oimg)
    print("    RX liveness: an OBSERVE between a receive and its CMP %s; the clean image %s"
          % (("refused (%s)" % rp[0]) if rp else "*** ACCEPTED",
             "accepted" if not cp else "*** REFUSED: %s" % cp))
    if not rp or cp:
        probs.append("pe_isa's OBSERVE RX-liveness refusal")

    print("\n  the one-POST-per-cycle assertion (Wilson 11-19)")
    av = os.path.join(tmp, "flags_M_FLAG_POST2.vvp")
    build(av, ["M_FLAG_POST2"])
    r = run(sim_run.vvp([av, "+IMG=%s" % p, "+NCYC=%d" % NCYC], images=[p]))
    hit = [ln.strip() for ln in (r.stdout + r.stderr).splitlines()
           if ln.strip().startswith("*** ASSERT pe_engine FLAG1:")]
    print("    must-fire M_FLAG_POST2 (a POST counts two flags): %s"
          % (("RED: %s" % hit[0]) if hit else "*** SURVIVED"))
    if not hit:
        probs.append("M_FLAG_POST2 survived: the one-POST assertion did not fire")
    print("\n  must-fires")
    for d, what in MUTANTS:
        mv = os.path.join(tmp, "flags_%s.vvp" % d)
        build(mv, [d])
        mfirst, _f, _e = edges(mv, p)
        red = bool(problems(mfirst))
        print("    %-17s %-34s %s" % (d, what, "RED" if red else "*** SURVIVED"))
        if not red:
            probs.append("%s survived" % d)
    print()
    for x in probs:
        print("  *** %s" % x)
    print("=" * 78)
    print("  GATE flags: %s" % ("PASSED" if not probs else "FAILED"))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
