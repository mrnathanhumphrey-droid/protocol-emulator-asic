"""RULING TX4 -- CLOCKED TRANSMIT VALUES, OVER EVERY CASE THE FIX TOUCHED.

Silicon fix #2 moved the clocked SHIFT's host load off the HIGH phase. The
checking is Layer V of `test/clocked_conform.vh` (V1: the golden model's load
point and bit order; V2: the host-pushed bytes decoded off the pins). This
script owns the cases, built into scratch from `pe_isa`:

  lane 0  OPEN-DRAIN, MSB-first, clocked SHIFTs of 1, 2, ... 8 bits BACK TO
          BACK (no ACK between), then two bytes each FOLLOWED BY an ACK slot,
          then a STOP. ⚠ TX8, MEASURED: after a clocked SHIFTIN the COLLECT
          leaves SCL LOW, so the STOP is SDA low, SCL high, STOP (3); after a
          clocked SHIFT it would need SCL low first (4).
  lane 1  PUSH-PULL, LSB-first, widths 8 3 8 5 1 7 2 4 6 back to back
  host    non-palindromic bytes on both queues (tb_cktx.v)

ARMS:
  fed         V1 and V2 clean on both lanes (lane 0's program carries every
              width 1..8, so every width's bits are checked), no underrun
  starve      the feeder stops for a window, so the queues run EMPTY and
              refill: V2 must still pass (it sends the residue and counts the
              underrun actions), and some lane must have underrun
  MUST-FIRE   `M_TX_LOAD_ANYPHASE` (the pre-fix silicon) on `fed`: V1 and V2
              must both go red
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool          # noqa: E402  ruling V

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_cktx"))
SRCS = ["pe_engine.v", "pe_store.v", "project.v"]


def image(path):
    from pe_isa import (ACT_BASE, ACT_BYTES, OP_LEVEL, OP_REARM, OP_START,
                        OP_STOP, ORDER_LSB, ORDER_MSB, act, act_shift_clocked,
                        act_shiftin_clocked, hdr, write_image)
    sda, scl, d0 = 2, 1, 70
    l0 = [act(OP_START, sda, 0, d0)]
    l0 += [act_shift_clocked(sda, d0, nbits=n, q=0) for n in range(1, 9)]
    for _ in range(2):
        l0 += [act_shift_clocked(sda, d0, nbits=8, q=0),
               act_shiftin_clocked(sda, d0, nbits=1)]
    l0 += [act(OP_LEVEL, sda, 0, d0), act(OP_LEVEL, scl, 1, d0),
           act(OP_STOP, sda, 1, d0), act(OP_REARM, 0, 1, d0)]
    dat, ck, d1 = 3, 4, 30
    l1 = [act_shift_clocked(dat, d1, nbits=n, q=1)
          for n in (8, 3, 8, 5, 1, 7, 2, 4, 6)]
    l1 += [act(OP_REARM, 0, 1, d1)]
    b0 = ACT_BASE
    b1 = b0 + len(l0) * ACT_BYTES
    park = b1 + len(l1) * ACT_BYTES
    tail = [act(OP_REARM, 0, 0, 500)]
    headers = [hdr(sda, scl, 0, d0, 2, 2 * d0, 3 * d0, b0, order=ORDER_MSB),
               hdr(dat, ck, 1, d1, 2, 2 * d1, 3 * d1, b1, order=ORDER_LSB)]
    headers += [hdr(p, p, 0, 500, 2, 200, 240, park) for p in (0, 5, 6)]
    write_image(path, b"".join(headers) + b"".join(l0 + l1 + tail))
    return path


def build(defines, tag):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "cktx_%s.vvp" % tag)
    cmd = [tool("iverilog"), "-g2012", "-o", out, "-s", "tb_cktx"]
    cmd += ["-D%s" % d for d in defines]
    cmd += ["test/tb_cktx.v"] + [os.path.join(ROOT, "src", s) for s in SRCS]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("*** build failed (%s)\n%s"
                         % (tag, (r.stdout + r.stderr)[-900:]))
    return out


def run(vvp, img, ncyc, starve, starve_len):
    with open(img, encoding="ascii") as fh:
        nb = len(fh.read().split())
    r = subprocess.run([tool("vvp"), vvp, "+IMG=" + img.replace(os.sep, "/"),
                        "+NBYTES=%d" % nb, "+NCYC=%d" % ncyc,
                        "+STARVE=%d" % starve, "+STARVE_LEN=%d" % starve_len],
                       cwd=ROOT, capture_output=True, encoding="utf-8",
                       errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    if "END tb_cktx" not in txt:
        raise SystemExit("*** tb_cktx did not finish:\n%s" % txt[-800:])
    return txt


def lanes(txt):
    """{lane: (shifts, popped, sent, underrun)} from Layer V2's lane lines."""
    return {int(m[0]): tuple(int(x) for x in m[1:]) for m in re.findall(
        r"\[V2\] lane (\d+): (\d+) clocked SHIFT\(s\), (\d+) host byte\(s\) "
        r"popped, (\d+) sent, (\d+) underrun", txt)}


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("TX4 -- clocked transmit VALUES: widths 1..8, MSB/LSB, ACK or not,")
    print("       queue empty and refill (Layer V of clocked_conform.vh)")
    print("=" * 78)
    os.makedirs(SCRATCH, exist_ok=True)
    img = image(os.path.join(SCRATCH, "cktx.hex"))
    good, mut = build([], "good"), build(["M_TX_LOAD_ANYPHASE"], "mut")
    rc = 0

    def say(ok, what):
        nonlocal rc
        print("    %-62s %s" % (what, "ok" if ok else "*** FAIL"))
        if not ok:
            rc = 1

    print("  --- fed ---")
    t = run(good, img, 60000, 0, 0)
    ln = lanes(t)
    fails = [l for l in t.splitlines() if "*** FAIL" in l]
    for l in fails[:6]:
        print("      %s" % l)
    say(not fails, "no FAIL line (V1, V2, B, progress, ...)")
    say("[V1]: ok" in t and "[V2]: ok" in t, "Layer V1 and V2 report ok")
    say(set(ln) == {0, 1}, "both lanes transmitted clocked bytes: %s"
        % sorted(ln))
    say(all(v[3] == 0 for v in ln.values()), "no underrun action on a fed run")
    say(all(v[1] - v[2] in (0, 1) and v[2] >= 20 for v in ln.values()),
        "bytes consumed == bytes on the wire (+1 in flight), >= 20 each")
    print("      lanes %s" % ln)

    print("  --- starve: the queues run empty, then refill ---")
    t = run(good, img, 80000, 20000, 12000)
    ln = lanes(t)
    fails = [l for l in t.splitlines() if "*** FAIL" in l]
    for l in fails[:6]:
        print("      %s" % l)
    say(not fails, "no FAIL line: the residue went out as V2 predicts")
    say(any(v[3] > 0 for v in ln.values()),
        "some lane UNDERRAN (the boundary was reached): %s"
        % {k: v[3] for k, v in ln.items()})
    say(re.search(r"CKTX underrun=0*1", t) is not None,
        "the engine's own underrun sticky agrees")

    print("  --- MUST-FIRE: M_TX_LOAD_ANYPHASE (pre-fix silicon) on fed ---")
    t = run(mut, img, 60000, 0, 0)
    say("*** FAIL clocked_conform[V1]" in t, "V1 red (load point / model bit)")
    say("*** FAIL clocked_conform[V2]" in t, "V2 red (the pushed bytes)")
    print()
    print("  GATE cktx: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
