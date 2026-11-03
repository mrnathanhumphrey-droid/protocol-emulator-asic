"""GATE clock-cross -- the same programs, assembled at two clocks, behave the
same in REAL TIME (Wilson 11-03).

⛔⛔ WHY. A program is written in real time (a rate, a minimum in ns) and the
toolchain turns it into cycles for its target's clock. A program that kept a
typed cycle count would assemble fine at both clocks and be wrong at one of
them -- the 400 kHz I2C program typed at 50 MHz ran 472 kHz at 60. Nothing
in a single-clock suite can see that: every bench agrees with itself.

⇒ Each shipped program is assembled under BOTH targets (`PE_TARGET=chip`,
  60 MHz; `PE_TARGET=fpga`, 50 MHz), run on test/tb_xclock.v at the clock it
  was built for (the chip sized for it, `-DPE_CLK_PS`), and its wire measured
  in NANOSECONDS:

    i2c   corpus_i2c (Fm 400 kHz)    SCL low and high phase, median
    spi   corpus_spim25 (1 MHz)      SCLK period, median
    uart  uart_tx (115200)           the bit time (modal edge spacing)

  The two clocks must agree to the band (5 %) plus one cycle of the slower
  clock -- a cycle count derived from real time can land a cycle apart.

⭐ MUST-FIRE: the same I2C program with its delay TYPED (70 cycles, the old
50 MHz number) must disagree across the clocks -- red. And PWM, which has no
chip program, is held at the model: `per_rate(500 kHz)` at both clocks.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEST = os.path.join(ROOT, "test")
sys.path.insert(0, HERE)
sys.path.insert(0, TEST)

import clock                                            # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TMP = os.path.join(TEST, "sim_build_xclock")
SRC = ["test/tb_xclock.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
NCYC = 60000
TYPED_D = 70            # clock-ok: the must-fire's typed delay, the old 50 MHz Fm number

#: name -> (builder, pin, what)
PROGRAMS = {
    "i2c": ("corpus.build_i2c()", "P_SCL", "SCL low / high phase"),
    "spi": ("corpus.build_spi_master_1mhz()", "P_M_SCLK", "SCLK period"),
    "uart": ("uart_tx.build()", "P_TX", "bit time"),
    "i2c_typed": ("corpus.build_i2c(d=%d)" % TYPED_D, "P_SCL", "SCL low / high phase"),
}


def emit(outdir, target):
    """Child mode: build every program under THIS process's PE_TARGET."""
    import corpus
    import pe_isa
    import uart_tx
    pins = {}
    for name, (expr, pin, _w) in PROGRAMS.items():
        got = eval(expr, {"corpus": corpus, "uart_tx": uart_tx})   # noqa: S307
        img = got[0] if isinstance(got, tuple) else got
        path = os.path.join(outdir, "probe_xclk_%s_%s.hex" % (name, target))
        pe_isa.write_image(path, img)
        pins[name] = getattr(corpus, pin) if hasattr(corpus, pin) else getattr(uart_tx, pin)
    print(json.dumps({"hz": clock.hz(), "pins": pins}))


def run(cmd, env=None):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def level(row, pin):
    uo, out, oe = row
    if pin >= 8:
        return (uo >> (pin - 8)) & 1
    return ((out >> pin) & 1) if (oe >> pin) & 1 else 1      # pulled up


def edges(trace, pin, ps):
    """[(t_ns, level)] at each change of `pin`."""
    out, last = [], None
    for line in trace:
        if line.startswith("#"):
            continue
        f = line.split()
        row = (int(f[1], 2), int(f[2], 2), int(f[3], 2))
        v = level(row, pin)
        if v != last:
            out.append((int(f[0]) * ps / 1000.0, v))
            last = v
    return out


def measure(name, ev):
    """The program's real-time figure(s), in ns."""
    gaps = [(b[0] - a[0], a[1]) for a, b in zip(ev, ev[1:])]
    if len(gaps) < 6:
        return None
    if name.startswith("i2c"):
        lo = [g for g, v in gaps if v == 0]
        hi = [g for g, v in gaps if v == 1]
        return {"low": statistics.median(lo), "high": statistics.median(hi)}
    if name == "spi":
        per = [ev[i + 2][0] - ev[i][0] for i in range(len(ev) - 2) if ev[i][1] == 1]
        return {"period": statistics.median(per)}
    # the MODAL edge spacing: one bit. Not the minimum -- the first gap is the
    # start-up before the first frame (134 cycles at either clock, measured),
    # and a few are a cycle or two off by EDF service jitter
    import collections
    return {"bit": collections.Counter(round(g, 1) for g, _v in gaps).most_common(1)[0][0]}


