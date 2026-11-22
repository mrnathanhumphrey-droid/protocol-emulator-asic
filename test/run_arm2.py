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
  A5  the ARM features on lanes 0-4: golden per lane + symmetry with lane 0
      (the FT edge path's out by the K..K+1 bound, Wilson 11-19).
  A5-FT  the FT edge path swept over every prr phase on every lane; must-fires:
      a planted K+2 and a flattened (vacuous) lane each turn it red.
  A4  the FT edge swept against the lane's refills; must-fires M_FT_SCAN_RACE (the
      scan selects a flushing lane) and M_FT_NO_PKILL (K5: the in-flight refill is
      not killed) each turn it red.

POSITIVE TOKEN: `GATE arm2: PASSED`.
"""

from __future__ import annotations

import json
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
        _cov_write(os.path.join(ROOT, COV_DIR, "%s.hex" % k), f())
    # the `none` / `timeout` scenarios retire nothing by design: declared quiescent
    # +PHA_ABS=-1: the absolute flip (run_arm2 A4's race sweep) is OFF here, stated
    arms = [(name, ["+IMG=%s/%s.hex" % (COV_DIR, im), "+IDLE=%d" % idle, "+PHA=%d" % pha,
                    "+PHB=%d" % phb, "+NCYC=%d" % ncyc, "+PHA_ABS=-1"]
             + (["+QUIESCENT"] if kind in ("none", "timeout") else []))
            for name, im, idle, pha, phb, ncyc, kind in SCEN]
    # ⭐ (11-15) THE FT EDGE AGAINST THE LANE'S OWN IN-FLIGHT REFILL (pe_engine `pkill`:
    # set at the edge when this lane's refill is in P_REQ / P_WAIT, the refill then
    # DROPPED at P_CAP). A4 judges this race (ft_race) but only on absolute flips, which
    # coverage never ran, so both points read uncovered after 9c0df0c. The edge is
    # placed RELATIVE to the arming cycle (+PHA), no stored run cycle: PHA 1 measured to
    # set pkill and drop at P_CAP (iverilog probe, 11-15); 2-3 keep the window if a
    # cycle moves. Reach only -- A4 is the judge.
    _cov_write(os.path.join(ROOT, COV_DIR, "ft_race.hex"), ft_race_image())
    arms += [("ft_pkill_pha%d" % pha, ["+IMG=%s/ft_race.hex" % COV_DIR, "+IDLE=1",
                                       "+PHA=%d" % pha, "+PHB=-1", "+NCYC=300",
                                       "+PHA_ABS=-1"])
             for pha in (1, 2, 3)]
    # ⭐ A5 (11-18): every lane scenario on every lane; A5 is the judge
    for lane in range(I.N_LANES):
        for pn in lane_progs(*LANE_PINS[lane]):
            _cov_write(os.path.join(ROOT, COV_DIR, "L%d_%s.hex" % (lane, pn)), lane_scen_image(pn, lane))
        for name, pn, idle, pha, phb, pha2, ncyc, kind in LANE_SCEN:
            arms.append(("%s_l%d" % (name, lane), ["+IMG=%s/L%d_%s.hex" % (COV_DIR, lane, pn)]
                         + lane_plusargs(lane, idle, pha, phb, pha2, ncyc, kind)))
    return arms


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

# ---------------------------------------------------------------------------
# ⭐ A5 (11-18, Wilson's toggle ruling, E1-E4): THE ARM FEATURES ON EVERY LANE.
# The 11-14 modifiers and the two-pin level ARM were swept on lane 0 only, so
# their per-lane state on lanes 1-4 (l_arm2, l_armpinb, l_armhalf, l_armft,
# arm_half, ft_flush, g_arm[n].*) read uncovered. Each scenario runs the SAME
# program on each lane (lane_image: that lane live, the rest parked), on that
# lane's own peer pins, and is judged two ways:
#   GOLDEN (edge / level kinds): A1's golden on that lane -- fire = max(armed,
#     drives + L), out = fire + K, K from THAT lane's own edge control -- so an
#     all-lane fault (the A3 mutants) turns lanes 1-4 red as well as lane 0;
#   SYMMETRY (every kind, HALF / FT / the sequence included): each field
#     relative to arming equals lane 0's -- a fault on one lane shows here.
# ---------------------------------------------------------------------------
#: (pin, pinb) per live lane: lane_image parks lane n on uio n+1, so the peer pins
#: avoid the parked lanes' pins -- the live lane's own n+1, and uio 7 as pinb (7 sets
#: pinb's bits 0-2; lane 0's pinb >= 4 was never swept)
LANE_PINS = {0: (0, 7), 1: (2, 7), 2: (3, 7), 3: (4, 7), 4: (5, 7)}
_LV1, _LV0 = I.act(I.OP_LEVEL, I.UO0, 1, D1), I.act(I.OP_LEVEL, I.UO0, 0, D1)


def lane_progs(pa, pb):
    """name -> the lane program (lane_image appends the parked tail)"""
    t = lambda arm: [arm, _LV1, _LV0, _LOOP]
    return {
        "edge": t(I.act(I.OP_ARM, pa, 0, 200)),
        "lvl0": t(I.act_arm2(pa, pb, 0, 200)),
        "lvl1": t(I.act_arm2(pa, pb, 1, 0)),
        # A1's guard on this lane: pinb on the tied-low uo bank never fires (pe_isa
        # refuses it; the silicon's arm2_real guard is what is tested)
        "guard": t(I.act(I.OP_ARM, pa, 0, 0, pinb=UO_PIN, mod=I.ARM_MOD_LEVEL2)),
        "half": t(I.act_arm(pa, 0, 200, half=True)),
        # FT: timeout -> PC+1 (loops back to the ARM), edge -> PC+2 (the LEVELs)
        "ft": [I.act_arm(pa, 0, 200, ft=True), _LOOP, _LV1, _LV0, _LOOP],
        # the ARM SEQUENCE: each modifier's per-lane flops loaded AND replaced in one
        # run -- two-pin (fires on PHA + PHB) -> HALF rise (fires on PHA2) -> FT fall
        # (times out, falls through) -> a plain ARM on pinb's rise that never comes
        "seq": [I.act_arm2(pa, pb, 0, 0), _LV1, _LV0, I.act_arm(pa, 1, 0, half=True), _LV1, _LV0,
                I.act_arm(pa, 0, 60, ft=True), I.act(I.OP_ARM, pb, 1, 0), _LOOP],
    }


#: name, program, IDLE, PHA, PHB, PHA2, NCYC, kind (A1's kinds; "rel" = symmetry only)
LANE_SCEN = [
    ("L_edge", "edge", 1, 50, -1, -1, 300, "edge"),
    ("L_lvl0", "lvl0", 1, 50, 57, -1, 300, "fire"),
    ("L_lvl1", "lvl1", 0, 30, 45, -1, 300, "fire"),
    ("L_lvl0_to", "lvl0", 1, 30, -1, -1, 700, "timeout"),
    ("L_guard", "guard", 1, 30, -1, -1, 600, "none"),
    ("L_half", "half", 1, 50, -1, -1, 300, "rel"),
    ("L_ft_edge", "ft", 1, 50, -1, -1, 300, "rel"),
    ("L_ft_to", "ft", 1, -1, -1, -1, 700, "rel"),
    ("L_seq", "seq", 1, 20, 20, 100, 500, "rel"),
]
_REL = ("ta", "tb", "fire", "out")

# ⭐ THE FT EDGE PATH IS JUDGED BY A BOUND, NOT BY SYMMETRY (Wilson 11-18 / 11-19).
# After the FT edge flushes both slots the HEAD refills first (the EDF-first branch),
# then the SPARE waits for the round-robin pointer `prr`, which restarts at 0 and
# steps one lane per idle cycle; when (lane - prr phase at the edge) mod 5 falls in a
# two-lane window the spare lands after the next dispatch would have gone, and that
# dispatch waits ONE cycle. Traced 11-18: every lane takes the +1 at some phase,
# period 5, two adjacent lanes at a time; the plain-edge control is K everywhere.
# So out - fire on the FT edge path is K or K + 1 -- `FT_LATE` -- on any lane, and
# exact symmetry with lane 0 is the check for every OTHER field and scenario.
# Why not an exact golden modelling prr (ruling (a)): the buffer RTL issues at
# capture, so the scan should not be involved after an FT flush at all.
# ⛔ THE PREDICTION FOR THE BUFFER RTL (an exact golden, the RTL batch's checks):
#    out - fire = K on EVERY lane at EVERY phase -- FT_LATE goes to 0 there.
FT_LATE = 1
#: the A5-FT sweep's edge drives (cycles after arming): six consecutive phases, so
#: each lane meets every prr phase (period 5) at least once -- 30 runs
FT_SWEEP_PHA = range(50, 56)


def ft_out_problem(tag, rec, k):
    """'' or the problem: K <= out - fire <= K + FT_LATE on the FT edge path"""
    if k is None:
        return "%s: no K -- the lane's edge control did not fire" % tag
    if rec["fire"] < 0 or rec["out"] < 0:
        return "%s: fire %d out %d -- the FT edge path did not run" % (tag, rec["fire"], rec["out"])
    d = rec["out"] - rec["fire"]
    if not k <= d <= k + FT_LATE:
        return "%s: out - fire = %d, outside K..K+%d = %d..%d" % (tag, d, FT_LATE, k, k + FT_LATE)
    return ""


def lane_scen_image(prog_name, lane):
    pa, pb = LANE_PINS[lane]
    return lane_image(lane_progs(pa, pb)[prog_name], lane)


# ⭐⭐ T_EXT FOR THE `seq` IMAGES, GENERATED FROM THE BENCH (Wilson 11-19). Each
# L{lane}_seq.hex lane is EDGE-PACED (three delay-0 ARMs), so program_a2 needs its
# peer's period -- and the peer is THIS testbench. The claim is READ from what it
# drives, never typed: tb_arm2 flips pin A at arming + PHA and pin B at arming + PHB
# (both falls release the ARM2), then pin A again at arming + PHA2 (the HALF rise),
# so the spacing between the two RELEASES is PHA2 - max(PHA, PHB) cycles. The A and
# B falls are one release, and arming is not a peer edge. IN CYCLES, NOT Hz: the
# bench drives simulation cycles, which do not move with the target clock.
# Written to T_EXT_BENCH by `python test/run_arm2.py --write-t-ext`; program_a2 reads
# it, and gate_admissible_images re-derives it here and reds any mismatch -- so a
# bench phase changed without regenerating is caught.
T_EXT_BENCH = os.path.join(ROOT, "model", "a2", "t_ext_bench.json")


def _cite(rel, needle):
    """'path:line' of the first line of `rel` holding `needle` -- read, not typed."""
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        for i, ln in enumerate(fh, 1):
            if needle in ln:
                return "%s:%d" % (rel, i)
    raise RuntimeError("bench_t_ext: %r is not in %s -- the citation moved" % (needle, rel))


def bench_t_ext(scen=None):
    """{sha of each L{lane}_seq image: its T_ext entry}, from `scen` (LANE_SCEN, the
    tuples main() passes to the bench)."""
    import hashlib
    scen = LANE_SCEN if scen is None else scen
    rows = [s for s in scen if s[1] == "seq"]
    if len(rows) != 1:
        raise RuntimeError("bench_t_ext: %d `seq` scenarios, want 1" % len(rows))
    name, pn, _idle, pha, phb, pha2, _ncyc, _kind = rows[0]
    t = pha2 - max(pha, phb)
    if min(pha, phb, pha2) < 0 or t <= 0:
        raise RuntimeError("bench_t_ext: %s's phases (%d, %d, %d) give no release spacing"
                           % (name, pha, phb, pha2))
    src = [_cite("test/run_arm2.py", '("%s",' % name),
           _cite("test/tb_arm2.v", "cyc == t_armed + pha)"),
           _cite("test/tb_arm2.v", "cyc == t_armed + phb)"),
           _cite("test/tb_arm2.v", "cyc == t_armed + pha2)")]
    out = {}
    for lane in range(I.N_LANES):
        img = I.full_store(bytes(lane_scen_image(pn, lane)))
        out[hashlib.sha256(img).hexdigest()] = {
            "image": "%s/L%d_%s.hex" % (COV_DIR, lane, pn),
            "lanes": {str(lane): t},
            "unit": "cycles",
            "label": "read (bench)",
            "why": "the testbench is the peer: releases at arming + max(PHA %d, PHB %d) "
                   "and arming + PHA2 %d, %d cycles apart" % (pha, phb, pha2, t),
            "source": src,
        }
    return out


def write_bench_t_ext(path=T_EXT_BENCH):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(bench_t_ext(), fh, indent=1, sort_keys=True)
        fh.write("\n")


def lane_plusargs(lane, idle, pha, phb, pha2, ncyc, kind):
    pa, pb = LANE_PINS[lane]
    return (["+IDLE=%d" % idle, "+PHA=%d" % pha, "+PHB=%d" % phb, "+PHA2=%d" % pha2,
             "+NCYC=%d" % ncyc, "+LANE=%d" % lane, "+PINA=%d" % pa, "+PINB=%d" % pb,
             "+PHA_ABS=-1"] + (["+QUIESCENT"] if kind in ("none", "timeout") else []))


def lane_records(vvp, tmp, tag=""):
    """-> {(scenario, lane): record or None}, on one build"""
    recs = {}
    for lane in range(I.N_LANES):
        for name, pn, idle, pha, phb, pha2, ncyc, kind in LANE_SCEN:
            p = os.path.join(tmp, "arm2_L%s_%s_%d.hex" % (tag, pn, lane))
            if not os.path.isfile(p):
                I.write_image(p, lane_scen_image(pn, lane))
                sim_run.scratch_image(GEN, p)
            r = run(sim_run.vvp([vvp, "+IMG=%s" % p]
                                + lane_plusargs(lane, idle, pha, phb, pha2, ncyc, kind), images=[p]))
            m = re.search(r"^ARM2 (.*)$", r.stdout + r.stderr, re.M)
            recs[(name, lane)] = ({k: int(v) for k, v in (kv.split("=") for kv in m.group(1).split())}
                                  if m else None)
    return recs


def lane_problems(recs):
    """[problem]: A1's golden per lane (K from that lane's edge control) and the
    symmetry of every scenario against lane 0 -- the judge A5's verdicts go through."""
    out = []
    for lane in range(I.N_LANES):
        e = recs.get(("L_edge", lane))
        k = (e["out"] - e["fire"]) if e and e["fire"] >= 0 and e["out"] >= 0 else None
        for name, _pn, _i, _a, _b, _a2, _n, kind in LANE_SCEN:
            rec = recs.get((name, lane))
            tag = "%s@lane%d" % (name, lane)
            if rec is None:
                out.append("%s: no ARM2 line" % tag)
                continue
            if kind != "rel":
                if k is None and kind != "edge":
                    out.append("%s: no K -- lane %d's edge control did not fire" % (tag, lane))
                else:
                    out += scenario_problems(tag, kind, rec, k)
            ft = name == "L_ft_edge"
            if ft:
                x = ft_out_problem(tag, rec, k)
                if x:
                    out.append(x)
            ref = recs.get((name, 0))
            if lane and ref:
                rel = lambda r, f: r[f] - r["armed"] if r[f] >= 0 and r["armed"] >= 0 else r[f]
                for f in _REL:
                    if ft and f == "out":
                        continue          # the FT edge's out: the bound above, not symmetry
                    if rel(rec, f) != rel(ref, f):
                        out.append("%s: %s - armed = %d, lane 0 gives %d" % (tag, f, rel(rec, f), rel(ref, f)))
                for f in ("live", "to", "oe", "x"):
                    if rec[f] != ref[f]:
                        out.append("%s: %s = %d, lane 0 gives %d" % (tag, f, rec[f], ref[f]))
            if kind == "rel" and rec["oe"] + rec["x"]:
                out.append("%s: the engine drove uio or the bus went X" % tag)
    return out


