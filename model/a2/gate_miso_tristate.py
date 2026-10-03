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
    """SUPERSEDED -- fully synchronous enable, so release costs L_sync+out_reg.

    CS arrives on `uio` as an asynchronous input, so it is synchronised
    (L_SYNC) and the enable is registered (OUT_REG) per F2. The enable
    therefore follows CS by L_SYNC + OUT_REG cycles IN BOTH DIRECTIONS, and the
    deassert direction is the one that matters: for that many cycles after the
    master deselects us, we are still driving.

    ⛔ THIS IS NOW A MUTANT, NOT THE DESIGN. It was the design for one batch,
    and its cost was being pushed onto the host as "the master must leave >= N
    cycles". That is a fallback, not a fix: a 4-cycle contention window is real
    and the host cannot be relied on to avoid it.
    """
    lat = L_SYNC + OUT_REG
    past = hist["cs"][max(0, step - lat)] if step - lat >= 0 else False
    return bool(past)


def oe_async_clear(step, cs_asserted, hist):
    """✅ RULED -- ASYNC-ASSERT / SYNC-DEASSERT on the enable.

    ⭐ The reset-synchroniser pattern, applied to `uio_oe` instead of to a
    reset. The asymmetry is the whole idea, and it is principled rather than
    clever:

      RELEASE (oe -> 0)  CS rising ASYNCHRONOUSLY CLEARS the enable flop. No
                         clock, no synchroniser: the lag is the pad plus the
                         flop's clear delay, nanoseconds rather than 80 ns.
      ASSERT  (oe -> 1)  goes through the synchroniser exactly as before, so
                         nothing metastable ever reaches the pad.

    ⭐⭐ AND IT KEEPS F2. The pin is still driven by a flop's Q -- an
    async-clear flop is a flop. So the ruling does not trade a correctness
    property for a timing one; F2's checker simply has to recognise the cell,
    which is a classification question and not a waiver.

    ⛔ THE DIRECTION OF THE RESIDUAL RISK IS THE SAFE ONE, AND THAT IS WHY THE
    ASYMMETRY IS ALLOWED AT ALL. A glitch on CS now releases MISO for a moment.
    That costs a CORRUPTED BIT (the master samples a floating line) and it can
    NEVER cause contention, because the glitch can only turn a driver OFF. The
    superseded design had the opposite failure: it could only ever turn a
    driver ON late, which is contention. Priced in section 4.
    """
    lat = L_SYNC + OUT_REG
    if not cs_asserted:
        return False            # async clear: no clock needed, no latency
    if step == hist.get("cs_glitch_at"):
        return False            # a glitch on CS releases -- safe direction
    past = hist["cs"][max(0, step - lat)] if step - lat >= 0 else False
    return bool(past)


CS_FILTER_N = 3         # the digital filter's depth, if one existed


def oe_filtered_release(step, cs_asserted, hist):
    """⛔ THE REJECTED MITIGATION -- a DIGITAL filter on CS before the clear.

    ⛔⛔ IT CONTRADICTS THE FIX BY CONSTRUCTION, AND THAT IS WHY IT IS REJECTED
    ON STRUCTURE RATHER THAN ON PREFERENCE. To filter a glitch you must observe
    CS high for N consecutive SAMPLES before believing it -- and samples need
    the CLOCK. So the release path becomes synchronous again and the lag comes
    straight back. A filter deep enough to suppress a glitch is a filter deep
    enough to re-open the contention window the async clear exists to close.

    ⭐ A digital CS filter and an asynchronous release are MUTUALLY EXCLUSIVE.
    This is not an argument: the face below runs it through the same zero-gap
    master and the contention returns, scaling with the filter depth.

    ⇒ The only filter compatible with an async release is ANALOG, which is a
    board-level part and off this chip. Hence: RECORD the sensitivity, and ship
    a board note.
    """
    n = CS_FILTER_N
    # release only once CS has read deasserted for N consecutive samples
    if not cs_asserted:
        window = [hist["cs"][j] for j in range(max(0, step - n + 1), step + 1)]
        if len(window) == n and not any(window):
            return False
        return True             # still driving: the filter has not believed it
    lat = L_SYNC + OUT_REG
    past = hist["cs"][max(0, step - lat)] if step - lat >= 0 else False
    return bool(past)


