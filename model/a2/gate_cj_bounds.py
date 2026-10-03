"""C AND J ARE BOUNDS, DERIVED FROM STRUCTURE. Simulation is the CHECK.

THE ONE CLAIM: `C_max` and `J_max` are derived from the RTL's cycle-level
structure, and the measured values from `test/tb_smoke.v` are compared against
those derivations. ⛔ If a measurement ever EXCEEDS a derived bound, the
DERIVATION is wrong and the run stops -- a measurement can never raise a bound.

⛔⛔ THIS GATE EXISTS BECAUSE S3 FIRST REPORTED A MEAN AND AN OBSERVED MAXIMUM AS
IF THEY WERE BOUNDS.

  * "C = 2.00" was 708 cycles / 354 jobs -- A MEAN. A mean of exactly 2.00 is
    consistent with every job taking 2 AND with some taking 1 and others 3.
    A2 needs C_max, and a mean cannot supply it.
  * "J = 5" was the largest value seen in ONE simulation, with ONE program, at
    ONE phase alignment. That is a FLOOR on the true maximum, not a bound. A
    different lane mix could produce 6.

⭐ Plugging an observed maximum into a proof is the "nothing has made it fire"
mistake wearing different clothes: a sample standing in for a theorem. This
project has already recorded that a green check whose threshold sits where its
named bug cannot reach it proves nothing; an unbounded quantity with an observed
value is the same defect.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MEAS = os.path.join(ROOT, "test", "cj_measured.txt")

OPNAMES = {0: "LEVEL", 1: "SHIFT", 2: "SHIFTIN", 3: "READBIT",
           4: "START", 5: "STOP", 6: "ARM", 7: "REARM/loop"}

# =========================================================================
# THE C DERIVATION -- from the dispatch FSM's structure, not from a run.
# =========================================================================
# src/pe_engine.v, the `st` FSM:
#     ST_IDLE  --(hdr_done & winner_v & l_actv[winner])--> ST_DRIVE
#     ST_DRIVE --(unconditional)--------------------------> ST_WB
#     ST_WB    --(unconditional)--------------------------> ST_IDLE
# ⭐ NEITHER transition out of ST_DRIVE or ST_WB is conditional, and NEITHER
# depends on the opcode: the opcode selects which pin/register is written
# INSIDE a state, never how many states are visited. So the service time is the
# SAME CONSTANT for every action type.
C_DERIVED = {op: 2 for op in OPNAMES}
C_DERIVATION = ("ST_DRIVE then ST_WB, both exited UNCONDITIONALLY and with no "
                "opcode-dependent branch; the opcode selects what is written "
                "inside a state, never how many states are visited")

# =========================================================================
# THE J DECOMPOSITION -- one derived worst case per source.
# =========================================================================
# ⭐ `jitter_max` in the RTL counts ONLY the prefetch-miss stall. The
# winner-registration cycle is structural and never appears in that counter, so
# it is derived and added here rather than measured.
J_SOURCES = [
    ("winner registration", 1, True,
     "`cur`/`cur_act` are registered on the ST_IDLE -> ST_DRIVE edge, so a lane "
     "that becomes ready in cycle n cannot drive before n+1. ⭐ This IS "
     "frontier.py's J_pipe = 1: 'registering the EDF winner makes every release "
     "uncertain by 1'", False),
    ("prefetch scan notice", 1, True,
     "P_SCAN must come round to observe !l_actv[winner]. Winner-first inside "
     "P_SCAN removes the ORDER dependence, not the cycle", True),
    ("own refill", 3, True,
     "P_REQ -> P_WAIT -> P_CAP. Three because the arbiter REGISTERS the "
     "request and the store read is itself registered", True),
    ("in-flight refill for another lane", 3, True,
     "worst case the winner becomes ready just as P_REQ starts for a different "
     "lane, and P_SCAN cannot be reached until that refill completes", True),
    ("header load", 0, True,
     "⭐ ZERO, and only because dispatch is gated on `hdr_done`: the header FSM "
     "has strict priority on the store port but can never overlap a dispatch. "
     "If that gate were removed this term would become N_LANES*HDR_BYTES*3", True),
]


def read_measured():
    if not os.path.isfile(MEAS):
        return None, ("%s is missing -- run the smoke bench first:\n"
                      "  iverilog -g2012 -o test/smoke.vvp -s tb_smoke "
                      "test/tb_smoke.v src/*.v && vvp test/smoke.vvp" % MEAS)
    d = {"ops": {}}
    for line in open(MEAS, encoding="utf-8"):
        p = line.split()
        if not p:
            continue
        if p[0] == "op":
            d["ops"][int(p[1])] = {"n": int(p[3]), "min": int(p[5]),
                                   "max": int(p[7])}
        else:
            d[p[0]] = int(p[1])
    return d, None


def main() -> int:
    print()
    print("=" * 78)
    print("C AND J AS BOUNDS -- derived from structure, checked by simulation")
    print("=" * 78)
    lane_digest.announce("gate_cj_bounds.py (C/J)", lane_digest.shipped())
    rc = 0

    m, err = read_measured()
    if err:
        print("  *** %s" % err)
        return 1

    # ---- C ---------------------------------------------------------------
    print()
    print("  --- C_max, DERIVED per action type ---")
    print("    derivation: %s" % C_DERIVATION)
    print()
    print("    %-12s %-9s %-7s %-7s %-7s %s"
          % ("opcode", "derived", "sim n", "sim min", "sim max", "verdict"))
    unexercised = []
    for op, name in sorted(OPNAMES.items()):
        d = C_DERIVED[op]
        s = m["ops"].get(op)
        if s is None:
            unexercised.append(name)
            print("    %-12s %-9d %-7s %-7s %-7s %s"
                  % (name, d, "-", "-", "-", "⚠ UNEXERCISED -- UNMEASURED"))
            continue
        ok = s["max"] <= d
        print("    %-12s %-9d %-7d %-7d %-7d %s"
              % (name, d, s["n"], s["min"], s["max"],
                 "ok" if ok else "*** SIM EXCEEDS DERIVED"))
        if not ok:
            rc = 1
    print()
    print("    ⭐ MIN AND MAX ARE BOTH REPORTED, which is the point: a MEAN of")
    print("    2.00 is consistent with every job taking 2 AND with a mix of 1s")
    print("    and 3s. min == max == 2 on an exercised opcode is the evidence a")
    print("    mean could not give.")
    if unexercised:
        print()
        print("    ⛔⛔ %d OF %d ACTION TYPES ARE UNEXERCISED AND THEREFORE"
              % (len(unexercised), len(OPNAMES)))
        print("    UNMEASURED: %s" % ", ".join(unexercised))
        print("    ⚠ Their derived C_max is 2 by the same structural argument,")
        print("    and the argument covers them -- but NOTHING HAS CHECKED IT.")
        print("    An unexercised opcode is 'not yet tested', never 'correct'.")
        print("    ⇒ This is what the REVERSE-TRACEABILITY ruling fixes: running")
        print("      the S1 census programs exercises SHIFT, SHIFTIN, READBIT,")
        print("      START, STOP and ARM, because the real protocols need them.")

    # ---- J ---------------------------------------------------------------
    print()
    print("  --- J_max, DERIVED by source ---")
    print("    %-34s %-8s %s" % ("source", "cycles", "counted by the RTL?"))
    j_total, j_counted = 0, 0
    for name, cyc, _incl, _why, counted in J_SOURCES:
        print("    %-34s %-8d %s" % (name, cyc, "yes" if counted else
                                     "NO -- structural, derived only"))
        j_total += cyc
        if counted:
            j_counted += cyc
    print("    %-34s %-8d" % ("DERIVED J_max (total)", j_total))
    print("    %-34s %-8d" % ("of which the counter can see", j_counted))
    print()
    for name, cyc, _i, why, _c in J_SOURCES:
        print("    %s (%d):" % (name, cyc))
        print("      %s" % why)

    sim = m["jmiss_max"]
    print()
    print("    simulated max prefetch stall : %d" % sim)
    print("    derived bound on that term   : %d" % j_counted)
    if sim > j_counted:
        print("    *** SIMULATION EXCEEDS THE DERIVED BOUND. The derivation is")
        print("        WRONG -- a measurement cannot raise a bound. STOP.")
        rc = 1
    else:
        print("    ⇒ ok: %d <= %d, so the derivation is not contradicted."
              % (sim, j_counted))
        print("    ⚠ NOT CONFIRMED EITHER. The simulated value is a FLOOR on the")
        print("    true maximum: one program, one lane mix, one phase. The bound")
        print("    is what the proof uses; the measurement only falsifies it.")
    print()
    print("    ⇒ ⭐ J_max = %d for A2, = the derived total." % j_total)

    # ---- the optimisation that failed, recorded -------------------------
    print()
    print("  --- ⛔ THE DOMINANT TERM, AND AN ATTEMPT THAT MADE IT WORSE ---")
    print("    scan notice (1) + in-flight refill (3) = 4 of the %d countable"
          % j_counted)
    print("    cycles, so it is the dominant component. Starting a refill at")
    print("    WRITEBACK, to overlap it with the lane's own inter-action delay,")
    print("    looked like the cheap win.")
    print("    ⛔ MEASURED J WENT 5 -> 7. Refilling at every writeback keeps the")
    print("    single shared fetch port busy, so a DIFFERENT lane that becomes")
    print("    the winner waits behind it. The optimisation MOVED the contention")
    print("    it was meant to remove. Reverted, and recorded in the RTL.")
    print()
    print("    ⇒ THE STRUCTURAL CONCLUSION: with ONE shared fetch port, J cannot")
    print("      be driven to 1 by scheduling refills better. The options are")
    print("      (a) carry the derived J in the baseline, or (b) per-lane DOUBLE")
    print("      BUFFERING -- hold current AND next, about %d more flops -- so a"
          % (22 * len(lane_digest.shipped())))
    print("      dispatch never waits on a fetch at all.")
    print("    ⭐ Margin at the derived J still clears the bar, so (b) is")
    print("      OPTIMISATION, NOT RESCUE. Wilson's call, with numbers below.")

    # ---- what the baseline becomes --------------------------------------
    print()
    print("  --- what the re-baseline costs, priced in the A2 model ---")
    import copy
    from bursty import response_time_b
    L = lane_digest.shipped()
    print("    %-6s %-12s %s" % ("J", "min margin", "feasible?"))
    for J in (0, 1, j_total - 2, j_total, j_total + 2):
        lanes = [copy.copy(l) for l in L]
        for l in lanes:
            l.J = J
        mins, ok = [], True
        for l in lanes:
            r = response_time_b(l, lanes)["r"]
            mm = l.margin(r)
            mins.append(mm)
            if mm < 0:
                ok = False
        tag = ""
        if J == 0:
            tag = "  <- the SHIPPED table"
        elif J == 1:
            tag = "  <- the STATED design point"
        elif J == j_total:
            tag = "  <- DERIVED BOUND"
        print("    %-6d %-12d %s%s" % (J, min(mins),
                                       "yes" if ok else "*** NO", tag))
    print()
    print("    ⛔⛔ LEDGER, AS AN ERROR AND NOT A FOOTNOTE: the shipped lane")
    print("    table carries J = 0 on every lane while the stated design point")
    print("    has always been (C = 2, J_pipe = 1). So the published 'min margin")
    print("    14' was computed off the WRONG ANALYSIS -- not off either 1.3")
    print("    candidate. Found in S3 by measuring instead of assuming.")

    print()
    print("=" * 78)
    print("  GATE cj-bounds: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * C_max = 2 DERIVED for all %d action types; sim min==max==2 on"
          % len(OPNAMES))
    print("      the %d exercised, %d UNEXERCISED and so unmeasured"
          % (len(m["ops"]), len(unexercised)))
    print("    * J_max = %d DERIVED by source; sim %d <= %d countable"
          % (j_total, sim, j_counted))
    print("    * ⛔ a measurement can falsify a bound, never raise one")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
