"""program_a2 -- A2's post-HIGH gap bound, derived PER PROGRAM (ruling S).

⛔⛔ WHAT WAS WRONG, AND IT IS THE SAME CATEGORY ERROR THIS SESSION HAS MADE
FOUR TIMES. `test/clocked_conform.vh` bounded every clocked lane's post-HIGH
release at `d + CK_GAP_SLACK` with `CK_GAP_SLACK = 8 = L_SYNC + 1 + (r_i - C)`,
and that `r_i` came from `gate_clocked_lane_a2.build()` -- the A2 MODEL's
shipped lane set (UART-tx, SPI-tx, UART-rx, SPI-rx, one clocked I2C lane). The
bound was then enforced on `ckod`, whose lane set is FOUR clocked open-drain
lanes at 33/60/120/240 and nothing else. A number derived for one lane set,
enforced on another. It happened to hold (measured 7 against 8), which is
exactly why it went unnoticed -- and every other clocked arm ran with the bound
switched OFF because nobody had a number for its lane set.

⇒ `r_i` belongs to the pair (PROGRAM, LANE). This module derives it from the
  program's OWN image: its own headers, its own delays, its own `J`.

THE LANE SET, READ FROM THE IMAGE AND NOT ASSUMED:

    T        the lane's MINIMUM action delay over every action it can reach.
             By P8 the timestamp advances absolutely by `a_dly`, so the tightest
             delay is the tightest inter-release.
    C        `C_SHIPPED` -- the measured dispatch service time.
    D_sched  the header's `dsched`, because that IS the engine's EDF key.
             ⛔ Not a protocol tolerance. `r_i` depends on priority, and the
             silicon's priority is this field; using anything else would derive
             the response of a differently-scheduled machine.
    D_tol    the header's `dtol`. Admissibility only -- it does not move `r_i`.
    J        `j_of(d_min_program, k)` for every lane, plus `L_JIT` on a lane
             released by an OBSERVED EDGE (a clocked open-drain lane parks on
             SCL's rise). J is a function of the program, not one number
             (ruling 1(b)), so the program's own `d_min` sets it.

⚠ AN OVERLOADED PROGRAM HAS NO BOUND, AND THAT IS A RESULT, NOT A GAP. A lane
set whose utilisation exceeds 1 has no finite worst-case response; the RTA does
not converge and pyRTA returns no bound. `corpus_all5` runs four lanes at
d = 9..13 beside a clocked lane at 70, ON PURPOSE (it is the scheduler stress
image), and its clocked lane MEASURED 131 cycles late. Quoting a bound for it
would be inventing one. It is reported UNBOUNDED with the utilisation that
makes it so, and the bench reports its lateness without a verdict -- which is
the status Wilson's earlier ruling already gave it.
"""

from __future__ import annotations

import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "test"))

import gate_degenerate_fields as dgf                              # noqa: E402
import gate_j_program as jp                                       # noqa: E402
import zero_spacing as zs                                         # noqa: E402
import pe_isa as I                                                # noqa: E402
import pyrta_bound                                                # noqa: E402
from bursty import C_SHIPPED, L_JIT, L_SYNC, BLane, response_time_b  # noqa
from pyrta_src import pinned_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

N_PINS = I.UO3 + 1
OUT_JSON = os.path.join(ROOT, "test", "clocked_a2_bounds.json")


def lanes_of(img):
    """Every lane the image runs, as (lane, header, actions)."""
    by = {}
    for ln, h, a in dgf.walk(img):
        by.setdefault(ln, (h, []))[1].append(a)
    return [(ln, h, acts) for ln, (h, acts) in sorted(by.items())]


def is_clocked(h, a):
    return (h["clkpin"] < N_PINS and a["level"] == 1
            and a["op"] in (I.OP_SHIFT, I.OP_SHIFTIN))


def gaps(h, a):
    """The release gaps one action puts on its lane (ruling CE1).

    ⛔⛔ THE TWO-LEVEL LANE. A clocked action on a HALF_HIGH lane releases at
    alternating gaps: `d` after each LOW, `d // 2` after each HIGH (plus the
    sync latency on an open-drain clock, which only lengthens it). Every other
    action releases at `d`. The A2 model takes such a lane as SPORADIC WITH
    MINIMUM SEPARATION `d // 2` -- it never releases faster than that, so its
    demand on the engine is bounded by it. ⚠ CONSERVATIVE, AND SAID SO: half
    the lane's gaps are really `d`, so the bound over-counts its interference.
    The same `d // 2` is what J = 1's premise is judged on (`pe_asm` refuses
    HALF_HIGH when it is under D*), so the premise holds PER GAP."""
    sys.path.insert(0, os.path.dirname(HERE))
    from clocked_phase import high_gap
    half = bool(h.get("flags", 0) & I.FLAG_HALF_HIGH)
    if is_clocked(h, a) and half:
        return [a["delay"], high_gap(a["delay"], True)]
    return [a["delay"]]