def run_bus(ours_policy, cs_ours, cs_other, glitch_at=-1, cs_glitch_at=-1):
    """Walk a trace of a shared MISO with our target and the FRAM on it.

    Returns (contention_steps, float_while_selected_steps).

    ⛔⛔ THE BUS IS MODELLED AS ONE RESOLVED NET CARRYING BOTH DRIVERS, AND THAT
    IS THE LOAD-BEARING PART OF THE MODEL. If our MISO and the FRAM's SO were
    separate signals that a bench merely compared, contention would be
    INVISIBLE even with the FRAM present -- each driver would look fine on its
    own wire. Contention is not a property of a driver, it is a property of the
    NET, so the net is what gets modelled and `resolve` is what reports X.
    ⭐ This is the shape the Phase-2 cocotb bench has to copy.
    """
    n = len(cs_ours)
    hist = {"cs": cs_ours, "glitch_at": glitch_at,
            "cs_glitch_at": cs_glitch_at}
    ours = Target("ours", [1, 0, 1, 1, 0, 0, 1, 0], ours_policy)
    # the FRAM: a correct target, by its own datasheet
    fram = Target("MB85RS64V", [0, 1, 0, 0, 1, 1, 0, 1], oe_correct)
    bad, floating = [], []
    for s in range(n):
        mine = ours.drive(s, cs_ours[s], hist)
        d = {"ours": mine,
             "MB85RS64V": fram.drive(s, cs_other[s], hist)}
        val, conf = resolve(d)
        if conf:
            bad.append((s, conf))
        # selected but not driving = the master samples a float = a lost bit.
        # ⭐ Tracked separately from contention because they are different
        # failures with different severities, and the async-clear ruling trades
        # one for the other ON PURPOSE.
        if cs_ours[s] and mine is Z:
            floating.append(s)
    return bad, floating


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
        ("RULED: async-clear OE, CS never asserted", oe_async_clear, -1,
         False),
        ("reference: ideal uio_oe = our CS", oe_correct, -1, False),
        ("MUTANT: MISO on uo_out (always driven)", oe_always, -1, True),
        ("MUTANT: combinational uio_oe (glitch at step 10)", oe_glitchy, 10,
         True),
    ]
    print()
    print("    %-48s %-10s %s" % ("face", "contends", "verdict"))
    for label, pol, gl, want_bad in faces:
        bad, _ = run_bus(pol, cs_ours, cs_other, glitch_at=gl)
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

    # ---- 4. release latency, FIXED IN HARDWARE -------------------------
    print()
    print("  --- 4. ✅ RELEASE LATENCY: FIXED IN HARDWARE, NOT PUSHED ONTO THE")
    print("          MASTER (async-assert / sync-deassert) ---")
    lat = L_SYNC + OUT_REG
    ns = lat / HZ * 1e9
    spi_t = next(l for l in LANES if l.name.startswith("SPI-target"))
    half = spi_t.t
    print("    A FULLY SYNCHRONOUS enable costs L_sync %d + out_reg %d = %d"
          % (L_SYNC, OUT_REG, lat))
    print("    cycles = %.0f ns of release lag, IN BOTH DIRECTIONS. ⛔ Writing"
          % ns)
    print("    'the master must leave >= %d cycles' into the host spec is a"
          % (lat + 1))
    print("    FALLBACK, NOT A FIX: the contention window is real and a host")
    print("    cannot be relied on to avoid it.")
    print()
    print("    ✅ THE FIX -- the reset-synchroniser pattern on the ENABLE:")
    print("      RELEASE  CS rising ASYNCHRONOUSLY CLEARS the uio_oe flop.")
    print("               No clock, no synchroniser -> lag is the pad plus the")
    print("               flop's clear delay. NANOSECONDS, not %.0f ns." % ns)
    print("      ASSERT   re-enable on CS falling goes through the")
    print("               synchroniser as before, so nothing metastable ever")
    print("               reaches the pad.")
    print()
    print("    ⭐⭐ AND F2 STILL HOLDS. The pin is driven by a flop's Q -- an")
    print("    async-clear flop IS a flop. So this does not trade a")
    print("    correctness property for a timing one. F2's checker only has to")
    print("    RECOGNISE the cell, which is classification, not a waiver, and")
    print("    F2 now carries a face that proves it does.")

    # ---- the two-sided must-fire Wilson specified ----------------------
    print()
    print("    --- MUST-FIRE: a ZERO-GAP master. The fix must show 0 cycles,")
    print("        and the superseded synchronous design must FAIL ---")
    cs_fast_ours = [True] * 4 + [False] * 12
    cs_fast_other = [False] * 4 + [True] * 12
    print()
    print("    %-40s %-12s %s" % ("enable design", "contends", "verdict"))
    two_sided = True
    for label, pol, want in (
            ("✅ async-clear (RULED)", oe_async_clear, 0),
            ("⛔ fully synchronous (SUPERSEDED)", oe_registered_release, lat)):
        bad, _ = run_bus(pol, cs_fast_ours, cs_fast_other)
        ok = len(bad) == want
        print("    %-40s %-12s %s"
              % (label, "%d cyc" % len(bad),
                 "as expected" if ok else "*** WRONG, wanted %d" % want))
        if not ok:
            rc = 1
            two_sided = False
    if two_sided:
        print()
        print("    ⭐⭐ TWO-SIDED, WHICH IS WHAT MAKES IT A REAL MUST-FIRE. The")
        print("    fix shows ZERO contention beyond pad delay and the design it")
        print("    replaces shows exactly %d cycles. A one-sided arm would only" % lat)
        print("    show the new design passing, which any design that never")
        print("    drives would also do.")

    # ---- the risk the asymmetry introduces, priced ---------------------
    print()
    print("    --- ⚠ THE RISK THE ASYMMETRY BUYS, PRICED ---")
    print("    A glitch on CS now RELEASES MISO mid-transfer. Modelled: our CS")
    print("    asserted throughout, one spurious CS glitch at step 6.")
    cs_sel = [True] * 12
    cs_idle = [False] * 12
    # ⛔ ISOLATE THE TERM. The same trace WITHOUT a glitch already floats for
    # the first L_sync+out_reg steps, because the ASSERT path is synchronised.
    # Reporting the raw count would charge the glitch for the assert warm-up
    # and overstate the risk this arm exists to price, so the cost is the
    # DIFFERENCE between the two runs.
    base_bad, base_float = run_bus(oe_async_clear, cs_sel, cs_idle)
    g_bad, g_float = run_bus(oe_async_clear, cs_sel, cs_idle, cs_glitch_at=6)
    only_glitch = sorted(set(g_float) - set(base_float))
    print("      contention cycles, no glitch   %d" % len(base_bad))
    print("      contention cycles, WITH glitch %d" % len(g_bad))
    print("      floating, no glitch            %d  (steps %s -- the ASSERT"
          % (len(base_float), base_float))
    print("                                         path's synchroniser)")
    print("      floating, WITH glitch          %d  (steps %s)"
          % (len(g_float), g_float))
    print("      ⇒ COST OF THE GLITCH ALONE     %d  (steps %s)"
          % (len(only_glitch), only_glitch))
    print()
    print("    ⭐ THE DIRECTION IS THE SAFE ONE, AND THAT IS THE WHOLE")
    print("    JUSTIFICATION FOR THE ASYMMETRY. A glitch can only turn a")
    print("    driver OFF, so it costs a CORRUPTED BIT (the master samples a")
    print("    float) and can NEVER cause contention. The superseded design")
    print("    failed the other way -- it could only turn a driver ON late,")
    print("    which IS contention. ⛔ A corrupted bit is a detected,")
    print("    retryable protocol error; contention is two output stages")
    print("    fighting. Not the same severity.")
    if len(g_bad) != 0:
        print("    *** the async-clear path produced contention -- the safety")
        print("        argument for the asymmetry does not hold")
        rc = 1
    if not only_glitch:
        print("    *** UNPRICED: the CS glitch cost nothing ON TOP OF the")
        print("        assert warm-up, so this arm is not measuring the risk")
        print("        it names")
        rc = 1
    # ---- the mitigation, RULED -- and ruled on structure ---------------
    print()
    print("    --- ✅ MITIGATION RULED: *RECORD*, NOT FILTER. And the reason is")
    print("        STRUCTURAL, so it is checked rather than argued ---")
    print("    To filter a glitch you must see CS deasserted for N consecutive")
    print("    SAMPLES before believing it -- and samples need the CLOCK. So a")
    print("    digital filter makes the release path synchronous again and the")
    print("    lag comes back. ⛔ A DIGITAL CS FILTER AND AN ASYNC RELEASE ARE")
    print("    MUTUALLY EXCLUSIVE. Run it through the same zero-gap master:")
    print()
    print("    %-44s %-12s %s" % ("release path", "contends", "glitch cost"))
    for label, pol in (("✅ async clear, NO filter (RULED)", oe_async_clear),
                       ("⛔ async clear + %d-sample digital filter"
                        % CS_FILTER_N, oe_filtered_release),
                       ("⛔ fully synchronous (superseded)",
                        oe_registered_release)):
        zb, _ = run_bus(pol, cs_fast_ours, cs_fast_other)
        _, bf = run_bus(pol, cs_sel, cs_idle)
        _, gf2 = run_bus(pol, cs_sel, cs_idle, cs_glitch_at=6)
        gonly = sorted(set(gf2) - set(bf))
        print("    %-44s %-12s %s"
              % (label, "%d cyc" % len(zb), "%d bit" % len(gonly)))
    filt_bad, _ = run_bus(oe_filtered_release, cs_fast_ours, cs_fast_other)
    if not filt_bad:
        print("    *** the filter did NOT re-introduce contention, so the")
        print("        structural argument for rejecting it is not supported")
        rc = 1
    else:
        print()
        print("    ⭐⭐ THE FILTER BUYS THE GLITCH BACK BY PAYING THE CONTENTION")
        print("    AGAIN -- %d cycles for an %d-sample filter (N-1: it releases"
              % (len(filt_bad), CS_FILTER_N))
        print("    on the Nth agreeing sample), AND IT SCALES WITH DEPTH. It")
        print("    suppresses a 1-BIT corruption by re-opening a MULTI-CYCLE")
        print("    window of two output stages fighting. A strictly worse")
        print("    trade, and the SAME trade the fully synchronous design")
        print("    already lost.")
    print()
    print("    ⇒ ✅ RULED: ASYNC RELEASE, NO DIGITAL FILTER.")
    print("      * the glitch sensitivity is RECORDED, not engineered away:")
    print("        1 floating bit, SAFE DIRECTION (driver off, 0 contention)")
    print("      * the only filter compatible with an async release is ANALOG,")
    print("        which is a board part and OFF THIS CHIP")
    print("      * ⇒ BOARD NOTE, shipped with the datasheet: KEEP CS CLEAN.")
    print("    ⭐ This settles Part 1's open choice BY STRUCTURE, not by")
    print("    preference -- which is the only kind of settlement that survives")
    print("    somebody re-opening it later.")
    print()
    print("    ⛔ AND STA MUST CONSTRAIN THE ASYNC PATH. An asynchronous clear")
    print("    needs RECOVERY and REMOVAL checks on its DEASSERT edge -- the")
    print("    clear releasing too near a clock edge is its own metastability")
    print("    hazard, moved rather than removed. That is an SDC obligation and")
    print("    it joins the Phase-4 design SDC, named here so it is not")
    print("    discovered by a timing report nobody read.")

    # ---- what remains on the host, which is only the assert side -------
    print()
    print("    --- what REMAINS in the host-facing spec: the ASSERT side only")
    print("    MISO becomes valid ~%d cycles (%.0f ns) after CS falls, because"
          % (lat, ns))
    print("    the assert direction still goes through the synchroniser. So the")
    print("    requirement on the master is a SETUP, not a gap:")
    print("      CS setup >= %d cycles before the first SCLK edge" % lat)
    print("      against the SCK half-period of %d cyc (%.0f ns) = %.0f%%"
          % (half, half / HZ * 1e9, 100.0 * lat / half))
    ok_margin = lat < half
    print("    ⇒ inside one SCK half-period: %s"
          % ("yes" if ok_margin else "*** NO"))
    if not ok_margin:
        rc = 1
    print("    ⭐ CS-setup-before-first-clock is ROUTINE for an SPI target --")
    print("    every target has one. That is the difference between this and")
    print("    what it replaces: an inter-select GAP is an unusual demand on a")
    print("    master, a CS setup time is what masters already provide.")
    print()
    print("    ⛔ ONE NUMBER IS STILL DELIBERATELY NOT QUOTED. The MB85RS64V AC")
    print("    table NAMES an 'Output disable time' and a 'Deselect time', so")
    print("    release latency is a budgeted quantity on real parts rather than")
    print("    something this gate invented. But that table's text layer is")
    print("    SCRAMBLED (the 1.1 boundary for this very part): it reads 'Clock")
    print("    low time tCSH 25' and 'Chip select hold time tODV', with the")
    print("    parameter and symbol columns misaligned. ⇒ The parameter NAMES")
    print("    are evidence; the VALUES are not, and none is used.")

    # ---- 5. what Part 1 owes -------------------------------------------
    print()
    print("  --- 5. what Part 1 and Phase 2 owe ---")
    print("    Part 1 RTL:")
    print("      * MISO on `uio`; `uio_oe[MISO]` is a flop with an ASYNC CLEAR")
    print("        driven by CS rising, and a synchronised ASSERT path")
    print("      * ✅ NO digital CS filter -- RULED, on structure: a filter")
    print("        needs the clock and so re-introduces the release lag")
    print("      * the glitch sensitivity is RECORDED (1 floating bit, safe")
    print("        direction) + a BOARD NOTE: keep CS clean")
    print("      * every other `uio_oe` bit for an INPUT pin held at 0")
    print("      * I2C SCL/SDA stay open-drain on `uio`: drive 0, release for 1")
    print("    Phase 4 SDC:")
    print("      * RECOVERY/REMOVAL on the async clear's deassert edge")
    print("    Phase 2 cocotb must-fire:")
    print("      * with our CS deasserted, MISO reads high-Z (not 0, not 1)")
    print("      * ⛔⛔ THE BUS MUST BE ONE RESOLVED TRI-STATE NET CARRYING BOTH")
    print("        DRIVERS (our MISO + the FRAM's SO), contention resolving to")
    print("        X, and the bench asserting NO X. If the bench wires the two")
    print("        drivers to SEPARATE signals and compares them, contention is")
    print("        INVISIBLE even with the FRAM present -- each driver looks")
    print("        fine on its own wire. Contention is a property of the NET.")
    print("      * the always-driven mutant must fail WITH X ON THE SHARED NET,")
    print("        not merely with a wrong data value. ⛔ A single-target bench")
    print("        cannot kill it at all: with nothing else driving, an")
    print("        always-driven MISO reads correct.")
    print("      * the zero-gap master arm: 0 contention cycles with the")
    print("        async-clear enable, and the fully synchronous enable FAILS it")

    print()
    print("=" * 78)
    print("  GATE miso-tristate: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * target MISO moved to `uio` with uio_oe = CS; uio %d of %d"
          % (u, N_UIO))
    print("      (full), uo_out %d of %d (%d spare)"
          % (o + N_SERIAL, N_UO, N_UO - o - N_SERIAL))
    print("    * %d of %d subsets still feasible -- COUNTED, not assumed"
          % (n_ruled, n_all))
    print("    * 4 bus faces on ONE RESOLVED NET: always-driven and")
    print("      combinational-OE both contend; the async-clear enable does not")
    print("    * ✅ release FIXED IN HARDWARE: async-clear enable -> 0 cycles of")
    print("      contention under a zero-gap master, where the fully")
    print("      synchronous design shows %d. Two-sided must-fire." % lat)
    print("    * ⚠ priced: a CS glitch costs a floating bit, NEVER contention")
    print("    * host spec keeps the ASSERT side only: CS setup >= %d cyc"
          % lat)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
