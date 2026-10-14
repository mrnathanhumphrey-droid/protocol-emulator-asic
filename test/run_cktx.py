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
from toolchain import banner, tool, scratch_sub  # noqa: E402  ruling V
import scratch_heads                              # noqa: E402

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
    headers = [hdr(sda, scl, 0, d0, 0, 2 * d0, 3 * d0, b0, order=ORDER_MSB),
               hdr(dat, ck, 1, d1, 0, 2 * d1, 3 * d1, b1, order=ORDER_LSB)]
    headers += [hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 5, 6)]
    write_image(path, b"".join(headers) + b"".join(l0 + l1 + tail))
    return path


def pindiv_image(path=None):
    """RULING PN4: every pin-taking opcode with its ACTION pin != the lane's
    HEADER data pin (and != its clock pin where that is legal) -- the case
    silicon fix #3 hid in, because every program before named one pin per
    lane. Pads 6/7 (the SPI-target CS/MISO pair) are avoided.
      L0  push-pull, header 8, clock 9 (uo): LEVEL, clocked SHIFT and
          unclocked SHIFT on pin 10; a clocked SHIFTIN on pin 3 (a uo clock:
          the capture fix #3 part b made possible)
      L1  push-pull, header 1, clock 2 (uio): a clocked SHIFTIN on pin 3
      L2  push-pull, header 5, no clock: toggles pin 3 -- the data the others
          receive
      L3  open-drain, header 4, clock 5: ARM, READBIT, unclocked SHIFTIN and a
          clocked SHIFTIN, all on pin 3
      L4  push-pull, header 11, no clock: START / STOP on pin 8
    -> image bytes (and written to `path` when given)."""
    from pe_isa import (ACT_BASE, ACT_BYTES, OP_ARM, OP_LEVEL, OP_READBIT,
                        OP_REARM, OP_SHIFT, OP_SHIFTIN, OP_START, OP_STOP,
                        PIN_NONE, act, act_shift_clocked, act_shiftin_clocked,
                        full_store, hdr, order_for, write_image)
    lanes = {
        0: (8, 9, 1, 30, [act(OP_LEVEL, 10, 0, 30),
                          act_shift_clocked(10, 30, nbits=8, q=0),
                          act(OP_SHIFT, 10, 0, 30, count=0, q=0),
                          act_shiftin_clocked(3, 30, nbits=8),
                          act(OP_REARM, 0, 1, 30)]),
        1: (1, 2, 1, 40, [act_shiftin_clocked(3, 40, nbits=8),
                          act(OP_REARM, 0, 1, 40)]),
        2: (5, PIN_NONE, 1, 23, [act(OP_LEVEL, 3, 1, 23),
                                 act(OP_LEVEL, 3, 0, 23),
                                 act(OP_REARM, 0, 1, 23)]),
        3: (4, 5, 0, 70, [act(OP_ARM, 3, 1, 70),
                          act(OP_READBIT, 3, 0, 70),
                          act(OP_SHIFTIN, 3, 0, 70, count=1),
                          act_shiftin_clocked(3, 70, nbits=8),
                          act(OP_REARM, 0, 1, 70)]),
        4: (11, PIN_NONE, 1, 50, [act(OP_START, 8, 0, 50),
                                  act(OP_STOP, 8, 1, 50),
                                  act(OP_REARM, 0, 1, 50)]),
    }
    base, prog, hs = ACT_BASE, [], []
    for ln in range(5):
        pin, ck, mode, d, acts = lanes[ln]
        ops = [int.from_bytes(a, "big") >> (ACT_BYTES * 8 - 3) for a in acts]
        hs.append(hdr(pin, ck, mode, d, 0, 2 * d, 3 * d, base,
                      order=order_for(ops)))
        prog += acts
        base += len(acts) * ACT_BYTES
    img = b"".join(hs) + b"".join(prog)
    if path:
        write_image(path, img)
    return full_store(img)