#: ⛔⛔ EDGE-PACED LANES (Wilson 10-18 ruling 3, built 10-20). A lane whose
#: data actions are each released by a delay-0 ARM on a PEER edge -- the SPI
#: target answers SCK one bit at a time -- has no period of its own: the
#: smallest action delay (its SHIFT's 20) is the gap AFTER a bit, not the gap
#: between bits, and taking it as T judged the lane at the wrong rate. Its T
#: is the peer's claimed maximum clock, T_EXT, and its D_tol is that clock's
#: half-period budget (`bursty.abs_tolerance`) -- at 2 MHz that budget is 4.
#: ⭐ THE RULE: two or more delay-0 ARMs in one lane. One ARM that starts an
#: internally timed frame (UART-rx, the edge images) is NOT edge-paced;
#: checked 10-20 against all 49 universe images -- none has two.
#: ⛔ FAIL CLOSED: an edge-paced lane with no T_EXT entry is REFUSED, never
#: given a period. Keyed by the image's SHA-256 (images carry no name; the
#: content is the identity, as in v3_table): sha -> {lane: T_ext cycles}.
EDGE_PACED_MIN_ARMS = 2
#: the SPI-target witness images (make_smoke_image.py --sptgt): the master's
#: claimed maximum SCK period -- 50 cycles at 1 MHz MISO-only, 100 for the
#: MOSI-capture variant witnessed at 500 kHz. Each sha is the image's own.
T_EXT = {
    "63a10e20a3ec58169d40b97abf5e51ce8912e42f56c338d6af7d5826df5404f4": {0: 50},   # sptgt_m0
    "d9f3fb51aac86358a33f6747bfe6d3800504dbab09a6fc84af1dc9d9892ed84d": {0: 50},   # sptgt_m1
    "9984ed54eff0f0c254d23be388dafe8c8387c87867b76d0dec34eb9360fb338b": {0: 50},   # sptgt_m2
    "dbb28371bf956d6b96e1a30c9707406d98965ec800f1698aab6b817d9295582d": {0: 50},   # sptgt_m3
    "3a2687c762cab0de86116ed930d8dbfdd33b5725d4e063b1a215560048c054bd": {0: 100},  # sptgt_mosi
    # B3b, the contention arm (make_smoke_image.py --b3b): lane 0 is the SPI
    # target at 1 MHz beside the four other shipped lanes
    "d58f491e6bcdfe94d89662a5b889ce7ee999270dffa577b727ccfc127420ae56": {0: 50},   # b3b_a
    "0656a43d7ba1491c7a750a9130d174e9822c3671f0196c97e560cd793464c211": {0: 50},   # b3b_a3
    "110475383587f265568e3b637e1bcb1384fff41bd69f076506102cbc78cdb94b": {0: 50},   # b3b_b
    "aad1c06753e687562ff70c87a352d7a4e269987c83d4765cd8fbab34fd3e6baa": {0: 50},   # b3b_bnoi2c
}


class EdgePacedNoTExt(ValueError):
    pass


def edge_paced(acts):
    return sum(1 for a in acts
               if a["op"] == I.OP_ARM and a["delay"] == 0) >= EDGE_PACED_MIN_ARMS


def image_sha(img):
    import hashlib
    return hashlib.sha256(bytes(img)).hexdigest()


def lane_set(img, t_ext=None):
    """The program's own A2 lane set, plus which entries are clocked OD.
    `t_ext` ({lane: cycles}) overrides the registry for edge-paced lanes."""
    rows = lanes_of(img)
    if t_ext is None:
        t_ext = T_EXT.get(image_sha(img), {})
    # ⛔⛔ DELAY-0 REARM RULING: the `delay > 0` filters below dropped a
    # delay-0 action's ZERO spacing, so 1.6a (`queue_slot`) certified the
    # WS2812 3-sub-bit build. A zero spacing has no lane set -- no T, no J --
    # so it RAISES here rather than being quoted (`model/zero_spacing.py`;
    # an ARM's delay 0 is "no timeout", exempt by its RTL anchors).
    zs.check([(ln, i, a["op"], a["delay"]) for ln, _h, acts in rows
              for i, a in enumerate(acts)])
    delays = [g for _ln, h, acts in rows for a in acts if a["delay"] > 0
              for g in gaps(h, a)]
    d_min = min(delays) if delays else None
    k = len(rows)
    j_prog = jp.j_of(d_min, k) if d_min else 0
    out = []
    for ln, h, acts in rows:
        T = min((g for a in acts if a["delay"] > 0 for g in gaps(h, a)),
                default=500)
        ck_od = any(is_clocked(h, a) for a in acts) and h["mode"] == 0
        # ⛔ BLane asserts D_sched <= D_tol; a header that violates it is a
        # program whose EDF key is looser than its own tolerance, which the
        # model refuses rather than silently swapping.
        ds, dt = h["dsched"], h["dtol"]
        if ds > dt:
            dt = ds
        if edge_paced(acts):
            if ln not in t_ext:
                raise EdgePacedNoTExt(
                    "lane %d is EDGE-PACED (%d delay-0 ARMs: the peer's edges "
                    "release it) and has no T_ext -- its period is the peer's "
                    "claimed maximum clock, not its smallest action delay (%d); "
                    "add it to program_a2.T_EXT (image sha %s...)"
                    % (ln, sum(1 for a in acts if a["op"] == I.OP_ARM
                               and a["delay"] == 0), T, image_sha(img)[:12]))
            from bursty import abs_tolerance
            T = int(t_ext[ln])
            dt = min(dt, abs_tolerance(T // 2, c9_at_completion=True,
                                       C=C_SHIPPED))
            ds = min(ds, dt)
        J = j_prog + (L_JIT if ck_od else 0)
        bl = BLane("lane%d%s" % (ln, " ckOD" if ck_od else ""), T=T,
                   C=C_SHIPPED, D_tol=dt, D_sched=ds, J=J)
        loads, chains = hold_profile(h, acts)
        cap = cap_profile(h, acts)
        out.append({"lane": ln, "blane": bl, "clocked_od": ck_od, "T": T,
                    "loads_hold": loads, "chains": chains,
                    "chain_gaps": chain_gaps(h, acts),
                    "loads_cap": cap is not None, "cap_lat": cap})
    return out, d_min, k, j_prog


