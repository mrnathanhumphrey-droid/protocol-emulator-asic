"""UART-rx gate (Wilson's UART ruling): the 8N1 receive program against a
baud-errored peer, bytes compared with what the PEER SENT, count exact.

  PASS ARMS   the program (test/uart_rx.py, pe_asm) at T = 434 (the board's
              115200 baud) AND at T_MIN = 232 (the published speed limit,
              Wilson) against baud error -3, -2, 0, +2, +3 % on two seeds,
              random idle gaps with a quarter back-to-back: every arm
              `UART-RX: ok`.
  SPEED LIMIT `uart_rx.build` refuses T_MIN - 1 (below the certified rate).
  FRAMING     the peer sends frame 5 with stop = 0: the host-side check must
              REPORT it (exactly one framing error) and every byte still match.
  MUST-FIRES  "edge"   -- sample 0 at the bit's START edge, not mid-bit: red
                          at +2 and +3 % (a slow peer; see the note below).
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
    TM = uart_rx.T_MIN
    for var, t in (("ok", T), ("edge", T), ("nostop", T), ("ok", TM)):
        p = os.path.join(TMP, "uart_%s_%d.hex" % (var, t))
        with open(p, "w", encoding="ascii", newline="\n") as fh:
            fh.write("\n".join("%02x" % b for b in uart_rx.build(t, None, var)) + "\n")
        imgs[(var, t)] = p
    print("  program: offset 1.5 T - %d (measured), stop + REARM at D*, "
          "pe_asm-assembled; arms at T = %d and T_MIN = %d"
          % (uart_rx.OFFSET_LAT, T, TM))

    # ⛔ THE SPEED LIMIT IS ENFORCED, not only published: one cycle below
    # T_MIN the builder must refuse, naming the limit.
    try:
        uart_rx.build(TM - 1, None, "ok")
        lim = False
    except uart_rx.pe_asm.Reject as exc:
        lim = "T_MIN" in str(exc)
    print("  speed limit  build at T = %d (T_MIN - 1): %s"
          % (TM - 1, "refused, naming T_MIN" if lim
             else "*** NOT REFUSED"))
    ok = lim

    def sim(var, err, seed, extra=(), t=T):
        o = run([tool("vvp"), vvp, "+IMG=" + imgs[(var, t)], "+NBYTES=256",
                 "+BITP=%d" % t, "+ERR=%d" % err, "+SEED=%d" % seed,
                 "+NFR=%d" % NFR] + list(extra))
        return o.stdout + o.stderr

    jobs = [("ok", e, s, (), t) for t in (T, TM) for e in ERRS for s in SEEDS]
    with ThreadPoolExecutor(3) as ex:
        outs = list(ex.map(lambda j: (j, sim(*j)), jobs))
    import re
    for (var, e, s, _x, t), o in outs:
        m = re.search(r"\((\d+) back-to-back\)", o)
        # ⛔ the back-to-back case must be EXERCISED, not just possible
        good = ("UART-RX: ok" in o and "*** FAIL" not in o
                and m is not None and int(m.group(1)) > 0)
        ok = ok and good
        line = next((l for l in o.splitlines() if "UART-RX" in l or "*** FAIL" in l), "?")
        print("  pass  T %3d err %+3d/1000 seed %d  %s"
              % (t, e, s, line.strip()[:100] if good
                 else "*** " + line.strip()[:100]))

    o = sim("ok", 0, 1, ["+BADSTOP=5"])
    hit = ("FRAMING ERROR reported on frame 5" in o and "UART-RX: ok" in o
           and o.count("FRAMING ERROR") == 1)
    print("  framing  bad stop on frame 5: %s" % (
        "reported, exactly once; every byte still the peer's" if hit
        else "*** NOT REPORTED AS EXPECTED"))
    ok = ok and hit

    # ⚠ "edge" IS PRICED ON THE SLOW SIDE ONLY, AND THAT IS MEASURED (T =
    # 434). Sampling at a bit's START edge reads the PREVIOUS bit once a
    # slow peer's edges lag the chip's grid (+2 %: red, frame 0). A FAST peer
    # pulls its edges EARLIER, so the edge sample drifts INTO the bit and
    # reads it correctly (-2 % passed). At T = 64 both sides were red because
    # the fixed ~10-cycle edge-to-sample latency was 16 % of a bit; at 434 it
    # is 2 %. The variant still fails where a mid-bit sampler does not.
    for var, errs, why in (("edge", (20, 30), "sample at the bit edge"),
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
