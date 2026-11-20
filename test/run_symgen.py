"""run_symgen -- the symbol generator (Wilson 11-17, option (c) K = 4), judged
cycle for cycle against its golden model (test/symgen_model.py).

Lane 0 owns the generator (header FLAG_SYMGEN). Its program: SYMDEF's three
config words, then one SER per byte (pin A = uio[0], pin B = uio[1], 8 bits,
delay = the byte time B), then a park. tb_pair feeds TX queue 0 with
A5 3C 96 0F. The model runs the same config on the same bytes with a load every
B cycles; the RTL's uio[1:0] waveform, from its first change away from the idle
levels, must equal the model's from its own, through the frame and the underrun
back to idle.

Configurations (each a table instance from the 11-17 study):
  ws2812     pulse width: 4 slots of 19, A = HIGH, D, LOW, LOW
  manch      10BASE-T Manchester: 2 half-bits of 3, A = ~D, D; B the complement
  nrzi       NRZI (spare code TOGGLE-if-~D): one slot of 5, idle A = 1
  biphase    biphase-mark (spare codes TOGGLE, TOGGLE-if-D): 2 halves of 3
  spi_dirty1 the data-phase case, SPI mode 1: data one cycle before the clock edge
Must-fire: M_SG_NOSPARE reads the spare codes 5-7 as HOLD; nrzi and biphase
must go red.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402
import symgen_model as M                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BENCH = "test/tb_pair.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_symgen"
PA, PB = 0, 1                       # uio[0], uio[1]
FEED = (0xA5, 0x3C, 0x96, 0x0F)     # tb_pair's +FEED=1 bytes (host_feed.vh)
T_SYMDEF = 40                       # lane 0's header period: SYMDEF's delay
LAT = 8                             # the start latency (>= J + 1 with lanes 1-4 parked)

CFGS = {
    "ws2812": M.ws2812(19),
    "manch": M.manchester(),
    "nrzi": M.nrzi(5),
    "biphase": M.biphase_mark(3),
    "spi_dirty1": M.spi_dirty(1, 30),
}
SPARE = ("nrzi", "biphase")          # the arms that use codes 5-7
MUTANTS = [("M_SG_NOSPARE", "the spare codes 5-7 read as HOLD", SPARE)]


def cfg_with_lat(c):
    c.lat = LAT
    return c


def image(c):
    l0 = I.ACT_BASE
    prog = I.act_symdef(c.lens, c.code_a, c.code_b, c.idle_a, c.idle_b, c.lat)
    b = c.byte_cycles
    prog += [I.act_ser(PA, PB, c.nbits, b) for _ in FEED]
    lp = l0 + len(prog) * I.ACT_BYTES
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    order = I.ORDER_MSB if c.msb else I.ORDER_LSB
    hdrs = [I.hdr(PA, I.PIN_NONE, 1, T_SYMDEF, I.FLAG_SYMGEN, 2 * T_SYMDEF, 3 * T_SYMDEF,
                  l0, order=order)]
    for n in range(1, I.N_LANES):
        hdrs.append(I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, lp))
    return I.join_image(hdrs, prog)


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_pair"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def rtl_wave(vvp, img, ncyc):
    """per-cycle (a, b) of uio[0] / uio[1] from tb_pair's change events, and
    whether both pins were driven at every change after the first SER."""
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img, "+FEED=1", "+NCYC=%d" % ncyc], images=[img]))
    out = r.stdout + r.stderr
    ev = [(int(c), oe, o) for c, oe, o in re.findall(r"^EV (\d+) (\d\d) (\d\d)$", out, re.M)]
    cur, j, w = ("00", "00"), 0, []
    for c in range(ncyc):
        while j < len(ev) and ev[j][0] <= c:
            cur = (ev[j][1], ev[j][2])
            j += 1
        w.append(cur)
    return w, ("END" in out), out[-300:]


def first_change(seq, idle, start=0):
    for t in range(start, len(seq)):
        if seq[t] != idle:
            return t
    return None


def judge(name, c, w):
    """[problem]: the RTL's driven waveform from its first change away from idle
    equals the model's from its own, for the frame plus 2 bit times of idle."""
    b = c.byte_cycles
    loads = {k * b: v for k, v in enumerate(FEED)}
    ncyc = c.lat + len(FEED) * b + 4 * c.bit_cycles + 10
    mo, _und, ovr = M.run(c, loads, ncyc)
    mw = [(a, bb) for a, bb, _r in mo]
    idle = (c.idle_a, c.idle_b)
    drv = [t for t, (oe, _o) in enumerate(w) if oe == "11"]
    if not drv:
        return ["%s: the generator never drove uio[1:0] (no SER reached it?)" % name]
    rw = [(int(o[1]), int(o[0])) for _oe, o in w]
    t_r = first_change(rw, idle, drv[0])
    t_m = first_change(mw, idle)
    if t_r is None or t_m is None:
        return ["%s: no waveform (RTL first change %s, model %s)" % (name, t_r, t_m)]
    n = min(len(FEED) * b + 2 * c.bit_cycles, len(mw) - t_m, len(rw) - t_r)
    for k in range(n):
        if rw[t_r + k] != mw[t_m + k]:
            return ["%s: cycle +%d after the first edge: RTL A,B = %s, model %s (RTL edge at %d)"
                    % (name, k, rw[t_r + k], mw[t_m + k], t_r)]
    if ovr:
        return ["%s: the model overran (the test's loads are too fast)" % name]
    return []


def run_all(vvp, tmp, tag=""):
    probs, rep = [], {}
    for name, c0 in CFGS.items():
        c = cfg_with_lat(c0)
        p = os.path.join(tmp, "symgen_%s.hex" % name)
        if not os.path.isfile(p):
            I.write_image(p, image(c))
            sim_run.scratch_image(GEN, p)
        ncyc = 400 + c.lat + len(FEED) * c.byte_cycles + 8 * c.bit_cycles
        w, ended, tail = rtl_wave(vvp, p, ncyc)
        if not ended:
            probs.append("%s: the bench did not finish: %s" % (name, tail))
            continue
        pr = judge(name, c, w)
        rep[name] = pr
        probs += pr
    return probs, rep


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("SYMGEN -- the symbol generator against its golden model, cycle for cycle")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_symgen_")
    if True:
        vvp = os.path.join(tmp, "symgen.vvp")
        build(vvp)
        p, rep = run_all(vvp, tmp)
        for name in CFGS:
            r = rep.get(name)
            print("    %-11s %s" % (name, "matches the model" if r == [] else
                                    ("*** %s" % r[0]) if r else "*** not judged"))
        probs += p
        print("\n  must-fires")
        for d, what, arms in MUTANTS:
            mv = os.path.join(tmp, "symgen_%s.vvp" % d)
            build(mv, [d])
            _mp, mrep = run_all(mv, tmp)
            red = [a for a in arms if mrep.get(a)]
            print("    %-14s %-36s %s" % (d, what, ("RED on %s" % ", ".join(red)) if red
                                         else "*** SURVIVED"))
            if sorted(red) != sorted(arms):
                probs.append("%s survived on %s" % (d, sorted(set(arms) - set(red))))
    print()
    for x in probs:
        print("  *** %s" % x)
    print("=" * 78)
    print("  GATE symgen: %s" % ("PASSED" if not probs else "FAILED"))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
