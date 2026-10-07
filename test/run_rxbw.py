"""THE SERIAL LINK'S CAPACITY, MEASURED -- and the one-deep RX margin.

⛔⛔ WHAT WAS PUBLISHED AND WHY IT WAS WRONG. `1.6p` priced the RX link at
"2.2% utilised" against a capacity of 50 Mb/s -- "1 bit per cycle on the data
pin". That is the RAW PIN RATE, and the stream does not run at it:

    the serialiser shifts ONE BIT PER TWO CYCLES   (`ser_phase` toggles)
    a frame is 12 bits of which 8 are payload      (was 9 of which 8)
    `status_turn` forces a STATUS frame after every payload frame

so a payload byte leaves at best once every `2 * FRAME_BITS * 2` cycles -- 48
now, 36 at 9 bits -- and the real payload capacity is 8.33 Mb/s, not 50. The
published figure was SIX TIMES too generous, and it was already wrong before
the frame widened (11.1 Mb/s at 9 bits, quoted as 50). ⚠ That is the forbidden
direction: a host told it had 50 Mb/s of headroom has 8.33.

⭐ THE SHARPER QUANTITY IS THE ONE-DEEP PENDING REGISTER. `rx_pend` holds
exactly ONE byte; a second completion inside the payload slot sets
`rx_drop_sticky` and the byte is gone. Average rates say nothing about that --
what matters is whether two completions can land inside one slot.

WHAT THIS SWEEP DOES: drives one RX lane at a controlled completion rate and
finds the spacing at which loss STOPS. The derivation says 48 cycles; the
measurement is what decides.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from toolchain import banner, tool          # noqa: E402  ruling V

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_rx"))

SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
NCYC = 200000
FRAME_BITS = 12
CYC_PER_BIT = 2
# ⭐ DERIVED FROM THE SERIALISER, AND THE FIRST DERIVATION WAS SHORT BY TWO.
# A frame is FRAME_BITS bits at CYC_PER_BIT cycles -- but when `ser_cnt` hits
# zero the serialiser spends ONE MORE CYCLE in the else-branch queueing the
# next frame, so a frame occupies `FRAME_BITS*CYC_PER_BIT + 1` cycles. And
# `status_turn` forces a status frame after every payload frame, so payload
# slots are two frames apart:
#       2 * (12*2 + 1) = 50 cycles
# ⛔ I DERIVED 48 BY FORGETTING THE QUEUEING CYCLE, and the measurement said
# 50 -- which is the right way round: the bench reports the closest two
# payload frames ever came, and 50 was reproduced at every single sweep point.
# The constant is corrected to match the mechanism, not fitted to the data:
# the +1 is visible in the RTL's `if (ser_cnt != 4'd0) ... else` structure.
SLOT_DERIVED = 2 * (FRAME_BITS * CYC_PER_BIT + 1)

# ⛔⛔ AND THE SWEEP'S BOUNDARY IS NOT THE SLOT -- IT IS THE PROGRAM'S AVERAGE
# RATE CROSSING THE SLOT, which is a different number and was worth getting
# right rather than calling the derivation wrong. `build_rxfast` emits EIGHT
# SHIFTINs and then a REARM, so a loop is 9 actions `d` apart and carries 8
# completions: the average completion period is `9d/8`, not `d`. Inside a loop
# the arrivals ARE `d` apart and a backlog builds, and the REARM's gap is what
# drains it -- which is why the program tolerates `d` below the slot at all.
# ⇒ Sustainable iff `9d/8 >= SLOT`, i.e. `d >= ceil(8*SLOT/9)` = 45 at SLOT 50.
ACTIONS_PER_LOOP = 9
COMPL_PER_LOOP = 8
# ceil(SLOT * COMPL / ACTIONS): the smallest `d` whose average completion
# period `d * ACTIONS / COMPL` reaches the slot.
D_BOUNDARY = -(-SLOT_DERIVED * COMPL_PER_LOOP // ACTIONS_PER_LOOP)

# ⛔ THE SWEEP STRADDLES THE DERIVATION AND IS DENSE AROUND IT. A sweep that
# only sampled far from the boundary would confirm "fast drops, slow does not"
# and locate nothing -- and the project has three separate cases of a
# must-fire's witness sliding between hand-picked points, so the points near
# the predicted boundary are consecutive integers.
D_POINTS = [24, 32, 40, 44, 45, 46, 47, 48, 49, 50, 52, 64]

KEYS = ("compl", "pay", "status", "rb", "lost", "drop", "mingap", "slot",
        "matched", "unmatched")


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def build():
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "rxbw.vvp")
    r = run([tool("iverilog"), "-g2012", "-o", out, "-s", "tb_rxbw",
             "test/tb_rxbw.v"] + SRCS)
    if r.returncode != 0:
        print("*** build failed")
        print((r.stdout + r.stderr)[-800:])
        return None
    return out


def one(vvp, img, nbytes):
    r = run([tool("vvp"), vvp, "+IMG=%s" % img, "+NBYTES=%d" % nbytes,
             "+NCYC=%d" % NCYC])
    txt = r.stdout + r.stderr
    m = re.search(r"RXBW " + " ".join(r"%s=(-?\d+)" % k for k in KEYS), txt)
    if not m:
        return None, ["no RXBW line"]
    d = {k: int(m.group(i + 1)) for i, k in enumerate(KEYS)}
    bad = [l.strip() for l in txt.splitlines() if "*** FAIL" in l]
    return d, bad


def main() -> int:
    banner("iverilog", "vvp")   # ruling V2: the log names the binary that ran
    rc = 0
    print()
    print("=" * 78)
    print("THE SERIAL LINK'S CAPACITY -- measured against the derivation")
    print("=" * 78)
    print("  frame            : %d bits at %d cycles/bit = %d cycles"
          % (FRAME_BITS, CYC_PER_BIT, FRAME_BITS * CYC_PER_BIT))
    print("  payload slot     : %d cycles (a payload frame and the status"
          % SLOT_DERIVED)
    print("                     frame that always follows it)")
    print("  payload capacity : %.3f Mb/s, against the 50 Mb/s `1.6p` quoted"
          % (50e6 / SLOT_DERIVED * 8 / 1e6))
    print("  predictions, BOTH checked below:")
    print("    (a) the closest two payload frames can be is %d cycles"
          % SLOT_DERIVED)
    print("    (b) this program sustains d >= %d, because its loop carries"
          % D_BOUNDARY)
    print("        %d completions in %d actions so the average completion"
          % (COMPL_PER_LOOP, ACTIONS_PER_LOOP))
    print("        period is 9d/8, not d")
    print()
    vvp = build()
    if vvp is None:
        return 1

    print("  %-6s %-8s %-8s %-7s %-6s %-8s %-10s %s"
          % ("d", "compl", "payload", "lost", "drop", "mingap", "in-order",
             "verdict"))
    rows = []
    for d in D_POINTS:
        # ⛔ A PROBE NAME. This swept `--rxfast d` into the TRACKED
        # `rxfast_image.hex` once per point, leaving it at the last `d` under a
        # manifest entry that says 24 -- and it was committed that way,
        # because the clean room had already run and passed on the real file.
        g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
                 "--rxfast", str(d), "probe_rxfast"])
        if g.returncode != 0:
            print("  %-6d *** could not build the image" % d)
            rc = 1
            continue
        path = os.path.join(HERE, "probe_rxfast.hex")
        with open(path, encoding="ascii") as fh:
            nb = len([w for w in fh.read().split() if w])
        r, bad = one(vvp, "test/probe_rxfast.hex", nb)
        if r is None:
            print("  %-6d *** NO READING: %s" % (d, bad))
            rc = 1
            continue
        if bad:
            print("  %-6d *** bench FAILED: %s" % (d, bad[0][:46]))
            rc = 1
            continue
        # ⛔ THE TWO READINGS OF LOSS MUST AGREE -- the arithmetic and the
        # design's own flag. The bench asserts it too; asserted here as well
        # because this is where the boundary verdict is formed.
        agree = (r["lost"] > 0) == (r["drop"] == 1)
        order = r["unmatched"] == 0
        print("  %-6d %-8d %-8d %-7d %-6d %-8d %-10s %s"
              % (d, r["compl"], r["pay"], r["lost"], r["drop"], r["mingap"],
                 "ok" if order else "*** REORDERED",
                 ("clean" if r["lost"] == 0 else "drops")
                 + ("" if agree else "  *** FLAG DISAGREES")))
        if not agree or not order:
            rc = 1
        rows.append((d, r))

    print()
    print("  --- where does loss stop? ---")
    clean = [d for d, r in rows if r["lost"] == 0]
    dirty = [d for d, r in rows if r["lost"] > 0]
    if not clean or not dirty:
        print("    *** the sweep did not straddle the boundary: clean %s,"
              % clean)
        print("        dropping %s. A sweep that locates nothing confirms"
              % dirty)
        print("        nothing.")
        return 1
    boundary = min(clean)
    print("    dropping at d = %s" % dirty)
    print("    clean    at d = %s" % clean)
    print("    loss stops at d = %d; prediction (b) says %d  %s"
          % (boundary, D_BOUNDARY,
             "ok" if boundary == D_BOUNDARY else "*** THEY DISAGREE"))
    if boundary != D_BOUNDARY:
        print("    ⛔ THE DERIVATION IS WRONG, NOT THE MEASUREMENT. Both")
        print("       factors are structural -- the slot from the serialiser's")
        print("       frame-plus-queue-cycle and the 9-to-8 from the program's")
        print("       own action list -- so a different boundary means one of")
        print("       them is not what it looks like. Do not re-fit either.")
        rc = 1
    gaps = sorted({r["mingap"] for _d, r in rows if r["mingap"] > 0})
    print("    closest payload-frame gap seen : %s; prediction (a) says %d  %s"
          % (gaps, SLOT_DERIVED,
             "ok" if min(gaps) == SLOT_DERIVED else "*** THEY DISAGREE"))
    if min(gaps) != SLOT_DERIVED:
        print("    ⛔ A GAP SHORTER THAN THE SLOT would mean the frame costs")
        print("       fewer cycles than the serialiser's structure allows; a")
        print("       longer one at EVERY point would mean the link never")
        print("       reached its ceiling and the sweep proved nothing.")
        rc = 1

    # ---- the shipped lane set, re-quoted -------------------------------
    print()
    print("  --- 1.6p RE-QUOTED (the shipped two RX lanes) ---")
    sys.path.insert(0, os.path.join(ROOT, "model", "a2"))
    try:
        from bursty import SPI_RX, TX, UART_RX
    except Exception as e:                                  # pragma: no cover
        print("    *** could not import the lane table: %s" % e)
        return 1
    lanes = list(TX) + [UART_RX, SPI_RX]
    bpe = {"UART-rx": 1.0, "SPI-target": 0.5}
    rx = [l for l in lanes if l.name.startswith(tuple(bpe))]
    agg = sum(next(v for k, v in bpe.items() if l.name.startswith(k))
              / (l.t * 20e-9) for l in rx)
    cap = 50e6 / SLOT_DERIVED * 8
    print("    %-22s %s" % ("lane", "payload rate"))
    for l in rx:
        b = next(v for k, v in bpe.items() if l.name.startswith(k))
        print("    %-22s %.3f Mb/s   (t = %d, %.1f bit/event)"
              % (l.name, b / (l.t * 20e-9) / 1e6, l.t, b))
    print("    %-22s %.3f Mb/s" % ("AGGREGATE", agg / 1e6))
    print("    %-22s %.3f Mb/s  (NOT the 50 Mb/s pin rate)"
          % ("payload capacity", cap / 1e6))
    print("    %-22s %.1f%%   (1.6p published 2.2%%)"
          % ("utilisation", 100 * agg / cap))
    cap9 = 50e6 / (2 * (9 * CYC_PER_BIT + 1)) * 8
    print("    ⛔ THE PUBLISHED 2.2%% WAS THE RAW PIN RATE -- 1 bit per cycle")
    print("       on the data pin, which the stream never runs at. Corrected")
    print("       it is %.1f%%, and it was already %.1f%% at the 9-bit frame,"
          % (100 * agg / cap, 100 * agg / cap9))
    print("       so the error PREDATES this round's widening: the frame going")
    print("       9 -> 12 bits moved it from %.1f%% to %.1f%%, while the"
          % (100 * agg / cap9, 100 * agg / cap))
    print("       mis-stated capacity accounted for the other 4.8x.")
    print()
    print("  --- the ONE-DEEP PENDING MARGIN, which is the binding one ---")
    print("    Average utilisation says nothing about a one-deep register.")
    print("    What binds is whether two COMPLETIONS can land inside one")
    print("    %d-cycle slot -- a question about the lanes' phase, not about"
          % SLOT_DERIVED)
    print("    average rates. On the two-RX-lane program the link reached its")
    print("    CEILING (consecutive payload frames exactly %d cycles apart,"
          % SLOT_DERIVED)
    print("    the minimum the serialiser allows) and lost NOTHING.")
    print("    ⚠ EARLIER I CALLED THAT A TWO-CYCLE MARGIN, against a slot I")
    print("      had derived as 48. The slot is %d, so the measurement was"
          % SLOT_DERIVED)
    print("      not near the limit -- it WAS the limit, and the margin is on")
    print("      COMPLETION spacing, which this run never pushed below it.")
    print("    ⚠ THAT IS NOT A GUARANTEE. The two lanes' byte periods (400")
    print("      and 3312 cycles) are unrelated, so their phase drifts and a")
    print("      closer approach is reachable at some alignment this run did")
    print("      not visit. The protection is that a collision is REPORTED")
    print("      (`rx_drop_sticky`) and the survivors stay IN ORDER, both")
    print("      measured above -- not that collisions cannot happen.")

    print()
    print("=" * 78)
    print("  GATE rx-bandwidth: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means the measured boundary matches the derived slot")
    print("      and every loss was reported in order -- NOT that the shipped")
    print("      set can never drop a byte. See the margin note above.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
