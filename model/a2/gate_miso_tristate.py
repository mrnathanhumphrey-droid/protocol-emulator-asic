"""MISO RULING -- an SPI TARGET's MISO must be able to STOP DRIVING.

THE ONE CLAIM: SPI-target's MISO cannot live on `uo_out`, because `uo_out` is
always driven and a target's MISO must release when its CS is deasserted. The
fix moves it to `uio` with `uio_oe` tied to the target's own CS -- and that fix
is NOT complete at "uio_oe = CS", because releasing takes TIME.

⛔⛔ THE ERROR WAS IN A CATEGORY, NOT IN ARITHMETIC. `PINS_DIR` split the
protocol pins by DIRECTION -- (push-pull, inputs, open-drain). On that axis a
target's MISO is simply "an output", so it went to `uo_out` with the other
outputs and the bank arithmetic came out consistent. Every count was right. The
AXIS was wrong: what `uo_out` cannot do is not "carry an input", it is
RELINQUISH. An open-drain I2C line and a tri-stated target MISO are different
protocols making the same demand, and only one of them was in the table.

⭐ THE CONSEQUENCE IS NOT A PIN COUNT, IT IS A CHIP THAT FIGHTS THE BUS. A
shared MISO has exactly one driver at a time, chosen by CS. A target that always
drives is a permanent second driver: it contends with every other device on
every transfer that is not addressed to it. That is not a degraded reading, it
is two output stages shorted through whatever logic levels disagree.

⭐⭐ PRIMARY EVIDENCE, FROM THE PART THAT IS OUR OWN RUNG-5 ORACLE. MB85RS64V --
the FRAM the demo writes -- documents the convention in its own pin table:
    pin 1 CS : "When CS is the 'H' level, device is in deselect (standby)
                status and SO becomes High-Z."
    pin 2 SO : "This is High-Z during standby."
So the rule is not a convention we adopted, it is the observable behaviour of
the device our target shares a bus with. ORIGIN: refs/mb85rs64v_ramxeed.txt,
the RAMXEED datasheet's own PIN FUNCTIONAL DESCRIPTIONS section.

⛔ AND ONE NUMBER IS DELIBERATELY NOT QUOTED HERE. That datasheet's AC
characteristics table HAS a named "Output disable time" and a "Deselect time" --
so release latency is a budgeted quantity on real parts, not something this gate
invented. But the table's text layer is SCRAMBLED: the parameter column and the
symbol column are misaligned, so it reads "Clock low time tCSH 25" and "Chip
select hold time tODV". That is the same scrambled-text-layer boundary already
recorded for this part in 1.1. ⇒ The parameter NAMES are evidence; the VALUES
from that table are not, and none is quoted.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import L_SYNC, OUT_REG                                 # noqa: E402
from gate_pin_subsets import (PINS, PINS_DIR, N_UIO, N_UO,         # noqa: E402
                              N_SERIAL, bank_need, feasible_ruled,
                              feasible_subsets_ruled)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LANES = lane_digest.shipped()
HZ = 50e6                       # the shipped clock, info.yaml clock_hz

Z = None                        # a driver that is not driving


# ---------------------------------------------------------------------------
# A shared MISO line with two targets on it. The point of modelling the BUS
# rather than our pin is that "always driven" is only a bug in the presence of
# another driver -- and the other driver is the FRAM we already ship against.
# ---------------------------------------------------------------------------
def resolve(drivers):
    """Resolve a wired-together line. Returns (value, contending_drivers).

    ⛔ Two drivers holding the SAME value is still contention in the electrical
    sense, but it is not DETECTABLE as a wrong level, so this returns it as a
    conflict only when the driven values DISAGREE. That is the conservative
    direction for a must-fire: a mutant that contends invisibly must not be
    counted as killed.
    """
    live = [(n, v) for n, v in drivers.items() if v is not Z]
    if not live:
        return Z, []
    vals = {v for _, v in live}
    if len(live) > 1 and len(vals) > 1:
        return "X", [n for n, _ in live]
    return live[0][1], []


class Target:
    """An SPI target's MISO driver. `oe_policy` is the thing under test."""

    def __init__(self, name, data, oe_policy):
        self.name = name
        self.data = data            # the bits it would send if selected
        self.oe_policy = oe_policy

    def drive(self, step, cs_asserted, hist):
        oe = self.oe_policy(step, cs_asserted, hist)
        if not oe:
            return Z
        return self.data[step % len(self.data)]


# ---- the OE policies, one per face ---------------------------------------
def oe_correct(step, cs_asserted, hist):
    """RULED: drive only while selected. (Steady-state model -- the release
    LATENCY is face 3, deliberately separated so each face kills one thing.)"""
    return bool(cs_asserted)


