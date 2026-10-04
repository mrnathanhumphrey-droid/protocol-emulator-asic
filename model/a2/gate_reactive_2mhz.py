"""R2 -- THE REACTIVE ABSOLUTE BUDGET for SPI-target MISO.

⛔⛔ WHY AN ABSOLUTE CHECK AND NOT A DIFFERENTIAL ONE. A source lane only has
to place its edges on a grid, so a bounded lateness relative to its own
nominal release is enough. A REACTIVE lane answers a peer: the master drives
SCLK and samples MISO, and the chip has from the master's clock edge until the
master's setup window to get a bit onto the pin. That is an ABSOLUTE budget
against the peer's clock, and no amount of internal consistency satisfies it.

    half_period - tSU(master)  >=  L_sync + start_delay + output_reg + C9_off

⭐ 0.9b, AND IT IS A MUST-FIRE HERE: a configuration where the DIFFERENTIAL
check passes and the ABSOLUTE one fails must still be REJECTED. A lane can be
perfectly punctual relative to its own releases and still miss the peer's
sampling window; a gate that only checked the differential would call that
case good.

⚠ EVERY TERM IS CITED OR DECLARED PARAMETRIC. `tSU(master)` is a property of
the PEER, not of this chip, so it is a parameter with a declared default of
1 cycle rather than a number smuggled in as if we knew it.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pyrta_bound                                   # noqa: E402
import pyrta_src                                     # noqa: E402
from gate_j9_margins import lanes_d12                # noqa: E402
from gate_j_sound import lanes_at                    # noqa: E402

F_CLK = 50_000_000          # the shipped clock

# ---- the terms, each with its origin ------------------------------------
L_SYNC = 3                  # the 3-flop edge-capture synchroniser
                            # src/pe_engine.v -- the ARM/edge path, L_sync = 3 +/- 1
OUTPUT_REG = 1              # every output is flop-driven (F2, 24/24 on the netlist)
C9_OFFSET = 0               # ⭐ C9 = START: the pin moves in the FIRST cycle of
                            # service, so service contributes no extra offset
                            # before the edge. That is the whole point of the
                            # pipelined dispatch -- an unpipelined engine would
                            # read its descriptor in cycle 1 and owe +1 here.
C_SVC = 2                   # measured and derived, min == max == 2

# ⚠ A PEER PROPERTY, PARAMETRIC. The master's setup requirement before its own
# sampling edge. 1 cycle (20 ns) is the declared default and it is DELIBERATELY
# OPTIMISTIC: a real master needs more, so a budget that fails at 1 fails at
# any realistic value, and one that passes at 1 is not yet proof it passes.
TSU_MASTER_CYCLES = 1


def budget(name, bit_hz, r, c=C_SVC, tsu=TSU_MASTER_CYCLES):
    """The absolute check for one reactive configuration.

    `r` is the lane's response time from the analysis -- so `r - c` is the
    LATEST the service can start and still complete by `r`, which is the
    start delay the budget has to absorb.
    """
    half = (F_CLK // bit_hz) // 2          # cycles in half a bit period
    start = r - c
    need = L_SYNC + start + OUTPUT_REG + C9_OFFSET
    have = half - tsu
    return {
        "name": name, "bit_hz": bit_hz, "half": half, "tsu": tsu,
        "start": start, "need": need, "have": have, "margin": have - need,
    }


def show(b):
    print("    %s" % b["name"])
    print("      bit rate                 : %.3f MHz (half period %d cycles)"
          % (b["bit_hz"] / 1e6, b["half"]))
    print("      available: half - tSU    : %d - %d = %d"
          % (b["half"], b["tsu"], b["have"]))
    print("      needed: L_sync + start + output_reg + C9_off")
    print("                               : %d + %d + %d + %d = %d"
          % (L_SYNC, b["start"], OUTPUT_REG, C9_OFFSET, b["need"]))
    print("      MARGIN                   : %d  %s"
          % (b["margin"], "ok" if b["margin"] > 0 else "*** FAILS (must be > 0)"))


def r_of(src, lanes, frag):
    """pyRTA's response time for the lane whose name contains `frag`."""
    for k, l in enumerate(lanes):
        if frag in l.name:
            r, err = pyrta_bound.bound(src, lanes, k)
            return r, err
    return None, "no lane matching %r" % frag


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("R2 -- REACTIVE ABSOLUTE BUDGET, SPI-target MISO")
    print("=" * 78)
    print("  half_period - tSU(master) >= L_sync + start + output_reg + C9_off")
    print("  L_sync=%d  output_reg=%d  C9_offset=%d  C=%d  tSU(master)=%d "
          "(PARAMETRIC, peer property)"
          % (L_SYNC, OUTPUT_REG, C9_OFFSET, C_SVC, TSU_MASTER_CYCLES))
    print()

    src = pyrta_src.require_pyrta("gate_reactive_2mhz")
    if not src:
        print("  *** pyRTA is the PRIMARY source of `r` and it is absent.")
        return 1

    # ---- the shipped 1 MHz configuration, at the shipped J ---------------
    print("  --- the SHIPPED configuration (1 MHz, J = 1) ---")
    r1, e1 = r_of(src, lanes_at(1), "SPI-target")
    if r1 is None:
        print("    *** no r for SPI-target: %s" % e1)
        return 1
    b1 = budget("SPI-target 1 MHz, J = 1", 1_000_000, r1)
    show(b1)
    if b1["margin"] <= 0:
        print("    ⛔⛔ THE SHIPPED CONFIGURATION FAILS ITS OWN ABSOLUTE")
        print("       BUDGET. That is a STOP, not a finding about 2 MHz.")
        rc = 1
    print()

    # ---- the 2 MHz question, at the OPTIMISTIC J = 9 --------------------
    # ⛔ J = 9 IS USED HERE DELIBERATELY, AND IT IS NOT THE SOUND BOUND.
    # docs/J_LANE_PROOF.md finds the sound release-to-dispatch non-execution
    # bound is k*L_REFILL + 1 = 21, because a waiting lane that loses winner
    # status to a lane whose head is ALSO invalid waits through that lane's
    # refill with nothing executing -- a delay pyRTA charges nothing for.
    # ⇒ Using 9 asks the kindest possible version of the question. A failure
    #   at 9 is a failure at 21 as well, and reporting the kind case makes the
    #   verdict independent of that argument.
    print("  --- the 2 MHz question, at the OPTIMISTIC J = 9 ---")
    print("    ⚠ J = 9 is NOT the sound bound (see docs/J_LANE_PROOF.md: the")
    print("      sound figure is k*L_REFILL + 1 = 21). It is used here so the")
    print("      verdict does not depend on that argument -- a failure at the")
    print("      kindest J is a failure at the sound one too.")
    r2, e2 = r_of(src, lanes_d12(9), "SPI-target")
    if r2 is None:
        print("    *** no r for SPI-target at d=12: %s" % e2)
        return 1
    b2 = budget("SPI-target 2 MHz, J = 9 (optimistic)", 2_000_000, r2)
    show(b2)
    print()

    # ---- and the next ceiling the ruling asked for ----------------------
    print("  --- the NEXT ceiling asked for (3 MHz), same two terms ---")
    b3 = budget("SPI-target 3 MHz, J = 9 (optimistic)", 3_000_000, r2)
    show(b3)
    print("    ⚠ `r` is reused from the d = 12 set, so this is an INDICATION")
    print("      only: a 3 MHz lane would need d = 8, a different task set and")
    print("      a different r. It is reported because the ruling asked for")
    print("      the next ceiling to be computed, not because it is a result.")
    print()

    # ---- 0.9b MUST-FIRE -------------------------------------------------
    # ⛔ A CASE WHERE THE DIFFERENTIAL PASSES AND THE ABSOLUTE FAILS MUST
    # STILL BE REJECTED. The differential question is "is the lane punctual
    # relative to its own releases", which is exactly `r <= D_tol`; the
    # absolute question is against the PEER's clock. Constructed here with a
    # lane that meets its deadline comfortably and still misses the window.
    print("  --- must-fire 0.9b: differential passes, absolute fails ---")
    ls = lanes_d12(9)
    tgt = [l for l in ls if "SPI-target" in l.name][0]
    differential_ok = (r2 is not None and r2 <= tgt.D_tol)
    print("    differential (r %d <= D_tol %d) : %s"
          % (r2, tgt.D_tol, "PASSES" if differential_ok else "fails"))
    print("    absolute (margin %d > 0)        : %s"
          % (b2["margin"], "passes" if b2["margin"] > 0 else "FAILS"))
    if differential_ok and b2["margin"] <= 0:
        print("    ⇒ FIRED: the differential check alone would ADMIT this")
        print("      configuration, and the absolute check REJECTS it. That is")
        print("      0.9b exactly, on the real 2 MHz case rather than on a")
        print("      constructed one.")
    elif not differential_ok:
        print("    ⚠ the differential ALSO fails here, so this case does not")
        print("      exercise 0.9b -- the must-fire needs a configuration that")
        print("      passes one and fails the other, and this is not one.")
        rc = 1
    else:
        print("    *** DID NOT FIRE: both checks pass, so this configuration")
        print("        cannot demonstrate that the absolute check adds")
        print("        anything.")
        rc = 1
    print()

    # ---- the verdict ----------------------------------------------------
    print("-" * 78)
    print("  R2 VERDICT")
    print("    1 MHz (shipped) : margin %+d  %s"
          % (b1["margin"], "ok" if b1["margin"] > 0 else "FAILS"))
    print("    2 MHz           : margin %+d  %s"
          % (b2["margin"], "ok" if b2["margin"] > 0 else "FAILS"))
    print("    3 MHz (indic.)  : margin %+d  %s"
          % (b3["margin"], "ok" if b3["margin"] > 0 else "FAILS"))
    print()
    if b2["margin"] > 0:
        print("    ⇒ R2 PASSES at 2 MHz. The reopening then depends on R1.")
    else:
        print("    ⇒ R2 FAILS AT 2 MHz by %d cycles, at the OPTIMISTIC J = 9."
              % -b2["margin"])
        print("      The peer's half period at 2 MHz is %d cycles and the"
              % b2["half"])
        print("      chain from its clock edge to a valid MISO bit needs %d."
              % b2["need"])
        print("      ⭐ THE BINDING TERM IS THE START DELAY (%d of %d), which"
              % (b2["start"], b2["need"]))
        print("      is `r - C` -- so this is the SAME scheduling pressure the")
        print("      D* refusal is about, arriving through the peer's clock")
        print("      instead of through a deadline.")
        print("      ⇒ SPI-target stays at 1 MHz. Not reopened.")
    print()
    print("=" * 78)
    print("  GATE reactive-2mhz: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means the budget was computed and the must-fire")
    print("      behaved -- NOT that 2 MHz is admitted.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
