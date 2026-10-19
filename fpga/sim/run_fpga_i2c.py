"""FPGA I2C FRAM build (OW = 2), SIMULATION -- before any Vivado run.

The whole FPGA core (fpga/rtl/pe_fpga_core.v, OW = 2) runs the one-pass
program of fpga/sim/i2c_fram.py (the shipped Fm lane: read old 0x0010..13,
write the PC's 4 bytes, read them back) against the MB85RC256V model, the
feeder paced by the chip's SCL FALLS (Wilson decision 1). The PC model sends
'G' + 4 data bytes. THIS RUNNER IS THE PC: it judges the bytes the board
sends back exactly as fpga/host/i2c_run.py will -- every ACK bit 0, the old
bytes, the new bytes == what it sent, the status trailer clean.

ALSO CHECKED (simulation introspection, labelled):
  * THE COUNT MODEL (Wilson 1a): at every pop, the BUS's SCL falls ==
    i2c_fram.falls()'s model, printed per byte;
  * COUNTED ONCE (1b): the glue's filtered total == the bus's == the model's,
    and at each pop the glue is level with the bus or one behind -- a START's
    fall lands a few cycles before the next pop, inside the 2-flop + DEGLITCH
    latency (the 5 START pops); a glue count AHEAD is a double count;
  * PUSH TIMING: each byte's low-nibble PUSH edge is after pop k-2 and at
    least 6 cycles (HOST_INTERFACE's window) before pop k; minimum reported;
  * LOAD ISOLATION: no SCL/SDA fall and no START at the FRAM during load.

ARMS
  ok          the real build (DEGLITCH 8 = 160 ns)
  glitch      a 3-cycle bounce on the FPGA's SCL input after bus fall 50:
              must be COUNTED ONCE -- the same counts, the run green (1b)
MUST-FIRES (each must reach END and be red for its own reason)
  glitch_raw  the same bounce with DEGLITCH 1: counted twice -> count red
  iso         ISO_MF: load bytes on J11 -> bus activity during the load
  slow        byte 12 pushed 30 falls late -> UNDERRUN in the PC's trailer
  fast        byte 12 pushed at once (no wait) -> TX-FULL in the trailer

POSITIVE TOKEN: `FPGA-I2C: PASSED` only on the success path.
Usage: python fpga/sim/run_fpga_i2c.py [arm ...] [--write]
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner, tool          # noqa: E402
import sim_run                               # noqa: E402
import i2c_fram as IF                        # noqa: E402
import run_fpga_onewire as RF                # noqa: E402  status_names

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TMP = os.environ.get("PE_FI2C_TMP") or os.path.join(ROOT, "probe_fpga_i2c")
FEED_DIR = os.path.join(ROOT, "fpga", "feeds")
TRK = {"feed": os.path.join(FEED_DIR, "i2c_fram_feed.hex"),
       "falls": os.path.join(FEED_DIR, "i2c_fram_falls.hex"),
       "params": os.path.join(FEED_DIR, "i2c_fram.params")}
IMG = os.path.join(ROOT, "fpga", "images", "i2c_fram_fpga.hex")
WINDOW = 6
OLD = 0xE0E1E2E3
DATA = 0x5A3CC3A5            # != OLD (the PC re-rolls on equality, 2a)


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def wanted():
    f, total = IF.falls()
    pr = IF.params()
    return {
        "feed": "\n".join(IF.feed_lines()) + "\n",
        "falls": "\n".join("%04x" % x for x in f) + "\n",
        "params": "NFEED %d\nNRX %d\n" % (pr["NFEED"], pr["NRX"]),
        "img": "\n".join("%02x" % b for b in IF.image()) + "\n"}


def tracked():
    w = wanted()
    paths = dict(TRK, img=IMG)
    if "--write" in sys.argv:
        for k, p in paths.items():
            with open(p, "w", encoding="ascii", newline="\n") as fh:
                fh.write(w[k])
    ok = True
    for k, p in sorted(paths.items()):
        have = open(p, encoding="ascii").read().replace("\r\n", "\n") \
            if os.path.exists(p) else None
        same = have == w[k]
        ok &= same
        print("  tracked %s == this simulation's: %s"
              % (rel(p), "yes" if same else "*** NO -- run with --write"))
    return ok


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def sim(name, **kw):
    pr = IF.params()
    prm = {"IMG": '"%s"' % rel(IMG), "FEED": '"%s"' % rel(TRK["feed"]),
           "FALLS": '"%s"' % rel(TRK["falls"]), "NFEED": pr["NFEED"],
           "NRX": pr["NRX"], "DATA": "32'h%08x" % DATA, "OLD": "32'h%08x" % OLD}
    prm.update(kw)
    vvp = os.path.join(TMP, "tb_%s.vvp" % name)
    b = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", "tb_fpga_i2c"]
            + ["-Ptb_fpga_i2c.%s=%s" % (k, v) for k, v in prm.items()]
            + ["fpga/sim/tb_fpga_i2c.v", "fpga/rtl/pe_fpga_core.v",
               "test/fram_i2c.v", "src/project.v", "src/pe_engine.v",
               "src/pe_store.v"])
    if b.returncode:
        raise SystemExit("*** build failed (%s)\n%s%s" % (name, b.stdout, b.stderr))
    log = os.path.join(TMP, "%s.log" % name)
    if os.path.exists(log):
        os.remove(log)
    # the program image is the core's compile-time IMG parameter, so it is
    # named here (sim_run cannot see it in a plusarg)
    run(sim_run.vvp(["-l", rel(log), rel(vvp)], images=[rel(IMG)]))
    return open(log, encoding="utf-8", errors="replace").read() \
        if os.path.exists(log) else ""


def pc_judge(rx, data, old=None):
    """THE PC'S CHECKS -- shared with fpga/host/i2c_run.py. `rx`: every byte
    the board sent. -> (checks, old bytes read, new bytes read, status)."""
    ck = []

    def chk(n, ok, det=""):
        ck.append((n, bool(ok), det))

    m = IF.rxmap()
    # the trailer is the LAST two bytes (nothing follows it), so a run that
    # lost or gained a byte cannot hide its status; `None` = an unreadable
    # byte (X in simulation), which no check accepts
    body, tr = rx[:len(m)], rx[-2:] if len(rx) >= 2 else []
    chk("received the pass's %d bytes + the 2-byte trailer, exactly" % len(m),
        len(rx) == len(m) + 2, "%d bytes" % len(rx))
    acks = [(info, b) for (k, info), b in zip(m, body) if k == "ack"]
    chk("every ACK slot read ACK (bit 0 == 0): %d slots" % len(acks),
        len(acks) == sum(1 for k, _i in m if k == "ack")
        and all(b is not None and b & 1 == 0 for _i, b in acks),
        " ".join("%s" % i for i, b in acks if b is None or b & 1) or "")
    got_old = [b for (k, _i), b in zip(m, body) if k == "old"]
    got_new = [b for (k, _i), b in zip(m, body) if k == "new"]
    want = list(data.to_bytes(4, "big"))
    hx = lambda bs: " ".join("--" if b is None else "%02X" % b for b in bs)
    if old is not None:
        chk("old contents == expected", got_old == list(old.to_bytes(4, "big")),
            hx(got_old))
    chk("readback == the 4 bytes the PC sent", got_new == want,
        "%s vs %s" % (hx(got_new), hx(want)))
    chk("the write CHANGED the contents (readback != old)", got_new != got_old)
    st = tr[1] if len(tr) == 2 and tr[0] == 0x53 else None
    chk("status trailer 'S' + byte, and clean (bits 7..1 == 0)",
        st is not None and st & 0xFE == 0, RF.status_names(st))
    return ck, got_old, got_new, st


def judge(txt):
    rx = [None if "x" in v else int(v, 16)
          for v in re.findall(r"^I2C-RX \d+ ([0-9a-fx]{2})", txt, re.M)]
    ck, got_old, got_new, st = pc_judge(rx, DATA, OLD)

    def chk(n, ok, det=""):
        ck.append((n, bool(ok), det))

    d = {"status": st, "end": "I2C-BENCH: END" in txt,
         "fails": [l for l in txt.splitlines() if "*** FAIL" in l]}
    chk("bench END token", d["end"])
    model, total = IF.falls()
    pops = [(int(k), int(g), int(b), int(c)) for k, g, b, c in
            re.findall(r"^I2C-POP (\d+) (\d+) (\d+) (\d+)", txt, re.M)]
    pushes = {int(k): int(c) for k, c in re.findall(r"^I2C-PUSH (\d+) (\d+)", txt, re.M)}
    glue = [g for _k, g, _b, _c in pops]
    bus = [b for _k, _g, b, _c in pops]
    d["glue"], d["bus"] = glue, bus
    # (1) THE COUNT MODEL is a statement about the WIRE: the bus's falls
    # before each pop
    chk("COUNT MODEL: the bus's SCL falls before each pop == the model (%d pops)"
        % len(model), bus == model,
        "" if bus == model else "first diff at %s" % next(
            (i for i, (a, b) in enumerate(zip(bus, model)) if a != b), len(bus)))
    # (2) EVERY FALL COUNTED ONCE BY THE GLUE: the same total, and at a pop
    # the glue is level with the bus or ONE behind -- the fall a START puts
    # a few cycles before the next pop is still inside the 2-flop + DEGLITCH
    # filter. A glue count AHEAD of the bus is a double count.
    m = re.search(r"^I2C-HOST .*glue_falls=(\d+) bus_falls=(\d+)", txt, re.M)
    tot = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    lag = [b - g for g, b in zip(glue, bus)]
    d["ahead"] = any(x < 0 for x in lag) or (tot[0] is not None and tot[0] != tot[1])
    chk("every SCL fall counted ONCE by the glue (totals equal; lag 0 or 1)",
        tot[0] is not None and tot[0] == tot[1] == total
        and lag and all(x in (0, 1) for x in lag),
        "glue %s / bus %s / model %d; %d pop(s) one behind (filter latency)"
        % (tot[0], tot[1], total, sum(1 for x in lag if x == 1)))
    pc = {k: c for k, _g, _b, c in pops}
    margins = [pc[k] - pushes[k] for k in pushes if k in pc and k >= 2]
    after = [pushes[k] > pc[k - 2] for k in pushes if k >= 2 and k - 2 in pc]
    d["margin"] = min(margins) if margins else None
    chk("every push lands >= %d cycles before its pop" % WINDOW,
        margins and min(margins) >= WINDOW,
        "min %s cycles" % d["margin"])
    chk("every push k comes after pop k-2 (the queue has room)",
        after and all(after), "%d pushes" % len(after))
    m = re.search(r"^I2C-ISO falls=(\d+)", txt, re.M)
    s = re.search(r"^I2C-ISO starts=(\d+)", txt, re.M)
    d["iso"] = (int(m.group(1)) if m else None, int(s.group(1)) if s else None)
    chk("J11 silent during load/reset: no SCL/SDA fall, no START at the FRAM",
        d["iso"] == (0, 0), "falls %s, starts %s" % d["iso"])
    m = re.search(r"^I2C-LOADCYC (\d+)", txt, re.M)
    chk("a load was observed (>= 1792 load-mode cycles)",
        m and int(m.group(1)) >= 1792, m.group(1) if m else "")
    m = re.search(r"^I2C-MEM ((?:[0-9a-fx]{2} ?){4})", txt, re.M)
    chk("the FRAM model holds the PC's bytes", m and m.group(1).split()
        == ["%02x" % b for b in DATA.to_bytes(4, "big")], m.group(1) if m else "")
    chk("no FAIL line", not d["fails"], d["fails"][0][:90] if d["fails"] else "")
    return d, ck


def show(name, ck):
    print("  --- %s ---" % name)
    for c, ok, det in ck:
        print("    %-66s %s %s" % (c, "ok " if ok else "***", det))


def count_model_table():
    model, total = IF.falls()
    acts, _m = IF.actions()
    print("  COUNT MODEL (Wilson 1a): START / repeated START = 1 fall each,")
    print("  each clocked bit = 1, LEVEL/STOP/REARM = 0; a SHIFT pops before")
    print("  its own falls. Falls before each fed byte's pop:")
    words = IF.feed()
    for k, (w, f) in enumerate(zip(words, model)):
        print("    byte %2d %-8s falls before pop %3d  -> pushed at fall %s"
              % (k, ("PC[%d]" % w[1]) if w[0] == "pc" else "%02X" % w[1], f,
                 "prefill" if k < 2 else model[k - 2] + 1))
    print("    pass total: %d falls" % total)


def main():
    print("FPGA I2C FRAM build (OW = 2) -- simulation before Vivado")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    rc = 0 if tracked() else 1
    want = set(a for a in sys.argv[1:] if not a.startswith("--"))
    if "--write" in sys.argv and not want:
        return rc
    count_model_table()

    for name, kw in (("ok", {}), ("glitch", {"GLITCH_AT": 50})):
        if want and name not in want:
            continue
        d, ck = judge(sim(name, **kw))
        show(name, ck)
        print("    push margin before pop: min %s cycles" % d["margin"])
        rc |= 0 if all(o for _c, o, _d in ck) else 1

    print()
    print("  --- must-fires ---")
    mfs = [("glitch_raw", {"GLITCH_AT": 50, "DEGLITCH": 1},
            lambda d: d["ahead"], "bounce, no deglitch -> glue counts AHEAD of the bus"),
           ("iso", {"ISO_MF": 1}, lambda d: d["iso"][0] and d["iso"][0] > 0,
            "load bytes copied onto J11"),
           ("slow", {"BAD_AT": 12, "BAD_SHIFT": 30},
            lambda d: d["status"] is not None and d["status"] & 0x02,
            "byte 12 pushed 30 falls late -> UNDERRUN"),
           ("fast", {"BAD_AT": 12, "BAD_SHIFT": -1000},
            lambda d: d["status"] is not None and d["status"] & 0x10,
            "byte 12 pushed without waiting -> TX-FULL")]
    for name, kw, red, why in mfs:
        if want and name not in want:
            continue
        d, ck = judge(sim(name, **kw))
        reds = [c for c, o, _d in ck if not o]
        fired = bool(d["end"] and red(d) and reds)
        print("  must-fire %-10s (%s): %s" % (
            name, why, ("red ok -- trailer %s; %s" % (
                RF.status_names(d["status"]), "; ".join(reds)[:140])) if fired
            else "*** MUST-FIRE FAILED (end=%s status=%s iso=%s reds=%s)"
            % (d["end"], d["status"], d["iso"], reds)))
        rc |= 0 if fired else 1

    print()
    print("  FPGA-I2C: %s" % ("PASSED" if rc == 0 else "*** FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