def oe_always(step, cs_asserted, hist):
    """MUTANT 1 -- MISO on `uo_out`. `uo_out` has no enable, so the pin is
    driven every cycle whatever CS says. This is the superseded pin map."""
    return True


def oe_glitchy(step, cs_asserted, hist):
    """MUTANT 2 -- a COMBINATIONAL `uio_oe`. Correct every settled cycle, but
    it glitches while its input cone settles. Modelled as one spurious assert.

    ⭐ THE ESCALATION THAT MAKES THIS F2's BUSINESS: a glitch on a DATA output
    is a wrong value for a few hundred ps. A glitch on an ENABLE is a second
    DRIVER switching on -- contention, not a wrong level. So `uio_oe` needs the
    flop at least as much as `uio_out` does, and F2 already covers it.
    """
    if step == hist["glitch_at"]:
        return True
    return bool(cs_asserted)


def oe_registered_release(step, cs_asserted, hist):
    """FACE 3 -- the RULED design, modelled WITH its release latency.

    CS arrives on `uio` as an asynchronous input, so it is synchronised
    (L_SYNC) and the enable is registered (OUT_REG) per F2. The enable
    therefore follows CS by L_SYNC + OUT_REG cycles IN BOTH DIRECTIONS, and the
    deassert direction is the one that matters: for that many cycles after the
    master deselects us, we are still driving.
    """
    lat = L_SYNC + OUT_REG
    past = hist["cs"][max(0, step - lat)] if step - lat >= 0 else False
    return bool(past)


def run_bus(ours_policy, cs_ours, cs_other, glitch_at=-1):
    """Walk a trace of a shared MISO with our target and the FRAM on it."""
    n = len(cs_ours)
    hist = {"cs": cs_ours, "glitch_at": glitch_at}
    ours = Target("ours", [1, 0, 1, 1, 0, 0, 1, 0], ours_policy)
    # the FRAM: a correct target, by its own datasheet
    fram = Target("MB85RS64V", [0, 1, 0, 0, 1, 1, 0, 1], oe_correct)
    bad = []
    for s in range(n):
        d = {"ours": ours.drive(s, cs_ours[s], hist),
             "MB85RS64V": fram.drive(s, cs_other[s], hist)}
        val, conf = resolve(d)
        if conf:
            bad.append((s, conf))
    return bad


