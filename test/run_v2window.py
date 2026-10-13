"""V2 WINDOW gate (Wilson, WF2 #8): the synchronizer window, MEASURED.

A host push crosses `ui_in[6]`'s synchronizer before the TX queue sees it,
so a byte pushed just before its slot may or may not be taken. V2 (pins
only, test/clocked_conform.vh) calls a slot AMBIGUOUS when its byte was
pushed fewer than TV_WIN cycles before it, and HOST_INTERFACE states how
early a host must push. Both numbers come from HERE, not from a reading.

  MEASURE   test/tb_v2win.v: one clocked SHIFT lane looping over an empty
            queue; a dry run finds the slots' writeback cycles; then ONE
            byte (0xFF) is pushed so its low nibble is decoded on the pins
            k cycles before slot 2, for k = 0..10. The THRESHOLD is the
            smallest k from which every larger k is taken.
  CHECKS    the outcome is monotone in k (a non-monotone window is red);
            V2's TV_WIN >= the threshold (no slot the chip may miss is
            judged as taken) and TV_WIN <= threshold + 2 (not padded).
  THE INSIDE-WINDOW ARM (Wilson): k = threshold - 1 is pushed deliberately
            inside the window and recorded -- the chip underruns that slot
            whole (zeros) and sends the byte in the next one; it never
            sends a mixed byte.
Verdict: `V2 WINDOW: PASSED` or `*** FAIL ...`.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402

TMP = os.environ.get("PE_V2WIN_TMP") or os.path.join(HERE, "sim_build_v2win")
CONFORM = os.path.join(HERE, "clocked_conform.vh")
SLOT = 2
LEADS = range(0, 11)


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def image(path):
    """One clocked push-pull SHIFT lane (MOSI uo_out[2], SCK uo_out[1]) at
    d = 40, looping; the other lanes parked on open-drain uio pins."""
    d, mosi, sck = 40, 10, 9
    prog = [I.act_shift_clocked(mosi, d, nbits=8, q=0),
            I.act(I.OP_REARM, 0, 1, d)]
    park = I.ACT_BASE + len(prog) * I.ACT_BYTES
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    hdrs = [I.hdr(mosi, sck, 1, d, 0, 2 * d, 3 * d, I.ACT_BASE)]
    hdrs += [I.hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 3, 4, 5)]
    I.write_image(path, b"".join(hdrs) + b"".join(prog))
    return path


def main():
    print("V2 WINDOW -- the synchronizer window, measured on the RTL in src/")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    img = os.path.relpath(image(os.path.join(TMP, "v2win.hex")),
                          ROOT).replace(os.sep, "/")
    vvp = os.path.join(TMP, "tb_v2win.vvp")
    r = run([tool("iverilog"), "-g2012", "-I", "test", "-o", vvp, "-s",
             "tb_v2win", "test/tb_v2win.v", "src/pe_engine.v",
             "src/pe_store.v", "src/project.v"])
    if r.returncode != 0:
        print("*** build failed\n" + (r.stdout + r.stderr)[-800:])
        return 1
    dry = run([tool("vvp"), vvp, "+IMG=" + img, "+DRY=1"]).stdout
    slots = [int(c) for c in re.findall(r"^SLOT \d+ WB (\d+)", dry, re.M)]
    if len(slots) <= SLOT:
        print("*** the dry run found %d slot(s)" % len(slots))
        return 1
    at = slots[SLOT]
    print("  slots (writeback cycle): %s; judging slot %d at %d"
          % (slots[:5], SLOT, at))
    took = {}
    for k in LEADS:
        o = run([tool("vvp"), vvp, "+IMG=" + img, "+AT=%d" % at,
                 "+LEAD=%d" % k]).stdout
        m = re.search(r"V2WIN lead=\d+ taken=(\d)", o)
        took[k] = int(m.group(1)) if m else None
    print("  lead -> taken: %s" % " ".join("%d:%s" % (k, took[k])
                                            for k in LEADS))
    ok = all(v is not None for v in took.values())
    thr = next((k for k in LEADS if all(took[j] == 1 for j in LEADS if j >= k)),
               None)
    mono = thr is not None and all(took[j] == 0 for j in LEADS if j < thr)
    m = re.search(r"localparam integer TV_WIN = (\d+);",
                  open(CONFORM, encoding="utf-8").read())
    win = int(m.group(1)) if m else None
    print("  threshold: the chip takes a push decoded >= %s cycle(s) before "
          "the slot's writeback%s" % (thr, "" if mono else
                                       "  *** NOT MONOTONE"))
    print("  inside-window arm (lead %s): %s" % (
        None if thr is None else thr - 1,
        "the slot UNDERRAN whole -- the byte waits for the next slot"
        if thr and took.get(thr - 1) == 0 else "*** not recorded"))
    good_win = win is not None and thr is not None and thr <= win <= thr + 2
    print("  V2's TV_WIN = %s: %s" % (win, "ok (>= the threshold, not padded)"
                                      if good_win else "*** must be in "
                                      "[threshold, threshold + 2]"))
    ok = ok and mono and good_win
    if ok:
        print("V2 WINDOW: PASSED")
        return 0
    print("*** FAIL v2window")
    return 1


if __name__ == "__main__":
    sys.exit(main())