def ft_sweep(vvp, tmp):
    """-> {(pha, lane): record or None}: A5's FT edge scenario at every FT_SWEEP_PHA"""
    recs = {}
    for lane in range(I.N_LANES):
        p = os.path.join(tmp, "arm2_L_ft_%d.hex" % lane)
        if not os.path.isfile(p):
            I.write_image(p, lane_scen_image("ft", lane))
            sim_run.scratch_image(GEN, p)
        for pha in FT_SWEEP_PHA:
            r = run(sim_run.vvp([vvp, "+IMG=%s" % p]
                                + lane_plusargs(lane, 1, pha, -1, -1, 300, "rel"), images=[p]))
            m = re.search(r"^ARM2 (.*)$", r.stdout + r.stderr, re.M)
            recs[(pha, lane)] = ({k: int(v) for k, v in (kv.split("=") for kv in m.group(1).split())}
                                 if m else None)
    return recs


def ft_sweep_problems(sweep, ks):
    """[problem]: every cell inside the bound, the fire on the golden (drive + L), and
    NOT VACUOUS -- each lane reaches both K and K + FT_LATE somewhere in the sweep"""
    out = []
    for lane in range(I.N_LANES):
        seen = set()
        for pha in FT_SWEEP_PHA:
            tag = "A5-FT pha %d@lane%d" % (pha, lane)
            rec = sweep.get((pha, lane))
            if rec is None:
                out.append("%s: no ARM2 line" % tag)
                continue
            if rec["ta"] < 0 or rec["fire"] != rec["ta"] + L:
                out.append("%s: fire %d, the golden gives drive %d + %d" % (tag, rec["fire"], rec["ta"], L))
            x = ft_out_problem(tag, rec, ks.get(lane))
            if x:
                out.append(x)
            elif ks.get(lane) is not None:
                seen.add(rec["out"] - rec["fire"] - ks[lane])
            if rec["oe"] + rec["x"]:
                out.append("%s: the engine drove uio or the bus went X" % tag)
        for late in range(FT_LATE + 1):
            if late not in seen:
                out.append("A5-FT lane %d: out - fire = K+%d never seen in the sweep -- the bound "
                           "is not exercised (vacuous)" % (lane, late))
    return out