def main() -> int:
    print()
    print("=" * 78)
    print("MISO RULING -- a target's MISO must release; `uo_out` cannot")
    print("=" * 78)
    lane_digest.announce("gate_miso_tristate.py (MISO)", LANES)
    rc = 0

    # ---- 1. the electrical classification -------------------------------
    print()
    print("  --- 1. WHY THE AXIS WAS WRONG ---")
    print("    `uo_out` is output-only AND ALWAYS DRIVEN. Two protocol classes")
    print("    need the opposite, for two different reasons:")
    print()
    print("    %-26s %-28s %s" % ("class", "must be able to", "bank"))
    print("    %-26s %-28s %s" % ("push-pull output",
                                  "drive 0 and 1", "uo_out or uio"))
    print("    %-26s %-28s %s" % ("input", "not drive at all", "uio"))
    print("    %-26s %-28s %s" % ("open-drain (I2C)",
                                  "release -> pull-up wins", "uio ONLY"))
    print("    %-26s %-28s %s" % ("tri-state (target MISO)",
                                  "release -> another target", "uio ONLY"))
    print()
    print("    ⛔ ON A DIRECTION AXIS THE LAST ROW DISAPPEARS. A target MISO is")
    print("    'an output', so it lands on uo_out and every count stays")
    print("    consistent. The table was arithmetically right and")
    print("    categorically wrong.")

    # ---- 2. the banks ---------------------------------------------------
    print()
    print("  --- 2. THE FIX, AND WHAT IT COSTS ---")
    u, o = bank_need(LANES)
    # the superseded map, recomputed here so the delta is shown not asserted
    u_old = sum(PINS_DIR[l.name][1] + PINS_DIR[l.name][2] for l in LANES)
    o_old = sum(PINS_DIR[l.name][0] + PINS_DIR[l.name][3] for l in LANES)
    print("    %-30s %-14s %s" % ("map", "uio", "uo_out (incl %d serial)"
                                  % N_SERIAL))
    print("    %-30s %-14s %s"
          % ("MISO as push-pull (superseded)", "%d of %d" % (u_old, N_UIO),
             "%d of %d" % (o_old + N_SERIAL, N_UO)))
    print("    %-30s %-14s %s"
          % ("RULED: MISO tri-state on uio", "%d of %d" % (u, N_UIO),
             "%d of %d" % (o + N_SERIAL, N_UO)))
    print()
    print("    ⭐ ONE PIN CHANGED BANKS AND BOTH BANKS STILL FIT:")
    print("      uio    %d of %d -- EXACTLY FULL, zero spare" % (u, N_UIO))
    print("      uo_out %d of %d -- %d spare, RESTORED"
          % (o + N_SERIAL, N_UO, N_UO - o - N_SERIAL))
    print("    ⛔ BUT THE SPARE IS ON THE WRONG BANK TO BE USEFUL. It can take")
    print("    another push-pull output and nothing else. 1.6o said the lost")
    print("    spare was the constraint; the real statement is that the")
    print("    constraint MOVED from uo_out to uio.")
    if not feasible_ruled(LANES):
        print("    *** the ruled map does not fit -- the five-lane set is not")
        print("        wireable and every r_i is back to being an envelope")
        rc = 1
    n_ruled = len(feasible_subsets_ruled())
    n_all = 2 ** len(LANES) - 1
    print("    subset feasibility under the ruled map: %d of %d"
          % (n_ruled, n_all))
    if n_ruled != n_all:
        print("    *** the ruling lost subsets -- re-quote the envelope claim")
        rc = 1
    else:
        print("    ⭐ UNCHANGED, AND IT HAD TO BE COUNTED. Only which bank a pin")
        print("    sits on moved, so no subset gained or lost feasibility and")
        print("    the A2 evidence is untouched. ⛔ That is also exactly why the")
        print("    error survived a whole batch: nothing downstream complained.")

    # ---- 3. the must-fires, on a modelled shared bus --------------------
    print()
    print("  --- 3. MUST-FIRE: a mutant that drives MISO while deselected ---")
    print("    Modelled as a real shared bus: our target plus the MB85RS64V,")
    print("    which by its own datasheet releases SO during standby. 16 steps;")
    print("    the master selects the FRAM for steps 8..15 and never selects us.")
    N = 16
    cs_ours = [False] * N
    cs_other = [False] * 8 + [True] * 8

    faces = [
        ("RULED: uio_oe = our CS", oe_correct, -1, False),
        ("MUTANT: MISO on uo_out (always driven)", oe_always, -1, True),
        ("MUTANT: combinational uio_oe (glitch at step 10)", oe_glitchy, 10,
         True),
    ]
    print()
    print("    %-48s %-10s %s" % ("face", "contends", "verdict"))
    for label, pol, gl, want_bad in faces:
        bad = run_bus(pol, cs_ours, cs_other, glitch_at=gl)
        got_bad = bool(bad)
        ok = (got_bad == want_bad)
        print("    %-48s %-10s %s"
              % (label, "%d cyc" % len(bad),
                 "as expected" if ok else "*** WRONG"))
        if not ok:
            rc = 1
        if bad:
            s0, who = bad[0]
            print("        first conflict at step %d, drivers %s -- the line is"
                  % (s0, " + ".join(who)))
            print("        driven to opposing levels by two output stages")
    print()
    print("    ⛔ THE GLITCH FACE IS NOT A TIMING NICETY. A glitch on a data")
    print("    output is a wrong level for a few hundred ps. A glitch on an")
    print("    ENABLE switches a second DRIVER on. So `uio_oe` earns the flop")
    print("    at least as much as `uio_out` does -- which is why F2's port")
    print("    list already includes it, and why F2 now carries a face whose")
    print("    data outputs are flopped and whose ENABLE is combinational.")

    # ---- 4. the part of the fix that is not done ------------------------
    print()
    print("  --- 4. ⛔ THE FIX IS NOT COMPLETE AT 'uio_oe = CS': RELEASE TAKES")
    print("          TIME, AND THAT IS A HOST-FACING REQUIREMENT ---")
    lat = L_SYNC + OUT_REG
    ns = lat / HZ * 1e9
    print("    CS is an asynchronous input on `uio`, so it is synchronised")
    print("    (L_sync = %d) and the enable is registered per F2 (out_reg = %d)."
          % (L_SYNC, OUT_REG))
    print("    The enable follows CS by %d cycles IN BOTH DIRECTIONS, and the"
          % lat)
    print("    deassert direction is the one that bites: for %d cycles = %.0f ns"
          % (lat, ns))
    print("    after the master deselects us, WE ARE STILL DRIVING.")
    print()
    print("    ⭐ This is a real, named quantity on real parts -- the MB85RS64V")
    print("    AC table has an 'Output disable time' and a 'Deselect time'. ⛔ Its")
    print("    VALUES are not quoted: that table's text layer is scrambled (the")
    print("    1.1 evidence boundary for this very part), so the parameter names")
    print("    are evidence and the numbers are not.")
    print()
    print("    So the threshold is NOT taken from the datasheet. It is stated as")
    print("    a requirement on the MASTER, and then priced against our own")
    print("    lane table, which we do own:")
    spi_t = next(l for l in LANES if l.name.startswith("SPI-target"))
    half = spi_t.t
    print("      our release latency              %d cyc  %.0f ns"
          % (lat, ns))
    print("      SPI-target SCK half-period       %d cyc  %.0f ns"
          % (half, half / HZ * 1e9))
    print("      release as a fraction of a HALF  %.0f%%"
          % (100.0 * lat / half))
    print("      release as a fraction of a BIT   %.0f%%"
          % (100.0 * lat / (2 * half)))
    ok_margin = lat < half
    print("    ⇒ release completes inside ONE SCK half-period: %s"
          % ("yes" if ok_margin else "*** NO"))
    if not ok_margin:
        rc = 1
    print()
    print("    ⭐ WHY THAT IS THE RIGHT COMPARISON. A master that deselects us")
    print("    and selects another target has to move two of its own GPIOs; it")
    print("    cannot plausibly do so faster than it clocks SCK. So a gap of at")
    print("    least one half-period is implied by the master being able to run")
    print("    the bus at all. ⚠ IMPLIED, NOT GUARANTEED -- so it goes in the")
    print("    host-facing spec next to the serial format, as 1.6r.")

    print()
    print("    --- the firing witness for 1.6r ---")
    # a master that re-selects the other target IMMEDIATELY on deselecting us
    cs_fast_ours = [True] * 4 + [False] * 12
    cs_fast_other = [False] * 4 + [True] * 12
    bad = run_bus(oe_registered_release, cs_fast_ours, cs_fast_other)
    print("    master deselects us at step 4 and selects the FRAM at step 4")
    print("    (gap = 0), RULED design including its release latency:")
    print("      contention on %d cycles%s"
          % (len(bad), (" -- steps %s" % [s for s, _ in bad]) if bad else ""))
    if not bad:
        print("    *** UNPRICED: a zero-gap master must contend, or the")
        print("        condition is not testing release latency at all")
        rc = 1
    else:
        print("    ⭐ FIRES, and the count IS the latency: %d cycles of overlap"
              % len(bad))
        print("    for a %d-cycle release. ⛔ Note the RULED design is what"
              % lat)
        print("    contends here -- this is not a mutant. The condition is on")
        print("    the MASTER, and that is what makes it host-facing spec.")
        need = lat
        print("    ⇒ 1.6r: the master must leave >= %d cycles (%.0f ns) between"
              % (need, ns))
        print("      deasserting SPI-target CS and asserting another target's.")

    # ---- 5. what Part 1 owes -------------------------------------------
    print()
    print("  --- 5. what Part 1 and Phase 2 owe ---")
    print("    Part 1 RTL:")
    print("      * MISO on `uio`, `uio_oe[MISO] = synchronised target CS`,")
    print("        REGISTERED (F2 covers uio_oe)")
    print("      * every other `uio_oe` bit for an INPUT pin held at 0")
    print("      * I2C SCL/SDA stay open-drain on `uio`: drive 0, release for 1")
    print("    Phase 2 cocotb must-fire:")
    print("      * with our CS deasserted, MISO reads high-Z (not 0, not 1)")
    print("      * a mutant driving MISO while deselected FAILS, and fails for")
    print("        CONTENTION with a second modelled target -- not merely for a")
    print("        wrong data value, which a single-target bench cannot tell")
    print("        apart. ⛔ A one-target bench CANNOT kill this mutant: with")
    print("        nothing else driving, an always-driven MISO reads correct.")
    print("        That is why the bench needs the FRAM model on the line.")

    print()
    print("=" * 78)
    print("  GATE miso-tristate: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * target MISO moved to `uio` with uio_oe = CS; uio %d of %d"
          % (u, N_UIO))
    print("      (full), uo_out %d of %d (%d spare)"
          % (o + N_SERIAL, N_UO, N_UO - o - N_SERIAL))
    print("    * %d of %d subsets still feasible -- COUNTED, not assumed"
          % (n_ruled, n_all))
    print("    * 3 bus faces: always-driven and combinational-OE both contend")
    print("    * ⛔ NEW: release latency %d cyc = %.0f ns -> 1.6r, a condition"
          % (lat, ns))
    print("      on the MASTER, not on us")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
