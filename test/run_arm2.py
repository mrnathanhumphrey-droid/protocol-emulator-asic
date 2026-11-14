#!/usr/bin/env python3
"""The TWO-PIN LEVEL ARM's gate (v2 primitive 3, bundle 1; Wilson 11-08).

THE ONE CLAIM: an ARM with `mod[0] = 1` releases its lane on the first cycle
BOTH `pin` and `pinb` sit at `level` -- exactly when the golden below says,
with exactly an edge ARM's latency from there to the pin -- never on one pin,
never on the wrong polarity, at once when the condition already holds, never
on the tied-low `uo_out` bank, and with ARM's timeout intact.

THE GOLDEN (cycles as `tb_arm2.v` counts them; drives land on falling edges):
  * a pin driven on cycle c is visible to the engine (`uio_q1`) on c + L,
    L = 2 (q0, q1), the edge ARM's own stage;
  * fire = max(armed, max over the two pins of (drive + L)) -- the level holds
    from then, so a condition present at arming fires AT arming;
  * out = fire + K, K = the edge ARM's fire-to-pin latency measured on the
    control scenario in the same build (same program shape, edge ARM): the
    claim is that the level ARM costs exactly what the edge ARM costs.

Bench: test/tb_arm2.v, one scenario per run. Images built here from pe_isa.
  A1  the scenarios, baseline: every recorded cycle equals the golden's.
  A2  pe_isa refuses the bad encodings (mod[1], edge pinb, uo bank, same pin).
  A3  the must-fires: ONEPIN / EDGE / POL / UNGUARDED each turn A1 red.

POSITIVE TOKEN: `GATE arm2: PASSED`.
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
for _p in (HERE, os.path.join(ROOT, "model")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402

BENCH = "test/tb_arm2.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_arm2"
L = 2                 # drive (falling edge, cycle c) -> uio_q1 -> seen on c + 2
D1 = 12               # the program's LEVEL delays (tb_edge's shape)
PIN_A, PIN_B = 0, 1   # uio[0], uio[1]: the bench's peer pins
UO_PIN = I.UO1        # a uo_out pin: the guard image's pinb


def image(kind, timeout, level=0):
    """lane 0: ARM (two-pin level, or edge for the control), LEVEL UO0 1,
    LEVEL UO0 0, REARM; lanes 1-4 parked. tb_edge's build_edge, with the ARM
    swapped -- the same shape is what makes K comparable."""
    if kind == "edge":
        arm = I.act(I.OP_ARM, PIN_A, 0, timeout)
    elif kind == "guard":
        arm = I.act(I.OP_ARM, PIN_A, level, timeout, pinb=UO_PIN, mod=I.ARM_MOD_LEVEL2)
    else:
        arm = I.act_arm2(PIN_A, PIN_B, level, timeout)
    l0 = I.ACT_BASE
    prog = [arm, I.act(I.OP_LEVEL, I.UO0, 1, D1), I.act(I.OP_LEVEL, I.UO0, 0, D1),
            I.act(I.OP_REARM, 0, 1, D1)]
    lp = l0 + 4 * I.ACT_BYTES
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    headers = [I.hdr(I.UO0, I.UO0, 1, D1, 0, 2 * D1, 3 * D1, l0)]
    for n in range(1, I.N_LANES):
        headers.append(I.hdr(n + 1, n + 1, 0, 500, 0, 200, 240, lp))
    return I.join_image(headers, prog)


IMAGES = {
    "lvl0_to200": lambda: image("level", 200, 0),
    "lvl0_noto": lambda: image("level", 0, 0),
    "lvl1_noto": lambda: image("level", 0, 1),
    "guard_noto": lambda: image("guard", 0, 0),
    "edge_to200": lambda: image("edge", 200),
}

#: name, image, IDLE, PHA, PHB, NCYC, expectation kind
SCEN = [
    ("ctl_edge", "edge_to200", 1, 50, -1, 300, "edge"),
    ("both_same", "lvl0_to200", 1, 20, 20, 300, "fire"),
    ("b_after_a", "lvl0_to200", 1, 50, 57, 300, "fire"),
    ("b_before_a", "lvl0_to200", 1, 80, 71, 300, "fire"),
    ("b_late", "lvl0_to200", 1, 110, 133, 300, "fire"),
    ("one_pin_long", "lvl0_noto", 1, 30, 330, 500, "fire"),
    ("already_se0", "lvl0_noto", 0, -1, -1, 300, "fire"),
    ("both_high", "lvl1_noto", 0, 30, 45, 300, "fire"),
    ("uo_guard", "guard_noto", 1, 30, -1, 600, "none"),
    ("timeout", "lvl0_to200", 1, 30, -1, 700, "timeout"),
]


#: ⭐ THE COVERAGE SWEEP'S tb_arm2 ARMS (Wilson 11-13): the gate's ten scenarios on
#: its own five images, so the two-pin level ARM is reached. Reach only.
COV_DIR = "probe_cov_arm2"


def coverage_arms():
    """[(label, plusargs)] for test/benchset.py's tb_arm2; images under COV_DIR."""
    os.makedirs(os.path.join(ROOT, COV_DIR), exist_ok=True)
    for k, f in IMAGES.items():
        I.write_image(os.path.join(ROOT, COV_DIR, "%s.hex" % k), f())
    # the `none` / `timeout` scenarios retire nothing by design: declared quiescent
    # +PHA_ABS=-1: the absolute flip (run_arm2 A4's race sweep) is OFF here, stated
    return [(name, ["+IMG=%s/%s.hex" % (COV_DIR, im), "+IDLE=%d" % idle, "+PHA=%d" % pha,
                    "+PHB=%d" % phb, "+NCYC=%d" % ncyc, "+PHA_ABS=-1"]
             + (["+QUIESCENT"] if kind in ("none", "timeout") else []))
            for name, im, idle, pha, phb, ncyc, kind in SCEN]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_arm2"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def sim(vvp, img, idle, pha, phb, ncyc, quiescent=False):
    args = [vvp, "+IMG=%s" % img, "+IDLE=%d" % idle, "+PHA=%d" % pha,
            "+PHB=%d" % phb, "+NCYC=%d" % ncyc]
    # the `none` / `timeout` scenarios retire nothing BY DESIGN: declared quiescent
    # here as in coverage_arms (Wilson 11-14 inventory: the gate path lacked it)
    if quiescent:
        args.append("+QUIESCENT")
    r = run(sim_run.vvp(args, images=[img]))
    m = re.search(r"^ARM2 (.*)$", r.stdout + r.stderr, re.M)
    if not m:
        return None, (r.stdout + r.stderr)[-300:]
    return {k: int(v) for k, v in (kv.split("=") for kv in m.group(1).split())}, ""


