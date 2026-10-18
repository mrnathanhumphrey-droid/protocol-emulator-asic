"""FPGA 1-Wire build (OW = 1), SIMULATION -- before any Vivado run (Wilson 10-17).

The whole FPGA core (fpga/rtl/pe_fpga_core.v, OW = 1) runs the CE5 program
`test/onewire_fpga_image.hex` against the DS18B20 model on a pulled-up DQ net
(2 us rise), fed by the core's own TIMED feeder; a model of the PC sends 'G'
and records every byte the board sends back. THIS RUNNER IS THE PC: it judges
those bytes exactly as `fpga/host` will on the real board -- presence, the
echoes, the ROM's CRC-8 and family code, the poll, the scratchpad's CRC-8 and
temperature -- walking the transaction's receive map, with the poll groups
counted from the bytes themselves (busy 00 ... first non-zero).

ARMS
  ok          the real build: every check green, status bits clean, J11 silent
              during the load, and the POLL SLACK measured (below)
  late_edge   the poll decision delayed by the measured minimum slack: the
              reply "arriving at the latest possible moment" -- must stay green
MUST-FIRES (each must reach the END token, and be red for its own reason)
  iso         ISO_MF = 1: the load bytes copied onto J11, as the real chip's
              pads would carry them -- DQ falls during the load must be > 0
  slow        one byte (k = BAD_AT) pushed 2 byte times late: the chip's
              UNDERRUN status bit must light and the run must fail
  fast        one byte pushed 1 byte time early: TX-FULL must light, run fails
              (both judged from the STATUS TRAILER the PC receives -- 'S' +
              st_or, the last two bytes -- not from inside the simulation)
  late_over   the poll decision delayed past the slack: underrun, run fails

THE POLL SLACK (Wilson condition 3). After a poll group's 4 bytes the feeder
waits for that group's reply byte before choosing the next push. The slack is
the cycles from the reply's arrival to the latest moment the decision can be
made: the next byte's queue POP minus the push's own 9 cycles to its low-nibble
PUSH edge minus HOST_INTERFACE's 6-cycle window. Measured per group, minimum
reported.

POSITIVE TOKEN: `FPGA-ONEWIRE: PASSED` only on the success path.
Usage: python fpga/sim/run_fpga_onewire.py [arm ...]   (default: all)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "test"))
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner, tool          # noqa: E402
import onewire                               # noqa: E402
import pe_proto as P                         # noqa: E402
import run_onewire as RO                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TMP = os.environ.get("PE_FOW_TMP") or os.path.join(ROOT, "probe_fpga_onewire")
PUSH_TO_LOW_EDGE = 9       # F_PUSH: low-nibble PUSH edge 9 cycles after start
WINDOW = 6                 # HOST_INTERFACE "Push before the slot"
BAD_AT = 20                # a READ ROM byte: well inside the transaction


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def feed():
    e = onewire.engine("fpga")
    lines, rxmap, pidx = onewire.feed("fpga")
    path = os.path.join(TMP, "ow_fpga_feed.hex")
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return e, lines, rxmap, pidx, path


#: what `build.tcl ow` builds from -- tracked, and checked here to be exactly
#: what this simulation ran (`--write` regenerates them)
#: ⛔ fpga/feeds/, NOT fpga/images/: every .hex in images/ is a 256-byte
#: program image to gate_wire_feed, and a feed's 12-bit words are not bytes
FEED_DIR = os.path.join(ROOT, "fpga", "feeds")
TRK_FEED = os.path.join(FEED_DIR, "onewire_fpga_feed.hex")
TRK_PRM = os.path.join(FEED_DIR, "onewire_fpga_feed.params")


def tracked(e, lines, pidx):
    want_feed = "\n".join(lines) + "\n"
    want_prm = ("NFEED %d\nPOLLIDX %d\nPER2 %d\nMARGIN %d\n"
                % (len(lines), pidx, 2 * e.P, e.P))
    if "--write" in sys.argv:
        for p, t in ((TRK_FEED, want_feed), (TRK_PRM, want_prm)):
            with open(p, "w", encoding="ascii", newline="\n") as fh:
                fh.write(t)
    ok = True
    for p, t in ((TRK_FEED, want_feed), (TRK_PRM, want_prm)):
        have = open(p, encoding="ascii").read().replace("\r\n", "\n") \
            if os.path.exists(p) else None
        same = have == t
        ok &= same
        print("  tracked %s == this simulation's: %s" % (
            rel(p), "yes" if same else "*** NO -- run with --write"))
    return ok


def sim(name, e, nfeed, pidx, fpath, **kw):
    prm = {"FEED": '"%s"' % rel(fpath), "NFEED": nfeed, "POLLIDX": pidx,
           "PER2": 2 * e.P, "MARGIN": e.P}
    prm.update(kw)
    vvp = os.path.join(TMP, "tb_%s.vvp" % name)
    b = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", "tb_fpga_onewire"]
            + ["-Ptb_fpga_onewire.%s=%s" % (k, v) for k, v in prm.items()]
            + ["fpga/sim/tb_fpga_onewire.v", "fpga/rtl/pe_fpga_core.v",
               "test/ds18b20_model.v", "src/project.v", "src/pe_engine.v",
               "src/pe_store.v"])
    if b.returncode:
        raise SystemExit("*** build failed (%s)\n%s%s" % (name, b.stdout, b.stderr))
    log = os.path.join(TMP, "%s.log" % name)
    if os.path.exists(log):
        os.remove(log)
    run([tool("vvp"), "-l", rel(log), rel(vvp)])
    if not os.path.exists(log):
        return ""
    return open(log, encoding="utf-8", errors="replace").read()


#: the chip's status byte (src/project.v): bit 0 = alive
STATUS_BITS = {1: "underrun", 2: "ovf", 3: "ovr", 4: "TX-full",
               5: "config_err", 6: "RX-drop", 7: "clock-stretch"}


def idle_replies(lines):
    """The feed ends in IDLE bytes (0xFF, `feed_file`), whose replies the glue
    forwards too: one reply per 4 bytes. Counted from the feed itself."""
    n = 0
    for w in reversed(lines):
        if w != "0ff":
            break
        n += 1
    return n // 4


def trailer(rx, nseq, nidle):
    """The status trailer is the LAST two bytes the PC receives (forwarding
    stops before it, nothing follows it), so a corrupted run cannot hide it
    by moving where the parse thinks the transaction ended. Between the
    transaction and the trailer: exactly `nidle` idle replies, each FF.
    -> (status or None, the count and the idle bytes are right?, the two bytes)"""
    tr = rx[-2:] if len(rx) >= 2 else []
    st = tr[1] if len(tr) == 2 and tr[0] == 0x53 else None
    idle = rx[nseq:nseq + nidle]
    ok = len(rx) == nseq + nidle + 2 and idle == [0xFF] * nidle
    return st, ok, tr


def status_names(st):
    if st is None:
        return "--"
    on = [n for b, n in sorted(STATUS_BITS.items()) if (st >> b) & 1]
    return "%02X%s" % (st, (" (" + ", ".join(on) + ")") if on else "")


def walk(rx, rxmap):
    """The PC's parse: rxmap in order; a poll entry consumes bytes up to and
    including the first non-zero. -> [(entry, byte)] or None if short."""
    out, i = [], 0
    for r in rxmap:
        if r[0] == "poll":
            while True:
                if i >= len(rx):
                    return out, False
                out.append((r, rx[i]))
                i += 1
                if rx[i - 1] != 0:
                    break
        else:
            if i >= len(rx):
                return out, False
            out.append((r, rx[i]))
            i += 1
    return out, True


def judge(txt, rxmap, nidle):
    d = RO.parse(txt)
    ck = []

    def chk(n, ok, det=""):
        ck.append((n, bool(ok), det))

    chk("bench END token", d["end"])
    seq, full = walk(d["rx"], rxmap)
    chk("received every byte of the transaction", full,
        "%d received" % len(d["rx"]))
    get = lambda kind: [b for r, b in seq if r[0] == kind]
    resets = [b for r, b in seq if r == ("reset", 0)]
    chk("presence after every reset (bit %d == 0)" % P.OneWire.PRESENCE_BIT,
        resets and all(not (b >> P.OneWire.PRESENCE_BIT) & 1 and (b & 0x1F) == 0
                       for b in resets),
        " ".join("%02X" % b for b in resets))
    chk("bus idle after presence (2nd reset byte == FF)",
        all(b == 0xFF for r, b in seq if r == ("reset", 1)))
    ech = [(r[1], b) for r, b in seq if r[0] == "echo"]
    chk("command echoes == the commands written",
        ech and all(a == b for a, b in ech),
        " ".join("%02X" % b for _a, b in ech))
    rom = [b for r, b in seq if r[0] == "read" and r[1] == "rom"]
    chk("ROM CRC-8 valid (PC-side)", len(rom) == 8 and RO.crc8(rom[:7]) == rom[7],
        " ".join("%02X" % b for b in rom))
    chk("ROM family 28h, not an all-zero frame",
        len(rom) == 8 and rom[0] == 0x28 and any(rom))
    chk("ROM == the model's ROM", rom == d["rom"])
    pol = get("poll")
    chk("Convert T polled: busy (00) first, done last",
        len(pol) >= 2 and pol[0] == 0 and pol[-1] != 0,
        " ".join("%02X" % b for b in pol))
    sp = [b for r, b in seq if r[0] == "read" and r[1] == "sp"]
    chk("scratchpad CRC-8 valid (PC-side)",
        len(sp) == 9 and RO.crc8(sp[:8]) == sp[8], " ".join("%02X" % b for b in sp))
    chk("scratchpad == the model's", sp == d["sp"])
    chk("temperature == +25.0625 C (0191h)",
        len(sp) == 9 and (sp[0] | sp[1] << 8) == RO.TEMP_RAW)
    chk("peer model: zero timing violations", d["viol"] == 0, "%s" % d["viol"])
    for nm, v in sorted(d["t"].items()):
        n, mn, mx, lo, hi = v
        chk("timing %s in [%s, %s] us" % (nm, lo / 1000, "inf" if hi is None else hi / 1000),
            n > 0 and mn >= lo and (hi is None or mx <= hi),
            "n=%d min %.3f max %.3f us" % (n, mn / 1000, mx / 1000))
    # ⭐ THE STATUS TRAILER, AS THE PC RECEIVES IT (Wilson #3): 'S' then the
    # status bits, right after the transaction's bytes -- the same check
    # fpga/host/ow_run.py makes on the board
    st, right_after, tr = trailer(d["rx"], len(seq), nidle)
    d["status"] = st
    chk("status trailer received: 'S' + status byte, the last 2 bytes (PC-side)",
        st is not None, " ".join("%02X" % b for b in tr) or "none")
    chk("transaction + %d idle replies (FF) + trailer, nothing missing or extra"
        % nidle, full and right_after,
        "%d bytes = %d + %d + 2?" % (len(d["rx"]), len(seq), nidle))
    chk("status bits clean, as the PC received them (bits 7..1 == 0)",
        st is not None and st & 0xFE == 0, status_names(st))
    m = re.search(r"^OW-STATUS ([0-9a-fx]{2})", txt, re.M)
    sim_st = int(m.group(1), 16) if m and "x" not in m.group(1) else None
    chk("PC status byte == the glue's st_or (simulation cross-check)",
        st is not None and st == sim_st, "sim %s" % ("%02X" % sim_st if sim_st is not None else "--"))
    chk("chip sticky flags clear", d["sticky"] == (0, 0, 0, 0), "%s" % (d["sticky"],))
    m = re.search(r"^OW-ISO falls=(\d+)", txt, re.M)
    d["iso"] = int(m.group(1)) if m else None
    m = re.search(r"^OW-LOADCYC (\d+)", txt, re.M)
    d["loadcyc"] = int(m.group(1)) if m else 0
    chk("J11 silent during load/reset (DQ falls == 0)", d["iso"] == 0,
        "falls %s" % d["iso"])
    # 256 bytes x 7 cycles each = 1792 cycles of load mode at the least
    chk("a load was observed under the monitor (>= 1792 load-mode cycles)",
        d["loadcyc"] >= 1792, "%d" % d["loadcyc"])
    chk("no FAIL line", not d["fails"], d["fails"][0][:90] if d["fails"] else "")
    return d, ck


def slack(txt):
    """-> [(group, reply cyc, pop cyc of the gated byte, slack)]"""
    pops = {int(a): int(b) for a, b in re.findall(r"^OW-POP (\d+) (\d+)", txt, re.M)}
    out = []
    for g, c, _v, kb in re.findall(r"^OW-REPLY (\d+) (\d+) (\w+) kb=(\d+)", txt, re.M):
        c, kb = int(c), int(kb)
        if kb in pops:
            out.append((int(g), c, pops[kb], pops[kb] - c - PUSH_TO_LOW_EDGE - WINDOW))
    return out


def show(name, ck):
    print("  --- %s ---" % name)
    for c, ok, det in ck:
        print("    %-62s %s %s" % (c, "ok " if ok else "***", det))


def main():
    print("FPGA 1-Wire build (OW = 1) -- simulation before Vivado")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    want = set(a for a in sys.argv[1:] if not a.startswith("--"))
    e, lines, rxmap, pidx, fpath = feed()
    print("  program: P = %d cycles (%.1f us); byte time PER2 = %d; margin %d"
          % (e.P, e.P / 50.0, 2 * e.P, e.P))
    print("  feed: %d words, first poll reply at rx %d" % (len(lines), pidx))
    rc = 0 if tracked(e, lines, pidx) else 1
    nidle = idle_replies(lines)
    print("  idle replies after the transaction: %d (FF each), then the trailer" % nidle)
    if "--write" in sys.argv and not want:
        return rc
    sl_min = None

    def go(name, **kw):
        return sim(name, e, len(lines), pidx, fpath, **kw)

    if not want or "ok" in want or "late_edge" in want or "late_over" in want:
        txt = go("ok")
        d, ck = judge(txt, rxmap, nidle)
        show("ok (the real build)", ck)
        rc |= 0 if all(o for _c, o, _d in ck) else 1
        sl = slack(txt)
        for g, c, p, s in sl:
            print("    poll group %d: reply at cyc %d, next pop at %d -> slack %d cycles (%.1f us)"
                  % (g, c, p, s, s / 50.0))
        if sl:
            sl_min = min(s for *_x, s in sl)
            print("    POLL SLACK (minimum): %d cycles = %.1f us" % (sl_min, sl_min / 50.0))
        else:
            print("    *** no poll decision measured")
            rc = 1
    if sl_min is not None and (not want or "late_edge" in want):
        txt = go("late_edge", LATE=sl_min)
        d, ck = judge(txt, rxmap, nidle)
        show("late_edge (decision delayed by the full slack, %d cycles)" % sl_min, ck)
        rc |= 0 if all(o for _c, o, _d in ck) else 1

    print()
    print("  --- must-fires ---")
    mfs = [("iso", dict(ISO_MF=1), lambda d, ck: d["iso"] and d["iso"] > 0,
            "load bytes copied onto J11"),
           ("slow", dict(BAD_AT=BAD_AT, BAD_SHIFT=4 * e.P),
            lambda d, ck: d["status"] is not None and d["status"] & 0x02,
            "byte %d pushed 2 byte times late -> UNDERRUN" % BAD_AT),
           ("fast", dict(BAD_AT=BAD_AT, BAD_SHIFT=-2 * e.P),
            lambda d, ck: d["status"] is not None and d["status"] & 0x10,
            "byte %d pushed 1 byte time early -> TX-FULL" % BAD_AT)]
    if sl_min is not None:
        mfs.append(("late_over", dict(LATE=sl_min + 2 * (PUSH_TO_LOW_EDGE + WINDOW) + 40),
                    lambda d, ck: d["status"] is not None and d["status"] & 0x02,
                    "poll decision past the slack -> UNDERRUN"))
    for name, kw, red, why in mfs:
        if want and name not in want:
            continue
        txt = go(name, **kw)
        d, ck = judge(txt, rxmap, nidle)
        reds = [c for c, o, _d in ck if not o]
        fired = bool(d["end"] and red(d, ck) and reds)
        print("  must-fire %-9s (%s): %s" % (
            name, why, ("red ok -- " + "; ".join(reds)[:160]) if fired
            else "*** MUST-FIRE FAILED (end=%s status=%s iso=%s reds=%s)"
            % (d["end"], d["status"], d["iso"], reds)))
        rc |= 0 if fired else 1

    print()
    print("  FPGA-ONEWIRE: %s" % ("PASSED" if rc == 0 else "*** FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
