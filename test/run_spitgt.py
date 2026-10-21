"""WF1 WITNESS -- SPI-TARGET: MISO at 1 MHz equals the HOST FEED, all four
modes; MOSI captured at 500 kHz (Wilson 10-18 ruling; build plan B3/B4).

THE SUBJECTS: `test/sptgt_m{0,1,2,3}_image.hex` and `test/sptgt_mosi_image.hex`
(`make_smoke_image.py --sptgt`, i.e. `pe_proto.SPITarget`): one lane answering
an external master's SCK one bit per change-edge -- a delay-0 ARM, then an
unclocked SHIFT on MISO. Admissible: pe_asm accepts each with its timing checks
ON and its T_ext DECLARED (program_a2.T_EXT: 50 cycles = 1 MHz; 100 = 500 kHz
for the MOSI variant).

⚠ THE CLAIMING LAYER: SIMULATION -- `test/tb_spitgt.v`, an SPI master on its own
real-time clock (never on a chip edge). The hardware witness (the Pico 2 as
controller, the microSD-slot pins) is later.

THE CHECKS (tb_spitgt, from the PINS; and clocked_conform's V3 independently):
  WIRE == FEED   every byte the master reads, at its own sampling edges, is
                 the next byte the HOST pushed, count exact (2 per transaction)
  DRIVEN         every master sample sees MISO DRIVEN (a released MISO reads
                 the pull-up -- which matched the data by luck once)
  CS RELEASE     MISO's enable is never 1 once CS has been high a cycle
  EDGE -> MISO   change-edge to the pad carrying a changed bit <= D_tol 17
  MOSI           (the variant) the chip's received bytes == the master's
THE HOST TIMING THIS STATES (docs/HOST_INTERFACE.md): tCSS -- MISO is valid
6 cycles after CS falls, so a mode-0/2 master needs > 6 cycles (+ margin)
between CS fall and its first sampling edge; tCSH >= 0 -- CS held through the
master's final sampling edge (the S7 arm shows tCSH = 0 is SUFFICIENT).

MUST-FIRES, each red for ITS OWN reason (the reason is matched, not inferred):
  M1 no feed               wire != feed (zeros), V3-U underruns on a fed arm
  M2 SCK 2.5 MHz           wire != feed (change-edges land before re-arm)
  M3 a 7-clock transaction wire != feed (desync: no CS abort, no two-pin wait)
  M3R the same + RECOVERY  wire == feed after the host RELOADS the program
                           (wire-only build, as tb_reload: a reload is the event)
  M4 the wrong edge        a mode-1 image under a mode-0 master: wire != feed
  M5 tCSS = 2 cycles       the master samples a RELEASED MISO
  M6 CS released early     V3 flags the last bit (and the master's byte)
  S7 tCSH = 0              PASSES -- the requirement is "through the final
                           sampling edge", and that is enough
POSITIVE TOKEN: `GATE spitgt-witness: PASSED`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model"), os.path.join(ROOT, "model", "a2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from toolchain import banner, tool          # noqa: E402
import sim_run                              # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRATCH = os.path.join(HERE, "sim_build_spitgt")
SRCS = ["src/project.v", "src/pe_engine.v", "src/pe_store.v"]
#: spelled out: gate_wire_feed requires a witness runner to NAME its images
IMG = {0: "test/sptgt_m0_image.hex", 1: "test/sptgt_m1_image.hex",
       2: "test/sptgt_m2_image.hex", 3: "test/sptgt_m3_image.hex",
       "mosi": "test/sptgt_mosi_image.hex",
       "b3b_a": "test/b3b_a_image.hex", "b3b_a3": "test/b3b_a3_image.hex",
       "b3b_b": "test/b3b_b_image.hex", "b3b_bnoi2c": "test/b3b_bnoi2c_image.hex"}

#: B3b: the master DETUNED below 1 MHz (500.3 ns half period, not 500) so its
#: change-edges walk through every phase of the chip clock and of the other
#: lanes' schedules over NTX transactions; the coverage is printed as counts.
B3B_HALFPS, B3B_NTX = 500300, 200


def build(tag, defines=()):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "spitgt_%s.vvp" % tag)
    cmd = [tool("iverilog"), "-g2012", "-o", out, "-s", "tb_spitgt", "-I."]
    cmd += ["-D%s" % d for d in defines]
    cmd += ["test/tb_spitgt.v"] + SRCS
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("*** build failed (%s)\n%s"
                         % (tag, (r.stdout + r.stderr)[-900:]))
    return out


def run(vvp, img, plus):
    r = subprocess.run(sim_run.vvp([vvp, "+IMG=" + img, "+NBYTES=256"] + plus,
                                   images=[img]),
                       cwd=ROOT, capture_output=True, encoding="utf-8",
                       errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    if "END tb_spitgt" not in txt:
        raise SystemExit("*** tb_spitgt did not finish (%s %s):\n%s"
                         % (img, plus, txt[-800:]))
    return txt


def measured(txt):
    m = re.search(r"spi_tgt: (bytes read .*)", txt)
    return m.group(1)[:150] if m else "(no measurement line)"


#: (label, image key, plusargs) -- the witness: every one must pass, with V3
WITNESS = [
    ("mode 0 @ 1 MHz", 0, ["+MODE=0", "+NTX=8"]),
    ("mode 1 @ 1 MHz", 1, ["+MODE=1", "+NTX=8"]),
    ("mode 2 @ 1 MHz", 2, ["+MODE=2", "+NTX=8"]),
    ("mode 3 @ 1 MHz", 3, ["+MODE=3", "+NTX=8"]),
    ("MOSI @ 500 kHz", "mosi", ["+MODE=0", "+NTX=8", "+HALF=50", "+MOSI=1"]),
    ("S7 tCSH = 0", 0, ["+MODE=0", "+NTX=4", "+TCSH=0"]),
]

#: (label, image key, plusargs, wire-only build?, must the arm FAIL?, reason)
MUSTFIRE = [
    ("M1 no feed", 0, ["+MODE=0", "+NTX=2", "+NOFEED=1"], False, True,
     r"FAIL spi_tgt: byte 0 read 00"),
    ("M2 SCK 2.5 MHz", 0, ["+MODE=0", "+NTX=2", "+HALF=10"], False, True,
     r"FAIL spi_tgt: byte \d+ read"),
    ("M3 7-clock transaction", 0, ["+MODE=0", "+NTX=4", "+SHORT=1"], False,
     True, r"FAIL spi_tgt: byte \d+ read"),
    ("M3R ... + host reload", 0, ["+MODE=0", "+NTX=4", "+SHORT=1",
                                  "+RECOVER=1"], True, False, r"RECOVERY"),
    ("M4 wrong edge", 1, ["+MODE=0", "+NTX=2"], False, True,
     r"FAIL spi_tgt: byte \d+ read"),
    ("M5 tCSS = 2 cycles", 0, ["+MODE=0", "+NTX=2", "+TCSS=2"], False, True,
     r"sampled MISO while it was RELEASED"),
    ("M6 CS released early", 0, ["+MODE=0", "+NTX=2", "+CSEARLY=10"], False,
     True, r"clocked_conform\[V3\]: lane 0 unclocked bit on pin 7"),
]


def main() -> int:
    print("=" * 78)
    print("SPI-TARGET WITNESS -- MISO == the host feed at the master's edges")
    print("=" * 78)
    banner("iverilog", "vvp")
    full = build("full")
    wire = build("wire", ["SPITGT_WIRE_ONLY"])
    rc = 0
    tcss = []
    print("  --- the witness (each must pass; V3 independently) ---")
    for label, key, plus in WITNESS:
        txt = run(full, IMG[key], plus)
        ok = ("SPI-TGT: ok" in txt and "*** FAIL" not in txt
              and "clocked_conform[V3]: ok" in txt)
        m = re.search(r"tCSS seen (-?\d+)", txt)
        if m and int(m.group(1)) >= 0:
            tcss.append(int(m.group(1)))
        print("    %-24s %s  %s" % (label, "ok " if ok else "***",
                                    measured(txt)))
        if not ok:
            rc = 1
            for ln in [l for l in txt.splitlines() if "*** FAIL" in l][:4]:
                print("        | " + ln[:110])
    print("    tCSS seen (CS fall -> MISO valid, modes 0/2): worst %s cycles"
          % (max(tcss) if tcss else "--"))
    print()
    print("  --- must-fires: each red for ITS OWN reason ---")
    for label, key, plus, wonly, must_fail, reason in MUSTFIRE:
        txt = run(wire if wonly else full, IMG[key], plus)
        passed = "SPI-TGT: ok" in txt and "*** FAIL" not in txt
        hit = re.search(reason, txt) is not None
        if must_fail:
            good = (not passed) and hit
            verdict = ("RED" if not passed else "*** SURVIVED") + \
                ("" if hit else "  *** not for its reason (%s)" % reason)
        else:
            good = passed and hit
            verdict = "RECOVERED" if good else "*** NOT RECOVERED"
        print("    %-24s %s" % (label, verdict))
        rc |= 0 if good else 1
    print()
    rc |= b3b(full)
    print()
    print("  GATE spitgt-witness: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


def a2_pad_bound(path):
    """A2's bound for the SPI target (lane 0) on this image, AT THE PAD:
    r + L_SYNC + OUT_REG (bursty.abs_tolerance's terms). Derived from the
    image on every run -- never typed (gate_a2_program section 2)."""
    import bursty
    import program_a2
    with open(os.path.join(ROOT, path)) as f:
        img = bytes(int(x, 16) for x in f.read().split())
    bl = [x["blane"] for x in program_a2.lane_set(img)[0]]
    r = bursty.response_time_b(bl[0], bl)["r"]
    return r, r + bursty.L_SYNC + bursty.OUT_REG


def b3b(full) -> int:
    """B3b, THE CONTENTION ARM (Wilson 10-20; prediction + addendum stamped
    in probe_reports before any of this ran). The SPI target beside the other
    four shipped lanes, all busy, each checked on its own wire."""
    print("  --- B3b: five-lane contention (master %.1f ns half period, %d "
          "transactions) ---" % (B3B_HALFPS / 1000.0, B3B_NTX))
    rc, worst = 0, {}
    # UART-rx peer at the NOMINAL 434 (the claim load); 421 = -3 %, the edge
    # of the receiver's verified band (Wilson 10-20)
    base = ["+FIVE=1", "+NTX=%d" % B3B_NTX, "+HALFPS=%d" % B3B_HALFPS]
    arms = [("A shipped, mode 0", "b3b_a", ["+MODE=0", "+RXT=434"]),
            ("A shipped, mode 3", "b3b_a3", ["+MODE=3", "+RXT=434"]),
            ("A, UART-rx -3 %", "b3b_a", ["+MODE=0", "+RXT=421"]),
            ("B envelope I2C", "b3b_b", ["+MODE=0", "+RXT=434"]),
            ("B without I2C", "b3b_bnoi2c", ["+MODE=0", "+NOI2C=1", "+RXT=434"])]
    for label, key, plus in arms:
        r, bound = a2_pad_bound(IMG[key])
        txt = run(full, IMG[key], base + plus + ["+BOUND=%d" % bound])
        ok = ("SPI-TGT: ok" in txt and "*** FAIL" not in txt
              and "clocked_conform[V3]: ok" in txt)
        m = re.search(r"edge->MISO worst (\d+)", txt)
        worst[key] = int(m.group(1)) if m else None
        print("    %-20s %s  worst %s cycles, A2 r %d -> pad bound %d"
              % (label, "ok " if ok else "***", worst[key], r, bound))
        print("        " + measured(txt))
        for ln in [l for l in txt.splitlines() if "b3b:" in l]:
            print("        " + ln.strip()[:150])
        if not ok:
            rc = 1
            for ln in [l for l in txt.splitlines() if "*** FAIL" in l][:4]:
                print("        | " + ln[:130])
    # the interferer must-fire: on arm B, A2 says I2C sets the bound (r 9 ->
    # 6 without it), so removing it must LOWER the measured worst bit
    wb, wn = worst.get("b3b_b"), worst.get("b3b_bnoi2c")
    dropped = wb is not None and wn is not None and wn < wb
    print("    interferer must-fire: B worst %s -> without I2C %s  %s"
          % (wb, wn, "DROPPED ok" if dropped else "*** DID NOT DROP"))
    rc |= 0 if dropped else 1
    # 2 MHz under contention: RECORDED, NOT JUDGED (Wilson 10-20). It was a
    # must-fire and it SURVIVED -- every byte exact -- so the bench cannot
    # break the target at 2 MHz under this load. A2 refuses 2 MHz (D_tol 4 at
    # T_ext 25 < r); the 1 MHz claim rests on A2, not on this arm. That the
    # bench CATCHES wrong bytes is shown by M2 above (2.5 MHz, red).
    txt = run(full, IMG["b3b_a"], ["+FIVE=1", "+NTX=%d" % B3B_NTX,
                                   "+HALFPS=250150", "+MODE=0", "+RXT=434"])
    print("    2 MHz, five lanes (recorded, no verdict): %s" % measured(txt))
    print("      => A2 is conservative at 2 MHz under this load; the 1 MHz "
          "claim rests on A2")
    return rc


if __name__ == "__main__":
    sys.exit(main())
