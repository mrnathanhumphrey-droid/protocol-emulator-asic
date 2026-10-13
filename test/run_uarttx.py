"""UART-tx gate (WF2 round 2, Wilson): the published UART-tx lane at its
RATED speed (115200 baud = 434 cycles/bit), judged by a PEER on the wire.

  TRACKED     test/uart_tx_image.hex and test/uart_tx_busy_image.hex are what
              pe_asm assembles from test/uart_tx.py today (a stale copy is red)
  PASS ARMS   both images (alone; beside four busy d = D* lanes), 200,000
              cycles: tb_uarttx's peer -- its own clock, nominal grid -- reads
              every frame FROM THE FIRST = the host's byte in order (silicon
              fix #8: no reset 0x00 first), stop bits 1, every bit held over the middle
              80 % of its nominal window; V3 exact on the bus; V3-T within the
              published bound. Every arm `UART-TX: ok`, no FAIL line.
  MUST-FIRES  a peer 5 % off nominal: the timing window goes RED (it is
              live, not decorative); the same program MSB-first: the CONTENT
              check goes red (byte order is judged, not assumed).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool          # noqa: E402
import uart_tx                               # noqa: E402

TMP = os.environ.get("PE_UARTTX_TMP") or os.path.join(ROOT, "test",
                                                        "sim_build_uarttx")
NCYC = 200000


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def hextext(img):
    return "\n".join("%02x" % b for b in img) + "\n"


def main():
    print("UART-TX -- the published lane at 115200 baud, judged by a peer")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    ok = True
    for name, busy in (("uart_tx_image.hex", False),
                       ("uart_tx_busy_image.hex", True)):
        with open(os.path.join(HERE, name), encoding="ascii") as fh:
            same = fh.read().replace("\r\n", "\n") == hextext(
                uart_tx.build(uart_tx.T_NOMINAL, busy))
        print("  tracked test/%s == pe_asm output: %s"
              % (name, "yes" if same else "*** NO -- regenerate: python "
                 "test/uart_tx.py test/%s%s" % (name, " busy" if busy else "")))
        ok = ok and same
    msb = os.path.join(TMP, "uart_tx_msb.hex")
    with open(msb, "w", encoding="ascii", newline="\n") as fh:
        fh.write(hextext(uart_tx.build(uart_tx.T_NOMINAL, False, True)))

    vvp = os.path.join(TMP, "tb_uarttx.vvp")
    r = run([tool("iverilog"), "-g2012", "-I", "test", "-o", vvp, "-s",
             "tb_uarttx", "test/tb_uarttx.v", "src/pe_engine.v",
             "src/pe_store.v", "src/project.v"])
    if r.returncode != 0:
        print("*** build failed\n" + r.stdout + r.stderr)
        return 1

    def sim(img, err=0):
        o = run([tool("vvp"), vvp, "+IMG=" + img, "+NBYTES=256",
                 "+NCYC=%d" % NCYC, "+BITP=%d" % uart_tx.T_NOMINAL,
                 "+ERR=%d" % err])
        return o.stdout + o.stderr

    for name in ("uart_tx_image.hex", "uart_tx_busy_image.hex"):
        o = sim("test/" + name)
        good = "UART-TX: ok" in o and "*** FAIL" not in o
        line = next((l.strip() for l in o.splitlines()
                     if "UART-TX" in l or "*** FAIL" in l), "?")
        t = next((l.strip() for l in o.splitlines()
                  if "[V3-T] lane 0" in l), "")
        print("  pass  %-24s %s" % (name, line[:110] if good
                                    else "*** " + line[:110]))
        if good:
            print("        %s" % t[:120])
        ok = ok and good

    o = sim("test/uart_tx_image.hex", 50)
    red = ("broke the peer's timing window" in o and "UART-TX: ok" not in o)
    print("  must-fire peer 5 %% off nominal: %s"
          % ("red  ok -- the timing window is live" if red
             else "*** MUST-FIRE FAILED (the window passed a 5 % grid)"))
    ok = ok and red
    o = sim(msb)
    red = ("not the bytes the host fed" in o and "UART-TX: ok" not in o
           and "*** FAIL clocked_conform[V3-ID]" not in o)
    print("  must-fire MSB-first program: %s"
          % ("red  ok -- byte order is judged (and the image is known)" if red
             else "*** MUST-FIRE FAILED"))
    ok = ok and red

    print()
    print("  UART-TX GATE: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
