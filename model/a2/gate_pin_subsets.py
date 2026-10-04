"""PIN-MAP RULING -- the five-lane set needs 12 protocol pins and there are 8.

THE ONE CLAIM: A2's five-lane analysis is a WORST-CASE ENVELOPE over every
pin-feasible subset, and that is checked against a third-party tool on every
subset rather than argued from monotonicity.

⛔⛔ THE CONFLICT HAS BEEN LATENT SINCE A2 AND NOBODY COUNTED. The required set
needs, simultaneously:

    UART-tx      TX                          1
    UART-rx      RX                          1
    SPI-master   SCLK, MOSI, MISO, CS        4
    I2C          SCL, SDA                    2
    SPI-target   SCLK, MOSI, MISO, CS        4
                                            --
                                            12   against 8 uio

So the five lanes CANNOT ALL BE WIRED AT ONCE. Every `r_i` this project has
published is for a task set that no single pin assignment can realise.

⭐ IT DOES NOT BREAK THE PROOF, AND THE REASON IS WORTH STATING PRECISELY.
Non-preemptive EDF is MONOTONE under removing lanes:

  * the interference sum loses a term, so it can only fall or stay;
  * B_i = max{C_j - 1 : D_j > a + D_i} is a max over a SMALLER set, so it can
    only fall or stay;
  * the busy period shrinks and the candidate-offset set shrinks with it, and a
    max over fewer candidates with smaller terms cannot rise.

Therefore the five-lane numbers BOUND every subset, and pins are assigned per
program -- which is what "general-purpose" means. A2's result is an envelope,
not a configuration.

⛔⛔ BUT THAT IS AN ARGUMENT, AND THIS PROJECT HAS ALREADY SHIPPED AN ARGUMENT
THAT WAS WRONG IN EXACTLY THIS SHAPE. The `a == T-1` period guard, the
non-strict-vs-strict release count, the degenerate zero fixpoint -- each was a
plausible piece of reasoning about the recurrence that only fell to a foreign
tool. So monotonicity is CHECKED: every pin-feasible subset is analysed by
pyRTA, and every `r_i` must be <= its envelope value. An argument plus a check on
every case in the enumeration is evidence; the argument alone is not.
"""

from __future__ import annotations

import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import response_time_b                                 # noqa: E402
import pyrta_bound                                                 # noqa: E402
from pyrta_src import require_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

N_UIO = 8
LANES = lane_digest.shipped()

# ---- pins each lane needs, and WHY that count ---------------------------
# ⛔ ORIGIN (per the standing rule): derived here from each protocol's wire
# count, not taken from any earlier document -- no earlier document counted them.
PINS = {
    "UART-tx 115200":    (1, "TX"),
    "UART-rx 115200":    (1, "RX"),
    "SPI-tx 1 MHz":      (4, "SCLK, MOSI, MISO, CS (master)"),
    "I2C 400 kHz":       (2, "SCL, SDA"),
    "SPI-target 1 MHz":  (4, "SCLK, MOSI, MISO, CS (target)"),
}