def tx_header_pin_engine():
    """CI5's must-fire, SCRATCH-BUILT (registered): the clocked push-pull
    SHIFT drives the lane HEADER's pin instead of the action's. A checker
    that samples the header pin (Layer V2 before CI5) would read the right
    bits there and PASS; V2 on the action pin must go red."""
    with open(os.path.join(ROOT, "src", "pe_engine.v"), encoding="utf-8",
              newline="") as fh:
        txt = fh.read().replace("\r\n", "\n")
    # (the driven bit is `tx_bit` since silicon fix #8: a byte's first bit
    # comes from the queue head, not `l_tx[cur][0]`)
    a = ("                      pin_out[a_pin] <= tx_bit & pin_pp[a_pin];\n"
         "                      pin_oe[a_pin]  <= 1'b1;\n")
    b = ("                      pin_out[l_pin[cur]] <= tx_bit;  // S_TX_HEADER_PIN\n"
         "                      pin_oe[l_pin[cur]]  <= 1'b1;\n")
    txt = scratch_sub(txt, a, b, "S_TX_HEADER_PIN")
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "pe_engine_txhdr.v")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt)
    return out


#: scratch-built mutants this file kills (gate_mutant_kills' SCRATCH table)
SCRATCH_MUTANTS = {
    "S_TX_HEADER_PIN": "the clocked push-pull SHIFT drives the header pin "
                       "instead of the action's (CI5's checker must-fire)",
}


#: the last commit BEFORE silicon fix #8 (its RTL is V1's must-fire)
PRE8 = "ff60d45"


def pre8_srcdir():
    """`src/` at PRE8, written to scratch, with ONE observation wire added:
    the queue pop as the per-queue vector `do_popq` the benches read (the
    same value as the old single `do_pop` on `q_sel`; no behaviour change)."""
    d = os.path.join(SCRATCH, "pre8_src")
    os.makedirs(d, exist_ok=True)
    for s in SRCS:
        r = subprocess.run(["git", "show", "%s:src/%s" % (PRE8, s)], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode != 0:
            raise SystemExit("*** git show %s:src/%s failed" % (PRE8, s))
        txt = r.stdout.replace("\r\n", "\n")
        if s == "project.v":
            txt = scratch_sub(
                txt, "  wire do_pop  = e_host_pop & tx_valid;\n",
                "  wire do_pop  = e_host_pop & tx_valid;\n"
                "  wire [3:0] do_popq = do_pop ? (4'b0001 << q_sel) : 4'b0000;"
                "  // PRE8 observation wire\n", "PRE8_OBS")
        with open(os.path.join(d, s), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)
    return d


def build(defines, tag, engine=None, srcdir=None):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "cktx_%s.vvp" % tag)
    cmd = [tool("iverilog"), "-g2012", "-o", out, "-s", "tb_cktx"]
    cmd += ["-D%s" % d for d in defines]
    sd = srcdir or os.path.join(ROOT, "src")
    cmd += ["test/tb_cktx.v", engine or os.path.join(sd, SRCS[0])]
    cmd += [os.path.join(sd, s) for s in SRCS[1:]]
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
                        "+STARVE=%d" % starve, "+STARVE_LEN=%d" % starve_len]
                       # ⭐ WF2 ruling 3: a starve window is a DECLARED underrun
                       + (["+V3_UNDERRUN=2"] if starve else []),
                       cwd=ROOT, capture_output=True, encoding="utf-8",
                       errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    if "END tb_cktx" not in txt:
        raise SystemExit("*** tb_cktx did not finish:\n%s" % txt[-800:])
    return txt


