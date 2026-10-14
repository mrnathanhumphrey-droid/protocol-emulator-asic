"""RELOAD gate (WF2, Wilson #9 / #10 / #11 / Q2 rule 1 / option 1'): A RELOAD IS
A CLEAN SLATE, judged by peers on the wire.

  PASS ARMS   tb_reload, every reload REAL (PROG high, the image rewritten,
              PROG low) and triggered by the PEER's timing:
                tx5 / tx1 / tx8   UART TX cut at bit 5, 1, 8 of frame 3: every
                                  whole frame is the host's byte in order, the
                                  first after the reload is the first pushed
                                  after PROG fell (rule 1: the queues clear)
                rx                UART RX cut mid-frame: the cut frame is never
                                  pushed, every later push is the peer's next
                                  whole frame, count exact
                rx2tx             RX image -> TX image (reconfiguration; a
                                  stale receive counter cannot touch a TX
                                  lane, so this is NOT a #9 arm)
                unread            a received byte still pending when PROG rose
                                  never reaches the host stream (rule 1)
                spi               SPI master mode 0, cut after bit 7 of C4: CS
                                  leads any halt-caused SCK edge by a clock
                                  (option 1'), the cut byte is not written,
                                  the READ after returns 5B C4
                i2c               I2C FRAM write, cut after bit 7 of C4, the
                                  peer ISOLATED by a bus switch during every
                                  load (HOST_INTERFACE): the next write is
                                  clean
              and on EVERY arm the quiet window: no pad moves in the 64
              cycles after PROG falls (no dispatch can have happened yet).
              onewire           tb_onewire +RELOAD_AT, cut in a write-0 slot:
                                the bytes the host receives after the reload
                                equal a clean run's; the DS18B20 model flags
                                EXACTLY the abort's two signatures (the
                                shortened write-0, and the new reset inside
                                the cut slot's recovery) and nothing else
  DEMO        i2c_harm: the I2C peer CONNECTED through the load -- the
              documented limit, MEASURED and printed, never judged.
  MUST-FIRES  each mutant red FOR ITS OWN REASON:
                M_NO_RELOAD_RESET  (#9)   tx5 and rx
                M_NO_HALT_IDLE     (#10)  tx5
                M_NO_RELOAD_FLUSH  (rule 1) tx1 (A7 re-sent) and unread
                M_HALT_KEEP_CKBIT  (#11)  spi (the 16-bit frame)
                M_ONE_PHASE_HALT   (1')   spi (CS and SCK in one cycle)
                M_HALT_KEEP_HOLD   (#11)  i2c (a pad moved before dispatch)

Usage: python test/run_reload.py [--src DIR]   (DIR holds pe_engine.v,
project.v; pe_store.v from DIR if present, else src/)
Verdict: `RELOAD GATE: PASSED` or `*** FAIL ...`.
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "model")]
from toolchain import banner, tool            # noqa: E402
import corpus                                 # noqa: E402
import onewire                                # noqa: E402
import pe_isa as I                            # noqa: E402

TMP = os.environ.get("PE_RELOAD_TMP") or os.path.join(ROOT, "test",
                                                      "sim_build_reload")
SIMS = 3                                       # local rule: <= 3 at a time
OW_TXN = [("reset",), ("write", 0x33), ("read", 8, "rom")]   # READ ROM
OW_RELOAD_AT = 12
OW_ABORT = ("write slot low inside the 15..60 us sample window",
            "slot (fall -> next fall) < tSLOT + tREC")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def hexfile(path, img):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in I.full_store(bytes(img))) + "\n")
    return path


def i2c_write_image():
    """S | A0 | 01 23 | 5B C4 | P -- an MB85RC256V write of 5B C4 at 0x0123
    (the bytes come from the host feed, tb_reload's `hf_put`)."""
    d, sda, scl = 70, corpus.P_SDA, corpus.P_SCL
    prog = [I.act(I.OP_START, sda, 0, d)]
    for _ in range(5):
        prog += [I.act_shift_clocked(sda, d, nbits=8, q=0),
                 I.act_shiftin_clocked(sda, d, nbits=1)]
    # P after a clocked SHIFTIN (SCL low): SDA low, SCL high, STOP
    prog += [I.act(I.OP_LEVEL, sda, 0, d), I.act(I.OP_LEVEL, scl, 1, d),
             I.act(I.OP_STOP, sda, 1, d), I.act(I.OP_REARM, 0, 1, 1000)]
    park = I.ACT_BASE + len(prog) * I.ACT_BYTES
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    hdrs = [I.hdr(sda, scl, 0, d, 0, 2 * d, 3 * d, I.ACT_BASE,
                  order=I.ORDER_MSB)]
    hdrs += [I.hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 3, 4, 5)]
    return b"".join(hdrs) + b"".join(prog)