def golden(kind, rec, k):
    """-> the expected record fields for one scenario (see the module doc)."""
    if kind == "edge":
        f = rec["ta"] + L
        return {"fire": f, "out": None if k is None else f + k}
    if kind in ("none", "timeout"):
        e = {"fire": -1, "out": -1}
        if kind == "timeout":
            e.update(live=0, to=1)
        return e
    drives = [t + L for t in (rec["ta"], rec["tb"]) if t >= 0]
    f = max([rec["armed"]] + drives)
    return {"fire": f, "out": f + k}


def scenario_problems(name, kind, rec, k):
    """[problem] for ONE scenario's record against the golden -- THE judge every
    verdict goes through (baseline clean, each mutant red)."""
    if rec is None:
        return ["%s: no ARM2 line" % name]
    out = []
    if rec["armed"] < 0 and kind != "none":
        out.append("%s: the lane never armed" % name)
    for f, want in golden(kind, rec, k).items():
        if want is not None and rec[f] != want:
            out.append("%s: %s = %d, golden %d" % (name, f, rec[f], want))
    if rec["oe"] or rec["x"]:
        out.append("%s: the engine drove uio (%d cycles) or the bus went X (%d)"
                   % (name, rec["oe"], rec["x"]))
    return out


def run_all(vvp, tmp):
    """-> (problems, records, K) for every scenario on one build."""
    hexes = {}
    for nm, fn in IMAGES.items():
        p = os.path.join(tmp, "arm2_%s.hex" % nm)
        I.write_image(p, fn())
        sim_run.scratch_image(GEN, p)
        hexes[nm] = p
    probs, recs, k = [], {}, None
    for name, im, idle, pha, phb, ncyc, kind in SCEN:
        rec, err = sim(vvp, hexes[im], idle, pha, phb, ncyc,
                       quiescent=kind in ("none", "timeout"))
        recs[name] = rec
        if kind == "edge" and rec is not None and rec["fire"] >= 0 and rec["out"] >= 0:
            k = rec["out"] - rec["fire"]
        if kind != "edge" and k is None:
            probs.append("%s: no K -- the edge control did not fire" % name)
            continue
        probs += scenario_problems(name, kind, rec, k) if rec else ["%s: %s" % (name, err)]
    return probs, recs, k


