"""WF2's must-fire -- the image that started it, judged on the WIRE.

Usage:  python test/run_wirefeed_mf.py            (the gate)
        python test/run_wirefeed_mf.py --write    (regenerate the tracked
                                                   control image, then exit)

⛔⛔ WHY (Wilson, delay-0 REARM ruling). pe_asm ACCEPTED the WS2812 3-sub-bit
lane with a delay-0 REARM ("J 1") and its wire stream was not its feed; nothing
in the bench set would have noticed. pe_asm now refuses it (`model/zero_
spacing.py`). This proves the OTHER half: the wire-level check (V3, in
`test/clocked_conform.vh`) catches that program if it ever runs again.

  OLD IMAGE  `pe_asm.ws2812_sub3(0)` emitted exactly as the old assembler did
             (the zero-spacing check stubbed out for this build only), run in
             tb_trace with the host feeder on queue 0: V3 must be RED -- the
             lane's bits land late against their nominal windows.
  CONTROL    `pe_asm.ws2812_sub3(21)` (the REARM at d = 21), assembled by
             today's pe_asm and TRACKED as test/ws2812_sub3_rearm21.hex (so
             `program_a2` records its pyRTA bound and CI can judge without
             pyRTA): V3 content exact AND V3-T within its published bound.
  REFUSAL    today's pe_asm refuses the old program (the assembler half).

⭐⭐ V3-T (Wilson, WF2 ruling 1) -- the three timing must-fires:
  the old image, judged against the CONTROL's bound (the same five lanes; only
  the REARM's delay differs, and the old program has no lane set of its own
  -- pe_asm refuses it), is RED: its lane drifts 28,000+ cycles late;
  the control is GREEN: worst response within r_i;
  the control with its lane-0 bound set to (measured - 1) is RED -- the
  comparison is live, not vacuous.
⚠ The old image's content is EXACT (every fed bit, in order): its failure is
  purely timing, which is why V3-T exists at all.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner, tool          # noqa: E402
import pe_asm                               # noqa: E402
import zero_spacing                         # noqa: E402

TMP = os.environ.get("PE_WFMF_TMP") or os.path.join(ROOT, "test",
                                                      "sim_build_wfmf")
TRACKED = os.path.join(HERE, "ws2812_sub3_rearm21.hex")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def write(img, name):
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in img) + "\n")
    return p


def main():
    if "--write" in sys.argv:
        ctl = pe_asm.assemble(*pe_asm.ws2812_sub3(21))
        with open(TRACKED, "w", encoding="ascii", newline="\n") as fh:
            fh.write("\n".join("%02x" % b for b in ctl) + "\n")
        print("wrote %s (pe_asm.ws2812_sub3(21), %d bytes)"
              % (os.path.relpath(TRACKED, ROOT), len(ctl)))
        return 0
    print("WF2 MUST-FIRE -- the WS2812 3-sub-bit image, judged on the wire")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    ok = True

    try:
        pe_asm.assemble(*pe_asm.ws2812_sub3(0))
        refused = False
    except pe_asm.Reject as exc:
        refused = "ZERO release spacing" in str(exc)
    print("  today's pe_asm on the delay-0 build: %s"
          % ("REFUSED (zero release spacing)" if refused
             else "*** NOT REFUSED"))
    ok = ok and refused

    real_find = zero_spacing.find
    zero_spacing.find = lambda *_a, **_k: []
    try:
        old = pe_asm.assemble(*pe_asm.ws2812_sub3(0))
    finally:
        zero_spacing.find = real_find
    ctl = pe_asm.assemble(*pe_asm.ws2812_sub3(21))
    text = "\n".join("%02x" % b for b in ctl) + "\n"
    with open(TRACKED, encoding="ascii") as fh:
        same = fh.read().replace("\r\n", "\n") == text
    print("  tracked %s == pe_asm.ws2812_sub3(21): %s"
          % (os.path.relpath(TRACKED, ROOT), "yes" if same else
             "*** NO -- regenerate: python test/run_wirefeed_mf.py --write"))
    ok = ok and same
    imgs = {"old": write(old, "ws2812_sub3_rearm0.hex"), "control": TRACKED}

    # the CONTROL's published bound (pyRTA, committed by program_a2)
    with open(os.path.join(HERE, "lane_response_bounds.json"),
              encoding="utf-8") as fh:
        rec = json.load(fh).get(os.path.basename(TRACKED))
    if not rec or not rec["lanes"]:
        print("  *** the control has no published bound in "
              "test/lane_response_bounds.json -- run program_a2")
        return 1
    rb = [-1] * 5
    dt = [-1] * 5
    for ln, e in rec["lanes"].items():
        rb[int(ln)] = e["r_pyrta"] if e["r_pyrta"] is not None else -1
        dt[int(ln)] = e["dtol"]

    vvp = os.path.join(TMP, "tb_trace.vvp")
    r = run([tool("iverilog"), "-g2012", "-I", "test", "-o", vvp, "-s", "tb_trace",
             "test/tb_trace.v", "test/fram_i2c.v", "test/fram_spi.v",
             "src/pe_engine.v", "src/pe_store.v", "src/project.v"])
    if r.returncode != 0:
        print("*** build failed\n" + r.stdout + r.stderr)
        return 1

    def sim(which, bound):
        o = run([tool("vvp"), vvp, "+IMG=" + imgs[which], "+NBYTES=256",
                 "+PEER=none", "+OUT=" + os.path.join(TMP, which + ".txt"),
                 "+NCYC=60000", "+SEED=1", "+ASYNC=0", "+STAYLOAD=0",
                 "+SCLHOLD=0", "+SPI_SCK_INV=0", "+FEEDN=0", "+V3_EXEMPT=0",
                 "+V3RBOUND=" + ",".join(str(x) for x in bound),
                 "+V3DTOL=" + ",".join(str(x) for x in dt)])
        return o.stdout + o.stderr

    def lane0_t(o):
        return next((l.strip() for l in o.splitlines()
                     if "clocked_conform[V3-T] lane 0" in l), "")

    o = sim("old", rb)
    content = "clocked_conform[V3]: ok" in o
    red = "*** FAIL clocked_conform[V3-T] lane 0: worst response" in o
    print("  old image (REARM d = 0)  : content %s; timing %s"
          % ("exact" if content else "NOT exact",
             ("RED  ok -- " + lane0_t(o)[9:140]) if red
             else "*** MUST-FIRE FAILED (V3-T did not go red)"))
    ok = ok and red

    o = sim("control", rb)
    good = ("clocked_conform[V3]: ok" in o and "*** FAIL" not in o
            and "clocked_conform[V3-T] lane 0: ok" in o)
    t = lane0_t(o)
    print("  control (REARM d = 21)   : %s"
          % (t[:150] if good else "*** " + (t or "no V3-T line")[:150]))
    ok = ok and good
    m = re.search(r"worst response (\d+)", t)
    if m:
        meas = int(m.group(1))
        tight = list(rb)
        tight[0] = meas - 1
        o = sim("control", tight)
        red = "*** FAIL clocked_conform[V3-T] lane 0: worst response" in o
        print("  control, lane-0 bound = measured - 1 = %d: %s"
              % (meas - 1, "RED  ok -- the comparison is live" if red
                 else "*** MUST-FIRE FAILED (passed at a bound below the "
                      "measurement)"))
        ok = ok and red
    else:
        print("  *** no measured response on the control -- cannot price")
        ok = False

    # ⛔ WF2 round 2 (Wilson): the fingerprint table's two guards, priced.
    # 1. a ONE-BYTE-ALTERED copy of the accepted control is an UNKNOWN program
    alt = bytearray(ctl)
    alt[250] ^= 0x01                     # store filler, never executed
    imgs["altered"] = write(bytes(alt), "ws2812_sub3_rearm21_altered.hex")
    o = run([tool("vvp"), vvp, "+IMG=" + imgs["altered"], "+NBYTES=256",
             "+PEER=none", "+OUT=" + os.path.join(TMP, "alt.txt"),
             "+NCYC=20000", "+SEED=1", "+ASYNC=0", "+STAYLOAD=0",
             "+SCLHOLD=0", "+SPI_SCK_INV=0", "+FEEDN=0"])
    o = o.stdout + o.stderr
    red = "*** FAIL clocked_conform[V3-ID]" in o
    print("  one byte altered (filler) : %s"
          % ("RED  ok -- unknown fingerprint" if red
             else "*** MUST-FIRE FAILED (an unknown image was judged)"))
    ok = ok and red
    # 2. a LOOSENING override that is not allowlisted
    wide = list(rb)
    wide[0] = rb[0] + 5
    o = sim("control", wide)
    red = "*** FAIL clocked_conform[V3-OV]" in o
    print("  control, lane-0 bound widened to %d (not allowlisted): %s"
          % (wide[0], "RED  ok -- an override may only tighten" if red
             else "*** MUST-FIRE FAILED (a loosening override was taken)"))
    ok = ok and red

    print()
    print("  GATE wirefeed-mustfire: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
