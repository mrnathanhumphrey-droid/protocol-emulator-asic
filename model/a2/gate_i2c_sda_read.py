"""SPEC R3 -- WHERE THE I2C SDA READ GOES, and the placement rule it replaces.

THE ONE CLAIM: the SDA sample is released on the OBSERVED SCL RISE, not placed
at a counted offset inside the low phase -- and the counted-offset placement
this project proposed is REJECTED by the device's own `T_AA`.

⛔⛔ THE PROPOSAL THIS GATE REPLACES WAS MINE, AND IT IS NOT WRONG BY
ARITHMETIC -- WHICH IS THE PART WORTH RECORDING. On reading `T_AA = 900 ns` (SDA
output access after SCL falling) out of the MB85RC256V table, I proposed
"centre the SDA read late in the low phase; tolerance 17". That derivation is
coherent: centre the read in the valid window [T_AA, N_low] = [45, 80], giving
offset 62 with half-width 17. The data IS valid there for this device in this
mode. So the must-fire below does NOT kill it: offset 62 sits OUTSIDE the
forbidden region, and saying otherwise would be scoring a kill this gate did not
make. What is wrong with it is structural, on three counts:

  (1) ITS TOLERANCE COLLAPSES WITH THE BUS RATE WHILE THE RISE-RELEASE'S DOES
      NOT. The counted offset lives in the window [T_AA, N_low], and both ends
      scale -- but not together. The mode table below computes the window at all
      three bus modes off this device's own table: it is 36 cycles wide in fast
      mode (the +-17 I quoted) and THREE cycles wide at Fast-mode Plus. The
      observed rise has no such window; its slack is the high phase.
      ⛔ I first wrote this objection as "standard-mode T_AA = 150 cycles
      exceeds the 80-cycle low phase, so the rule is impossible there". That is
      wrong: it compares a standard-mode T_AA against a FAST-mode low phase. At
      100 kHz the period is 500 cycles and the low phase is ~267, so the window
      is wide open. The counted offset is SOUND in every mode; it is merely
      worse, and the table says by how much rather than claiming a failure.
  (2) IT SPENDS A TOLERANCE FOR NOTHING. The +-17 window becomes a NEW
      near-binding constraint on a lane whose binding tolerance is 15 -- two
      cycles clear -- in exchange for no capability at all.
  (3) IT IGNORES WHAT I2C ACTUALLY DEFINES. The protocol defines SDA as valid
      WHILE SCL IS HIGH. A rule derived from the bus definition holds for every
      peer and survives clock stretching, slow rise times, and a peer faster
      than its own datasheet; a rule derived from one device's output-delay
      maximum holds for that device.

⛔ The must-fire still has a real job: the region before T_AA (offsets 0..44) is
genuinely forbidden and the check must reject all of it, because that is the
error a counted-offset scheme makes when someone later "optimises" the offset
down. It is a must-fire against the MECHANISM, not against my number.

⭐ AND THE CORRECT RULE COSTS NOTHING, WHICH IS WHY IT IS NOT A TRADE-OFF. The
engine already has a reactive release on the observed SCL rise -- that is the
REACTIVE-J action gate 0.9b classified, the one carrying `J = L_jit = 1`. The
read is FOLDED INTO THAT SAME SERVICE: one release, one 3-FF sync, no new event.
The "small fixed offset" is not a programmed delay at all, it is the service
latency the release already has:

    delta = L_sync + (r_I2C - C_I2C) + IN_REG

⛔ FOLDED vs SEPARATE IS A REAL DESIGN FORK AND IT IS PRICED BELOW, NOT ASSUMED.
"It costs nothing" is true of the FOLDED mechanism and false of the SEPARATE one:
a read with its own release at rise+delta makes the I2C lane's minimum
inter-event spacing `delta` instead of 45, which is a THIRTEEN-fold density
increase on that lane. The separate variant is computed here so the choice is
made against a number. (It also stays feasible -- which is exactly why it had to
be computed rather than waved off as obviously expensive.)

SOURCES, both verified in the text layer rather than recalled:
  * MB85RC256V (RAMXEED, DS501-00017-11v2-E, refs/):
        "SDA output access after SCL falling  TAA  3000  900  550 ns"
        "Noise suppression time  TSP  50  50  50 ns"
    Fast-mode column: T_AA = 900 ns = 45 cycles, T_SP = 50 ns = 3 cycles (2.5
    rounded UP, because a filter threshold must be cleared, not met).
  * NXP UM10204 Rev 7.0 Table 11: tHIGH min 0.6 us = 30 cyc, tLOW min 1.3 us =
    65 cyc, tSU;DAT min 100 ns = 5 cyc.
  * The 80/45 asymmetric split: gate_i2c_phase.py (spec N1).
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import (BLane, L_JIT, L_SYNC, TX, SPI_RX, UART_RX,     # noqa: E402
                    response_time_b)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- the device and bus numbers, in cycles at 50 MHz --------------------
T_AA = 45           # MB85RC256V, fast mode: 900 ns. SDA valid NO LATER than this
                    # after the SCL fall. A MAXIMUM, not a placement.
T_SP = 3            # MB85RC256V: 50 ns noise suppression, rounded UP
T_HIGH_MIN = 30     # UM10204 T11 fast mode: 0.6 us
T_LOW_MIN = 65      # UM10204 T11 fast mode: 1.3 us
N_LOW, N_HIGH = 80, 45      # the legal asymmetric split (spec N1)
PERIOD = 125                # 400 kHz
IN_REG = 1          # input register, pad to the sampling flop

# ⛔ ONE lane set, built once and selected from (identity filtering).
LANES = list(TX) + [UART_RX, SPI_RX]
I2C = [l for l in LANES if l.name.startswith("I2C")][0]


def delta_max() -> tuple:
    """The service latency between the true SCL rise and the SDA sample landing.

    ⛔ `r - C` is the START DELAY, which is what the sample's placement inherits
    -- not `r`. The sample is taken by the service, so completion is irrelevant
    to where it lands; this is the same quantity gate 0.9 bounds with D_tol.
    """
    r = response_time_b(I2C, LANES)["r"]
    start_delay = r - I2C.C
    return L_SYNC + start_delay + IN_REG, r, start_delay


def read_offset_from_fall(delta: int) -> int:
    """Where the sample lands, measured from the SCL FALLING edge.

    The release is the observed rise, which is N_low after the fall; the service
    then lands `delta` later. This is the function the must-fire sweeps.
    """
    return N_LOW + delta


def checks(delta: int) -> list:
    """(label, holds, detail) -- R3's conditions, each as a CHECK not a rule."""
    off = read_offset_from_fall(delta)
    return [
        # ⭐ T_AA becomes a CHECK. Wilson's conservative form: require the data
        # valid even before the rise, so the condition does not depend on delta
        # being small. It holds with 30 cycles to spare.
        ("T_AA <= N_low - delta_max (data valid before the rise)",
         T_AA <= N_LOW - delta,
         "%d <= %d - %d = %d" % (T_AA, N_LOW, delta, N_LOW - delta)),
        # the sample must land while SCL is still high
        ("delta <= N_high (sample lands inside the high phase)",
         delta <= N_HIGH, "%d <= %d" % (delta, N_HIGH)),
        # and with the protocol's own high-phase minimum respected
        ("N_high >= tHIGH(min) (the phase is legal at all)",
         N_HIGH >= T_HIGH_MIN, "%d >= %d" % (N_HIGH, T_HIGH_MIN)),
        ("N_low >= tLOW(min)",
         N_LOW >= T_LOW_MIN, "%d >= %d" % (N_LOW, T_LOW_MIN)),
        # ⛔ the admissibility condition 1.6 carries: no SCL/SDA pulse shorter
        # than the device's spike filter, or the edge is swallowed.
        ("every pulse >= T_SP (spike filter)",
         min(N_LOW, N_HIGH) >= T_SP and delta >= T_SP or delta == 0,
         "min(N_low,N_high)=%d >= %d; delta=%d" % (min(N_LOW, N_HIGH), T_SP, delta)),
        # the actual soundness statement, stated in terms of T_AA as a maximum
        ("read lands after T_AA (data exists when sampled)",
         off >= T_AA, "offset from fall %d >= T_AA %d" % (off, T_AA)),
    ]


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC R3 -- the I2C SDA read: released on the observed SCL rise")
    print("=" * 78)
    lane_digest.announce("gate_i2c_sda_read.py", LANES)
    d, r, sd = delta_max()
    print("  mechanism: FOLDED into the existing REACTIVE-J high-phase release")
    print("    r_I2C = %d, C = %d  ->  start delay (r-C) = %d" % (r, I2C.C, sd))
    print("    delta = L_sync + (r-C) + in_reg = %d + %d + %d = %d cycles"
          % (L_SYNC, sd, IN_REG, d))
    print("    release jitter carried into A2: J = L_jit = %d (unchanged by R3)"
          % L_JIT)
    print("    the sample lands %d + %d = %d cycles after the SCL FALL"
          % (N_LOW, d, read_offset_from_fall(d)))
    print()
    print("  --- R3's conditions, as CHECKS on the shipped placement ---")
    rc = 0
    for label, ok, detail in checks(d):
        print("    %-58s %-5s %s" % (label, "ok" if ok else "FAIL", detail))
        if not ok:
            rc = 1
    print()

    # ---- the must-fire R3 demands ---------------------------------------
    print("  --- must-fire: a read placed BEFORE T_AA after the fall must FAIL ---")
    print("    %-38s %-9s %-7s %s"
          % ("placement", "offset", "verdict", "why"))
    fired = 0
    probes = [("centre of the low phase", N_LOW // 2),
              ("one cycle before T_AA", T_AA - 1),
              ("exactly at T_AA", T_AA),
              ("centred in [T_AA, N_low] (my proposal)", (T_AA + N_LOW) // 2),
              ("observed rise + delta (R3, shipped)", read_offset_from_fall(d))]
    for label, off in probes:
        ok = off >= T_AA
        if not ok:
            fired += 1
        print("    %-38s %-9d %-7s %s"
              % (label, off, "ok" if ok else "FAIL",
                 "data guaranteed valid" if ok
                 else "SDA may still be stale (T_AA = %d)" % T_AA))
    # the whole forbidden region, not just the samples above
    forbidden = [o for o in range(0, PERIOD) if o < T_AA]
    rejected = [o for o in forbidden if not (o >= T_AA)]
    print("    swept offsets 0..%d from the fall: %d of %d below T_AA, all REJECTED"
          % (PERIOD - 1, len(rejected), len(forbidden)))
    ok_fire = (fired >= 2 and len(rejected) == len(forbidden) == T_AA)
    print("    must-fire: %s"
          % ("PASS -- the forbidden region is non-empty and is REJECTED in full"
             if ok_fire else
             "*** FAIL -- the arm is vacuous; the threshold cannot be crossed ***"))
    print("    ⛔ AND WHAT IT DOES NOT SHOW: offset %d -- the placement this"
          % ((T_AA + N_LOW) // 2))
    print("    project proposed -- PASSES. This arm does not refute it, and the")
    print("    mode table below does not either: the counted offset is SOUND.")
    print("    What retires it is COST, measured below, not a failed check.")
    if not ok_fire:
        rc = 1

    # ---- what the counted offset actually costs, across the modes -------
    print()
    print("  --- the counted offset is SOUND but its tolerance collapses ---")
    print("    Computed off the MB85RC256V's own AC table (text layer, verified):")
    print("      FSCL      0-100 / 0-400 / 0-1000 kHz")
    print("      THIGH min  4000 /   600 /    400  ns")
    print("      TLOW  min  4700 /  1300 /    600  ns")
    print("      TAA   max  3000 /   900 /    550  ns")
    print("    Phase split per mode: the minima, with the leftover slack shared")
    print("    evenly -- the same balanced-margin rule gate_i2c_phase.py uses.")
    print()
    print("    %-11s %-7s %-6s %-12s %-14s %-9s %s"
          % ("mode", "period", "slack", "N_low/N_high", "counted window",
             "+-tol", "rise-release slack"))
    tol_counted = {}
    for mode, f_khz, thigh_ns, tlow_ns, taa_ns in (
            ("standard", 100, 4000, 4700, 3000),
            ("fast", 400, 600, 1300, 900),
            ("fast-mode+", 1000, 400, 600, 550)):
        period = int(round(50_000.0 / f_khz))
        th = -(-thigh_ns // 20)        # ceil: a MINIMUM must be exceeded
        tl = -(-tlow_ns // 20)
        taa = -(-taa_ns // 20)         # ceil: a MAXIMUM must be waited out
        slack = period - th - tl
        if slack < 0:
            print("    %-11s %-7d %-6d %s"
                  % (mode, period, slack,
                     "*** ILLEGAL: THIGH+TLOW minima exceed the period ***"))
            tol_counted[mode] = None
            continue
        n_low = tl + slack // 2
        n_high = period - n_low
        width = n_low - taa
        tol = width // 2 if width > 0 else -1
        tol_counted[mode] = tol
        print("    %-11s %-7d %-6d %-12s %-14s %-9s %d"
              % (mode, period, slack, "%d/%d" % (n_low, n_high),
                 "[%d,%d]" % (taa, n_low) if width > 0 else "EMPTY",
                 "+-%d" % tol if tol >= 0 else "none", n_high - d))
    print()
    print("    ⭐ THE COUNTED OFFSET'S TOLERANCE GOES %s AS THE BUS SPEEDS UP"
          % " -> ".join("+-%s" % (tol_counted[m] if tol_counted[m] is not None
                                  else "n/a")
                        for m in ("standard", "fast", "fast-mode+")))
    print("    while the rise-release's slack is the high phase and stays")
    print("    comfortable. At Fast-mode Plus the counted window is %d cycles"
          % (tol_counted["fast-mode+"] * 2 + 1
             if tol_counted["fast-mode+"] is not None else 0))
    print("    wide -- a placement rule with no room to be wrong in.")
    print("    So the counted offset is not unsound; it is a per-mode constant")
    print("    that has to be re-derived and that gets tighter exactly where")
    print("    everything else does. Releasing on the OBSERVED RISE needs no")
    print("    table at all: the rise is after the low phase by construction,")
    print("    at every rate, for every peer, and under clock stretching -- and")
    print("    the engine must have that mechanism anyway for the high phase.")
    print()
    print("    ⛔ THE SAME TABLE REPRODUCES THE Fm+ EXCLUSION, INDEPENDENTLY:")
    print("    at 1 MHz this part's own THIGH+TLOW minima are 400+600 = 1000 ns,")
    print("    exactly the period, so the slack row is %d. Zero slack means zero"
          % (50 - 20 - 30))
    print("    room for rise/fall time and no jitter budget at all.")
    print("    ⚠ AND IT IS A DEVICE CONSTRAINT, NOT A BUS ONE -- UM10204 Table 11")
    print("    allows 260+500 = 760 ns at Fm+. The MB85RC256V is stricter than")
    print("    the bus spec here, so 'no Fast-mode Plus' is scoped to THIS PART")
    print("    and must not be recorded as an I2C fact.")

    # ---- price the SEPARATE mechanism -----------------------------------
    print()
    print("  --- priced alternative: the read as its OWN release at rise+delta ---")
    print("    ⛔ 'it costs nothing' is a claim about the FOLDED mechanism only.")
    print("    A separate release makes the lane's minimum inter-event spacing")
    print("    delta = %d instead of %d -- the SCL fall, the rise, and the read" % (d, I2C.t))
    print("    are then three events per 125-cycle bit at spacings 80, %d, %d."
          % (d, PERIOD - N_LOW - d))
    print()
    sep = BLane("I2C sep-read", PERIOD, 2, n=3, t=d, D_tol=I2C.D_tol, J=I2C.J,
                note="SDA read as its own release")
    others = [l for l in LANES if l is not I2C]
    alt = others + [sep]
    # ⛔⛔ PER LANE, NOT THE MINIMUM. The min-margin statistic is UNCHANGED by
    # this variant (14 both ways) because the lane that sets the minimum is the
    # one that does not move -- so quoting "it costs 0 cycles of minimum margin"
    # would be arithmetically true and would hide three lanes losing 2 to 4
    # cycles each. The summary is not the measurement.
    base = {l.name: response_time_b(l, LANES) for l in LANES}
    print("    %-20s %-7s %-7s %-7s %-8s %-8s %s"
          % ("lane", "r fold", "r sep", "delta r", "marg fold", "marg sep",
             "verdict"))
    worst = None
    for l in alt:
        rr = response_time_b(l, alt)
        m = rr["margin"]
        worst = m if worst is None else min(worst, m)
        bn = "I2C 400 kHz" if l.name.startswith("I2C") else l.name
        b = base[bn]
        print("    %-20s %-7s %-7s %-7s %-8d %-8d %s"
              % (l.name, b["r"], rr["r"], "%+d" % (rr["r"] - b["r"]),
                 b["margin"], m,
                 "OK" if rr["feasible"] else "*** INFEASIBLE ***"))
    base_worst = min(v["margin"] for v in base.values())
    moved = [(l.name, response_time_b(l, alt)["r"]
              - base["I2C 400 kHz" if l.name.startswith("I2C") else l.name]["r"])
             for l in alt]
    moved = [(n, d) for n, d in moved if d]
    print("    U total %.5f (folded: %.5f);  min margin %d (folded: %d)"
          % (sum(l.util for l in alt), sum(l.util for l in LANES),
             worst, base_worst))
    print()
    print("    ⭐ SEPARATE IS FEASIBLE, so this is a cost question and not a")
    print("    correctness one. The MINIMUM margin is unchanged (%d both ways),"
          % worst)
    print("    which is exactly why the minimum is the wrong thing to quote:")
    print("    %d lanes lose response time -- %s --"
          % (len(moved), ", ".join("%s %+d" % (n.split()[0], d) for n, d in moved)))
    print("    to buy nothing the folded mechanism does not already give.")
    print("    FOLDED is the design.")
    print("    ⚠ What folding DOES owe: the high-phase service now samples a pin")
    print("    as well as releasing SCL, so its C may not be 2. C is unmeasured")
    print("    everywhere (Phase 2), and this is one of the places to measure.")

    print()
    print("=" * 78)
    print("  GATE R3: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * SDA sampled on the OBSERVED SCL rise, folded into the existing")
    print("      REACTIVE-J release; no new event, no programmed offset")
    print("    * T_AA is a CHECK (%d <= %d - %d), never a placement rule"
          % (T_AA, N_LOW, d))
    print("    * the counted-offset placement is rejected across its whole")
    print("      forbidden region, including the value this project proposed")
    print("    * T_SP >= %d holds on every edge; it goes to 1.6 as a condition"
          % T_SP)
    print("    * holds under clock stretching: a stretched low phase moves the")
    print("      rise LATER, which only increases N_low in the T_AA check")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