def ft_race_image():
    """lane 0: ARM(fall, timeout 200, FALLTHROUGH) -> REARM (the timeout path,
    PC+1, loops to the ARM) -> LEVEL UO0 1 (the EDGE path, PC+2) -> LEVEL UO0 0
    -> REARM. A refill filed STALE into PC+2's slot (the scan-race, 11-14) puts
    the timeout path's successor -- the ARM itself -- where the LEVEL belongs,
    and uo_out[0] never rises."""
    l0 = I.ACT_BASE
    prog = [I.act_arm(PIN_A, 0, 200, ft=True), I.act(I.OP_REARM, 0, 1, D1),
            I.act(I.OP_LEVEL, I.UO0, 1, D1), I.act(I.OP_LEVEL, I.UO0, 0, D1),
            I.act(I.OP_REARM, 0, 1, D1)]
    lp = l0 + len(prog) * I.ACT_BYTES
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    headers = [I.hdr(I.UO0, I.UO0, 1, D1, 0, 2 * D1, 3 * D1, l0)]
    for k in range(1, I.N_LANES):
        headers.append(I.hdr(k + 1, k + 1, 0, 500, 0, 200, 240, lp))
    return I.join_image(headers, prog)


#: the flip, swept from 4 cycles before arming to 11 after (absolute run cycle
#: = armed + d - 4): the race needs the captured edge on the scan's selecting cycle
FT_RACE_PHASES = range(0, 16)


def ft_race(vvp, path):
    """[flip cycle] at which the FT edge path did NOT run its PC+2 word. The
    flip is ABSOLUTE (+PHA_ABS), swept around the arming cycle: the scan selects
    the lane's emptied spare the cycle AFTER it arms, and the 2-flop input
    synchroniser means the pin must move ~2 cycles before that."""
    base, _e = sim(vvp, path, 1, -1, -1, 300)
    t0 = base["armed"] if base else 0

    def one(flip):
        args = [vvp, "+IMG=%s" % path, "+IDLE=1", "+PHA=-1", "+PHB=-1", "+NCYC=300",
                "+PHA_ABS=%d" % flip]
        r = run(sim_run.vvp(args, images=[path]))
        m = re.search(r"^ARM2 (.*)$", r.stdout + r.stderr, re.M)
        return {k: int(v) for k, v in (kv.split("=") for kv in m.group(1).split())} if m else None

    # the REFERENCE: an edge well after the spare refill has landed -- the
    # captured edge's latency to the PC+2 word's pin, with nothing racing
    import proof_constants as PC
    kpc = PC.load()
    late = kpc["head_slack"] + kpc["br1_budget"]
    ref = one(t0 + 30)
    k_ref = (ref["out"] - ref["fire"]) if ref and ref["fire"] >= 0 and ref["out"] >= 0 else None
    bad = []
    for d in FT_RACE_PHASES:
        flip = t0 + d - 4
        rec = one(flip)
        if rec is None or rec["fire"] < 0:
            continue                         # no edge captured: nothing to judge
        # ⛔ the PC+2 word may be LATE -- fetched fresh when the edge beats the
        # spare refill (measured 16..19 against the reference's 16), which
        # agent 2's bound prices at head_slack + br1_budget past the reference
        # -- but a STALE refill (the ARM refetched into PC+2's slot) re-arms
        # the lane and the LEVEL runs only after its timeout falls through
        # (measured 217) or never
        if k_ref is None or rec["out"] < 0 or rec["out"] - rec["fire"] > k_ref + late:
            bad.append(flip)
    return bad


