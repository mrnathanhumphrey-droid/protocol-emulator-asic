"""rxfast -- the RX overrun MECHANISM image, checked EXACTLY for what it is.

⛔⛔ WHY (Wilson, on WF1): MECHANISM must not mean unchecked. `rxfast_image.hex`
completes a received byte every 24 cycles against a 50-cycle payload slot, so
the one-deep `rx_pend` drops bytes BY DESIGN -- wire != feed is its purpose.
"Some bytes dropped" is not a result; the drop count must equal the count the
link capacity predicts:

    capacity        = (last payload - first payload) / SLOT + 1, every gap = SLOT
    predicted drops = completions - capacity - in flight (rx_pend + a payload
                      frame shifting, read from the RTL at a mid-frame end)

checked exactly by `tb_rxbw +SATURATED=1` at two window lengths.

  TRACKED     test/rxfast_image.hex == make_smoke_image --rxfast 24, byte exact
  PASS ARMS   +SATURATED=1 at NCYC 200000 and 123457: `RXBW-SAT: ok`
  MUST-FIRE   the same program at d = 60 does NOT saturate the link: the
              saturated check must be RED ("NOT SATURATED"), so it cannot pass
              on a run where no prediction applies.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool          # noqa: E402

TMP = os.environ.get("PE_RXFAST_TMP") or os.path.join(ROOT, "test",
                                                        "sim_build_rxfast")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def nbytes(path):
    with open(path, encoding="ascii") as fh:
        return len([t for t in fh.read().split() if not t.startswith("//")])


def main():
    print("RXFAST -- the RX overrun mechanism image, drop count exact")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    ok = True
    for d in (24, 60):
        r = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
                 "--rxfast", str(d), "probe_wf_rxfast%d" % d])
        if r.returncode != 0:
            print("*** generator failed: " + (r.stdout + r.stderr)[-300:])
            return 1
    tracked = os.path.join(HERE, "rxfast_image.hex")
    built = os.path.join(HERE, "probe_wf_rxfast24.hex")
    with open(tracked, encoding="ascii") as a, open(built, encoding="ascii") as b:
        same = a.read().replace("\r\n", "\n") == b.read().replace("\r\n", "\n")
    print("  tracked test/rxfast_image.hex == make_smoke_image --rxfast 24: %s"
          % ("yes" if same else "*** NO"))
    ok = ok and same

    vvp = os.path.join(TMP, "tb_rxbw.vvp")
    r = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", "tb_rxbw",
             "test/tb_rxbw.v", "src/pe_engine.v", "src/pe_store.v",
             "src/project.v"])
    if r.returncode != 0:
        print("*** build failed\n" + r.stdout + r.stderr)
        return 1

    def sim(img, ncyc):
        o = run([tool("vvp"), vvp, "+IMG=" + img, "+NBYTES=%d" % nbytes(img),
                 "+NCYC=%d" % ncyc, "+SATURATED=1"])
        return o.stdout + o.stderr

    for ncyc in (200000, 123457):
        o = sim(tracked, ncyc)
        good = ("RXBW-SAT: ok" in o and "tb_rxbw: PASS" in o
                and "*** FAIL" not in o)
        ok = ok and good
        line = next((l.strip() for l in o.splitlines()
                     if "RXBW-SAT" in l or "*** FAIL" in l), "?")
        print("  pass  NCYC %6d  %s" % (ncyc, line[:150] if good
                                         else "*** " + line[:150]))

    o = sim(os.path.join(HERE, "probe_wf_rxfast60.hex"), 200000)
    red = ("NOT SATURATED" in o and "RXBW-SAT: ok" not in o
           and "tb_rxbw: *** FAILED" in o)
    print("  must-fire d = 60 (link not saturated): %s"
          % ("red  ok -- NOT SATURATED, no prediction claimed" if red
             else "*** MUST-FIRE FAILED (the saturated check passed)"))
    ok = ok and red

    print()
    print("  GATE rxfast: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
