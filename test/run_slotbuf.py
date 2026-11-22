"""run_slotbuf -- the slot buffer, piece 2 (Wilson 11-21): agent 2's `BufEng.stepB` in
pe_engine, its storage, capture filing, issue at capture, FCFS, below USB receive, and no
fetch past a branch -- each contract with its must-fire.

The checks are pe_engine's own sim-only assertions (`*** ASSERT pe_engine SLOT...`), which
every simulation runs and `sim_run.py judge` reads on every bench, so a clean build that
trips one is red in ANY gate. This runner supplies what the shipped images do not: the
contention each contract is about, and the planted case for each.

Four images on tb_pair (uio[3] is toggled by lane 1, and the ARM lanes wait on its rise):
  slotbuf_fcfs  two ARM lanes each behind a long word (the ARM is captured into the spare,
                its first slot fetch fills the buffer, the second waits for the load);
                lane 0 (USB receive's lane) wakes on the same edge and runs short words,
                so it is late exactly when the two ARM lanes unblock: two requests
                issuable at one scan, USB receive's branch 1 ahead of them, and another
                late lane's branch 1 behind them
  slotbuf_usb   slotbuf_fcfs with a USB receive on lane 0 (the earliest D_sched), reached
                only once lane 4 pulls pin GO low: before it lane 0 jumps back to its ARM by a
                taken BRANCH_BIT, so its branch 1 meets the slot with `usb_on` off (the
                slot outranks it) and, after the receive, with it set (the slot yields) -- K13.
                Only here does lane 0's branch 1 take the scan between two raises, so only
                here are two requests issuable at one scan (FCFS)
  slotbuf_npf   an ARM whose next word is a branch: the second fetch must never issue
  slotbuf_mask  a quiet port, so the round robin walks every lane each idle scan and lands
                on a lane in the cycle its buffered word loads
Vacuity: the clean build's `+SLOTSTAT` counts must show each situation happened.

P1 restated (Wilson 11-22, ruling 3) is clocked_conform's R4b, which lives in the clocked
benches, not tb_pair: a shipped ARM image (test/b3b_a_image.hex) on tb_trace, built as
gate_batch_equiv builds it. Clean: R4b silent and at least one slot fetch into a buffer (the
bench's R4 summary). Must-fire M_SLOT_FILE_NONE (a slot fetch bound for the buffer files
nothing): R4b's slot-fetch clause.

Must-fires (each RED on its image, by its assertion):
  M_SLOT_RAISE_LATE  the raise lands a cycle after the CAP cycle   SLOTRAISE (issue_at_capture)
  M_SLOT_LIFO        the youngest request served first             SLOTFCFS  (slot_fcfs_capture)
  M_SLOT_OVER_USB    the slot ahead of USB receive's branch 1      SLOTUSB   (slot_below_usb_rx;
                     on slotbuf_usb, after `usb_on`)
  M_SLOT_YIELD_UNGATED  the yield to lane 0 without `usb_on`     SLOTUSB   (K13: on slotbuf_fcfs,
                     a non-USB image, and on slotbuf_usb before the first receive)
  M_SLOT_BELOW_BR1   another lane's branch 1 ahead of the slot     SLOTUSB   (slot_below_usb_rx)
  M_SLOT_PAST_NPF    the requester ignores a held branch           SLOTNPF   (no_fetch_past_branch)
  M_SLOT_NOMASK      the round robin refills a buffered lane       SLOTMASK  (the mask; and
                     SLOTORD: the word after next overtakes the next)
  M_SLOT_BEFORE_PRIME  a slot issue before `primed`              SLOTPRIME (K12: lane 0's first
                     word is an ARM, captured during start-up)
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BENCH = "test/tb_pair.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_slotbuf"
PT = 3                        # the toggled uio pin
USB_PIN = 4                   # slotbuf_usb's receive samples this pin (its bits are not read)
GO_PIN, GO_AT = 4, 1000       # slotbuf_usb: lane 4 pulls GO low after GO_AT cycles; lane 0 then receives
NCYC = 8000
H = (I.PIN_NONE, 1, 40, 80, 120)          # pin, mode, t, dsched, dtol of a pinless lane
#: mutant -> (what it plants, its image, the assertion tag(s) that must report it)
MUTANTS = [
    ("M_SLOT_RAISE_LATE", "the raise a cycle after CAP", "fcfs", "SLOTRAISE"),
    ("M_SLOT_LIFO", "the youngest request first", "usb", "SLOTFCFS"),
    ("M_SLOT_OVER_USB", "the slot ahead of USB receive", "usb", "SLOTUSB"),
    ("M_SLOT_YIELD_UNGATED", "a yield with usb_on off", "fcfs", "SLOTUSB"),
    ("M_SLOT_YIELD_UNGATED", "a yield before the receive", "usb", "SLOTUSB"),
    ("M_SLOT_BELOW_BR1", "another lane's branch 1 first", "fcfs", "SLOTUSB"),
    ("M_SLOT_PAST_NPF", "a slot fetch past a branch", "npf", "SLOTNPF"),
    ("M_SLOT_NOMASK", "the refill mask removed", "mask", "SLOTMASK"),
    ("M_SLOT_BEFORE_PRIME", "a slot issue during start-up", "fcfs", "SLOTPRIME"),
]
#: the clean build's +SLOTSTAT counts each image must show (> 0): the situation it is for
#: (usbc / l0c: lane 0's branch 1 met an issuable slot request with `usb_on` set / clear)
#: (prereq: a request raised during start-up, held until `primed` -- K12)
VACUITY = {"fcfs": ("raise", "second", "tobuf", "load", "l0c", "br1c", "prereq"),
           "usb": ("raise", "second", "tobuf", "load", "multi", "l0c", "usbc"),
           "npf": ("raise", "npfblock"),
           "mask": ("raise", "tobuf", "load", "rrbuf")}


def build_image(lanes):
    base = I.ACT_BASE
    hdrs, prog = [], []
    for (pin, mode, t, ds, dt), acts in lanes:
        hdrs.append(I.hdr(pin, I.PIN_NONE, mode, t, 0, ds, dt, base))
        prog += acts
        base += len(acts) * I.ACT_BYTES
    return I.join_image(hdrs, prog)


def lvl(pin, v, d):
    return I.act(I.OP_LEVEL, pin, v, d)


def loop(d):
    return I.act(I.OP_REARM, 0, 1, d)


def toggler(d):
    return [lvl(PT, 1, d), lvl(PT, 0, d), loop(d)]


def image(name):
    if name in ("fcfs", "usb"):
        def armer(x):
            return ([lvl(I.PIN_NONE, 0, 50 + x), I.act_arm(PT, 1, 0)]
                    + [lvl(I.PIN_NONE, 0, 7) for _ in range(3)] + [loop(7)])
        run = [I.act_arm(PT, 1, 0)] + [lvl(I.PIN_NONE, 0, 1) for _ in range(8)]
        # slotbuf_usb: lane 0's branch 1 is the refill after its jump back to its ARM. While
        # pin GO reads 1 (the bench's open-drain pins idle high) that jump is a taken
        # BRANCH_BIT (word 0 = lane 0's ARM) and `usb_on` is off; once lane 4 pulls GO low,
        # lane 0 falls through to the receive, which sets it.
        if name == "usb":
            # (the 24-cycle word lands the jump among the ARM lanes' raises, as the loop's
            # longer path does after the receive)
            l0 = run + [lvl(I.PIN_NONE, 0, 24), I.act_branch_bit(GO_PIN, 1, 0, max(I.BR_W_MIN, 8)),
                        I.act_shiftin_usb(USB_PIN, 1, nbits=1), loop(1)]
            stress = ([lvl(I.PIN_NONE, 0, GO_AT), lvl(GO_PIN, 0, 9)]
                      + [lvl(I.PIN_NONE, 0, 9) for _ in range(4)] + [loop(9)])
        else:
            l0 = run + [loop(1)]
            stress = [lvl(I.PIN_NONE, 0, 9) for _ in range(5)] + [loop(9)]
        # a USB image's USB lane has strictly the earliest D_sched (pe_isa's rule), so its
        # branch 1 is the one the late-lane pick names when it is empty
        h0 = (I.PIN_NONE, 1, 40, 70, 120) if name == "usb" else H
        return build_image([(h0, l0), ((PT, 1, 40, 80, 120), toggler(150)),
                            (H, armer(0)), (H, armer(0)), (H, stress)])
    if name == "npf":
        def stress(d):
            return [lvl(I.PIN_NONE, 0, d) for _ in range(6)] + [loop(d)]
        # the branch target is a word of the whole program: lane 2's own ARM sits
        # after lanes 0 and 1's words (11-22: it was word 0, lane 0's code)
        l0, l1 = stress(20), toggler(60)
        arm2 = len(l0) + len(l1)
        a = ([I.act_arm(PT, 1, 0), I.act_branch_bit(PT, 1, arm2, max(I.BR_W_MIN, 8))]
             + [lvl(I.PIN_NONE, 0, 8) for _ in range(3)] + [loop(8)])
        return build_image([(H, l0), ((PT, 1, 40, 80, 120), l1),
                            (H, a), (H, stress(21)), (H, stress(22))])
    if name == "mask":
        a = ([lvl(I.PIN_NONE, 0, 34), I.act_arm(PT, 1, 0)]
             + [lvl(I.PIN_NONE, 0, 9) for _ in range(3)] + [loop(9)])
        idle = [lvl(I.PIN_NONE, 0, 900), loop(900)]
        return build_image([(H, idle), ((PT, 1, 40, 80, 120), toggler(101)),
                            (H, a), (H, idle), (H, idle)])
    raise ValueError(name)


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_pair"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def sim(vvp, img, stat=False):
    """(assertion tag -> count, the SLOTSTAT dict, the FLT line, ended)"""
    args = [vvp, "+IMG=%s" % img, "+NCYC=%d" % NCYC] + (["+SLOTSTAT"] if stat else [])
    r = run(sim_run.vvp(args, images=[img]))
    out = r.stdout + r.stderr
    tags = {}
    for m in re.finditer(r"^\s*\*\*\* ASSERT pe_engine (\w+):", out, re.M):
        tags[m.group(1)] = tags.get(m.group(1), 0) + 1
    st = re.search(r"^SLOTSTAT (.*)$", out, re.M)
    sd = {k: int(v) for k, v in (kv.split("=") for kv in st.group(1).split())} if st else {}
    flt = re.search(r"^FLT .*$", out, re.M)
    return tags, sd, (flt.group(0) if flt else "no FLT line"), ("END" in out)


P1_IMG = "test/b3b_a_image.hex"


def p1_run(vvp, tmp):
    """the image on tb_trace with gate_batch_equiv's arguments; the whole log"""
    import gate_corpus_trace as G
    from pe_isa import STORE_BYTES
    img = os.path.join(ROOT, P1_IMG)
    tr = os.path.join(tmp, "p1_trace.txt")
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img, "+NBYTES=%d" % STORE_BYTES, "+PEER=none",
                         "+OUT=%s" % tr, "+NCYC=8000"] + G.feed_args(img), images=[img]))
    return r.stdout + r.stderr


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("SLOTBUF -- the slot buffer, piece 2: BufEng.stepB's fetch path on the RTL")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_slotbuf_")
    imgs = {}
    for n in VACUITY:
        p = os.path.join(tmp, "slotbuf_%s.hex" % n)
        I.write_image(p, image(n))
        sim_run.scratch_image(GEN, p)
        imgs[n] = p
    vvp = os.path.join(tmp, "slotbuf.vvp")
    build(vvp)
    print("\n  clean build: no SLOT assertion, no fault, and each image's situation happens")
    for n, p in imgs.items():
        tags, sd, flt, ended = sim(vvp, p, stat=True)
        miss = [k for k in VACUITY[n] if sd.get(k, 0) <= 0]
        print("    %-14s %s  %s  %s" % (n, " ".join("%s=%d" % kv for kv in sd.items()), flt,
                                       ("asserts %s" % tags) if tags else "no asserts"))
        if tags:
            probs.append("%s: the clean build tripped %s" % (n, tags))
        if flt != "FLT cfg=0 ovr=0" or not ended:
            probs.append("%s: %s%s" % (n, flt, "" if ended else ", the bench did not finish"))
        if miss:
            probs.append("%s is vacuous: %s never happened" % (n, ", ".join(miss)))
    print("\n  must-fires")
    built = set()
    for d, what, n, tag in MUTANTS:
        mv = os.path.join(tmp, "slotbuf_%s.vvp" % d)
        if d not in built:
            build(mv, [d])
            built.add(d)
        tags, _sd, _f, _e = sim(mv, imgs[n])
        red = tags.get(tag, 0) > 0
        print("    %-20s %-30s %s" % (d, what, ("RED on %s: %s" % (n, tags)) if red
                                      else "*** SURVIVED on %s (%s)" % (n, tags or "none")))
        if not red:
            probs.append("%s survived on %s (no %s)" % (d, n, tag))
    print("\n  P1 (clocked_conform R4b) on tb_trace, %s" % P1_IMG)
    import gate_batch_equiv as GB
    pv = os.path.join(tmp, "p1_clean.vvp")
    GB.build(pv, ROOT)
    log = p1_run(pv, tmp)
    m = re.search(r"clocked_conform\[R4\]: ok -- .*?(\d+) slot fetch\(es\) \((\d+) into a buffer\)", log)
    r4b = re.findall(r"^\s*\*\*\* FAIL clocked_conform\[R4b\].*$", log, re.M)
    print("    clean            %s  %s" % (m.group(0) if m else "*** no R4 summary line",
                                          ("R4b x%d" % len(r4b)) if r4b else "R4b silent"))
    if r4b:
        probs.append("P1: the clean build trips R4b: %s" % r4b[0][:160])
    if not m or int(m.group(2)) <= 0:
        probs.append("P1 is vacuous on %s: no slot fetch into a buffer" % P1_IMG)
    mv = os.path.join(tmp, "p1_M_SLOT_FILE_NONE.vvp")
    GB.build(mv, ROOT, defines=("M_SLOT_FILE_NONE",))
    log = p1_run(mv, tmp)
    red = re.search(r"^\s*\*\*\* FAIL clocked_conform\[R4b\]: a slot fetch completed", log, re.M)
    print("    %-20s %-30s %s" % ("M_SLOT_FILE_NONE", "a slot fetch filing nothing",
                                  "RED (R4b slot-fetch clause)" if red else "*** SURVIVED"))
    if not red:
        probs.append("M_SLOT_FILE_NONE survived on %s (no R4b slot-fetch clause)" % P1_IMG)
    print()
    for x in probs:
        print("  *** %s" % x)
    print("=" * 78)
    print("  GATE slotbuf: %s" % ("PASSED" if not probs else "FAILED"))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