# ---------------------------------------------------------------------------
# RULING RX4 -- THE CAPTURE GATE (silicon fix #7) IS OWN-LANE BLOCKING TOO
# ---------------------------------------------------------------------------
# ⛔⛔ RX1 makes a PUSH-PULL clocked SHIFTIN lane ineligible while its capture
# is pending, exactly as W1 makes a hold-loading lane ineligible while its
# hold runs, so A2 carries it the same way (W6): as release jitter on that
# lane, seen by every OTHER lane, by the same fixed point.
# THE LATENCY, FROM THE RTL'S OWN PIPELINE (not fitted): the HIGH job is
# picked, DRIVEs the next cycle and writes back the cycle after (2); the
# writeback loads the capture slot `ppc_n` with 2 for a `uo_out` clock (one
# extra cycle behind `uo_q`) or 1 for a `uio` clock, and the capture fires
# when it reaches 0 (+ ppc_n + 1): pick + 5 on a uo clock, measured on
# corpus_all5 lane 2 (writeback at 2082, capture at 2085). The gate is EXACT:
# a LOW picked in cycle c consumes at c + 2, so it is allowed once the capture
# will have landed by c + 1 -- eligible from pick + 2 + ppc_n, the quantity
# that plays W6's `HS + 2` (HS + HOLD_PICK_LAG, corrected by HC1):
#     J_cap(i) = max(0, CAP_i + (r_i - C) - T_i),  CAP_i = 2 + ppc_n
# ⇒ the delayed job is the LOW (the consume), which arms no capture, so a
#   capture-blocked job is never itself capture-delayed: no chaining case.
PICK_TO_WB = 2


def cap_profile(h, acts):
    """CAP_i for a push-pull lane that runs a clocked SHIFTIN, else None."""
    if h["mode"] != 1 or h["clkpin"] >= N_PINS:
        return None
    if not any(is_clocked(h, a) and a["op"] == I.OP_SHIFTIN for a in acts):
        return None
    ppc_n = 2 if h["clkpin"] >= 8 else 1
    return PICK_TO_WB + ppc_n


def utilisation(ls):
    return sum(r["blane"].C / float(r["T"]) for r in ls)


# ---------------------------------------------------------------------------
# RULING W6 -- W1 IS OWN-LANE BLOCKING, ACCOUNTED AS RELEASE JITTER
# ---------------------------------------------------------------------------
# ⛔⛔ W1 makes a lane INELIGIBLE until SDA_HOLD + SDA_SETUP cycles after the
# dispatch that loaded its hold. MEASURED to bind on admissible programs under
# contention (`ckdense`, d = 20..23), so "it cannot bind at the mode floor" is
# FALSE and the bound has to carry it.
# THE DERIVATION. A loading job of lane i is picked at lateness j <= r_i - C
# (r_i measured from the nominal release, C the service time). The DRIVE is
# the cycle after the pick; the hold load is written at the edge that ENDS the
# DRIVE, so `l_hcnt` reads HS from pick + 2 and reaches 0 at pick + HS + 2 --
# the lane is next eligible HS + 2 cycles after the pick (HS + 1 after DRIVE).
# Its next job is released T_i after the loading job's release, so W1 holds
# that job back by
#     J_w1(i) = max(0, HS + 2 + (r_i - C) - T_i)
# ⛔ HC1 (Lean agent; RTL decides): this read HS + 1 -- "loaded at the DRIVE
# edge one cycle after the pick" counted the DRIVE cycle's START, not the edge
# that ends it. MEASURED on RTL signals, 2,556 hold loads over five images,
# HS = 18: load visible at pick + 2, l_hcnt == 0 and hz_q == 1 at pick + 20,
# `ready` at pick + 20 wherever the hold binds. Not TM1: M_TM1_UNREG gives the
# same +20. `model/gate_hold_offset.py` holds this constant to the RTL.
HOLD_PICK_LAG = 2      # eligible HS + HOLD_PICK_LAG cycles after the pick
# ⇒ TO EVERY OTHER LANE THAT IS RELEASE JITTER on lane i (`BLane.N_J`): lane i
#   still delivers one C per release, but up to J_w1 later. It costs the engine
#   nothing while blocked (a blocked lane is not served).
# ⇒ TO LANE i ITSELF the delayed job is the SCL RELEASE (the HIGH, or the
#   unclocked `OP_LEVEL` after the data). It loads no hold, and the bench's A2
#   check bounds the gap AFTER the high, not before it -- so the subject's own
#   `r_i` keeps its base J, and only the OTHER lanes see J + J_w1.
# ⚠ THAT RESTS ON "A LOADING JOB IS NEVER ITSELF W1-DELAYED", which holds iff
#   no lane runs two hold loads back to back. Checked per lane (`chains`), never
#   assumed: such a lane would feed its own delay back into its lateness, the
#   recurrence has no fixed point, and the lane is reported UNBOUNDED with that
#   reason rather than given a number.
LOADERS_UNCLOCKED = (I.OP_SHIFT, I.OP_SHIFTIN, I.OP_READBIT)


def _hs():
    import hold_bound
    return hold_bound.bound() + hold_bound.setup()