#: the refusals pe_isa must make (A2): name -> an ARM word that must be refused
BAD = {
    "mod1_reserved": I.act(I.OP_ARM, PIN_A, 0, 0, pinb=PIN_B, mod=3),
    "edge_pinb_set": I.act(I.OP_ARM, PIN_A, 0, 0, pinb=PIN_B, mod=0),
    "uo_pin": I.act(I.OP_ARM, I.UO0, 0, 0, pinb=PIN_B, mod=I.ARM_MOD_LEVEL2),
    "uo_pinb": I.act(I.OP_ARM, PIN_A, 0, 0, pinb=UO_PIN, mod=I.ARM_MOD_LEVEL2),
    "same_pin": I.act(I.OP_ARM, PIN_A, 0, 0, pinb=PIN_A, mod=I.ARM_MOD_LEVEL2),
    # the ARM/dispatcher batch (Wilson 11-14): each illegal modifier combination
    "half_level2": I.act(I.OP_ARM, PIN_A, 0, 0, pinb=PIN_B, mod=I.ARM_MOD_LEVEL2,
                         count=I.ARM_CNT_HALF),
    "qual_level2": I.act(I.OP_ARM, PIN_A, 0, 0, pinb=PIN_B, mod=I.ARM_MOD_LEVEL2,
                         count=I.ARM_CNT_QUAL),
    "half_ft": I.act_arm(PIN_A, 0, 100, half=True, ft=True),
    "ft_no_timeout": I.act_arm(PIN_A, 0, 0, ft=True),
    "q_reserved": I.act(I.OP_ARM, PIN_A, 0, 0, q=1),
    "count2_reserved": I.act(I.OP_ARM, PIN_A, 0, 0, count=I.ARM_CNT_RESERVED),
}


def lane_image(prog, lane):
    """`prog` on `lane`, every other lane parked -- for the refusals that need
    the lane (QUAL off the USB lane; an FT ARM's edge path)."""
    l0 = I.ACT_BASE
    lp = l0 + len(prog) * I.ACT_BYTES
    body = list(prog) + [I.act(I.OP_REARM, 0, 0, 500)]
    headers = []
    for n in range(I.N_LANES):
        if n == lane:
            headers.append(I.hdr(I.UO0, I.UO0, 1, D1, 0, 2 * D1, 3 * D1, l0))
        else:
            headers.append(I.hdr(n + 1, n + 1, 0, 500, 0, 200, 240, lp))
    return I.join_image(headers, body)


_LOOP = I.act(I.OP_REARM, 0, 1, D1)
#: name -> (lane, program, refused?) -- the lane-dependent 11-14 refusals and
#: their controls
LANE_CASES = {
    "qual_off_usb_lane": (1, [I.act_arm(PIN_A, 1, 0, qual=True), _LOOP], True),
    "qual_on_usb_lane": (I.USB_LANE, [I.act_arm(PIN_A, 1, 0, qual=True), _LOOP], False),
    "ft_edge_shiftin": (0, [I.act_arm(PIN_A, 0, 100, ft=True), _LOOP,
                            I.act(I.OP_SHIFTIN, PIN_A, 0, D1, count=8), _LOOP], True),
    "ft_edge_arm": (0, [I.act_arm(PIN_A, 0, 100, ft=True), _LOOP,
                        I.act(I.OP_ARM, PIN_A, 1, 0), _LOOP], False),
}

