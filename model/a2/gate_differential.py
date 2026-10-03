"""SPEC 0.9 -- DIFFERENTIAL-TOLERANCE ADJUDICATION.

THE CLAIM UNDER TEST: feasibility is `(r_i - C_i) <= D_i`, not `r_i <= D_i`,
because `D_i` is a DIFFERENTIAL tolerance. Soundness rests on two legs:

  (i)  a non-preemptive start delay lies in [0, r_i - C_i] -- so the achievable
       spread between two actions' delays is r_i - C_i, not r_i;
  (ii) a UNIFORM shift of every edge is invisible to the peer, because the peer
       re-synchronises (UART locks to the start edge; a clocked peer uses the
       clock we generate). Only differences matter.

⛔⛔ THIS RESULT RUNS IN THE FLATTERING DIRECTION AND OVERTURNS A RATIFIED
VERDICT. Under it every A2 margin gains exactly C_i, and unbuffered Ethernet
goes from "structurally infeasible" to feasible by one cycle. That is precisely
the shape of claim this project has learned to distrust, so nothing here is
asserted from the derivation: the derivation only says WHAT to measure.

⭐ WHY THE REAL LANES CANNOT ADJUDICATE IT. UART has r-C = 8 against D = 216.
Both the old test and the new one pass by two orders of magnitude, so running
the ladder on UART would produce agreement that means nothing. The instance
below is CONSTRUCTED so the two tests DISAGREE:

    analysed lane A : T = 10, C = 2, D = min(5, 4) = 4
    interferers     : two lanes at T = 7, C = 2, D = 3  (earlier deadlines)
    => r_A = 6
       OLD test  r_A <= D_A      :  6 <= 4   REFUSES this instance
       NEW test  r_A - C_A <= D_A:  4 <= 4   ACCEPTS it, with zero margin

Zero margin is deliberate: the instance sits exactly on the new test's boundary,
so a ladder across it discriminates the two readings in one step.

ARMS (spec 0.9):
  (a) differential sigrok ladder across spread = D and D+1, decode change
      ASSERTED, plus the discrimination shown explicitly;
  (b) END-TO-END: an EDF schedule SIMULATED from release offsets produces the
      per-action delays, those delays render the waveform, and sigrok decodes
      it. No hand-chosen delta vector anywhere between the scheduler and the
      foreign decoder;
  (c) uniform-shift invisibility (O7) re-asserted on the same instance.

FALSIFIERS:
  (a) old and new tests agree on this instance  -> ladder cannot discriminate
  (b) reachable spread != r - C                 -> recurrence or schedule wrong
  (c) a uniform shift changes a verdict         -> D_i is not purely
                                                   differential; reading VOID
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "ta01"))

from gate0_external import sigrok_decode, wsl_path          # noqa: E402,F401
from jitter_dmax import levels_jittered                     # noqa: E402
from bursty import BLane, response_time_b                   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

F_CLK = 50_000_000
BYTE = 0x55                      # not its own bit-reversal


# ============================================================================
# THE INSTANCE
# ============================================================================
def d_of(T: int) -> int:
    h = T // 2
    return min(h, T - h - 1)


T_A, C_A = 10, 2
D_A = d_of(T_A)
LANES = [BLane("A", T_A, C_A, D_A),
         BLane("I0", 7, 2, d_of(7)),
         BLane("I1", 7, 2, d_of(7))]


# ============================================================================
# AN EXPLICIT EDF SIMULATOR -- arm (b)'s engine
# ============================================================================
def simulate(lanes, offsets, prio, horizon: int):
    """Non-preemptive EDF, cycle by cycle, in the model's phase order.

    R (release) -> SC (schedule, only when idle) -> EX (one cycle of service).
    `prio` breaks deadline ties; Part 0 proved the bound is tie-break-free, so
    every permutation is explored by the caller rather than one being assumed.

    Returns per-lane lists of (release, start, completion).
    """
    nxt = list(offsets)
    ready = []                                   # (key, prio, release, lane)
    cur = None
    rem = 0
    out = [[] for _ in lanes]
    for c in range(horizon):
        # --- R: releases land and are eligible THIS cycle (convention C3)
        for i, l in enumerate(lanes):
            if c == nxt[i]:
                # C1: the EDF key is D_i + C_i (completion deadline). With
                # uniform C_i this is a constant shift and cannot change the
                # ordering -- recorded, not relied on.
                ready.append((c + l.D + l.C, prio[i], c, i))
                nxt[i] += l.T
        # --- SC: work-conserving, and only when the engine is free
        if cur is None and ready:
            ready.sort()
            key, _, rel, i = ready.pop(0)
            cur = (rel, i, c)
            rem = lanes[i].C
        # --- EX: one cycle of service
        if cur is not None:
            rem -= 1
            if rem == 0:
                rel, i, st = cur
                out[i].append((rel, st, c + 1))
                cur = None
    return out


def max_spread(lanes, target: int, horizon: int = 400):
    """Largest start-delay spread for `target`, over all offsets and tie-breaks."""
    import itertools
    best = None
    T = [l.T for l in lanes]
    for offs in itertools.product(*[range(t) for t in T]):
        for prio in itertools.permutations(range(len(lanes))):
            runs = simulate(lanes, offs, prio, horizon)[target]
            if len(runs) < 12:
                continue
            ds = [st - rel for rel, st, _ in runs]
            rs = [cp - rel for rel, _, cp in runs]
            sp = max(ds) - min(ds)
            if best is None or sp > best["spread"]:
                best = {"spread": sp, "offsets": offs, "prio": prio,
                        "deltas": ds, "max_r": max(rs), "runs": runs}
    return best


def window_of_max_spread(deltas, n=10):
    """The n consecutive actions whose delay spread is widest -- one UART frame."""
    best = (None, -1)
    for i in range(len(deltas) - n + 1):
        w = deltas[i:i + n]
        s = max(w) - min(w)
        if s > best[1]:
            best = (w, s)
    return best


# ============================================================================
def decode(deltas, tag: str) -> dict:
    """Render a frame from these per-action delays and let sigrok read it."""
    base = min(deltas)
    rel = [d - base for d in deltas]             # a uniform shift is invisible
    wave = levels_jittered(BYTE, T_A, rel)
    if wave is None:
        return {"ok": False, "why": "deltas reorder the waveform", "decoded": None}
    path = os.path.join(HERE, "wave_diff_%s.bin" % tag)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(bytes(l & 1 for l in wave))
    os.replace(tmp, path)
    raw = sigrok_decode(path, baud=round(F_CLK / T_A))
    try:
        os.remove(path)
    except OSError:
        pass
    if raw["rc"] != 0:
        return {"ok": False, "why": "SIGROK FAILED rc=%s" % raw["rc"], "decoded": None}
    dec = int(raw["bytes"][0], 16) if raw["bytes"] else None
    return {"ok": True, "conforms": bool(raw["start"] and raw["stop"]
                                         and dec == BYTE and not raw["frame_error"]),
            "decoded": dec, "spread": max(rel) - min(rel)}


def validate_simulator() -> bool:
    """Arm (b)'s engine must reproduce schedules whose answers are forced.

    ⛔ The same three cases that validated the TChecker model in Part 3, and for
    the same reason: a simulator is only an authority once it reproduces answers
    verifiable by hand. Arm (b) renders a waveform from this simulator's output,
    so an unvalidated simulator would hand sigrok a waveform that does not
    correspond to any schedule the engine can produce -- and sigrok would
    cheerfully decode it.
    """
    import itertools
    cases = [("solo", [("solo", 100, 2, 50)], 0, 2),
             ("B=0 + more-urgent lane", [("urgent", 100, 2, 10),
                                         ("relaxed", 100, 3, 50)], 1, 5),
             ("blocker one tick early", [("analysed", 100, 2, 10),
                                         ("blocker", 100, 4, 50)], 0, 5)]
    print("  --- arm (b) precondition: validate the EDF simulator ---")
    ok = True
    for lbl, spec, tgt, truth in cases:
        lanes = [BLane(n, T, C, D) for n, T, C, D in spec]
        best = 0
        for offs in itertools.product(*[range(l.T) for l in lanes]):
            for prio in itertools.permutations(range(len(lanes))):
                for rel, st, cp in simulate(lanes, offs, prio, 600)[tgt]:
                    best = max(best, cp - rel)
        good = best == truth
        ok = ok and good
        print("    %-26s truth %-4d simulator %-4d %s"
              % (lbl, truth, best, "OK" if good else "*** MISMATCH ***"))
    print("    simulator: %s" % ("validated" if ok else "*** NOT an authority ***"))
    return ok


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 0.9 -- DIFFERENTIAL-TOLERANCE ADJUDICATION")
    print("=" * 78)
    if not validate_simulator():
        print("  ABORTING: arm (b) cannot run on an unvalidated simulator.")
        return 1
    print()
    r = response_time_b(LANES[0], LANES)
    rA, dmax = r["r"], r["r"] - C_A
    print("  instance: A(T=%d,C=%d,D=%d) + I0,I1(T=7,C=2,D=%d)"
          % (T_A, C_A, D_A, d_of(7)))
    print("    r_A = %d   r_A - C_A = %d   D_A = %d" % (rA, dmax, D_A))
    print("    OLD test  r_A <= D_A       : %d <= %d  -> %s"
          % (rA, D_A, "ACCEPT" if rA <= D_A else "REFUSE"))
    print("    NEW test  r_A - C_A <= D_A : %d <= %d  -> %s"
          % (dmax, D_A, "ACCEPT" if dmax <= D_A else "REFUSE"))
    discriminates = (rA > D_A) and (dmax <= D_A)
    print("    FALSIFIER (a): the two tests %s"
          % ("DISAGREE -- the ladder can discriminate"
             if discriminates else
             "*** AGREE -- ladder cannot discriminate, redesign the instance ***"))
    if not discriminates:
        return 1
    print()

    # ---- arm (a): the differential ladder ------------------------------
    print("  --- ARM (a): differential sigrok ladder ---")
    print("    %-8s %-10s %-10s %s" % ("spread", "sigrok", "decoded", "expected"))
    rows_a = []
    for s in range(0, D_A + 4):
        res = decode([s] + [0] * 9, "a%02d" % s)
        if not res["ok"]:
            print("    %-8d *** %s" % (s, res["why"]))
            return 1
        exp = "CONF" if s <= D_A else "VIOL"
        got = "CONF" if res["conforms"] else "VIOL"
        rows_a.append((s, res["conforms"], res["decoded"]))
        print("    %-8d %-10s %-9s  %s %s"
              % (s, got, "0x%02X" % res["decoded"] if res["decoded"] is not None
                 else "-", exp, "OK" if got == exp else "*** MISMATCH ***"))
    inside = [x for x in rows_a if x[0] <= D_A]
    outside = [x for x in rows_a if x[0] > D_A]
    a_ok = all(x[1] for x in inside) and all(not x[1] for x in outside)
    shifted = {x[2] for x in outside}
    a_reason = bool(outside) and all(x[2] != BYTE for x in outside) and len(shifted) == 1
    print("    (a) conforms at spread <= %d, refuses above: %s"
          % (D_A, "PASS" if a_ok else "*** FAIL ***"))
    print("    (d) refuses for ONE stated reason (a single wrong decode %s): %s"
          % (["0x%02X" % v if v is not None else "None" for v in shifted],
             "PASS" if a_reason else "*** FAIL -- unnamed reason ***"))
    print()

    # ---- arm (c): uniform-shift invisibility ---------------------------
    print("  --- ARM (c): uniform shift must be invisible (O7) ---")
    c_ok = True
    for k in (0, 1, 3, 7, D_A, D_A + 3, T_A - 1):
        res = decode([k] * 10, "c%02d" % k)
        if not res["ok"]:
            print("    k=%-4d *** %s" % (k, res["why"]))
            return 1
        good = res["conforms"]
        c_ok = c_ok and good
        print("    every edge shifted by %-4d spread=%-3d sigrok %-6s %s"
              % (k, res["spread"], "CONF" if good else "VIOL",
                 "OK" if good else "*** FAIL: a uniform shift changed the verdict"))
    one = decode([D_A + 1] + [0] * 9, "c_one")
    print("    ONE edge shifted by %-4d spread=%-3d sigrok %-6s %s"
          % (D_A + 1, one.get("spread"), "CONF" if one.get("conforms") else "VIOL",
             "OK -- a single-edge shift DOES change it"
             if not one.get("conforms") else "*** FAIL: must-fire arm did not fire"))
    c_ok = c_ok and not one.get("conforms")
    print("    (c) uniform invisible AND single-edge visible: %s"
          % ("PASS" if c_ok else "*** FAIL -- D_i is not purely differential ***"))
    print()

    # ---- arm (b): end-to-end, schedule -> waveform -> sigrok -----------
    print("  --- ARM (b): END-TO-END, no hand-built waveform ---")
    print("    simulating every release offset x every tie-break...")
    best = max_spread(LANES, 0)
    if best is None:
        print("    *** FAIL: simulator produced no usable run")
        return 1
    print("    max observed response r_A        = %d   (recurrence: %d)"
          % (best["max_r"], rA))
    print("    max observed start-delay spread  = %d   (r_A - C_A: %d)"
          % (best["spread"], dmax))
    b_match = (best["spread"] == dmax) and (best["max_r"] == rA)
    print("    FALSIFIER (b): %s"
          % ("reachable spread == r-C and response == r_A -- the recurrence and"
             " the schedule agree" if b_match else
             "*** reachable spread %d != r-C %d (or r %d != %d) -- recurrence or"
             " schedule model is WRONG, this is a finding ***"
             % (best["spread"], dmax, best["max_r"], rA)))
    win, wsp = window_of_max_spread(best["deltas"])
    print("    worst 10-action window from that schedule: %s  spread %d"
          % (win, wsp))
    res = decode(win, "b_sched")
    if not res["ok"]:
        print("    *** %s" % res["why"])
        return 1
    print("    rendered from those delays, sigrok reads: %s (0x%02X)"
          % ("CONF" if res["conforms"] else "VIOL", res["decoded"] or 0))
    b_ok = b_match and res["conforms"]
    print("    (b) a schedule-derived worst case at spread %d still conforms: %s"
          % (res["spread"], "PASS" if b_ok else "*** FAIL ***"))
    print()

    ok = a_ok and a_reason and c_ok and b_ok
    print("=" * 78)
    print("  GATE 0.9: %s" % ("PASSED -- the differential reading is adjudicated."
                              if ok else "FAILED -- the reading is NOT established."))
    if ok:
        print("  Consequences, now licensed: feasibility is (r_i - C_i) <= D_i;")
        print("  every A2 margin gains C_i; the EDF key is D_i + C_i.")
        print("  ⛔ ETHERNET REMAINS UNSETTLED -- its D = 2 is a modelled stand-in")
        print("     (O4), and spec C3's grid-quantization check is independent of")
        print("     this gate and has not run. Do NOT reinstate Ethernet here.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