def sources(src):
    store = os.path.join(src, "pe_store.v")
    if not os.path.exists(store):
        store = os.path.join(ROOT, "src", "pe_store.v")
    return [os.path.join(src, "pe_engine.v"), store,
            os.path.join(src, "project.v")]


def build(src, top, benches, define, tag):
    out = os.path.join(TMP, "%s_%s.vvp" % (top, tag))
    cmd = [tool("iverilog"), "-g2012", "-I", "test", "-I", src, "-o", out,
           "-s", top]
    if define:
        cmd.append("-D" + define)
    r = run(cmd + benches + sources(src))
    if r.returncode != 0:
        raise SystemExit("*** build failed (%s %s)\n%s"
                         % (top, tag, (r.stdout + r.stderr)[-900:]))
    return out


def main():
    src = os.path.join(ROOT, "src")
    if "--src" in sys.argv:
        src = os.path.abspath(sys.argv[sys.argv.index("--src") + 1])
    print("RELOAD -- a reload is a clean slate, judged on the wire (%s)"
          % rel(src))
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)

    spim = hexfile(os.path.join(TMP, "spim_mode0.hex"),
                   corpus.build_spi_master(mode0=True)[0])
    i2cw = hexfile(os.path.join(TMP, "i2c_write.hex"), i2c_write_image())
    owimg = os.path.join(TMP, "ow_img.hex")
    onewire.write_hex(owimg, onewire.build("tt"))
    lines, _rx = onewire.engine("tt").feed_file(OW_TXN)
    owfeed = os.path.join(TMP, "ow_feed.hex")
    with open(owfeed, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    tbr = ["test/tb_reload.v", "test/fram_spi.v", "test/fram_i2c.v"]
    defines = ["", "M_NO_RELOAD_RESET", "M_NO_HALT_IDLE", "M_NO_RELOAD_FLUSH",
               "M_HALT_KEEP_CKBIT", "M_ONE_PHASE_HALT", "M_HALT_KEEP_HOLD",
               "M_KEEP_ON_HALT"]
    vvp = {d: build(src, "tb_reload", tbr, d, d or "good") for d in defines}
    owv = build(src, "tb_onewire",
                ["test/tb_onewire.v", "test/ds18b20_model.v"], "", "good")

    tx, rx = "+IMG=test/uart_tx_image.hex", "+IMG=test/uart_rx_image.hex"
    arms = {   # name -> plusargs (+IMG: the program reloaded)
        "tx5": [tx, "+MODE=0", "+RLB=5"], "tx1": [tx, "+MODE=0", "+RLB=1"],
        "tx8": [tx, "+MODE=0", "+RLB=8"], "rx": [rx, "+MODE=1"],
        "rx2tx": [tx, "+MODE=2"], "unread": [rx, "+MODE=3"],
        "spi": ["+MODE=4", "+IMG=" + rel(spim), "+RLF=5", "+RLB=7"],
        "i2c": ["+MODE=5", "+IMG=" + rel(i2cw), "+RLF=4", "+RLB=7"],
        "i2c_harm": ["+MODE=7", "+IMG=" + rel(i2cw), "+RLF=4", "+RLB=7"],
        # the keep-list arm: a REFUSED program sets status, the reload must
        # not erase it (reset-network halt: the twins are on power-on only)
        "keep": [tx, "+MODE=8", "+IMG0=test/tx_badclk_image.hex"],
    }
    mustfire = [   # (define, arm, the reason its red must carry)
        ("M_NO_RELOAD_RESET", "tx5", "TX frame"),
        ("M_NO_RELOAD_RESET", "rx", "RX push"),
        ("M_NO_HALT_IDLE", "tx5", "a pad moved"),
        ("M_NO_RELOAD_FLUSH", "tx1", "TX frame 4 (after the reload) decoded a7"),
        ("M_NO_RELOAD_FLUSH", "unread", "left UNREAD"),
        ("M_HALT_KEEP_CKBIT", "spi", "READ returned"),
        ("M_ONE_PHASE_HALT", "spi", "CS must lead"),
        ("M_HALT_KEEP_HOLD", "i2c", "a pad moved"),
        ("M_KEEP_ON_HALT", "keep", "KEEP-LIST CLEARED"),
    ]
    owa = ["+IMG=" + rel(owimg), "+NBYTES=256", "+FEED=" + rel(owfeed),
           "+NFEED=%d" % len(lines), "+POLLIDX=%d" % len(_rx)]

    jobs = [("", a) for a in arms] + [(d, a) for d, a, _w in mustfire]
    def one(job):
        d, a = job
        r = run([tool("vvp"), rel(vvp[d])] + arms[a])
        return job, r.stdout + r.stderr
    def ow(extra):
        r = run([tool("vvp"), rel(owv)] + owa + extra)
        return r.stdout + r.stderr
    with ThreadPoolExecutor(SIMS) as ex:
        res = dict(ex.map(one, jobs))
        ow_clean, ow_rl = ex.map(ow, [[], ["+RELOAD_AT=%d" % OW_RELOAD_AT]])

    ok = True
    def first(o, pat):
        return next((l.strip() for l in o.splitlines() if pat in l), "?")
    for a in arms:
        o = res[("", a)]
        if a == "i2c_harm":
            print("  demo  %-9s %s" % (a, first(o, "RELOAD-DEMO")[:150]))
            continue
        good = "RELOAD: ok" in o and "*** FAIL" not in o
        ok = ok and good
        print("  pass  %-9s %s" % (a, first(o, "RELOAD: ok")[:120] if good
                                   else "RED: " + first(o, "*** FAIL")[:140]))
    for d, a, why in mustfire:
        o = res[(d, a)]
        red = "RELOAD: ok" not in o and any(
            "*** FAIL" in l and why in l for l in o.splitlines())
        ok = ok and red
        print("  must-fire %-18s %-7s %s" % (d, a, "red (%s)" % why if red
                                            else "*** NOT RED for '%s'" % why))

    # ---- 1-Wire: the bytes after the reload == a clean run's ------------
    def rx(o):
        return [(int(m.group(1)), m.group(2))
                for m in re.finditer(r"^OW-RX (\d+) ([0-9a-f]{2})", o, re.M)]
    clean = [b for _i, b in rx(ow_clean)]
    m = re.search(r"received bytes from index (\d+) on", ow_rl)
    base = int(m.group(1)) if m else -1
    post = [b for i, b in rx(ow_rl) if i >= base]
    model_fails = [l for l in ow_rl.splitlines() if "*** FAIL ow-model" in l]
    unexpected = [l for l in model_fails
                  if not any(s in l for s in OW_ABORT)]
    good_clean = ("OW-BENCH: END" in ow_clean and "*** FAIL" not in ow_clean
                  and len(clean) >= 10)
    good_rl = (m is not None and post == clean and not unexpected
               and len(model_fails) == len(OW_ABORT)
               and "OW-BENCH: END" in ow_rl
               and "*** FAIL tb_onewire" not in ow_rl)
    print("  pass  onewire   clean run %s; reload %s -- %d byte(s) after it "
          "%s the clean run's %d; model flags %d (the abort's %d expected)%s"
          % ("ok" if good_clean else "*** RED",
             first(ow_rl, "OW-RELOAD at")[10:70] if m else "*** NEVER RAN",
             len(post), "==" if post == clean else "!=", len(clean),
             len(model_fails), len(OW_ABORT),
             "" if not unexpected else " *** UNEXPECTED: " + unexpected[0][:80]))
    ok = ok and good_clean and good_rl

    if ok:
        print("RELOAD GATE: PASSED")
        return 0
    print("*** FAIL reload: see above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