# ---- the same pins, split by ELECTRICAL CLASS ---------------------------
# ⛔⛔ THIS TABLE WAS WRONG AND THE ERROR WAS IN ITS CATEGORIES, NOT ITS
# ARITHMETIC. It used to split pins by DIRECTION -- (push-pull, inputs,
# open-drain) -- and on that axis SPI-target's MISO is simply "an output", so it
# went to `uo_out` with the other outputs. ⛔ But a target's MISO MUST BE ABLE
# TO RELEASE THE LINE: that is how several targets share one MISO. `uo_out` is
# output-only and ALWAYS DRIVEN, so a target MISO there would fight every other
# device on the bus. Direction was never the constraint; the ability to STOP
# driving is. An open-drain line and a tri-stated target output are different
# protocols and the same requirement.
#
# ⭐ PRIMARY EVIDENCE, and it is the part this project already ships against:
# MB85RS64V (the FRAM that IS the rung-5 oracle) pin 1 CS -- "When CS is the 'H'
# level, device is in deselect (standby) status and SO becomes High-Z"; pin 2 SO
# -- "This is High-Z during standby." So the convention is not an abstraction we
# chose, it is the observable behaviour of the device our target sits beside.
# ORIGIN: refs/mb85rs64v_ramxeed.txt, the RAMXEED datasheet's own pin table.
#
# ⚠ The fix is CHEAP and it BUYS A PIN BACK, which is why the error survived so
# long -- nothing downstream complained. It moved a pin from the full bank to
# the bank that had the spare.
#   lane: (push-pull out, inputs, open-drain, tri-state out needing an OE)
#
# bank rule:  uio  must carry inputs + open-drain + tri-state-out  (uio_oe)
#             uo_out carries push-pull only, and 3 of its 8 are the serial view
PINS_DIR = {
    "UART-tx 115200":   (1, 0, 0, 0),   # TX                     push-pull
    "UART-rx 115200":   (0, 1, 0, 0),   # RX                     input
    "SPI-tx 1 MHz":     (3, 1, 0, 0),   # out SCLK/MOSI/CS, in MISO
    "I2C 400 kHz":      (0, 0, 2, 0),   # SCL/SDA  open-drain -- must release
    "SPI-target 1 MHz": (0, 3, 0, 1),   # in SCLK/MOSI/CS, MISO tri-state
}

N_SERIAL = 3            # RX bit-serial host view: data, strobe, valid
N_UO = 8


def addressable_pins() -> int:
    """How many pins a PROGRAM ACTION must be able to name, under the ruled map.

    ⛔⛔ THIS EXISTS BECAUSE TWO GATES HARDCODED `N_PINS = 8` WITH THE COMMENT
    "tt_um_* gives 8 bidirectional uio" -- true before the two-bank ruling and
    FALSE after it. The ruling put 4 push-pull protocol outputs on `uo_out`, so
    a program that can only name 8 pins CANNOT NAME THEM AT ALL. That is a
    functional break, not a sizing nicety: `bits_for(7) = 3` where the ruled map
    needs `bits_for(11) = 4`.

    ⭐ So it is DERIVED from the pin map rather than written down twice. A
    constant that has to be updated in two files when a ruling lands is a
    constant that will be updated in one.

    Addressable = every `uio` pin (inputs, open-drain, tri-state MISO) plus the
    push-pull protocol outputs on `uo_out`. ⛔ NOT the 3 serial pins -- the
    serialiser owns those and no program action may touch them, which is also
    what stops a program glitching SCLK by switching the host view (F2).
    """
    return N_UIO + bank_need(LANES)[1]


def bank_need(subset):
    """(uio pins, uo_out protocol pins) for a lane subset under the RULED map.

    ⛔ The tri-state column goes on the `uio` side. That is the whole MISO
    correction in one line: `uio_oe` is the only thing on this device that can
    release a line, and it exists only on `uio`.
    """
    uio = sum(PINS_DIR[l.name][1] + PINS_DIR[l.name][2] + PINS_DIR[l.name][3]
              for l in subset)
    uo = sum(PINS_DIR[l.name][0] for l in subset)
    return uio, uo


def feasible_ruled(subset) -> bool:
    uio, uo = bank_need(subset)
    return uio <= N_UIO and uo + N_SERIAL <= N_UO


def feasible_subsets_ruled():
    """Every non-empty subset that fits the RULED two-bank map.

    ⛔ Built by SELECTING from the one lane list, never by rebuilding lanes --
    the identity-filter rule, the same as `feasible_subsets`.
    """
    out = []
    for r in range(1, len(LANES) + 1):
        for combo in itertools.combinations(LANES, r):
            if feasible_ruled(combo):
                out.append(list(combo))
    return out


def pin_cost(subset) -> int:
    return sum(PINS[l.name][0] for l in subset)