def chain_gaps(h, acts):
    """The spacings that follow a hold-LOADING action whose successor also
    loads -- the pairs where a loading job could itself be W1-delayed.
    [] when the lane has no such chain (same marks as `hold_profile`)."""
    if h["mode"] != 0 or h["clkpin"] >= N_PINS:
        return []
    def marks(a):
        if is_clocked(h, a):
            return (True, False)
        if a["op"] == I.OP_SHIFT and a["level"] == 0:
            return (True, True)
        if a["op"] in (I.OP_SHIFTIN, I.OP_READBIT) and a["pin"] == h["pin"]:
            return (True, True)
        return (False, False)
    n = len(acts)
    return [acts[i]["delay"] for i in range(n)
            if n > 1 and marks(acts[i])[1] and marks(acts[(i + 1) % n])[0]]


def hold_profile(h, acts):
    """(loads_hold, chains) for one lane, from its own actions.

    A clocked SHIFT/SHIFTIN loads at its FIRST dispatch (LOW) and ends on a
    dispatch that loads nothing (SHIFT retires on HIGH; SHIFTIN's COLL finds
    SDA already released). An unclocked SHIFT at level 0 loads; an unclocked
    SHIFTIN/READBIT on the lane's own pin may (only if SDA was driven) and is
    counted as loading. A REARM, LEVEL, START, STOP or ARM loads nothing.
    """
    if h["mode"] != 0 or h["clkpin"] >= N_PINS:
        return False, False
    marks = []                          # (loads at start, loads at end)
    for a in acts:
        if is_clocked(h, a):
            marks.append((True, False))
        elif a["op"] == I.OP_SHIFT and a["level"] == 0:
            marks.append((True, True))
        elif (a["op"] in (I.OP_SHIFTIN, I.OP_READBIT)
              and a["pin"] == h["pin"]):
            marks.append((True, True))
        else:
            marks.append((False, False))
    loads = any(s for s, _e in marks)
    n = len(marks)
    chains = any(marks[i][1] and marks[(i + 1) % n][0] for i in range(n)) \
        if n > 1 else (n == 1 and marks[0][0] and marks[0][1])
    return loads, chains


def _with_j(bl, J):
    return BLane(bl.name, T=bl.T, C=bl.C, D_tol=bl.D_tol, D_sched=bl.D_sched,
                 J=J)


def w1_jitter(ls, hs=None, max_iter=64, src=None):
    """Per lane J_w1, by fixed point; None for a lane with no bound.

    Returns (w1 list, reason or None). See the block comment above.
    ⛔⛔ RULING A8: `src` given -> the lateness `r_i - C` inside the fixed
    point is pyRTA's, so the jitter a pyRTA number is computed WITH is pyRTA's
    too and the foreign witness's input is not ours. Without `src` (CI) it is
    our recurrence's -- >= pyRTA on admissible lanes, so a PESSIMISTIC input,
    and every pyRTA figure in this file is computed with the pyRTA-side term.
    """
    hs = _hs() if hs is None else hs
    w1 = [0] * len(ls)
    # ⛔⛔ CHAINED HOLD LOADS (Wilson, WF2 round 2, finding 1 -- the 1-Wire
    # lane). The derivation below assumes a LOADING job is never itself
    # W1-delayed, and a lane whose loading actions follow one another breaks
    # that assumption -- so this used to REFUSE every such lane outright,
    # and pe_asm's 1.6a then SKIPPED the lane with no bound at all.
    # ⭐ EXTENDED, BY INDUCTION, NOT REFUSED: a loading job released on its
    # nominal schedule is picked within r_i - C of its release; its hold makes
    # the lane ineligible until pick + HS + HOLD_PICK_LAG; so the NEXT loading
    # job -- released g cycles later, g the loading action's own delay -- finds
    # the hold already expired iff
    #     HS + HOLD_PICK_LAG + (r_i - C) <= g        for every chained pair.
    # Then no loading job is ever W1-delayed (base case: the first job;
    # step: each one picked on time leaves the next undelayed), the W6 model
    # below holds unchanged, and the chain costs nothing. The condition is
    # CHECKED after the fixed point with the lane's OWN r_i; where it fails the
    # lane is refused exactly as before. 1-Wire: g >= 100 against HS + 2 = 20.
    chained = [r for r in ls if r["loads_hold"] and r["chains"]]
    for _ in range(max_iter):
        new = []
        for i, r in enumerate(ls):
            # RX4: a capture-gated lane blocks for CAP_i the way a hold
            # loader blocks for HS (disjoint: holds are open-drain only)
            if not (r["loads_hold"] or r.get("loads_cap")):
                new.append(0)
                continue
            # eligibility latency after the pick: W1's HS + 2 (HC1); RX1's CAP_i
            blk = hs + HOLD_PICK_LAG if r["loads_hold"] else r["cap_lat"]
            lanes = [ls[k]["blane"] if k == i else
                     _with_j(ls[k]["blane"], ls[k]["blane"].J + w1[k])
                     for k in range(len(ls))]
            rr = (pyrta_bound.bound(src, lanes, i)[0] if src
                  else response_time_b(lanes[i], lanes)["r"])
            if rr is None:
                return None, "pyRTA gave no bound inside the W1 fixed point"
            new.append(max(0, blk + (rr - C_SHIPPED) - r["T"]))
        if new == w1:
            # the induction's premise, on every chained lane's own r_i.
            # ⛔ THE CONSTANTS, BY NAME (Wilson's condition 2): the hold window
            # is `hs + HOLD_PICK_LAG` = HS + 2, the HC1-corrected eligibility
            # lag after the pick (`gate_hold_offset.py` holds it to the RTL),
            # and the lateness is `rr - C_SHIPPED` = r_i - C, the PICK
            # lateness -- the same quantity J_w1 above charges and the bound
            # r_i bounds (release to completion = pick lateness + C). Proof:
            # docs/A2_FRAMEWORK.md, "Chained hold loads".
            for r in chained:
                i = ls.index(r)
                lanes = [ls[k]["blane"] if k == i else
                         _with_j(ls[k]["blane"], ls[k]["blane"].J + w1[k])
                         for k in range(len(ls))]
                rr = (pyrta_bound.bound(src, lanes, i)[0] if src
                      else response_time_b(lanes[i], lanes)["r"])
                g = min(r["chain_gaps"])
                if rr is None or hs + HOLD_PICK_LAG + (rr - C_SHIPPED) > g:
                    return None, (
                        "lane %d runs two hold loads back to back %d cycles "
                        "apart, inside the hold window HS + %d + (r - C) = %s: "
                        "a loading job can itself be W1-delayed and the "
                        "recurrence has no fixed point"
                        % (r["lane"], g, HOLD_PICK_LAG,
                           None if rr is None
                           else hs + HOLD_PICK_LAG + rr - C_SHIPPED))
            return w1, None
        w1 = new
    return None, "W1 jitter did not converge in %d iterations" % max_iter


