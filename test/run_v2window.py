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
import sim_run                          # noqa: E402
import pe_isa as I                      # noqa: E402

TMP = os.environ.get("PE_V2WIN_TMP") or os.path.join(HERE, "sim_build_v2win")
#: phases (1 ns steps after the negedge) the asynchronous-edge walk covers,
#: each judged; held to model/phase_coverage.py's row by gate_phase_coverage
PHASE_FLOOR = 20
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
    I.write_image(path, I.join_image(hdrs, prog))
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
    dry = run(sim_run.vvp([vvp, "+IMG=" + img, "+DRY=1"], images=[img])).stdout
    slots = [int(c) for c in re.findall(r"^SLOT \d+ WB (\d+)", dry, re.M)]
    if len(slots) <= SLOT:
        print("*** the dry run found %d slot(s)" % len(slots))
        return 1
    at = slots[SLOT]
    print("  slots (writeback cycle): %s; judging slot %d at %d"
          % (slots[:5], SLOT, at))
    took = {}
    for k in LEADS:
        o = run(sim_run.vvp([vvp, "+IMG=" + img, "+AT=%d" % at,
                             "+LEAD=%d" % k], images=[img])).stdout
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

    # ---- THE WINDOW FROM AN ASYNCHRONOUS EDGE (audit item 2, 10-22) ------
    # The arms above raise PUSH on a negedge -- ONE phase. A host's edge can
    # land anywhere in a cycle, so the low-nibble rise is walked 0..19 ns
    # after its negedge (+PHPS) and the lead is measured edge -> slot in ns.
    # The contract's 6th cycle was ARGUED to cover this; here it is measured.
    # (probe_reports/v2window_walk_prediction.txt)
    from concurrent.futures import ThreadPoolExecutor

    def walk_one(pk):
        p, k = pk
        o = run(sim_run.vvp([vvp, "+IMG=" + img, "+AT=%d" % at,
                             "+LEAD=%d" % k, "+PHPS=%d" % (p * 1000)],
                            images=[img])).stdout
        mt = re.search(r"V2WIN lead=\d+ taken=(\d)", o)
        mn = re.search(r"edge_to_slot_ns=(-?[\d.]+)", o)
        return p, k, (int(mt.group(1)) if mt else None), \
            (float(mn.group(1)) if mn else None)

    with ThreadPoolExecutor(3) as ex:
        pts = list(ex.map(walk_one, [(p, k) for p in range(PHASE_FLOOR)
                                     for k in LEADS]))
    walk_ok = all(t is not None and ns is not None for _p, _k, t, ns in pts)
    for p in range(PHASE_FLOOR):             # monotone in k at EVERY phase
        row = {k: t for pp, k, t, _ns in pts if pp == p}
        th = next((k for k in LEADS
                   if all(row[j] == 1 for j in LEADS if j >= k)), None)
        if th is None or any(row[j] != 0 for j in LEADS if j < th):
            walk_ok = False
            print("  *** phase +%d ns: not monotone in k: %s" % (p, row))
    missed = [ns for _p, _k, t, ns in pts if t == 0]
    taken_ns = sorted(ns for _p, _k, t, ns in pts if t == 1)
    worst_miss = max(missed) if missed else None
    need = min(n for n in taken_ns if all(m < n for m in missed)) \
        if taken_ns and missed else None
    print("  walked (PUSH rise 0..19 ns after its negedge, 20 phases x %d "
          "leads): largest edge->slot lead MISSED %s ns; every lead >= %s ns "
          "TAKEN" % (len(LEADS), worst_miss, need))
    if need is not None:
        print("    = %.2f cycles from an asynchronous edge, worst over phases "
              "(the contract asks 6 = 120 ns)" % (need / 20.0))
    six_ok = worst_miss is not None and worst_miss < 120.0
    print("  6 cycles (120 ns) from ANY edge phase always taken: %s"
          % ("ok" if six_ok else "*** NO"))
    ok = ok and walk_ok and six_ok
    if ok:
        print("V2 WINDOW: PASSED")
        return 0
    print("*** FAIL v2window")
    return 1


if __name__ == "__main__":
    sys.exit(main())
