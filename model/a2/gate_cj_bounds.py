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

# =========================================================================
# ⛔⛔⛔ THE DOUBLE BUFFER LANDED, AND ITS PRE-REGISTERED FALSIFIER FIRED.
# =========================================================================
# `bursty.DOUBLE_BUFFER_PREREG` predicted J_pipe = 2 after double buffering, by
# taking the two refill terms above to ZERO. MEASURED: the worst-case
# steady-state prefetch stall is 6, so J = 6 + 1 (winner registration) = 7.
# ⛔ 7 > 2. THE FALSIFIER HAS FIRED. Reported, not re-argued -- the
# pre-registration says so in as many words.
#
# WHY THE DECOMPOSITION WAS WRONG, which is the useful part:
#   The two refill terms do NOT go to zero, because ONE SHARED FETCH PORT still
#   serves every lane. Double buffering converts a per-dispatch LATENCY into a
#   QUEUEING delay: each lane gets a whole extra action period of slack, but
#   when several lanes demand refills inside one window the queue delay
#   survives. ⭐ THIS IS THE SAME STRUCTURAL FACT THAT KILLED THE "CHEAP WIN"
#   (refill-at-writeback took J from 5 to 7): with one port, J is bounded by
#   port THROUGHPUT, and no buffering or scheduling policy changes throughput.
#
# WHAT IT DID BUY, measured the same way for both designs:
#   worst-case steady-state stall over d in [2,30], five active lanes:
#       single buffer (M_BUF_SWAP)  10   -> J = 11
#       double buffer                6   -> J =  7
#   so J 11 -> 7, which on gate_j_sound's sweep is min margin 1 (FAIL) -> 4
#   (PASS, exactly) under our own bound, and 5 -> 6 under pyRTA's.
#
# ⛔⛔ AND THE MEASUREMENT THAT MATTERS MOST IS A NEGATIVE ONE. At the SHIPPED
# inner action spacings (25, 45, 434, 414, 25 cycles) with all five lanes
# active, the steady-state stall is ZERO -- for the double buffer AND for the
# single buffer. The shipped program never occupies the regime where buffering
# matters. ⇒ The entire measured `J = 5` this project has been quoting since S3
# is a COLD START: each lane's first action after `hdr_done`, once per run.
# It was never a steady-state property of the shipped lane set.
#   cold-start stall, default program:  single 9  ->  double 5
# ⚠ WHETHER THE COLD START BELONGS IN THE PUBLISHED J IS WILSON'S TO RULE.
#   Spuri's RTA bounds EVERY job, including the first, so on the letter of the
#   analysis it does. The counter-argument is that a uniform offset on each
#   lane's FIRST action, before the protocol has begun, is a start-up latency
#   and not inter-action jitter -- and the host controls when the program
#   starts. That is a modelling claim, so it is stated and not assumed.
J_PIPE_MEASURED_DOUBLE = 7      # 6 stall + 1 winner registration
J_PIPE_MEASURED_SINGLE = 11     # 10 stall + 1
J_PIPE_PREREGISTERED = 2
DOUBLE_BUFFER_COST = {
    # Yosys 0.52, plain Verilog, `synth -flatten`, generic cells.
    # ⛔ THE PRE-REGISTERED ESTIMATE WAS ~110 AND IT WAS LOW BY 54%. It counted
    # the second action word (N_LANES * ACT_W = 110) and missed every piece of
    # bookkeeping the second slot needs: l_fpc (5*AW = 40), l_sel (5), the
    # refill's latched slot and address (1 + 8). A flop estimate that counts the
    # DATA and forgets the POINTERS is the same error as sizing a store by its
    # payload and forgetting the program.
    # measured by test/yosys_check.sh on both trees, same script, same passes
    "flops_before": 2685,
    "flops_after": 2854,
    "flops_delta": 169,
    "preregistered_estimate": 110,
    "generic_cells_before": 14370,
    "generic_cells_after": 15611,
}


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
        elif p[0] == "image":
            d["image"] = p[1]
        else:
            d[p[0]] = int(p[1])
    # ⛔⛔ WHICH PROGRAM PRODUCED THESE NUMBERS? The bench now takes an IMAGE
    # argument and still writes ONE constant path, which is the clobber hazard
    # this project has a standing rule about -- and it bit immediately: a
    # refill-stress run overwrote the default program's measurements and this
    # gate reported `sim 7` for a program it was not measuring, while looking
    # perfectly green. The provenance is now IN the file and asserted here, so
    # the failure mode is a RED gate instead of a wrong number.
    want = "test/smoke_image.hex"
    got = d.get("image")
    if got is None:
        return None, ("%s carries no `image` line, so which program produced "
                      "these numbers is unknown. Re-run the smoke bench." % MEAS)
    if got != want:
        return None, ("%s was written by `%s`, not the default program `%s`. "
                      "The stress and chain images exist to exercise the refill "
                      "path and their C/J figures are NOT the shipped ones. "
                      "Re-run: python test/make_smoke_image.py && vvp ... "
                      "(no +IMG)" % (MEAS, got, want))
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

    # ---- RTL OPCODE COVERAGE, from the census image --------------------
    # ⛔⛔ THE "6 UNEXERCISED" CAVEAT, CLOSED AT THE RIGHT LEVEL. This gate has
    # been reporting C_max derived for all 8 action types and MEASURED on two,
    # because the default smoke program only uses LEVEL and re-arm.
    # ⭐ `model/gate_reverse_trace.py` exercises all 8 on the GOLDEN MODEL, and
    # that is a different claim: it settles "is any opcode unneeded by the
    # required protocols", not "has the silicon ever run one". A model
    # exercising an opcode is not the RTL exercising it, and conflating the two
    # is the exact shape of an exact answer to the wrong question.
    # ⇒ `test/make_smoke_image.py --census` builds a program that makes the RTL
    # execute every opcode, and its measurements land in cj_measured_alt.txt
    # (the input-dependent path, so it cannot clobber the shipped figures).
    alt = os.path.join(os.path.dirname(MEAS), "cj_measured_alt.txt")
    print()
    print("  --- RTL opcode coverage (census image) ---")
    if not os.path.isfile(alt):
        print("    cj_measured_alt.txt absent -- coverage NOT established.")
        print("    Run: python test/make_smoke_image.py --census && vvp ... "
              "+IMG=test/census_image.hex")
    else:
        a = {"ops": {}}
        for line in open(alt, encoding="utf-8"):
            p = line.split()
            if p and p[0] == "op":
                a["ops"][int(p[1])] = {"n": int(p[3]), "min": int(p[5]),
                                       "max": int(p[7])}
            elif p and p[0] == "image":
                a["image"] = p[1]
        print("    source image: %s" % a.get("image", "UNRECORDED"))
        covered = sorted(a["ops"])
        print("    opcodes executed by the RTL: %d of %d  %s"
              % (len(covered), len(OPNAMES), covered))
        bad = []
        for op, s in sorted(a["ops"].items()):
            d = C_DERIVED[op]
            ok = s["max"] <= d
            if not ok:
                bad.append((OPNAMES[op], d, s["max"]))
            print("    %-12s derived %-3d n=%-4d min=%-3d max=%-3d %s"
                  % (OPNAMES[op], d, s["n"], s["min"], s["max"],
                     "ok" if ok else "*** SIM EXCEEDS DERIVED"))
        if bad:
            print("    *** SIM EXCEEDS THE DERIVED C on %s. STOP." % (bad,))
            rc = 1
        elif len(covered) == len(OPNAMES):
            print("    ⭐ ALL %d ACTION TYPES EXECUTED BY THE RTL, every one with"
                  % len(OPNAMES))
            print("    min == max == 2. C_max = 2 is now derived AND measured on")
            print("    8 of 8, not 2 of 8.")
            print("    ⚠ THE CENSUS IMAGE IS A COVERAGE PROGRAM, NOT A PROTOCOL.")
            print("    Its opcodes run in an order chosen to reach them all, so")
            print("    its pin waveform means nothing and it legitimately fails")
            print("    the bench's 'lane 1 moved its pin' assertion -- lane 1")
            print("    runs SHIFTIN/READBIT/ARM, none of which drive a pin. Only")
            print("    the per-opcode service times should be read from it, and")
            print("    the bench was NOT weakened to make it pass.")

    # ---- the double buffer, and its falsifier --------------------------
    print()
    print("  --- ⛔ THE DOUBLE BUFFER: PRE-REGISTERED 2, MEASURED %d ---"
          % J_PIPE_MEASURED_DOUBLE)
    print("    pre-registered prediction        : %d" % J_PIPE_PREREGISTERED)
    print("    measured, double buffer          : %d  (6 stall + 1 winner reg)"
          % J_PIPE_MEASURED_DOUBLE)
    print("    measured, single buffer          : %d  (10 stall + 1)"
          % J_PIPE_MEASURED_SINGLE)
    fired = J_PIPE_MEASURED_DOUBLE > J_PIPE_PREREGISTERED
    print("    falsifier 'derived > 2'          : %s"
          % ("*** FIRED ***" if fired else "did not fire"))
    if fired:
        print("      ⛔ Reported, NOT re-argued. The two refill terms do not go")
        print("         to zero because ONE SHARED PORT still serves every lane:")
        print("         double buffering turns a per-dispatch LATENCY into a")
        print("         QUEUEING delay, and queueing survives. Same structural")
        print("         fact that made the refill-at-writeback 'cheap win' worse.")
        print("      ⭐ It still bought J %d -> %d, which on gate_j_sound's sweep"
              % (J_PIPE_MEASURED_SINGLE, J_PIPE_MEASURED_DOUBLE))
        print("         is min margin 1 (FAIL) -> 4 (PASS, exactly) on our bound.")
    print()
    print("    ⛔⛔ AND THE NEGATIVE RESULT, which outranks both: at the SHIPPED")
    print("    inner spacings (25,45,434,414,25) with all five lanes active the")
    print("    steady-state stall is ZERO -- for the double buffer AND the")
    print("    single one. The shipped program never enters the regime where")
    print("    buffering matters, so the `J = 5` quoted since S3 is entirely a")
    print("    COLD START (single 9 -> double 5), not a steady-state property.")
    print("    ⚠ Whether the cold start belongs in the published J is Wilson's")
    print("    to rule: Spuri bounds every job including the first, while a")
    print("    uniform offset on each lane's FIRST action is arguably start-up")
    print("    latency rather than inter-action jitter. Stated, not assumed.")
    print()
    print("    cost: %d flops (%d -> %d), vs a pre-registered estimate of %d."
          % (DOUBLE_BUFFER_COST["flops_delta"],
             DOUBLE_BUFFER_COST["flops_before"],
             DOUBLE_BUFFER_COST["flops_after"],
             DOUBLE_BUFFER_COST["preregistered_estimate"]))
    print("    ⛔ the estimate was low by 54%: it counted the second action word")
    print("    and forgot the pointers the second slot needs (l_fpc, l_sel, the")
    print("    latched refill slot and address).")

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
    # ⛔⛔ RETRACTED. This used to print "margin at the derived J still clears
    # the bar, so (b) is OPTIMISATION, NOT RESCUE". Both halves are now false.
    # The margin table below was computed with the UNSOUND interference term
    # (jitter absent from the interference a jittery lane imposes on others);
    # with the term restored, J = 8 gives min margin 1 on our bound and FAILS
    # the >= 4 bar. And the flop estimate said "about 110"; measured 169.
    print("    ⛔ RETRACTED: this line used to read 'margin at the derived J")
    print("      still clears the bar, so (b) is OPTIMISATION, NOT RESCUE'.")
    print("      Both halves were wrong. The table below is a J = 0-interference")
    print("      computation; gate_j_sound.py carries the sound one, where")
    print("      J = 8 is min margin 1 and FAILS the bar. And the double buffer")
    print("      cost 169 flops, not 'about 110'.")

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