def with_w1(ls, w1, i):
    """The lane set as lane i's analysis sees it: others carry J + J_w1."""
    return [ls[k]["blane"] if k == i else
            _with_j(ls[k]["blane"], ls[k]["blane"].J + w1[k])
            for k in range(len(ls))]


def queue_slot(img, src=None, t_ext=None):
    """RULING DT-A -- condition 1.6a PER PROGRAM: r_i <= t_i on every lane.

    ⛔⛔ THE EXACT FORM, MEASURED AGAINST TCHECKER, NOT CHOSEN. `ovr` in the
    exact model (`zone/gen_edf.py`) fires when a lane's next NOMINAL release
    finds its previous job still pending or still waiting out its jitter. r is
    measured from the nominal release and already CONTAINS the lane's own
    delay, so the boundary is `r_i <= t_i` -- not `r_i + J_i <= t_i`, which
    would charge the jitter twice. Equality is admissible: solo T=5, C=2, J=3
    (r = 5 = T) and a blocked T=7 lane (r = 7 = T) both leave `ovr`
    unreachable, while a blocked T=6 lane at r = 7 reaches it.
    ⭐ THE LANE'S OWN W1 DELAY IS IN ITS OWN r HERE, unlike in `derive`: the
    question is whether ANY job of the lane -- including the SCL release W1
    held back -- can still be pending at the next release, so every lane
    carries J + J_w1, subject included.
    ⚠ `t_i` is the lane's tightest action delay (`T` in `lane_set`), which is
    the event spacing the queue slot has to clear.
    Returns {lane: {"r": r or None, "T": t, "ok": bool, "why": str or None}}.
    `t_ext`: the edge-paced lanes' T_ext, declared at build time (lane_set).
    """
    ls, _d, _k, _j = lane_set(img, t_ext)
    u = utilisation(ls)
    out = {}
    if u > 1.0:
        for r in ls:
            out[str(r["lane"])] = {"r": None, "T": r["T"], "ok": False,
                                   "why": "overloaded (U = %.3f)" % u}
        return out
    w1, w1_why = w1_jitter(ls)
    if w1 is None:
        for r in ls:
            out[str(r["lane"])] = {"r": None, "T": r["T"], "ok": False,
                                   "why": w1_why}
        return out
    full = [_with_j(r["blane"], r["blane"].J + w1[k]) for k, r in enumerate(ls)]
    # A8: pyRTA's figure uses pyRTA's own W1 term
    w1p = w1_jitter(ls, src=src)[0] if src else None
    fullp = ([_with_j(r["blane"], r["blane"].J + w1p[k])
              for k, r in enumerate(ls)] if w1p is not None else None)
    for i, r in enumerate(ls):
        try:
            ours = response_time_b(full[i], full)["r"]
        except Exception as exc:                          # noqa: BLE001
            out[str(r["lane"])] = {"r": None, "T": r["T"], "ok": False,
                                   "why": "own recurrence raised %s"
                                   % type(exc).__name__}
            continue
        p = pyrta_bound.bound(src, fullp, i)[0] if fullp else None
        rr = max(x for x in (ours, p) if x is not None)
        # ⭐ BOTH FIGURES ARE KEPT (WF2 / V3-T): `r` stays the max, the CI-safe
        # form 1.6a refuses on; V3-T judges the bench against `r_pyrta`, the
        # PRIMARY bound, so it needs it separately.
        out[str(r["lane"])] = {"r": rr, "T": r["T"], "ok": rr <= r["T"],
                               "why": None, "r_ours": ours, "r_pyrta": p}
    return out


#: WF2 / V3-T: the per-lane response bound the bench's scheduler-conformance
#: check judges every unclocked transmitting lane against.
RESP_JSON = os.path.join(ROOT, "test", "lane_response_bounds.json")


def response_images():
    """(name, img) for every image of the SHARED universe
    (`model/image_universe.py`, Wilson 10-18) with an UNCLOCKED SHIFT on some
    lane. This scanned test/*.hex plus the generated probe_cov_* images and
    missed fpga/images/ (none carries one today, so no bound moves)."""
    # ⛔ THE GENERATED IMAGES ARE BUILT by the universe, with the sweep's own
    # builder, so the set does not depend on whether a sweep ran first. A
    # generator failure or an image that does not load RAISES (gate_except):
    # it must stop the writer, not drop silently out of the bound set.
    import image_universe
    out = []
    for n, img in image_universe.images():
        if any(a["op"] == I.OP_SHIFT and not is_clocked(h, a)
               for _ln, h, acts in lanes_of(img) for a in acts):
            out.append((n, img))
    return out