#: mutant -> (what it breaks, the scenario that must go red)
MUTANTS = [
    ("M_ARM2_ONEPIN", "pinb ignored: fires on one pin", "one_pin_long"),
    ("M_ARM2_EDGE", "needs an edge: misses an SE0 already present", "already_se0"),
    ("M_ARM2_POL", "polarity swapped", "both_same"),
    ("M_ARM2_UNGUARDED", "no uio-bank guard: the tied-low uo pin fires", "uo_guard"),
]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("ARM, two-pin level mode (v2 primitive 3, bundle 1)")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_arm2_")
    vvp = os.path.join(tmp, "arm2.vvp")
    build(vvp)

    print("\n  A1 baseline: every recorded cycle against the golden")
    p, recs, k = run_all(vvp, tmp)
    print("    K (edge ARM fire -> pin, the control) = %s" % k)
    print("    %-14s %6s %6s %6s %6s %6s %5s %3s" % ("scenario", "armed", "ta", "tb", "fire", "out", "live", "to"))
    for name, *_ in SCEN:
        r = recs.get(name) or {}
        print("    %-14s %6s %6s %6s %6s %6s %5s %3s" % (name, r.get("armed"), r.get("ta"), r.get("tb"),
              r.get("fire"), r.get("out"), r.get("live"), r.get("to")))
    for x in p:
        print("    *** %s" % x)
    probs += p

    print("\n  A2 pe_isa refusals")
    good = [n for n in IMAGES if n != "guard_noto"]
    for n in good:
        pr = I.arm_problems(IMAGES[n]())
        if pr:
            probs.append("valid image %s refused: %s" % (n, pr))
    for n, word in BAD.items():
        img = bytearray(image("level", 0))
        img[I.ACT_BASE:I.ACT_BASE + I.ACT_BYTES] = word
        pr = I.arm_problems(bytes(img))
        print("    %-14s %s" % (n, "refused" if pr else "*** ACCEPTED"))
        if not pr:
            probs.append("pe_isa accepted %s" % n)
    for n, (lane, prog, want) in LANE_CASES.items():
        img = lane_image(prog, lane)
        pr = I.arm_problems(img) + I.arm_lane_problems(img)
        ok = bool(pr) == want
        print("    %-18s %s%s" % (n, "refused" if pr else "accepted",
                                  "" if ok else "  *** WRONG"))
        if not ok:
            probs.append("lane case %s: %s" % (n, pr or "accepted"))
    if not I.arm_problems(IMAGES["guard_noto"]()):
        probs.append("pe_isa accepted the guard image (pinb on the uo bank)")

    # A4: the FT edge never meets a stale refill (the scan-race, Wilson 11-14)
    print("\n  A4 the FT edge vs a refill selected that cycle (edge swept %d..%d)"
          % (FT_RACE_PHASES[0], FT_RACE_PHASES[-1]))
    frp = os.path.join(tmp, "arm2_ft_race.hex")
    I.write_image(frp, ft_race_image())
    sim_run.scratch_image(GEN, frp)
    bad = ft_race(vvp, frp)
    print("    fixed RTL: PC+2 ran at every phase %s" % ("ok" if not bad else "*** NOT at %s" % bad))
    if bad:
        probs.append("FT edge path skipped its PC+2 word at phase(s) %s" % bad)
    mv = os.path.join(tmp, "arm2_M_FT_SCAN_RACE.vvp")
    build(mv, ["M_FT_SCAN_RACE"])
    mbad = ft_race(mv, frp)
    print("    must-fire M_FT_SCAN_RACE (the old scan): %s"
          % ("RED at phase(s) %s" % mbad if mbad else "*** SURVIVED"))
    if not mbad:
        probs.append("M_FT_SCAN_RACE survived the swept FT edge")

    print("\n  A3 must-fires")
    for d, what, scen in MUTANTS:
        mv = os.path.join(tmp, "arm2_%s.vvp" % d)
        try:
            build(mv, [d])
        except RuntimeError as exc:
            probs.append("%s: %s" % (d, exc))
            continue
        mp, _r, _k = run_all(mv, tmp)
        hit = [x for x in mp if x.startswith(scen + ":")]
        print("    %-18s %-46s %s" % (d, what, ("RED on %s" % scen) if hit else "*** SURVIVED on %s" % scen))
        if not hit:
            probs.append("%s survived (%s)" % (d, scen))

    print()
    if probs:
        print("  GATE arm2: FAILED (%d)" % len(probs))
        return 1
    print("  GATE arm2: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