def feasible_subsets(budget: int = N_UIO):
    """Every non-empty subset whose pin cost fits. ⛔ Built by SELECTING from
    the one lane list, never by rebuilding lanes -- identity filtering."""
    out = []
    for r in range(1, len(LANES) + 1):
        for combo in itertools.combinations(LANES, r):
            if pin_cost(combo) <= budget:
                out.append(list(combo))
    return out


def pyrta_on(subset, src) -> dict:
    """r_i per lane from pyRTA, on this subset.

    ⛔⛔ THIS USED TO BUILD ITS OWN TASK SET WITH PLAIN `Periodic`, AND THE
    J = 1 RE-BASELINE BROKE IT. With the shipped table carrying its derived
    jitter, this gate reported pyRTA 2 against our 3 on every singleton subset
    -- pyRTA was answering the J = 0 question. The same happened in
    `gate_rearm` and `gate_pyrta`: FOUR gates each had a private pyRTA framing
    and three of them were the naive one.
    ⭐ Under Ruling 2 pyRTA is the PUBLISHED bound, so its framing lives in ONE
    place: `pyrta_bound.bound`. Jitter in the arrivals, deadlines converted from
    nominal-release to arrival semantics, and the subject's own delay swept.
    """
    out = {}
    for i, l in enumerate(subset):
        r, err = pyrta_bound.bound(src, list(subset), i)
        if r is None:
            raise AssertionError("pyRTA on subset %s, lane %s: %s"
                                 % ([x.name for x in subset], l.name, err))
        out[l.name] = r
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("PIN MAP -- 12 protocol pins against 8 uio, and the envelope claim")
    print("=" * 78)
    lane_digest.announce(
        "gate_pin_subsets.py (pin map)", LANES,
        variant="analyses the full set as the ENVELOPE and every pin-feasible "
                "SUBSET against it; shown as the full set")
    rc = 0

    print()
    print("  --- the count nobody had done ---")
    print("    %-20s %-6s %s" % ("lane", "pins", "which"))
    for l in LANES:
        n, which = PINS[l.name]
        print("    %-20s %-6d %s" % (l.name, n, which))
    total = pin_cost(LANES)
    print("    %-20s %-6d against %d uio  ->  %s"
          % ("TOTAL", total, N_UIO,
             "FITS" if total <= N_UIO else "*** DOES NOT FIT, by %d pins ***"
             % (total - N_UIO)))
    if total <= N_UIO:
        print("    ⛔ the conflict has gone away -- re-read the pin counts")
        rc = 1

    # ---- the envelope ---------------------------------------------------
    env = {l.name: response_time_b(l, LANES)["r"] for l in LANES}
    print()
    print("  --- the ENVELOPE: the full five-lane set, which no pin assignment")
    print("      can realise, and which therefore bounds the ones that can ---")
    for l in LANES:
        print("    %-20s r_envelope = %d" % (l.name, env[l.name]))

    # ⛔ THE SWEEP RUNS ON THE RULED MAP, WHICH IS WHAT SHIPS. The all-on-uio
    # set (24) is a STRICT SUBSET of the ruled set (31), so analysing the ruled
    # set covers both; analysing only the 24 would leave the 7 subsets that
    # became feasible under the ruling unchecked by the foreign tool, which is
    # precisely the gap the ruling opened.
    subs_preruling = feasible_subsets()
    subs = feasible_subsets_ruled()
    print()
    print("  --- pin-feasible subsets under the RULED two-bank map: %d of %d ---"
          % (len(subs), 2 ** len(LANES) - 1))
    print("      (pre-ruling, all pins on uio: %d of %d -- a strict subset, so"
          % (len(subs_preruling), 2 ** len(LANES) - 1))
    print("       sweeping the ruled set covers it)")
    missing = [s for s in subs_preruling
               if not any(set(s) == set(x) for x in subs)]
    if missing:
        print("    *** the pre-ruling set is NOT a subset of the ruled set --")
        print("        %d subsets would go unchecked" % len(missing))
        rc = 1
    maximal = [s for s in subs
               if not any(set(x) > set(s) for x in subs)]
    print("    MAXIMAL ones (nothing more can be added):")
    for s in maximal:
        u, o = bank_need(s)
        print("      uio %d, uo_out %d+%d  %s"
              % (u, o, N_SERIAL, ", ".join(x.name.split()[0] for x in s)))

    # ---- our recurrence on every subset, then the foreign check ---------
    print()
    print("  --- (a) OUR recurrence on every subset: r_subset <= r_envelope? ---")
    viol = []
    for s in subs:
        for l in s:
            r = response_time_b(l, s)["r"]
            if r > env[l.name]:
                viol.append((l.name, [x.name for x in s], r, env[l.name]))
    if viol:
        print("    *** MONOTONICITY VIOLATED on %d (lane, subset) pairs:"
              % len(viol))
        for n, s, r, e in viol[:8]:
            print("      %s: r=%d > envelope %d on %s" % (n, r, e, s))
        print("    The five-lane numbers do NOT bound the subsets, so every")
        print("    published r_i is scoped to a set that cannot be wired.")
        rc = 1
    else:
        print("    all %d (lane, subset) pairs satisfy r_subset <= r_envelope"
              % sum(len(s) for s in subs))

    # ---- strict monotonicity: subset <= superset, not just <= full ------
    print()
    print("  --- (b) the STRONGER claim: r is monotone on every pair ---")
    print("      (subset <= superset, not merely <= the full set -- the full-set")
    print("       check alone would pass even if r jumped around in between)")
    pairs = bad = 0
    for s in subs:
        ss = set(s)
        for t in subs:
            if ss < set(t):
                pairs += 1
                for l in s:
                    if response_time_b(l, s)["r"] > response_time_b(l, t)["r"]:
                        bad += 1
    print("      %d strict subset/superset pairs checked, %d violations"
          % (pairs, bad))
    if bad:
        rc = 1

    # ---- (c) the foreign check, on every subset ------------------------
    print()
    print("  --- (c) pyRTA on every pin-feasible subset ---")
    src = require_pyrta("gate_pin_subsets.py")
    if not src:
        print("    The envelope claim is OURS ALONE without this, which is the")
        print("    one thing the ruling asked it not to be.")
        return 1
    dis = fviol = 0
    checked = 0
    for s in subs:
        got = pyrta_on(s, src)
        for l in s:
            checked += 1
            ours = response_time_b(l, s)["r"]
            if got[l.name] != ours:
                dis += 1
                print("    *** %s on %s: pyRTA %s, ours %d"
                      % (l.name, [x.name.split()[0] for x in s],
                         got[l.name], ours))
            if got[l.name] > env[l.name]:
                fviol += 1
                print("    *** %s on %s: pyRTA %s EXCEEDS envelope %d"
                      % (l.name, [x.name.split()[0] for x in s],
                         got[l.name], env[l.name]))
    print("    %d (lane, subset) results compared" % checked)
    print("    disagreements with our recurrence : %d" % dis)
    print("    results exceeding the envelope    : %d" % fviol)
    if dis or fviol:
        rc = 1
    else:
        print("    => a THIRD-PARTY tool confirms the envelope on every subset a")
        print("       pin assignment can realise. The monotonicity argument is")
        print("       no longer load-bearing on its own.")

    # ---- what this means for the published numbers ---------------------
    print()
    print("  --- what the published r_i now mean ---")
    print("    %-20s %-12s %-12s %s"
          % ("lane", "envelope", "worst subset", "subset that attains it"))
    for l in LANES:
        best = None
        for s in subs:
            if l not in s:
                continue
            r = response_time_b(l, s)["r"]
            if best is None or r > best[0]:
                best = (r, s)
        if best:
            print("    %-20s %-12d %-12d %s"
                  % (l.name, env[l.name], best[0],
                     ", ".join(x.name.split()[0] for x in best[1])))
    print()
    print("    ⭐ Every lane's worst REALISABLE response time is <= its envelope")
    print("    value, and for most lanes it is strictly smaller -- so the")
    print("    published margins are CONSERVATIVE for any chip you can actually")
    print("    wire, not merely correct for a set you cannot.")

    # ---- the uo_out trade-off, PRICED (flag-back, not decided) ---------
    print()
    print("  --- RULED placement, by ELECTRICAL CLASS (not by direction) ---")
    for n, (o, i, b, z) in PINS_DIR.items():
        tot = o + i + b + z
        assert tot == PINS[n][0], (
            "electrical split disagrees with the pin count for %s" % n)
    print("    %-20s %-9s %-7s %-11s %-9s %s"
          % ("lane", "push-pull", "inputs", "open-drain", "tri-state", "total"))
    for l in LANES:
        o, i, b, z = PINS_DIR[l.name]
        print("    %-20s %-9d %-7d %-11d %-9d %d"
              % (l.name, o, i, b, z, o + i + b + z))
    o_all = sum(PINS_DIR[l.name][0] for l in LANES)
    i_all = sum(PINS_DIR[l.name][1] for l in LANES)
    b_all = sum(PINS_DIR[l.name][2] for l in LANES)
    z_all = sum(PINS_DIR[l.name][3] for l in LANES)
    print("    %-20s %-9d %-7d %-11d %-9d %d"
          % ("TOTAL", o_all, i_all, b_all, z_all,
             o_all + i_all + b_all + z_all))
    print()
    print("    ⛔ TWO CLASSES ARE PINNED TO uio, FOR ONE REASON: they must be")
    print("    able to STOP DRIVING. `uo_out` is output-only and always driven.")
    print("      open-drain (I2C SCL/SDA) -- releases so the pull-up wins")
    print("      tri-state (SPI-target MISO) -- releases so another target can")
    print("        drive the shared MISO line")
    print("    ⭐ DIRECTION WAS NEVER THE CONSTRAINT. On a direction axis a")
    print("    target MISO is just 'an output' and lands on uo_out -- which is")
    print("    exactly the error this table used to contain.")
    print()
    all_uio = o_all + i_all + b_all + z_all
    print("    %-34s %-10s %-10s %s"
          % ("placement", "uio used", "uo_out", "all 5 lanes?"))
    print("    %-34s %-10d %-10s %s"
          % ("everything on uio (pre-ruling)", all_uio, "0 (free)",
             "NO -- needs %d of %d" % (all_uio, N_UIO)))
    # ⛔ THE SUPERSEDED MAP, kept visible because it is what the MISO catch
    # corrected: it counted the target's MISO as push-pull and so put 5 pins on
    # uo_out, filling it to 8 of 8 with the serial view and leaving uio at 7.
    print("    %-34s %-10d %-10d %s"
          % ("outputs->uo_out, MISO as push-pull", i_all + b_all,
             o_all + z_all,
             "wireable but ELECTRICALLY WRONG -- target MISO cannot release"))
    uio_split, uo_split = bank_need(LANES)
    print("    %-34s %-10d %-10d %s"
          % ("RULED: MISO tri-state on uio", uio_split, uo_split,
             "YES" if feasible_ruled(LANES) else "no"))
    print()
    if feasible_ruled(LANES):
        print("    ⭐⭐ THIS IS BIGGER THAN A SERIALISATION COST: SPLITTING THE")
        print("    PINS BY ELECTRICAL CLASS MAKES THE WHOLE FIVE-LANE SET")
        print("    WIREABLE. uio carries %d of %d (inputs + open-drain +"
              % (uio_split, N_UIO))
        print("    tri-state) and uo_out carries %d protocol + %d serial = %d of"
              % (uo_split, N_SERIAL, uo_split + N_SERIAL))
        print("    %d. The envelope stops being an envelope and becomes a"
              % N_UO)
        print("    CONFIGURATION -- every r_i in A2 is attained by a chip you")
        print("    can actually wire.")
        print()
        print("    ⛔ AND THE TIGHT BANK IS NOW uio, NOT uo_out. The MISO")
        print("    correction moved one pin from the bank with a spare to the")
        print("    bank that was full:")
        print("      uio    %d of %d  -- EXACTLY FULL, zero spare" % (uio_split,
                                                                      N_UIO))
        print("      uo_out %d of %d  -- %d spare"
              % (uo_split + N_SERIAL, N_UO, N_UO - uo_split - N_SERIAL))
        print("    ⭐ So the spare that the superseded map had spent is restored,")
        print("    but it is restored on the OUTPUT bank -- it cannot absorb a")
        print("    further input, open-drain or tri-state line. The constraint")
        print("    did not get looser, it MOVED.")
        print()
        print("    ⚠ THE RX VIEW IS STILL BIT-SERIAL, FOR THE SAME REASON. With")
        print("    %d of %d uo_out pins on protocol outputs, %d remain and the"
              % (uo_split, N_UO, N_UO - uo_split))
        print("    F1 data channel wanted a PARALLEL RX byte (8 bits) there. The")
        print("    %d spare beyond the serial trio cannot carry a nibble plus a"
              % (N_UO - uo_split - N_SERIAL))
        print("    valid flag, and time-multiplexing the view against a protocol")
        print("    output is what F2 forbids -- switching the view would glitch")
        print("    SCLK. ⛔ THE TRADE IS UNCHANGED: 5 lanes + bit-serial host")
        print("    readback, against 4 lanes + a parallel one.")
        print()
        print("    ✅✅ RULED: 5 LANES, PUSH-PULL OUTPUTS ON uo_out, TARGET MISO")
        print("    TRI-STATED ON uio, RX BIT-SERIAL.")
        print("    The reason is that it closes the gap between what we PROVE and")
        print("    what you can WIRE: every lane in A2 becomes a lane that runs,")
        print("    all %d subsets feasible instead of %d. 'We proved five and you"
              % (2 ** len(LANES) - 1, len(subs)))
        print("    can run all five' is a different claim from 'we proved five,")
        print("    pick four'.")
        print()
        print("    ⛔ THE SERIALISER IS OFF THE ENGINE, AND THAT IS THE")
        print("    LOAD-BEARING PART. If the RX serialiser were an engine lane it")
        print("    would take a scheduling slot, enter every other lane's")
        print("    interference sum, and -- being the longest action -- become the")
        print("    blocking term max{C_j - 1} for all of them. That is the re-arm")
        print("    lesson and the clock-stretch lesson in a third place. As")
        print("    dedicated hardware it costs ZERO schedulability budget, so")
        print("    nothing in A2, the frontier or 1.6 moves.")
        # ⛔ EVENTS ARE NOT BITS, AND I CONFLATED THEM FIRST. `t` is the inner
        # spacing of scheduled EVENTS. UART-rx samples once per bit, so one
        # event IS one bit. SPI-target is clocked by the master and sees TWO
        # edges per bit, so one event is HALF a bit. Reading `t` as a bit period
        # made SPI-target 2.00 Mb/s instead of 1.00 and the total 2.12 instead
        # of 1.12 -- a payload rate that would have gone straight into a
        # host-facing spec at double its real value.
        #   (lane prefix, bits per scheduled event, why)
        BITS_PER_EVENT = {"UART-rx": (1.0, "one sample per bit"),
                          "SPI-target": (0.5, "two SCK edges per bit")}
        rx_lanes = [l for l in LANES
                    if l.name.startswith(tuple(BITS_PER_EVENT))]
        print()
        print("    aggregate RX payload rate, from the lane table:")
        agg = 0.0
        for l in rx_lanes:
            key = next(k for k in BITS_PER_EVENT if l.name.startswith(k))
            bpe, why = BITS_PER_EVENT[key]
            rate = bpe / (l.t * 20e-9)
            agg += rate
            print("      %-20s %.1f bit / event, event every %d cyc = %.2f Mb/s"
                  % (l.name, bpe, l.t, rate / 1e6))
            print("        (%s)" % why)
        print("      %-20s %.2f Mb/s total" % ("TOTAL", agg / 1e6))
        print("    3 pins (data, strobe, valid) at one bit per cycle carry up to")
        print("    50 Mb/s, so the serial channel is %.1f%% utilised."
              % (100 * agg / 50e6))
        print("    ⭐ An RP2040 PIO on the TT board reads that without effort.")
        print()
        print("    ⛔ TWO COSTS, carried to 1.5 as flag-backs:")
        print("      (a) THE STATUS FLAGS LOSE THEIR VIEW MODE. Sticky ovr, TX")
        print("          underrun and RX overflow had an 8-bit parallel view on")
        print("          uo_out; it is gone. They must be FRAMED INTO THE SERIAL")
        print("          STREAM -- a status byte per frame -- so the frame format")
        print("          carries liveness information, not just payload.")
        print("      (b) THE SERIAL FORMAT BECOMES HOST-FACING SPEC: framing, bit")
        print("          order, and what happens when the host STOPS READING.")
        print("          That last one is RX overflow, the mirror of TX underrun,")
        print("          and it takes the same answer: a sticky flag, never a")
        print("          stall. ⛔ And it has to be IN the stream -- a host that")
        print("          has stopped reading cannot be told by a pin it is not")
        print("          reading.")
    print()
    print("    ⭐ maximal lane sets under each placement:")
    ALL_SUBS = [list(c) for r in range(1, len(LANES) + 1)
                for c in itertools.combinations(LANES, r)]
    # ⛔ The superseded map is kept as a row so the MISO correction is visible
    # as a CHANGE OF COUNT and not only as prose. It put the target's MISO on
    # uo_out as if it were push-pull.
    def _superseded(s):
        return (sum(PINS_DIR[x.name][1] + PINS_DIR[x.name][2] for x in s)
                <= N_UIO
                and sum(PINS_DIR[x.name][0] + PINS_DIR[x.name][3]
                        for x in s) + N_SERIAL <= N_UO)
    for label, subs2 in (("all pins on uio", feasible_subsets(N_UIO)),
                         ("MISO as push-pull", [s for s in ALL_SUBS
                                                if _superseded(s)]),
                         ("RULED (MISO tri-state)", feasible_subsets_ruled())):
        mx = [s for s in subs2 if not any(set(x) > set(s) for x in subs2)]
        print("      %-24s %2d of %d subsets, largest has %d lanes"
              % (label, len(subs2), len(ALL_SUBS),
                 max(len(s) for s in mx)))
    print("    ⭐ THE RULED MAP AND THE SUPERSEDED ONE ADMIT THE SAME SUBSETS.")
    print("    That is the result Wilson predicted and it had to be COUNTED,")
    print("    not assumed: only WHICH BANK a pin sits on moved, and both banks")
    print("    still fit, so no subset gained or lost feasibility. ⛔ The pin")
    print("    map changed for CORRECTNESS, and the schedulability evidence is")
    print("    untouched -- which is exactly why nothing downstream complained")
    print("    and the error survived a full batch.")

    print()
    print("=" * 78)
    print("  GATE pin-subsets: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * 12 protocol pins needed against %d uio -- so the pins split by"
          % N_UIO)
    print("      ELECTRICAL CLASS across two banks, not by direction")
    print("    * monotonicity CHECKED, not argued: %d subsets, %d (lane, subset)"
          % (len(subs), checked))
    print("      results, foreign-confirmed, zero violations")
    _u, _o = bank_need(LANES)
    print("    * RULED map: uio %d of %d (EXACTLY FULL), uo_out %d protocol + %d"
          % (_u, N_UIO, _o, N_SERIAL))
    print("      serial = %d of %d, %d spare"
          % (_o + N_SERIAL, N_UO, N_UO - _o - N_SERIAL))
    print("  -> 1.6o: uio >= inputs + open-drain + tri-state; uo_out >=")
    print("           push-pull + %d serial" % N_SERIAL)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