def response_bounds(src, images=None):
    """{image: {"lanes": {lane: {r_pyrta, r_ours, T, dtol, why}}}}.

    r is 1.6a's own quantity (`queue_slot`): worst-case response from the
    NOMINAL release to completion, W1 jitter on every lane. `dtol` is the
    lane header's declared tolerance. An image with a zero release spacing has
    no lane set (refused by pe_asm) and gets no bound; an overloaded one gets
    r = None with the reason -- the bench reports both as UNBOUNDED, never as a
    pass."""
    blob = {}
    for name, img in (images if images is not None else response_images()):
        lanes = {}
        try:
            q = queue_slot(img, src)
        except zs.ZeroSpacingError as exc:
            blob[name] = {"lanes": {}, "why": "zero release spacing: %s"
                          % str(exc)[:80]}
            continue
        hdr = {str(ln): h for ln, h, _a in lanes_of(img)}
        for ln, v in q.items():
            lanes[ln] = {"r_pyrta": v.get("r_pyrta"), "r_ours": v.get("r_ours"),
                         "T": v["T"], "dtol": int(hdr[ln]["dtol"]),
                         "why": v.get("why")}
        blob[name] = {"lanes": lanes, "why": None}
    return blob


def derive(img, src=None, t_ext=None):
    """Per clocked open-drain lane: r_i (pyRTA primary), and the bench slack.

    ⛔⛔ `src=None` IS A SUPPORTED MODE, AND THE FIRST VERSION DID NOT HAVE IT.
    pyRTA is NOT vendored, and every pyRTA-primary gate in this project lives
    OUTSIDE `ci/run_gates.sh` for exactly that reason (`run_a2.py` runs them by
    hand at each checkpoint). Ruling S first wired two pyRTA-dependent checks
    into CI; both passed here only because a pyRTA clone sits in a scratch
    directory, and CI went red at 20 of 22 -- caught by checking CI on the
    exact SHA, which is what ruling CI1 is for.
    ⇒ Without pyRTA this computes EVERYTHING EXCEPT the pyRTA column: the lane
      set, U, J and our own recurrence's `r_ours`. That is what CI re-derives
      to hold the committed JSON current. The pyRTA column -- and therefore the
      bench budgets, which are pyRTA-primary -- is re-derived by
      `gate_a2_bounds_pyrta.py` under `run_a2.py`, RED without pyRTA.
    ⭐ `r_floor` IS THE LARGER OF THE TWO WHEN BOTH EXIST. Measured over every
    clocked lane in the repo, `r_ours >= r_pyrta` (equal on most, larger on two
    `ckdense` lanes), so a floor taken from `r_ours` alone is never LESS strict
    than the pyRTA one on any program we have -- but that is an observation,
    not a theorem, so when pyRTA is present the max is used rather than trusted.
    ⛔⛔ AND THE OBSERVATION WAS FALSE, which is why the max was right -- but
    the first diagnosis of WHY was also false, and is WITHDRAWN (ruling Y-R1).
    Under W1's jitter pyRTA came out above ours on `ckdense`, and this
    docstring blamed pyrta_bound for "charging J twice". TChecker refutes
    that: on large-jitter instances the D - J framing is EXACT (8 of 8 lanes)
    and the "charge once" alternative is BELOW the truth (5 of 8). The defect
    was OURS: `response_time_b` searched only the subject's own release
    offsets, and fell below the exact worst case (7 of 8 queue-depth-one
    instances; 184 of 6,601 even with no jitter). Ruling Z gave it Spuri's full
    candidate set; `model/gate_spuri_candidates.py` holds it there. ⇒ After Z,
    ours >= pyRTA on every lane of every ADMISSIBLE program (checked in
    `gate_a2_program` §1b), which is what CI's pyRTA-free floor needs.
    ⚠ `ckdense` still has ours < pyRTA; it fails 1.6a (ruling DT-B) and is a
    declared stress image, outside what any exact witness adjudicates.
    `t_ext`: the edge-paced lanes' T_ext, declared at build time (lane_set).
    """
    ls, d_min, k, j_prog = lane_set(img, t_ext)
    blanes = [r["blane"] for r in ls]
    u = utilisation(ls)
    res = {"d_min": d_min, "k": k, "J": j_prog, "U": round(u, 4),
           "lanes": {}}
    # ⛔ W6: the W1 release jitter of every hold-loading lane, by fixed point
    # (see `w1_jitter`). Only defined on a set that is not overloaded.
    w1, w1_why, w1p = (None, None, None)
    if u <= 1.0:
        w1, w1_why = w1_jitter(ls)
        res["w1"] = ({str(r["lane"]): w1[i] for i, r in enumerate(ls)
                      if r["loads_hold"]} if w1 is not None else None)
        # ⛔ A8: pyRTA's column is computed with pyRTA's OWN W1 term. Recorded
        # beside ours (top-level key `w1_pyrta`, pyRTA-only like `r_pyrta`).
        w1p = w1_jitter(ls, src=src)[0] if (src and w1 is not None) else None
        if w1p is not None:
            res["w1_pyrta"] = {str(r["lane"]): w1p[i]
                               for i, r in enumerate(ls) if r["loads_hold"]}
    for i, r in enumerate(ls):
        if not r["clocked_od"]:
            continue
        entry = {"T": r["T"], "r_pyrta": None, "r_ours": None, "slack": None,
                 "r_floor": None, "why": None}
        # ⛔ OVERLOAD FIRST: an RTA over a set with U > 1 has no fixed point,
        # and a number returned anyway would be the horizon, not a bound.
        if u > 1.0:
            entry["why"] = ("lane set overloaded (U = %.3f > 1): no finite "
                            "worst-case response exists" % u)
            res["lanes"][str(r["lane"])] = entry
            continue
        if w1 is None:
            entry["why"] = w1_why
            res["lanes"][str(r["lane"])] = entry
            continue
        blanes = with_w1(ls, w1, i)
        try:
            ours = response_time_b(blanes[i], blanes)["r"]
        except Exception as exc:                          # noqa: BLE001
            ours = None
            entry["why"] = "own recurrence raised %s" % type(exc).__name__
        entry["r_ours"] = ours
        if not src:
            # ⭐ NO pyRTA: our recurrence only, and the entry SAYS so. The
            # pyRTA column stays None rather than being filled with `r_ours`,
            # so nothing downstream can mistake one for the other.
            entry["r_floor"] = ours
            res["lanes"][str(r["lane"])] = entry
            continue
        p, err = pyrta_bound.bound(src, with_w1(ls, w1p, i)
                                   if w1p is not None else blanes, i)
        entry["r_pyrta"] = p
        cands = [x for x in (ours, p) if x is not None]
        entry["r_floor"] = max(cands) if cands else None
        if p is None:
            entry["why"] = entry["why"] or ("pyRTA gave no bound: %s" % err)
        else:
            # ⭐ pyRTA IS PRIMARY. The bench budget is the same expression the
            # shipped constant came from -- only the lane set it is evaluated
            # over has changed, which is the entire point of ruling S.
            entry["slack"] = L_SYNC + 1 + (p - C_SHIPPED)
        res["lanes"][str(r["lane"])] = entry
    return res


