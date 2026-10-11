"""HOLD OFFSET GATE -- the W1 eligibility offset, held to the RTL (HC1).

⛔⛔ WHY. W6 derived "eligible HS + 1 after the pick" and PORT_SPEC §7E said
"HS + 1 = 19 after the loading pick". The Lean model, built from the RTL's
effective `l_hcnt`, said decision + 20. MEASURED on RTL signals (2,556 loads
over five images, then 12,062 on ckdense): the hold load lands at decision + 2
and the gate opens at decision + 20 = HS + 2 -- the derivation counted the
DRIVE cycle's start, not the edge that ends it. Nothing held the three (RTL,
program_a2's constant, §7E's text) to each other, so they drifted.

CHECKS (one simulation: tb_trace + test/hold_mon.v on ckdense, 40k cycles)
  1. Every hold load: the decision is found, and the hold gate (`hz_q`) opens
     at the SAME offset K after it. At least 500 loads.
  2. Wherever the hold BINDS (the lane already due when `hz_q` opens): `ready`
     asserts at exactly K too. At least 100 binding loads.
  3. K == HS + program_a2.HOLD_PICK_LAG  (HS = hold_bound.bound() + setup()).
  4. PORT_SPEC §7E states "HS + <LAG> = <K>" (anchor-checked).
MUST-FIRES: program_a2's constant +1 and -1 -> red; §7E text off by one -> red.
"""
import collections
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "model", "a2"), os.path.join(ROOT, "model"),
                os.path.join(ROOT, "test")]
from toolchain import banner, tool        # noqa: E402
import hold_bound                         # noqa: E402
import program_a2                         # noqa: E402

TMP = os.environ.get("PE_HOLD_TMP") or os.path.join(ROOT, "test", "sim_build_hold")
IMG = "test/ckdense_image.hex"
NCYC = 40000
MIN_LOADS, MIN_BINDS = 500, 100


def measure():
    os.makedirs(TMP, exist_ok=True)
    vvp = os.path.join(TMP, "hold.vvp")
    r = subprocess.run([tool("iverilog"), "-g2012", "-I", "test", "-o", vvp,
                        "-s", "tb_trace", "-s", "hold_mon", "test/tb_trace.v",
                        "test/hold_mon.v", "test/fram_i2c.v", "test/fram_spi.v",
                        "src/pe_engine.v", "src/pe_store.v", "src/project.v"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("*** build failed\n" + r.stdout + r.stderr)
    o = subprocess.run([tool("vvp"), vvp, "+IMG=" + IMG, "+NBYTES=256",
                        "+PEER=none", "+NCYC=%d" % NCYC,
                        "+OUT=" + os.path.join(TMP, "o.txt"), "+SEED=1",
                        "+ASYNC=0", "+STAYLOAD=0", "+SCLHOLD=0"],
                       cwd=ROOT, capture_output=True, text=True)
    return [list(map(int, l.split()[1:])) for l in o.stdout.splitlines()
            if l.startswith("HOLD ")]


def spec_text():
    with open(os.path.join(ROOT, "docs", "PORT_SPEC.md"), encoding="utf-8") as fh:
        t = fh.read()
    m = re.search(r"### 7E\..*?(?=\n### 7F\.)", t, re.S)
    return m.group(0) if m else ""


def judge(rows, lag, sec):
    probs = []
    hs = hold_bound.bound() + hold_bound.setup()
    if len(rows) < MIN_LOADS:
        probs.append("only %d hold load(s) seen (< %d): not exercised" % (len(rows), MIN_LOADS))
        return probs, None, None
    nodec = sum(1 for r in rows if r[1] < 0)
    if nodec:
        probs.append("%d load(s) with no decision found" % nodec)
    hz = collections.Counter(r[5] - r[1] for r in rows if r[1] >= 0)
    binds = [r for r in rows if r[1] >= 0 and 0 <= r[7] <= r[5]]
    rd = collections.Counter(r[6] - r[1] for r in binds)
    if len(hz) != 1:
        probs.append("hold-gate offset is not constant: %s" % dict(hz))
    k = next(iter(hz)) if len(hz) == 1 else None
    if len(binds) < MIN_BINDS:
        probs.append("only %d binding load(s) (< %d)" % (len(binds), MIN_BINDS))
    if k is not None and set(rd) != {k}:
        probs.append("where the hold binds, ready - decision = %s, not %d" % (dict(rd), k))
    if k is not None and k != hs + lag:
        probs.append("RTL opens at decision + %d, program_a2 uses HS + %d = %d"
                     % (k, lag, hs + lag))
    want = "HS + %d = %d" % (lag, hs + lag)
    if want not in sec:
        probs.append("PORT_SPEC §7E does not state \"%s\"" % want)
    return probs, k, len(binds)


def main():
    print("=" * 78)
    print("HOLD OFFSET GATE -- W1's eligibility offset == RTL == program_a2 == §7E")
    print("=" * 78)
    banner("iverilog", "vvp")
    rows = measure()
    lag = program_a2.HOLD_PICK_LAG
    sec = spec_text()
    probs, k, nb = judge(rows, lag, sec)
    hs = hold_bound.bound() + hold_bound.setup()
    print("  %s, %d cycles: %d hold load(s), %s binding" % (IMG, NCYC, len(rows), nb))
    print("  RTL: hold gate opens at decision + %s; HS = %d; program_a2 HS + %d = %d"
          % (k, hs, lag, hs + lag))
    for s in probs:
        print("  *** " + s)
    ok = not probs
    print("  --- must-fires: each must go RED ---")
    for name, l2, s2 in (("program_a2 constant + 1", lag + 1, sec),
                         ("program_a2 constant - 1", lag - 1, sec),
                         ("§7E text off by one", lag,
                          sec.replace("HS + %d = %d" % (lag, hs + lag),
                                      "HS + %d = %d" % (lag - 1, hs + lag - 1)))):
        p, _k, _b = judge(rows, l2, s2)
        print("  must-fire %-26s %s" % (name, ("red  ok -- " + p[0][:70]) if p
                                         else "*** STAYED GREEN"))
        ok = ok and bool(p)
    print()
    print("  GATE hold-offset: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
