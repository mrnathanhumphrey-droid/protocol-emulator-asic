"""UART-rx gate (Wilson's UART ruling): the 8N1 receive program against a
baud-errored peer, bytes compared with what the PEER SENT, count exact.

  PASS ARMS   the program (test/uart_rx.py, pe_asm) at T = 64 against baud
              error -3, -2, 0, +2, +3 % on two seeds, random idle gaps with a
              quarter back-to-back: every arm `UART-RX: ok`.
  FRAMING     the peer sends frame 5 with stop = 0: the host-side check must
              REPORT it (exactly one framing error) and every byte still match.
  MUST-FIRES  "edge"   -- sample 0 at the bit's START edge, not mid-bit: red
                          at +-2 %.
              "nostop" -- the stop sample dropped (no framing check): red, on
                          the exact count (one push per frame, not two).

V-RX (clocked_conform) stays in the bench as the second, same-hand witness;
the USB-TTL adapter is the foreign one at FPGA bring-up.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool          # noqa: E402
import uart_rx                               # noqa: E402

TMP = os.environ.get("PE_UART_TMP") or os.path.join(ROOT, "test", "sim_build_uartrx")
T = uart_rx.T_NOMINAL
ERRS = (-30, -20, 0, 20, 30)
SEEDS = (1, 2)
NFR = 40


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main():
    print("UART-RX -- 8N1 receive vs a baud-errored peer (T = %d cycles/bit)" % T)
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    vvp = os.path.join(TMP, "tb_uartrx.vvp")
    r = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", "tb_uartrx",
             "test/tb_uartrx.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"])
    if r.returncode != 0:
        print("*** build failed\n" + r.stdout + r.stderr)
        return 1
    imgs = {}
    # ⛔ the TRACKED image (coverage sweep, examples) must be what pe_asm
    # assembles from test/uart_rx.py today -- a stale copy is red
    tracked = os.path.join(ROOT, "test", "uart_rx_image.hex")
    want = "\n".join("%02x" % b for b in uart_rx.build(T, None, "ok")) + "\n"
    with open(tracked, encoding="ascii") as fh:
        same = fh.read().replace("\r\n", "\n") == want
    print("  tracked test/uart_rx_image.hex == pe_asm output: %s"
          % ("yes" if same else "*** NO -- regenerate: python test/uart_rx.py "
             "test/uart_rx_image.hex"))
    if not same:
        return 1
    for var in ("ok", "edge", "nostop"):
        p = os.path.join(TMP, "uart_%s.hex" % var)
        with open(p, "w", encoding="ascii", newline="\n") as fh:
            fh.write("\n".join("%02x" % b for b in uart_rx.build(T, None, var)) + "\n")
        imgs[var] = p
    print("  program: offset %d (= 1.5 T - %d, measured), pe_asm-assembled"
          % (uart_rx.default_offset(T), uart_rx.OFFSET_LAT))

    def sim(var, err, seed, extra=()):
        o = run([tool("vvp"), vvp, "+IMG=" + imgs[var], "+NBYTES=256",
                 "+BITP=%d" % T, "+ERR=%d" % err, "+SEED=%d" % seed,
                 "+NFR=%d" % NFR] + list(extra))
        return o.stdout + o.stderr

    jobs = [("ok", e, s) for e in ERRS for s in SEEDS]
    with ThreadPoolExecutor(3) as ex:
        outs = list(ex.map(lambda j: (j, sim(*j)), jobs))
    ok = True
    import re
    for (var, e, s), o in outs:
        m = re.search(r"\((\d+) back-to-back\)", o)
        # ⛔ the back-to-back case must be EXERCISED, not just possible
        good = ("UART-RX: ok" in o and "*** FAIL" not in o
                and m is not None and int(m.group(1)) > 0)
        ok = ok and good
        line = next((l for l in o.splitlines() if "UART-RX" in l or "*** FAIL" in l), "?")
        print("  pass  err %+3d/1000 seed %d  %s" % (e, s, line.strip()[:110]
                                                    if good else "*** " + line.strip()[:110]))

    o = sim("ok", 0, 1, ["+BADSTOP=5"])
    hit = ("FRAMING ERROR reported on frame 5" in o and "UART-RX: ok" in o
           and o.count("FRAMING ERROR") == 1)
    print("  framing  bad stop on frame 5: %s" % (
        "reported, exactly once; every byte still the peer's" if hit
        else "*** NOT REPORTED AS EXPECTED"))
    ok = ok and hit

    for var, errs, why in (("edge", (-20, 20), "sample at the bit edge"),
                           ("nostop", (0,), "stop-bit check dropped")):
        for e in errs:
            o = sim(var, e, 1)
            red = "*** FAIL uart_rx" in o and "UART-RX: ok" not in o
            first = next((l.strip() for l in o.splitlines()
                          if l.startswith("*** FAIL uart_rx")), "")
            print("  must-fire %-7s err %+3d (%s): %s" % (
                var, e, why, ("red  ok -- " + first[9:90]) if red
                else "*** MUST-FIRE FAILED (passed)"))
            ok = ok and red

    print()
    print("  UART-RX GATE: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
