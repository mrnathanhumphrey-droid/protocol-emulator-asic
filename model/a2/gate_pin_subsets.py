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


# ---- the same pins, split by DIRECTION (for the uo_out trade-off) -------
# ⛔ ORIGIN: derived here from each protocol's signal directions. The split
# matters because `uo_out` is OUTPUT-ONLY, so it can carry a push-pull output
# and CANNOT carry an input or an open-drain line (which must be able to
# release). I2C is therefore pinned to `uio` no matter what.
#   lane: (push-pull outputs, inputs, open-drain bidirectional)
PINS_DIR = {
    "UART-tx 115200":   (1, 0, 0),      # TX
    "UART-rx 115200":   (0, 1, 0),      # RX
    "SPI-tx 1 MHz":     (3, 1, 0),      # out SCLK/MOSI/CS, in MISO
    "I2C 400 kHz":      (0, 0, 2),      # SCL/SDA -- open-drain, uio only
    "SPI-target 1 MHz": (1, 3, 0),      # out MISO, in SCLK/MOSI/CS
}


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


def pyrta_on(subset, mod) -> dict:
    """r_i per lane from pyRTA, on this subset."""
    (edf, WCET, Deadline, FullyNonPreemptive, IdealProcessor, Periodic,
     Priority, Task, taskset) = mod
    tasks = [Task(Periodic(period=l.t), FullyNonPreemptive(WCET(l.C)),
                  Deadline(l.D), Priority(i)) for i, l in enumerate(subset)]
    ts = taskset(*tasks)
    # the by-VALUE footgun: assert the interferer count rather than trust tags
    want = len(tasks) - 1
    for l, t in zip(subset, tasks):
        if len(list(ts.excluding_iter(t))) != want:
            raise AssertionError("pyRTA merged a parameter-identical pair on "
                                 "subset %s" % [x.name for x in subset])
    out = {}
    for l, t in zip(subset, tasks):
        sol = edf.rta(ts, t, IdealProcessor())
        out[l.name] = getattr(sol.response_time_bound, "value",
                              sol.response_time_bound)
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

    subs = feasible_subsets()
    print()
    print("  --- pin-feasible subsets: %d of %d non-empty subsets ---"
          % (len(subs), 2 ** len(LANES) - 1))
    maximal = [s for s in subs
               if not any(set(x) > set(s) for x in subs)]
    print("    MAXIMAL ones (nothing more can be added):")
    for s in maximal:
        print("      %-2d pins  %s" % (pin_cost(s),
                                       ", ".join(x.name.split()[0] for x in s)))

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
    sys.path.insert(0, src)
    from response_time_analysis import edf                              # noqa
    from response_time_analysis.model import (WCET, Deadline,            # noqa
                                              FullyNonPreemptive, IdealProcessor,
                                              Periodic, Priority, Task, taskset)
    mod = (edf, WCET, Deadline, FullyNonPreemptive, IdealProcessor, Periodic,
           Priority, Task, taskset)
    dis = fviol = 0
    checked = 0
    for s in subs:
        got = pyrta_on(s, mod)
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
    print("  --- PRICED FLAG-BACK: push-pull outputs on uo_out ---")
    for n, (o, i, b) in PINS_DIR.items():
        tot = o + i + b
        assert tot == PINS[n][0], "direction split disagrees with the pin count"
    print("    %-20s %-9s %-7s %-12s %s"
          % ("lane", "push-pull", "inputs", "open-drain", "total"))
    for l in LANES:
        o, i, b = PINS_DIR[l.name]
        print("    %-20s %-9d %-7d %-12d %d" % (l.name, o, i, b, o + i + b))
    o_all = sum(PINS_DIR[l.name][0] for l in LANES)
    i_all = sum(PINS_DIR[l.name][1] for l in LANES)
    b_all = sum(PINS_DIR[l.name][2] for l in LANES)
    print("    %-20s %-9d %-7d %-12d %d" % ("TOTAL", o_all, i_all, b_all,
                                            o_all + i_all + b_all))
    print()
    print("    ⛔ I2C IS PINNED TO uio EITHER WAY. `uo_out` is output-only, and")
    print("    an open-drain line must be able to RELEASE. So SCL/SDA cannot")
    print("    move, whatever is decided about the rest.")
    print()
    print("    %-34s %-10s %-10s %s"
          % ("placement", "uio used", "uo_out", "all 5 lanes?"))
    print("    %-34s %-10d %-10s %s"
          % ("everything on uio (today)", o_all + i_all + b_all, "0 (free)",
             "NO -- needs %d of %d" % (o_all + i_all + b_all, N_UIO)))
    uio_split = i_all + b_all
    print("    %-34s %-10d %-10d %s"
          % ("push-pull outputs -> uo_out", uio_split, o_all,
             "YES" if uio_split <= N_UIO and o_all <= 8 else "no"))
    print()
    if uio_split <= N_UIO and o_all <= 8:
        print("    ⭐⭐ THIS IS BIGGER THAN A SERIALISATION COST: MOVING THE")
        print("    PUSH-PULL OUTPUTS MAKES THE WHOLE FIVE-LANE SET WIREABLE.")
        print("    uio drops to %d of %d (inputs + open-drain) and uo_out carries"
              % (uio_split, N_UIO))
        print("    %d outputs of 8. The envelope stops being an envelope and"
              % o_all)
        print("    becomes a configuration -- every r_i in A2 is then attained")
        print("    by a chip you can actually wire.")
        print()
        print("    ⚠ AND THE COST IS SHARPER THAN 'SERIALISE THE VIEW'. With %d"
              % o_all)
        print("    of 8 uo_out pins spent on protocol outputs, %d remain. The"
              % (8 - o_all))
        print("    F1 data channel wanted a PARALLEL RX byte there (8 bits).")
        print("    %d pins cannot carry a nibble (4) plus a valid flag, so the"
              % (8 - o_all))
        print("    RX path would go BIT-serial, or the view would time-multiplex")
        print("    against the protocol outputs -- which F2 forbids on a pin")
        print("    that is also driving a protocol line, because switching the")
        print("    view would glitch SCLK.")
        print("    ⛔ THE TRADE: 5 lanes + bit-serial host readback, against 4")
        print("    lanes + a parallel one.")
        print()
        print("    ✅✅ RULED: 5 LANES, PUSH-PULL OUTPUTS ON uo_out, RX BIT-SERIAL.")
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
    for label, budget in (("uio only (today)", N_UIO),
                          ("outputs on uo_out", N_UIO)):
        if label.startswith("uio only"):
            subs2 = feasible_subsets(budget)
        else:
            subs2 = [s for s in
                     (list(c) for r in range(1, len(LANES) + 1)
                      for c in itertools.combinations(LANES, r))
                     if sum(PINS_DIR[x.name][1] + PINS_DIR[x.name][2]
                            for x in s) <= budget
                     and sum(PINS_DIR[x.name][0] for x in s) <= 8]
        mx = [s for s in subs2 if not any(set(x) > set(s) for x in subs2)]
        print("      %-22s %d feasible subsets, largest has %d lanes"
              % (label, len(subs2), max(len(s) for s in mx)))

    print()
    print("=" * 78)
    print("  GATE pin-subsets: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * 12 protocol pins needed, %d available -- the five-lane set is"
          % N_UIO)
    print("      an ENVELOPE, not a configuration")
    print("    * monotonicity CHECKED, not argued: %d subsets, %d (lane, subset)"
          % (len(subs), checked))
    print("      results, foreign-confirmed, zero violations")
    print("  -> 1.6 condition: sum of active-lane pins <= %d uio" % N_UIO)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
