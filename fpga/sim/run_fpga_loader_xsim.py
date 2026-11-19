"""FPGA PC-UART LOADER -- THE SECOND-SIMULATOR CHECK (Wilson 11-15 meta-slow ruling, done 11-16).

The loader gate (run_fpga_loader.py) runs on Verilator since 11-16. iverilog stays as a second
simulator, in the FULL gate run only (CI's fpga shard; ci-only, not pre-push): this gate runs the
four tb_fpga_loader scenarios (ok, boot_mf, ld_magic, ld_short) on BOTH engines and is red on any
difference between their transcripts.

THE COMPARISON. Every line the bench prints, in order, after dropping each engine's own banner
lines (Verilator's `- ...` report, `$finish` notes, VCD and sim_run lines) and collapsing runs of
whitespace. The bench checks the received data itself and prints a FAIL on any mismatch, so the
transcript carries every check it makes; a scenario missing on either side is red too.

MEASURED (11-16): identical on all four (9 / 8 / 8 / 8 lines); iverilog ~940 s per scenario
with the four in parallel, Verilator ~26 s. The iverilog leg's timeout is run_fpga_loader.IV_RUN_S.

MUST-FIRES (run first, on planted transcripts): one changed line -> red; a line missing on one
side -> red; a scenario missing on one side -> red; the same lines in a different order -> red;
control: identical transcripts with different engine banners -> green.

POSITIVE TOKEN: `FPGA-LOADER-XSIM: PASSED`.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_fpga_loader as L  # noqa: E402  (sets PE_SIM=verilator by default)
import fpga_engine  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ENGINE_LINE = re.compile(r"^(- |VCD|\$finish|sim_run:|WARNING:|.*Verilator|.*verilator|"
                         r".*\.v:\d+: \$finish|.*S i m u l a t i o n)")


def norm(text):
    return [re.sub(r"\s+", " ", ln.strip()) for ln in text.splitlines()
            if ln.strip() and not ENGINE_LINE.match(ln.strip())]


def compare(a, b):
    """[problem] -- {scenario: transcript} on two engines; empty iff every scenario's normalized
    transcript is identical, line for line, in order."""
    probs = []
    for n in sorted(set(a) | set(b)):
        if n not in a or n not in b:
            probs.append("%s: ran on one engine only" % n)
            continue
        x, y = norm(a[n]), norm(b[n])
        if x != y:
            i = next((k for k in range(min(len(x), len(y))) if x[k] != y[k]), min(len(x), len(y)))
            probs.append("%s: transcripts differ at line %d: iverilog %r / verilator %r"
                         % (n, i + 1, x[i] if i < len(x) else None, y[i] if i < len(y) else None))
    return probs


def must_fires():
    base = {"ok": "A\nFPGA-LOADER: ok -- x\n", "ld_short": "*** FAIL y\nLD-BOOT bytes=256\n"}
    vl = {k: v + "- Verilator: $finish at 143ms\n" for k, v in base.items()}
    out = []
    for label, b in (("one changed line", dict(vl, ok="A\nFPGA-LOADER: ok -- z\n")),
                     ("a line missing on one side", dict(vl, ok="FPGA-LOADER: ok -- x\n")),
                     ("a scenario missing on one side", {"ok": vl["ok"]}),
                     ("the same lines reordered", dict(vl, ld_short="LD-BOOT bytes=256\n*** FAIL y\n"))):
        out.append((label, bool(compare(base, b))))
    return out, not compare(base, vl)


def main():
    print("FPGA PC-UART loader -- the second-simulator check (iverilog vs Verilator)")
    rc = 0
    mf, ctl = must_fires()
    for label, red in mf:
        print("  must-fire %-34s %s" % (label, "red  ok" if red else "*** MISSED"))
        rc |= 0 if red else 1
    print("  control   %-34s %s" % ("identical, different banners", "green ok" if ctl else "*** RED"))
    rc |= 0 if ctl else 1
    outs = {}
    for eng in ("verilator", "iverilog"):
        fpga_engine.SIM = eng
        outs[eng] = L.run_scenarios()
        print("  ran the four scenarios on %s" % eng)
    probs = compare(outs["iverilog"], outs["verilator"])
    for n in sorted(outs["iverilog"]):
        print("  %-9s %d lines  %s" % (n, len(norm(outs["iverilog"][n])),
                                     "identical" if not any(p.startswith(n + ":") for p in probs)
                                     else "***"))
    for p in probs:
        print("  *** %s" % p)
    rc |= 1 if probs else 0
    print("\nFPGA-LOADER-XSIM: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