def lane_responses(img, src=None):
    """{lane: (r_floor, why)} for EVERY lane, W1 accounted (ruling W7).

    `derive` answers for clocked open-drain lanes only, because the bench's
    post-HIGH budget is theirs. W7's mode floor also judges UNCLOCKED
    open-drain frames, whose low phase shrinks by the same start delay, so it
    needs `r_i` for any lane. Same lane set, same W1 term, same max(ours,
    pyRTA) rule as `derive`.
    """
    ls, _d, _k, _j = lane_set(img)
    u = utilisation(ls)
    if u > 1.0:
        why = ("lane set overloaded (U = %.3f > 1): no finite worst-case "
               "response exists" % u)
        return {r["lane"]: (None, why) for r in ls}
    w1, w1_why = w1_jitter(ls)
    if w1 is None:
        return {r["lane"]: (None, w1_why) for r in ls}
    w1p = w1_jitter(ls, src=src)[0] if src else None     # A8
    out = {}
    for i, r in enumerate(ls):
        bl = with_w1(ls, w1, i)
        try:
            ours = response_time_b(bl[i], bl)["r"]
        except Exception as exc:                          # noqa: BLE001
            out[r["lane"]] = (None, "own recurrence raised %s"
                              % type(exc).__name__)
            continue
        p = (pyrta_bound.bound(src, with_w1(ls, w1p, i), i)[0]
             if w1p is not None else None)
        out[r["lane"]] = (max(x for x in (ours, p) if x is not None), None)
    return out


def clocked_images():
    """Every image of the SHARED universe (`model/image_universe.py`) that has
    at least one clocked open-drain lane.

    ⛔ THE UNIVERSE IS SHARED (Wilson 10-18). This scanned test/*.hex, then
    test/ + fpga/images/ -- and both times missed images the bench runs: the
    tb_cktx arms probe_cov_pindiv (lane 3) and probe_cov_cemodes (lane 0) had
    clocked open-drain lanes and no bound, so they ran with A2 switched off.
    Readers that load an image BY NAME use `image_universe.resolve`."""
    import image_universe
    out = []
    for name, img in image_universe.images():
        ls, _d, _k, _j = lane_set(img)
        if any(r["clocked_od"] for r in ls):
            out.append((name, img))
    return out


# ⛔⛔ RULING HC1-B (Wilson): A BUDGET IS EMITTED ONLY ON A BOUND THE PRIMARY
# ANALYSIS PROVED. Under HS + 2, pyRTA's W1 fixed point on `ckdense` gave NO
# bound, and `derive` fell back to pyRTA evaluated with OUR jitter -- a number
# that looked like a bound (r 25, slack 26) and silently became the bench
# budget. An absent result was counted as a pass: the third time that shape
# appeared in one arc (the equivalence tool twice before it).
# ⇒ `budgets()` REFUSES (raises) when a non-overloaded image has a lane whose
#   pyRTA bound or pyRTA W1 term is missing -- unless the image is named here,
#   where its bench budget is EMPIRICAL and labelled as such: the measured
#   widest post-HIGH gap past d (clocked_conform[A2] `lanes ... widest`) plus a
#   STATED margin. Its functional checks (bytes, EX1, rx_e2e) are unchanged.
NO_RTA_BUDGET = {
    "ckdense_image.hex": {
        "why": ("stress image, outside admissibility (fails 1.6a, ruling "
                "DT-B): pyRTA's W1 fixed point gives no bound under HS + 2, "
                "so there is NO ANALYTIC BOUND; the budget is EMPIRICAL"),
        # MEASURED: tb_trace, the benchset `ckdense` arm (+PEER=none, 200k
        # cycles), +A2SLACK absent, seeds 1-3 identical
        "measured_widest": {"0": 6, "1": 7, "2": 10, "3": 5},
        "margin": 4,
    },
}

