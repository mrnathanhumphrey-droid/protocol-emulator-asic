"""SPEC 1.3 -- the microarchitecture sketch, CHECKED against the 1.2 frontier.

THE ONE CLAIM: the sketch's per-stage cycle counts add up to a (C, J) that 1.2
says is admissible -- and the two architectural decisions (pipeline, C9) are
COUPLED, so they cannot be taken separately.

⛔⛔ THIS IS A SKETCH AND IT IS FLAGGED BACK BEFORE RTL. Nothing here is built.
Every count below is an ESTIMATE with its basis named, and the three that cannot
be known before synthesis carry an explicit fallback. A sketch whose numbers are
not separable into "derived", "estimated" and "unknowable yet" is a sketch that
will be quoted as a measurement.

⭐⭐ THE FINDING 1.2 COULD NOT SEE: THE PIPELINE AND C9 ARE ONE DECISION.
1.2 reported the two pipeline candidates TIED at minimum margin 12 under both C9
variants, and concluded that 1.3 must choose on area and critical path. That is
right as far as it goes, and it misses a structural constraint that is not in
the schedulability model at all:

    C9 = START means the pin moves in the FIRST cycle of service.
    The pin's value comes from the descriptor.
    An unpipelined engine READS the descriptor in its first cycle.

So an unpipelined engine CANNOT drive at START -- the value does not exist yet.
C9 = COMPLETION is not a choice there, it is forced. A pipelined engine has
already fetched the descriptor, so START is available and free.

    unpipelined  =>  C = 3, J = 0, C9 = COMPLETION forced
    pipelined    =>  C = 2, J = 1, C9 = START available

That turns a tie into a 4-cycle difference on the binding reactive lane
(SPI-target margin 12 vs 16), and it is computed below rather than argued.

⛔ AND IT STILL DOES NOT RESTORE 2 MHz, WHICH I EXPECTED IT TO. At the best
configuration SPI-target's 2 MHz absolute margin is 3 cycles -- one short of the
>= 4 bar. R1 cost this lane 2 cycles of budget by reordering EDF; pipelining and
C9 = START give 3 back; the bar needs 4. 1 MHz remains the declared rate under
every candidate, and no architectural choice in this sketch changes that.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bursty import (L_JIT, L_SYNC, OUT_REG, TSU_MASTER,            # noqa: E402
                    abs_tolerance)
from frontier import BAR, evaluate                                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- item 1: the service pipeline, stage by stage -----------------------
# (stage, cycles, basis)
#   "derived"   -- follows from something already measured or proved
#   "estimated" -- a judgement with its reasoning stated
#   "post-RTL"  -- cannot be known before synthesis; carries a FALLBACK
UNPIPELINED = [
    ("fetch descriptor from the store", 1, "derived",
     "one synchronous read of the register file; the store is already a "
     "synchronous array in src/project.v"),
    ("compute next timestamp + select EDF winner", 1, "estimated",
     "one add (now + delay) and a 5-way min over 16-bit keys; 3 comparator "
     "levels, well inside a 20 ns cycle given the worst flop path today is "
     "10.82 ns"),
    ("drive pin + write descriptor back", 1, "derived",
     "one array write and one output register load"),
]
PIPELINED = [
    ("drive pin (descriptor PREFETCHED) + select next winner", 1, "estimated",
     "the pin value is already in the pipeline register, so the drive is a "
     "register-to-pad path; the EDF select runs in parallel on last cycle's "
     "timestamps -- which IS the J = 1"),
    ("compute next timestamp + write back + prefetch next", 1, "estimated",
     "one add, one array write, one array read; the read lands in the pipeline "
     "register and NOTHING combinational follows it"),
]

CANDIDATES = [
    ("unpipelined", UNPIPELINED, 0, [True],
     "C9 = COMPLETION is FORCED: the descriptor is not read until cycle 1, so "
     "the pin cannot move before cycle 3"),
    ("pipelined", PIPELINED, 1, [False, True],
     "C9 = START is AVAILABLE: the descriptor is prefetched, so the pin value "
     "exists at the start of service"),
]

# ---- item 6: where the critical path sits ------------------------------
# From docs/SILICON_EVIDENCE.md, slow corner nom_slow_1p08V_125C:
SLOW_PERIOD_NS = 20.0
WNS_NS = 1.5612          # worst setup slack, ALL paths
WORST_FLOP_SLACK_NS = 9.18   # worst slack at a FLOP endpoint


def used(slack_ns: float) -> float:
    return SLOW_PERIOD_NS - slack_ns


def spi_target_rate_margins(rc: int, C: int, c9_completion: bool) -> list:
    """SPI-target's ABSOLUTE margin per SCLK rate. The lane C9 is worth MHz on."""
    out = []
    for mhz in (1, 2, 2.5, 3):
        half = 25.0 / mhz
        budget = L_SYNC + rc + OUT_REG + (C if c9_completion else 0)
        out.append((mhz, int(half - TSU_MASTER - budget)))
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 1.3 -- microarchitecture sketch, checked against 1.2")
    print("=" * 78)
    rc_gate = 0

    # ---- items 1 + 3, together, because they are one decision ----------
    print()
    print("  ITEMS 1 + 3 -- the service pipeline AND C9, which are coupled")
    print("  " + "-" * 74)
    results = {}
    for name, stages, j_pipe, c9s, note in CANDIDATES:
        C = sum(c for _s, c, _b, _w in stages)
        print()
        print("  %s: C = %d, J_pipe = %d" % (name.upper(), C, j_pipe))
        print("    %-52s %-7s %s" % ("stage", "cycles", "basis"))
        for s, c, basis, why in stages:
            print("    %-52s %-7d %s" % (s, c, basis))
            print("        %s" % why)
        print("    => C = %d cycles, J_pipe = %d" % (C, j_pipe))
        print("    ⛔ %s" % note)
        for c9 in c9s:
            m, rows = evaluate(C, j_pipe, c9)
            tag = "COMPLETION" if c9 else "START"
            if m is None:
                print("    C9 = %-10s -> NOT ADMISSIBLE (%s)" % (tag, rows))
                rc_gate = 1
                continue
            sp = [(l, rr) for l, rr in rows if l.name.startswith("SPI-target")][0]
            bind = min(rows, key=lambda x: x[1]["margin"])[0].name
            ok = m >= BAR
            results[(name, c9)] = (m, sp[1]["margin"], sp[1]["r"] - sp[0].C, C)
            print("    C9 = %-10s min margin %-4d binding lane %-20s "
                  "SPI-target margin %-4d %s"
                  % (tag, m, bind, sp[1]["margin"],
                     "ok" if ok else "*** BELOW THE >= %d BAR ***" % BAR))
            if not ok:
                rc_gate = 1

    # ---- the gate 1.3 is required to pass ------------------------------
    print()
    print("  GATE: every candidate's (C, J) must be inside 1.2's frontier")
    print("  " + "-" * 74)
    for (name, c9), (m, spm, rc_sp, C) in sorted(results.items()):
        print("    %-12s C9=%-11s C=%d J=%d  min margin %-3d  %s"
              % (name, "COMPLETION" if c9 else "START", C,
                 1 if name == "pipelined" else 0, m,
                 "INSIDE the frontier" if m >= BAR else "*** OUTSIDE ***"))

    # ---- what the coupling is worth ------------------------------------
    print()
    print("  WHAT THE COUPLING IS WORTH (and what it is not)")
    print("  " + "-" * 74)
    unp = results[("unpipelined", True)]
    pip = results[("pipelined", False)]
    print("    forced  unpipelined + C9=COMPLETION : SPI-target margin %d" % unp[1])
    print("    chosen  pipelined   + C9=START      : SPI-target margin %d" % pip[1])
    print("    => %d cycles on the binding REACTIVE lane, from a decision 1.2"
          % (pip[1] - unp[1]))
    print("       reported as a TIE. The minimum margin is 12 either way, so the")
    print("       gain is entirely in SPI-target's frequency headroom.")
    print()
    print("    %-30s %s" % ("SPI-target absolute margin",
                            "  ".join("%gMHz" % r for r, _ in
                                      spi_target_rate_margins(0, 2, False))))
    for label, (m, spm, rc_sp, C) in (("unpipelined, C9=COMPLETION", unp),
                                      ("pipelined, C9=START", pip)):
        c9 = "COMPLETION" in label
        ms = spi_target_rate_margins(rc_sp, C, c9)
        print("    %-30s %s"
              % (label, "  ".join("%6d" % v for _r, v in ms)))
    print("    bar is >= %d" % BAR)
    print()
    print("    ⛔ 2 MHz IS STILL OUT OF REACH. Best case is margin %d -- one short."
          % [v for r, v in spi_target_rate_margins(pip[2], pip[3], False)
             if r == 2][0])
    print("       R1 cost this lane 2 cycles by reordering EDF; pipelining plus")
    print("       C9 = START give 3 back; the bar wants 4. 1 MHz stays declared")
    print("       under every candidate, and no choice in this sketch moves it.")

    # ---- robustness to the C measurement -------------------------------
    print()
    print("  ROBUSTNESS TO THE C MEASUREMENT, which is the real tiebreak")
    print("  " + "-" * 74)
    print("    C is UNMEASURED. The honest comparison is not the design point")
    print("    but what happens when the measurement comes in one cycle high:")
    print("    %-34s %-14s %-14s %s"
          % ("candidate", "as designed", "C + 1", "degradation"))
    for label, C, j, c9 in (("unpipelined C=3 J=0, COMPLETION", 3, 0, True),
                            ("pipelined   C=2 J=1, START", 2, 1, False)):
        a, _ = evaluate(C, j, c9)
        b, _ = evaluate(C + 1, j, c9)
        print("    %-34s %-14d %-14s %s"
              % (label, a, b if b is not None else "n/a",
                 "-%d" % (a - b) if b is not None else "falls off"))
    print("    ⭐ Both still clear the bar, but the pipelined point loses 1 cycle")
    print("    where the unpipelined loses 3 -- because an extra service cycle")
    print("    is charged to every lane's r AND (on the reactive lane) to its")
    print("    D_tol, while an extra jitter cycle is charged once. The reserve is")
    print("    the whole reason the >= %d bar exists, so sensitivity to the" % BAR)
    print("    unmeasured quantity is the right tiebreak, not the design point.")

    # ---- item 2 ---------------------------------------------------------
    print()
    print("  ITEM 2 -- the EDF winner")
    print("  " + "-" * 74)
    print("    key = D_sched + C_i, compared as an ABSOLUTE deadline")
    print("          release_time + D_sched_i + C_i")
    print("    5 live lanes -> a 5-way min: 2 levels of 2-way compare plus one.")
    print("    ⛔ Only LIVE lanes enter the tree. A lane with no pending event")
    print("       must be MASKED, not given a large key -- a large key is a")
    print("       value that can be reached by a real deadline after a wrap,")
    print("       and then an idle lane wins.")
    print("    ⛔ D_sched, not D_tol (spec R2). The key is the design's deadline;")
    print("       the tolerance is what admissibility checks. Part 1 ships them")
    print("       equal, so the RTL must read D_sched and not 'the deadline'.")
    print("    ⚠ post-RTL: the comparator tree's depth in ns. FALLBACK if it")
    print("      does not meet timing -- register the winner one level earlier,")
    print("      which costs J = 2 and is still inside the frontier (margin %d)."
          % (evaluate(2, 2, False)[0]))

    # ---- item 4 ---------------------------------------------------------
    print()
    print("  ITEM 4 -- the reactive release path")
    print("  " + "-" * 74)
    print("    3-FF synchroniser -> edge detect -> release, per reactive input.")
    print("    L_sync = %d cycles latency, L_jit = %d cycle uncertainty -- read"
          % (L_SYNC, L_JIT))
    print("    off `reg [2:0] wr_sync` in src/project.v, not assumed.")
    print("    ⭐ ONE mechanism serves FOUR things, which is why R3 was free:")
    print("      * I2C high-phase release (REACTIVE-J, carries J = %d)" % L_JIT)
    print("      * I2C SDA sample, FOLDED into that same release (spec R3)")
    print("      * the I2C clock-stretch wait -- the same observed-rise signal")
    print("      * UART-rx start-edge detect (REACTIVE-anchor)")
    print("    ⛔ THE STRETCH WAIT MUST BE A HARDWARE CONDITION ON THE LANE, never")
    print("       engine occupancy. A busy-wait makes C unbounded, and B_i is")
    print("       max(C_j - 1) over later-deadline lanes, so ONE busy-wait makes")
    print("       EVERY lane infeasible (bursty.clock_stretch(): U = 80.7).")

    # ---- item 5 ---------------------------------------------------------
    print()
    print("  ITEM 5 -- C2: how a release is timed. BOTH priced, not chosen here")
    print("  " + "-" * 74)
    N = 16
    nl = 5
    print("    (a) RELATIVE down-counter per lane")
    print("        cost   %d x %d-bit decrementer, %d x zero-detect" % (nl, N, nl))
    print("        ⭐ no wrap condition AT ALL -- 'time to deadline' is directly")
    print("           comparable, so the EDF key needs no modular compare and")
    print("           1.6 loses an admissibility condition.")
    print("        ⛔ every counter must tick EVERY cycle (%d adders switching"
          % nl)
    print("           continuously -- power, on a 2.09 mW design), and a delay")
    print("           longer than %d cycles needs explicit chaining." % (2 ** N - 1))
    print("    (b) ABSOLUTE counter + wrap-safe compare")
    print("        cost   1 x %d-bit incrementer, %d x %d-bit modular compare"
          % (N, nl, N))
    print("        ⭐ ONE adder instead of %d, and the descriptor already stores" % nl)
    print("           a 'next-action timestamp' (ARCH_PREREG_01), so this is the")
    print("           representation the field was specified in.")
    print("        ⛔ requires max programmed delay < 2^(N-1) = %d, which becomes"
          % (2 ** (N - 1)))
    print("           an admissibility condition (1.6) rather than disappearing.")
    print("    RECOMMENDATION (b), on the adder count and the descriptor field --")
    print("    but this is a FLAG-BACK item: the wrap condition is a new")
    print("    obligation on the programmer and that is a spec decision, not an")
    print("    implementation one.")

    # ---- item 6 ---------------------------------------------------------
    print()
    print("  ITEM 6 -- where the engine's critical path sits")
    print("  " + "-" * 74)
    print("    measured today (slow corner, nom_slow_1p08V_125C):")
    print("      worst path  ALL endpoints  slack +%.4f ns -> %.4f of %.1f ns used"
          % (WNS_NS, used(WNS_NS), SLOW_PERIOD_NS))
    print("        and it is a COMBINATIONAL FEEDTHROUGH ui_in[7] -> uo_out[7]")
    print("        through the mem[rd_ptr] readback mux -- not a register path.")
    print("      worst FLOP endpoint        slack +%.2f ns -> %.2f ns used"
          % (WORST_FLOP_SLACK_NS, used(WORST_FLOP_SLACK_NS)))
    print("    => registered logic has about %.2f ns of headroom; the readback"
          % (SLOW_PERIOD_NS - used(WORST_FLOP_SLACK_NS)))
    print("       feedthrough has %.4f ns and NOTHING NEW GOES ON IT."
          % WNS_NS)
    print()
    print("    ⭐⭐ AND THIS IS THE REAL ARGUMENT FOR PIPELINING, stronger than")
    print("    the cycle count. The descriptor fetch reads the SAME program-store")
    print("    mux that the %.4f ns path runs through. ⚠ That %.4f ns is PAD TO"
          % (used(WNS_NS), used(WNS_NS)))
    print("    PAD -- input pad, mux, output pad -- and the report does not")
    print("    separate the mux's own share, so the mux is NOT known to be 18 ns")
    print("    of logic. What is known is that this structure sits on the only")
    print("    nearly-full path in the design. In the unpipelined design the EDF")
    print("    compare and the timestamp add would stack ON TOP of that mux")
    print("    inside one cycle. In the pipelined design the mux output")
    print("    goes straight into the pipeline register and nothing combinational")
    print("    follows it. Pipelining is not buying a cycle of C here -- 1.2 says")
    print("    the cycle is free either way -- it is buying the register that")
    print("    keeps the engine OFF the path that is already nearly full.")
    print()
    print("    ⚠ post-RTL, with fallbacks:")
    print("      * descriptor-store read delay. FALLBACK: narrow the store or")
    print("        split it per lane, trading area for mux depth.")
    print("      * EDF comparator depth. FALLBACK: register one level earlier")
    print("        (J = 2, still inside the frontier).")
    print("      * timestamp adder width. FALLBACK: a smaller N with a tighter")
    print("        wrap condition in 1.6.")
    print("    ⛔ status and `ovr` are REGISTERED, never combinational to a pad --")
    print("       the one path that is nearly full is a pad-to-pad feedthrough,")
    print("       and that is exactly the shape not to add to.")

    print()
    print("=" * 78)
    print("  GATE 1.3: %s" % ("PASSED -- every candidate's (C, J) is inside the "
                              "1.2 frontier, and the recommended point is "
                              "pipelined C=2 J=1 with C9=START"
                              if rc_gate == 0 else "FAILED"))
    print("  ⛔ FLAG-BACK: the recommendation is not adopted. Two items need a")
    print("     ruling before RTL -- the pipeline/C9 pair (items 1+3, coupled)")
    print("     and C2's counter representation (item 5).")
    return rc_gate


if __name__ == "__main__":
    raise SystemExit(main())