def ft_sweep_plants(sweep, ks):
    """the sweep judge's must-fires, on the measured records: per lane, (1) one cell
    planted at K + 2 must turn THAT lane red; (2) every K+1 cell flattened to K must
    turn the non-vacuity check red on that lane. -> [(plant, lane, red?)]"""
    res = []
    for lane in range(I.N_LANES):
        cells = [pha for pha in FT_SWEEP_PHA if sweep.get((pha, lane))]
        if not cells or ks.get(lane) is None:
            res.append(("+2", lane, False))
            res.append(("flat", lane, False))
            continue
        s = dict(sweep)
        r = dict(s[(cells[0], lane)])
        r["out"] = r["fire"] + ks[lane] + FT_LATE + 1
        s[(cells[0], lane)] = r
        res.append(("+2", lane, any(("@lane%d:" % lane) in x for x in ft_sweep_problems(s, ks))))
        s = dict(sweep)
        for pha in cells:
            r = dict(s[(pha, lane)])
            r["out"] = r["fire"] + ks[lane]
            s[(pha, lane)] = r
        res.append(("flat", lane, any(x.startswith("A5-FT lane %d:" % lane) for x in ft_sweep_problems(s, ks))))
    return res


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

    print("\n  A5 the ARM features on every lane (golden per lane + symmetry with lane 0)")
    for lane in range(I.N_LANES):
        for pn in lane_progs(*LANE_PINS[lane]):
            img = lane_scen_image(pn, lane)
            pr = I.arm_problems(img) + I.arm_lane_problems(img)
            if bool(pr) != (pn == "guard"):
                probs.append("A5 image %s on lane %d: pe_isa %s" % (
                    pn, lane, pr if pr else "ACCEPTED the uo-bank guard"))
    lrecs = lane_records(vvp, tmp)
    print("    %-12s %s" % ("scenario", "  ".join("lane%d armed/fire/out" % n for n in range(I.N_LANES))))
    for name, *_ in LANE_SCEN:
        cells = []
        for lane in range(I.N_LANES):
            r = lrecs.get((name, lane)) or {}
            cells.append("%5s/%5s/%5s" % (r.get("armed"), r.get("fire"), r.get("out")))
        print("    %-12s %s" % (name, "  ".join(cells)))
    lp = lane_problems(lrecs)
    for x in lp:
        print("    *** %s" % x)
    print("    A5: %s" % ("every lane on the golden and symmetric with lane 0" if not lp else "%d problem(s)" % len(lp)))
    probs += lp

    # A5-FT: the FT edge path across every prr phase on every lane (Wilson 11-19)
    print("\n  A5-FT the FT edge path, edge swept %d..%d on every lane: out - fire (K = the lane's edge control)"
          % (FT_SWEEP_PHA[0], FT_SWEEP_PHA[-1]))
    ks = {}
    for lane in range(I.N_LANES):
        e = lrecs.get(("L_edge", lane))
        ks[lane] = (e["out"] - e["fire"]) if e and e["fire"] >= 0 and e["out"] >= 0 else None
    sweep = ft_sweep(vvp, tmp)
    print("    %-4s %s" % ("PHA", "  ".join("lane%d" % n for n in range(I.N_LANES))))
    for pha in FT_SWEEP_PHA:
        cells = []
        for lane in range(I.N_LANES):
            r = sweep.get((pha, lane))
            cells.append("%5s" % ((r["out"] - r["fire"]) if r and r["fire"] >= 0 and r["out"] >= 0 else "-"))
        print("    %-4d %s" % (pha, "  ".join(cells)))
    print("    K     %s" % "  ".join("%5s" % ks[n] for n in range(I.N_LANES)))
    fp = ft_sweep_problems(sweep, ks)
    for x in fp:
        print("    *** %s" % x)
    print("    A5-FT: %s" % ("every cell in K..K+%d, every lane reaches both" % FT_LATE if not fp
                              else "%d problem(s)" % len(fp)))
    probs += fp
    for plant, lane, red in ft_sweep_plants(sweep, ks):
        what = "a cell at K+2" if plant == "+2" else "every K+1 flattened to K (non-vacuity)"
        print("    must-fire %-4s lane %d  %-40s %s" % (plant, lane, what, "RED (killed)" if red else "*** SURVIVED"))
        if not red:
            probs.append("A5-FT plant %s on lane %d survived the judge" % (plant, lane))

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
    # A4-K5 (Wilson 11-17, contract K5): a refill for the flushed lane in flight at the
    # edge (P_REQ / P_WAIT) is killed (`pkill`) and files nothing. Its must-fire:
    # M_FT_NO_PKILL drops the kill, so the timeout path's in-flight successor (the
    # ARM, the loop base) is filed after the flush and the LEVEL at PC+2 waits for
    # the re-armed timeout [measured 11-20: out 341 against 143 at d = 4, 5]
    kv = os.path.join(tmp, "arm2_M_FT_NO_PKILL.vvp")
    build(kv, ["M_FT_NO_PKILL"])
    kbad = ft_race(kv, frp)
    print("    must-fire M_FT_NO_PKILL (K5: the in-flight refill not killed): %s"
          % ("RED at phase(s) %s" % kbad if kbad else "*** SURVIVED"))
    if not kbad:
        probs.append("M_FT_NO_PKILL survived the swept FT edge (K5's kill unguarded)")

    # A4-K8: the flush-spacing check (Wilson 11-19, contract K8). The check itself
    # is pe_engine's `*** ASSERT pe_engine K8` (sim only), judged on EVERY run by
    # sim_run; the fixed RTL's A4 / A5-FT sweeps above flush every lane and must
    # print none. Here the planted case: M_FT_REFLUSH applies the FT edge's flush
    # again the next cycle, and the check must report it.
    print("\n  A4-K8 flush spacing: no lane flushed again at f + 1 or f + 2")
    k8v = os.path.join(tmp, "arm2_M_FT_REFLUSH.vvp")
    build(k8v, ["M_FT_REFLUSH"])
    k8b, _e = sim(vvp, frp, 1, -1, -1, 300)
    k8t0 = k8b["armed"] if k8b else 0
    r = run(sim_run.vvp([k8v, "+IMG=%s" % frp, "+IDLE=1", "+PHA=-1", "+PHB=-1", "+NCYC=300",
                         "+PHA_ABS=%d" % (k8t0 + 30)], images=[frp]))
    k8_lines = [ln.strip() for ln in (r.stdout + r.stderr).splitlines()
                if ln.strip().startswith("*** ASSERT pe_engine K8:")]
    print("    must-fire M_FT_REFLUSH (a second flush at f + 1): %s"
          % (("RED: %s" % k8_lines[0]) if k8_lines else "*** SURVIVED"))
    if not k8_lines:
        probs.append("M_FT_REFLUSH survived: the K8 check did not report a lane flushed twice")

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
        # A5's judge must see an all-lane fault on lanes 1-4 too (the per-lane golden)
        lhit = sorted({x.split(":")[0] for x in lane_problems(lane_records(mv, tmp, d))
                       if "@lane0" not in x.split(":")[0]})
        print("    %-18s %-46s %s" % ("", "... A5 on lanes 1-4", ("RED on %d scenario-lanes" % len(lhit))
                                      if lhit else "*** SURVIVED on lanes 1-4"))
        if not lhit:
            probs.append("%s survived A5 on lanes 1-4" % d)

    print()
    if probs:
        print("  GATE arm2: FAILED (%d)" % len(probs))
        return 1
    print("  GATE arm2: PASSED")
    return 0


def _cov_write(path, img):
    """coverage_arms' write WITH its provenance (Wilson 11-21: a probe_cov image without this
    run's provenance is refused). Defined down here so no line above moves: t_ext_bench.json
    cites this file by line."""
    I.write_image(path, img)
    sim_run.cov_image("run_arm2", path)


if __name__ == "__main__":
    if sys.argv[1:] == ["--write-t-ext"]:
        write_bench_t_ext()
        print("run_arm2: wrote %s" % os.path.relpath(T_EXT_BENCH, ROOT))
        sys.exit(0)
    sys.exit(main())