# ⛔⛔ WILSON, SP2/P4: MEMBERSHIP IS THE REGISTRY's, NOT THIS DICT's. The dict
# above keeps the MEASUREMENT (widest gap, margin -- `measure_a2_widest.py`'s);
# which images may carry an empirical budget at all is
# `model/nonadmissible.py` TIMING_EXEMPT (permit `no_rta_budget`), the same
# file that declares every non-admissible image. A key here the registry does
# not grant -- or a grant here with no measurement -- refuses at import, so no
# tool can run on a budget nobody declared.
import nonadmissible as _NA                                       # noqa: E402
_NRB_PROBS = _NA.no_rta_problems(NO_RTA_BUDGET)
if _NRB_PROBS:
    raise RuntimeError("program_a2.NO_RTA_BUDGET disagrees with the "
                       "non-admissible registry: " + "; ".join(_NRB_PROBS))


def budgets(src, images=None):
    """{image: derive() result with bench budgets}, refusing unbounded ones.

    `images` defaults to every clocked image. ⛔ Raises RuntimeError on an
    image with a missing pyRTA bound that is not in NO_RTA_BUDGET.
    """
    blob = {}
    for name, img in (images if images is not None else clocked_images()):
        res = derive(img, src)
        mark = NO_RTA_BUDGET.get(name)
        if mark is not None:
            # ⛔ the registry, every use: a key planted after import is red
            _NA.require(name, _NA.NO_RTA)
            res.pop("w1_pyrta", None)
            for ln, e in res["lanes"].items():
                w = mark["measured_widest"].get(ln)
                if w is None:
                    raise RuntimeError("%s lane %s: marked no_rta_budget but "
                                       "has no measured widest gap" % (name, ln))
                e["r_pyrta"] = None
                e["r_floor"] = e["r_ours"]
                e["slack"] = w + mark["margin"]
                e["budget"] = "EMPIRICAL"
                e["why"] = ("%s -- measured widest %d + stated margin %d"
                            % (mark["why"], w, mark["margin"]))
            blob[name] = res
            continue
        overloaded = res["U"] > 1.0
        holds = res.get("w1") or {}
        if not overloaded and holds and src and res.get("w1_pyrta") is None:
            raise RuntimeError(
                "%s: pyRTA's W1 fixed point gave NO bound (ours: %s). A budget "
                "derived from it would be unsound. Mark the image in "
                "NO_RTA_BUDGET with a measured, labelled budget, or fix the "
                "program." % (name, holds))
        for ln, e in res["lanes"].items():
            if not overloaded and src and e["r_pyrta"] is None:
                raise RuntimeError("%s lane %s: pyRTA gave no bound (%s) -- "
                                   "refusing to emit a budget" % (name, ln, e["why"]))
            if e.get("slack") is not None:
                e["budget"] = "pyRTA"
        blob[name] = res
    return blob


def main() -> int:
    print()
    print("=" * 78)
    print("  RULING S -- A2's POST-HIGH GAP BOUND, PER PROGRAM")
    print("=" * 78)
    # ⛔ P6: only a PINNED (or declared) pyRTA writes the budgets the bench
    # enforces -- an unpinned witness cannot certify a committed artefact.
    src = pinned_pyrta()
    if not src:
        print("  *** pyRTA NOT FOUND -- the per-program bound is pyRTA-primary,")
        print("      so nothing is written rather than a fallback number.")
        return 1
    print("  pyRTA source: %s" % src)
    print("  slack = L_SYNC (%d) + 1 + (r_i - C), r_i from pyRTA over the"
          % L_SYNC)
    print("  program's OWN lane set")
    print()
    print("  %-26s %-5s %-3s %-3s %-7s %-5s %-6s %-7s %-6s %s"
          % ("image", "dmin", "k", "J", "U", "lane", "T", "r(pyRTA)",
             "slack", "note"))
    try:
        blob = budgets(src)
    except RuntimeError as exc:
        print("  *** REFUSED, NOTHING WRITTEN: %s" % exc)
        return 1
    for name, res in blob.items():
        for ln, e in sorted(res["lanes"].items(), key=lambda kv: int(kv[0])):
            print("  %-26s %-5s %-3s %-3s %-7s %-5s %-6s %-7s %-6s %s"
                  % (name, res["d_min"], res["k"], res["J"], res["U"], ln,
                     e["T"], e["r_pyrta"], e["slack"], e["why"] or ""))
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=1, sort_keys=True)
    print()
    print("  -> %s (%d image(s))" % (os.path.relpath(OUT_JSON, ROOT),
                                     len(blob)))
    # ⭐ WF2 / V3-T: the per-lane response bound for every image that runs an
    # unclocked transmitter, pyRTA-primary, written beside the clocked one.
    rb = response_bounds(src)
    print()
    print("  %-26s %-5s %-8s %-7s %-5s %s" % ("image (V3-T)", "lane",
                                             "r(pyRTA)", "r(ours)", "dtol",
                                             "note"))
    for name, res in rb.items():
        if not res["lanes"]:
            print("  %-26s %s" % (name, res["why"]))
        for ln, e in sorted(res["lanes"].items(), key=lambda kv: int(kv[0])):
            print("  %-26s %-5s %-8s %-7s %-5s %s"
                  % (name, ln, e["r_pyrta"], e["r_ours"], e["dtol"],
                     e["why"] or ""))
    with io.open(RESP_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rb, fh, indent=1, sort_keys=True)
    print("  -> %s (%d image(s))" % (os.path.relpath(RESP_JSON, ROOT),
                                     len(rb)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