def agree(a, b, slow_ps):
    """|a - b| within the band plus one cycle of the slower clock."""
    tol = float(clock.BAND - 1) * max(a, b) + slow_ps / 1000.0
    return abs(a - b) <= tol, tol


def main(argv):
    if "--emit" in argv:
        emit(argv[argv.index("--emit") + 1], os.environ.get("PE_TARGET", "chip"))
        return 0
    import sim_run
    from toolchain import tool
    os.makedirs(TMP, exist_ok=True)
    rc = 0
    res = {}
    print("  --- the programs, assembled per target and run at its clock ---")
    for target in ("chip", "fpga"):
        env = dict(os.environ, PE_TARGET=target)
        r = run([sys.executable, os.path.abspath(__file__), "--emit", TMP], env)
        if r.returncode != 0:
            print("  *** COULD NOT RUN: building at target %s failed\n%s" % (target, r.stderr[-800:]))
            return 1
        meta = json.loads(r.stdout.strip().splitlines()[-1])
        ps = clock.period_ps(meta["hz"])
        vvp = os.path.join(TMP, "tb_xclock_ps%d.vvp" % ps)
        b = run([tool("iverilog"), "-g2012", "-I", ".", "-DPE_CLK_PS=%d" % ps,
                 "-s", "tb_xclock", "-o", vvp] + SRC)
        if b.returncode != 0:
            print("  *** COULD NOT RUN: tb_xclock build at %d ps\n%s" % (ps, b.stdout + b.stderr))
            return 1
        for name in PROGRAMS:
            img = os.path.join(TMP, "probe_xclk_%s_%s.hex" % (name, target))
            sim_run.scratch_image("gate_clock_cross", img)
            out = os.path.join(TMP, "xclk_%s_%s.txt" % (name, target))
            rel = lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")
            from pe_isa import STORE_BYTES
            s = run(sim_run.vvp([vvp, "+IMG=" + rel(img), "+NBYTES=%d" % STORE_BYTES,
                                 "+OUT=" + rel(out), "+NCYC=%d" % NCYC], images=[rel(img)]))
            if "tb_xclock: END" not in s.stdout:
                print("  *** COULD NOT RUN: %s at %s\n%s" % (name, target, (s.stdout + s.stderr)[-600:]))
                return 1
            with open(out, encoding="utf-8") as fh:
                m = measure(name, edges(fh.read().splitlines(), meta["pins"][name], ps))
            res[(name, target)] = (m, ps)
            print("    %-10s %-5s %5.1f MHz  %s" % (name, target, meta["hz"] / 1e6,
                  "  ".join("%s %.1f ns" % kv for kv in sorted(m.items())) if m
                  else "*** too few edges to measure"))
            if m is None:
                rc = 1
    print("  --- the same program at two clocks, in real time ---")
    verdict = {}
    for name in PROGRAMS:
        (a, pa), (b, pb) = res[(name, "chip")], res[(name, "fpga")]
        if a is None or b is None:
            continue
        oks = []
        for k in sorted(a):
            ok, tol = agree(a[k], b[k], max(pa, pb))
            oks.append(ok)
            print("    %-10s %-7s chip %8.1f  fpga %8.1f ns   tol %.1f  %s"
                  % (name, k, a[k], b[k], tol, "ok" if ok else "DISAGREE"))
        verdict[name] = all(oks)
    for name in ("i2c", "spi", "uart"):
        if not verdict.get(name):
            print("    *** %s does not behave the same in real time at both clocks" % name)
            rc = 1
    red = verdict.get("i2c_typed") is False
    print("    must-fire: %-38s %s" % ("I2C with its delay typed (%d)" % TYPED_D,
                                       "red  ok" if red else "*** MISSED"))
    rc |= 0 if red else 1
    sys.path.insert(0, os.path.join(ROOT, "model", "ta02"))
    pwm = {t: clock.per_rate(500_000, clock.target_hz(t)) for t in ("chip", "fpga")}
    khz = {t: clock.target_hz(t) / pwm[t] / 1000.0 for t in pwm}
    ok = all(abs(v - 500.0) <= 500.0 * float(clock.BAND - 1) for v in khz.values())
    print("    %-10s %-7s chip %8.1f  fpga %8.1f kHz  %s" % ("pwm", "rate", khz["chip"], khz["fpga"],
                                                         "ok" if ok else "DISAGREE"))
    rc |= 0 if ok else 1
    print()
    print("  GATE clock-cross: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