def lanes(txt):
    """{lane: (shifts, popped-and-sent, underrun)} from Layer V2's lane lines.
    ⭐ Since silicon fix #8 a clocked SHIFT sends the byte it pops, so popped
    and sent are one number (they used to differ by the byte in flight)."""
    return {int(m[0]): tuple(int(x) for x in m[1:]) for m in re.findall(
        r"\[V2\] lane (\d+): (\d+) clocked SHIFT\(s\), (\d+) host byte\(s\) "
        r"taken and sent, (\d+) underrun", txt)}


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
    say(all(v[2] == 0 for v in ln.values()), "no underrun action on a fed run")
    say(all(v[0] - v[1] in (0, 1) and v[1] >= 20 for v in ln.values()),
        "every clocked SHIFT sent the byte it popped (+1 not yet at its "
        "first HIGH), >= 20 each")
    print("      lanes %s" % ln)

    print("  --- starve: the queues run empty, then refill ---")
    t = run(good, img, 80000, 20000, 12000)
    ln = lanes(t)
    fails = [l for l in t.splitlines() if "*** FAIL" in l]
    for l in fails[:6]:
        print("      %s" % l)
    say(not fails, "no FAIL line: an underrun sent zeros, as V2 predicts")
    say(any(v[2] > 0 for v in ln.values()),
        "some lane UNDERRAN (the boundary was reached): %s"
        % {k: v[2] for k, v in ln.items()})
    say(re.search(r"CKTX underrun=0*1", t) is not None,
        "the engine's own underrun sticky agrees")

    print("  --- MUST-FIRE: M_TX_LOAD_ANYPHASE (pre-fix silicon) on fed ---")
    t = run(mut, img, 60000, 0, 0)
    say("*** FAIL clocked_conform[V1]" in t, "V1 red (load point / model bit)")
    say("*** FAIL clocked_conform[V2]" in t, "V2 red (the pushed bytes)")

    # ⛔ V1 IS THE SECONDARY CHECK SINCE V2 WENT PINS-ONLY (Wilson): its load
    # point became "the slot's byte is consumed by its first HIGH", and it
    # must still be RED on silicon fix #8 undone -- both the mutant and the
    # real pre-#8 RTL.
    print("  --- MUST-FIRE: M_TX_PRELOAD (silicon fix #8 undone) on fed ---")
    t = run(build(["M_TX_PRELOAD"], "preload"), img, 60000, 0, 0)
    say("*** FAIL clocked_conform[V1]" in t, "V1 red (the byte is popped a "
        "byte late -- the model loads on the first LOW)")
    print("  --- MUST-FIRE: the pre-#8 silicon (%s) on fed ---" % PRE8)
    t = run(build([], "pre8", srcdir=pre8_srcdir()), img, 60000, 0, 0)
    say("*** FAIL clocked_conform[V1]" in t, "V1 red on the real pre-#8 RTL")

    # ⛔ ATTRIBUTION, PINS ONLY (Wilson): two queues' heads swapped must be
    # caught by V2 from the pins -- `fed` drives two lanes on queues 0 and 1
    # with DISTINCT non-palindromic bytes, so a swap cannot hide. The patch
    # is test/scratch_heads.py's, applied to the CURRENT src/ (declared and
    # registered in test/run_mutants.py, whose tb_tx arm is the killer).
    print("  --- MUST-FIRE: S_QUEUE_SWAP (queues 0<->1 heads swapped) on fed ---")
    t = run(build([], "qswap", srcdir=scratch_heads.patched_srcdir(
        "S_QUEUE_SWAP", SCRATCH)), img, 60000, 0, 0)
    say("*** FAIL clocked_conform[V2]" in t, "V2 red from the pins alone")

    # ---- PN4: every pin-taking opcode with action pin != header pin -------
    print("  --- pindiv: action pin != header pin, every pin-taking opcode ---")
    pimg = os.path.join(SCRATCH, "pindiv.hex")
    pindiv_image(pimg)
    t = run(good, pimg, 80000, 0, 0)
    fails = [l for l in t.splitlines() if "*** FAIL" in l]
    for l in fails[:6]:
        print("      %s" % l)
    say(not fails, "no FAIL line (V1, V2, V-RX, B, progress, ...)")
    m = re.search(r"\[V-RX\]: ok -- (\d+) RX frame", t)
    say(m is not None and int(m.group(1)) >= 8,
        "V-RX: the received bytes are the pins' on the ACTION's pin (%s)"
        % (m.group(1) if m else "none"))
    say("[V2]: ok" in t, "V2: the transmitted bits on the ACTION's pin")
    print("  --- MUST-FIRE (CI5): S_TX_HEADER_PIN -- the SHIFT drives the "
          "header pin ---")
    th = run(build([], "txhdr", tx_header_pin_engine()), pimg, 80000, 0, 0)
    say("*** FAIL clocked_conform[V2]" in th,
        "V2 red: the action pin did not carry the bits (a header-pin "
        "checker would have read them there and passed)")
    print()
    print("  GATE cktx: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
