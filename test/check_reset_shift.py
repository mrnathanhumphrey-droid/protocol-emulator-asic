"""RESET-SHIFT -- the reset-network halt moves recorded traces by exactly +1.

The reset-network halt (Wilson) takes the engine's reset from one flop in the
top, `eng_rst_n <= eng_run`, so the engine leaves reset ONE CYCLE LATER after
the PROG release than the mux halt let it. Every record that counts time from
that release moves; every record that counts from a later engine event does
not. Re-recording is allowed only after this script has shown, on FULL
TRACES, that nothing else moved.

⛔⛔ FULL TRACES, NOT DIGESTS (Wilson). A digest cannot be shifted, so each
bench is re-run at BOTH revisions in FRESH DETACHED WORKTREES with a dump-only
root module compiled beside the unchanged bench. It prints, every cycle from
the reset release (sampled on the FALLING edge, so the bench and the dump
cannot race), the output pins and the engine's dispatch state:

    T <a> <uo_out & 8F> <uio_out> <uio_oe> <st> <cur> <cur_act> <primed>
      <PROG> <eng_run> <uo_out[6:4]>

THE +1 RULE, exact and over every cycle, each column from its own RTL source:
  * PROG (bench) and the top's `eng_run` (the PROG synchroniser): NOT MOVED.
  * the ENGINE columns, with r = the first cycle `eng_run` is high:
        new[0..r] == old[0..r]   and   new[a + 1] == old[a] for every a >= r
    up to and INCLUDING old's last cycle (the new run is one cycle longer).
  * the host view uo_out[6:4] (the serialiser, on rst_n_s): the same, from
    q = its first idle cycle at or after r -- a frame it began before the
    engine ran keeps its time; every frame after q is engine-started.
⛔ The first draft took the PROG release as the start for every column and
went red on all 12 images -- correctly: uo_out[6:4] and the cycles between
the release and `eng_run` are not the engine's. Measured, then derived from
`project.v` (uo_q = {0, ser_v, ser_s, ser_d, proto_out}), never fitted.

THE EXPECTED SHIFT IS DERIVED PER TRACE, NOT ASSUMED -- from its timing base:
    counted from power-on / the PROG release   -> +1 (later)
    counted from `primed`                       -> byte-identical
and a trace in the identical class that shifts is RED, as is any "other".

⛔⛔ RECORDED MISCLASSIFICATION, FOUND BY THIS CHECKER (2026-10-15). The
first version put `model/a2/sweep_w.json` in the IDENTICAL class "because
every arm is measured after a warm-up". That reasoning was wrong, and this
script's own sweep comparison went red on it: `tb_w.v` opens the window at
`hdr_done + WARMUP` (line 126), which moves +1 with the engine, and closes it
at the FIXED `NCYC`, so the window is one cycle SHORTER -- `warm_from` +1 on
all 80 arms and -1 on the counts that lost a final cycle (`scan`, `consumed`,
`decisions`, `viol_cyc`, all COUNTS: `tb_w.v` 221 adds one per stalled cycle).
RECLASSIFIED to +1, with a prediction that can still fail, written here
BEFORE the run (Wilson): the new revision's sweep at NCYC + 1 (a one-landmark
run-time patch of `run_w_sweep.py` in a scratch worktree) matches the old
record in EVERY field except exactly two -- `warm_from` +1 on every arm, and
`_src_sha256` different.

RELOAD: the +1 rule is about the engine's release from `eng_run`, which a
reload exercises too. Each trace's PROG column says whether it passed through
a reload (a PROG rise after the first release); if none did, the summary says
so in one line rather than letting the rule read as tested on reload.

MUST-FIRES (planted on copies of a real old trace; each must go RED):
    MF1  a 2-cycle shift
    MF2  a -1 shift (one cycle EARLIER)
    MF3  a +1 shift on a trace that must be byte-identical
    MF4  a correct +1 with one bit flipped afterwards
    MF5  the serial view: a frame begun BEFORE the engine ran, shifted +1
    MF6  the serial view: the engine-started frames left unshifted
and the serial stream is decoded per trace: frame COUNTS and payloads must
match old vs new (they are printed). HOST_INTERFACE: the cycles from PROG
sampled low to `eng_run` and to the engine's first action are measured on
every trace and must be old + 1, uniformly -- the latency line the doc takes.

Usage: python test/check_reset_shift.py --old REV [--new REV]
                                        --sweep OLD.json NEW.json
       (the two `run_w_sweep.py --full` records, each run at its revision)
Verdict: `RESET-SHIFT: PASSED`, after the summary line
         `RESET-SHIFT: N identical, M shifted +1, 0 other`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool          # noqa: E402  ruling V
from run_lockstep import IMAGES, NCYC as LOCK_NCYC   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
SMOKE_NCYC = 4000                            # tb_smoke's default = the record
REASON_ABS = ("counted from the PROG release: the engine leaves reset one "
              "flop later (eng_rst_n <= eng_run)")
REASON_REL = "counted from `primed`, which itself moved +1"

DUMP = """
module shift_dump;
  integer a = 0;
  always @(negedge `TB.clk) if (`TB.rst_n === 1'b1) begin
    $display("T %0d %h %h %h %0d %0d %h %b %b %b %h", a,
             `TB.uo_out & 8'h8F, `TB.uio_out, `TB.uio_oe, `TB.dut.u_eng.st,
             `TB.dut.u_eng.cur, `TB.dut.u_eng.cur_act, `TB.dut.u_eng.primed,
             `TB.ui_in[7], `TB.dut.eng_run, `TB.uo_out[6:4]);
    a = a + 1;
  end
endmodule
"""
ENG = slice(0, 7)       # uo&8F uio oe st cur cur_act primed
PROG = 7                # bench-driven                    -> must not move
RUN = 8                 # top's eng_run (both revisions)  -> must not move
FIXED = (PROG, RUN)
HOST = 9                # uo_out[6:4] = {ser_v, ser_s, ser_d}: the readback /
                        # RX serialiser. It runs on rst_n_s, NOT the engine
                        # reset, so a frame it started before the engine ran
                        # keeps its time; once it goes idle after the start,
                        # every later frame is started by the ENGINE (a sticky
                        # status flag, an RX payload) -> +1 from that idle cycle


def git(args, cwd=ROOT):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("*** git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def prepare(rev, scratch, label):
    """fresh detached worktree at rev, images generated -> its path."""
    wt = os.path.join(scratch, label)
    git(["worktree", "add", "--detach", wt, rev])
    for r in (["test/make_smoke_image.py", "--all"], ["test/corpus.py"]):
        p = subprocess.run([sys.executable] + r, cwd=wt, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise SystemExit("*** %s at %s failed:\n%s" % (r[0], rev,
                                                         p.stdout[-400:]))
    return wt


def build(wt, tb, scratch, label):
    out = os.path.join(scratch, "%s_%s.vvp" % (tb, label))
    dump = os.path.join(scratch, "shift_dump.v")
    r = subprocess.run([tool("iverilog"), "-g2012", "-DTB=" + tb, "-o", out,
                        "-s", tb, "-s", "shift_dump", "test/%s.v" % tb]
                       + SRCS + [dump], cwd=wt, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("*** build %s at %s:\n%s" % (tb, label,
                                                    (r.stdout + r.stderr)[-600:]))
    return out


def sim(wt, vvp, args):
    """-> (T rows as tuples of strings, D/P stream lines, raw stdout)."""
    r = subprocess.run([tool("vvp"), vvp] + args, cwd=wt, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    t, dp = [], []
    for l in r.stdout.splitlines():
        if l.startswith("T "):
            t.append(tuple(l.split()[2:]))
        elif l[:2] in ("D ", "P "):
            dp.append(l)
    return t, dp, r.stdout


def release(t):
    """p = the last cycle PROG is high (the bench's release of the store)."""
    hi = [a for a, row in enumerate(t) if row[PROG] == "1"]
    return hi[-1] if hi else None


def reloads(t, p):
    """PROG rises after the first release -- a reload in this trace."""
    return sum(1 for a in range(p + 1, len(t))
               if t[a][PROG] == "1" and t[a - 1][PROG] == "0")


def start(t):
    """r = the first cycle `eng_run` is high after the PROG release: the old
    engine runs from the next edge, the new one a cycle after that."""
    p = release(t)
    if p is None:
        return None
    return next((a for a in range(p + 1, len(t)) if t[a][RUN] == "1"), None)


def ser_idle(t, r):
    """q = the first cycle at or after the engine start with ser_v low."""
    return next((a for a in range(r, len(t))
                 if (int(t[a][HOST], 16) >> 2) & 1 == 0), len(t) - 1)


def _insert(col, at, k):
    if k >= 0:
        return col[:at + 1] + [col[at]] * k + col[at + 1:]
    return col[:at + 1] + col[at + 1 - k:] + [col[-1]] * (-k)


def frames(t):
    """the serial stream decoded: (start cycle, bits MSB-last-shifted) per
    frame -- ser_v high brackets a frame, a ser_s rise samples ser_d."""
    out, cur, st, pv, ps = [], [], None, 0, 0
    for a, row in enumerate(t):
        # X before the reset synchroniser clears it: idle here; the per-cycle
        # rule still compares those cycles as text, so an X cannot hide
        h = int(row[HOST], 16) if re.fullmatch(r"[0-9a-f]+", row[HOST]) else 0
        v, s, d = (h >> 2) & 1, (h >> 1) & 1, h & 1
        if v and not pv:
            cur, st = [], a
        if v and s and not ps:
            cur.append(str(d))
        if pv and not v:
            out.append((st, "".join(cur)))
        pv, ps = v, s
    return out


def plant(old, k, host_at=None, host_k=None):
    """old with k cycles inserted (k < 0: removed): the ENGINE columns at the
    start, the host view at the serialiser's first idle cycle after it (or
    `host_at` / `host_k`, for the must-fires); the FIXED columns stay exactly
    where they were (padded with the last row)."""
    r = start(old)
    q = ser_idle(old, r) if host_at is None else host_at
    eng = _insert([row[ENG] for row in old], r, k)
    host = _insert([row[HOST] for row in old], q, k if host_k is None
                   else host_k)
    n = max(len(eng), len(host))
    eng += [eng[-1]] * (n - len(eng))
    host += [host[-1]] * (n - len(host))
    fixed = [tuple(old[min(a, len(old) - 1)][c] for c in FIXED)
             for a in range(len(eng))]
    return [e + f + (h,) for e, f, h in zip(eng, fixed, host)]


def check_shift(old, new):
    """the +1 rule, over every cycle of old -> None or the reason."""
    r = start(old)
    if r is None:
        return "old trace has no engine start (eng_run never rose)"
    if start(new) != r:
        return "eng_run rose at %s, not %s: the bench is not the same" % (
            start(new), r)
    if len(new) < len(old) + 1:
        return "new trace %d cycles, needs %d to cover old's last cycle" % (
            len(new), len(old) + 1)
    want = plant(old, 1)
    q = ser_idle(old, r)
    for a in range(len(old)):
        for c in FIXED:
            if new[a][c] != old[a][c]:
                return "cycle %d: %s moved" % (a, "PROG" if c == PROG
                                               else "eng_run")
    for a in range(len(want)):
        if new[a][ENG] != want[a][ENG]:
            return "cycle %d: new %s != expected %s (%s the start at %d)" % (
                a, " ".join(new[a][ENG]), " ".join(want[a][ENG]),
                "before" if a <= r else "after", r)
        if new[a][HOST] != want[a][HOST]:
            return "cycle %d: host view new %s != expected %s (%s the " \
                   "serialiser's idle at %d)" % (a, new[a][HOST], want[a][HOST],
                                                 "before" if a <= q else "after", q)
    return None


def check_identical(old, new):
    if old == new:
        return None
    n = min(len(old), len(new))
    i = next((i for i in range(n) if old[i] != new[i]), n)
    return "first difference at line %d of %d/%d" % (i, len(old), len(new))


def smoke_counts(out):
    keys = {"jobs": r"jobs dispatched\s*:\s*(\d+)",
            "svc_cycles": r"total service cycles\s*:\s*(\d+)",
            "hdr_cyc": r"hdr_done at cycle\s*:\s*(-?\d+)",
            "cycles": r"cycles observed\s*:\s*(\d+)"}
    got = {}
    for k, rx in keys.items():
        m = re.search(rx, out)
        got[k] = int(m.group(1)) if m else None
    return got


def sweep_check(paths, wts):
    """-> (ok, reason). Each record must carry ITS revision's RTL hash."""
    recs = []
    for p, wt in zip(paths, wts):
        with open(p, encoding="utf-8") as fh:
            rec = json.load(fh)
        for s, h in rec["_src_sha256"].items():
            with open(os.path.join(wt, "src", s), "rb") as fh:
                live = hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()
            if live != h:
                return False, "%s was not recorded at its revision (%s)" % (p, s)
        recs.append(rec)
    o, n = recs
    if o["_src_sha256"] == n["_src_sha256"]:
        return False, "both records carry the same RTL hash -- nothing compared"
    head = [k for k in set(o) | set(n) if k not in ("_src_sha256", "arms")
            and o.get(k) != n.get(k)]
    if head:
        return False, "record header differs: %s" % head
    if set(o["arms"]) != set(n["arms"]):
        return False, "arm sets differ"
    for name in sorted(o["arms"]):
        a, b = o["arms"][name], json.loads(json.dumps(n["arms"][name]))
        if b["issue"]["warm_from"] != a["issue"]["warm_from"] + 1:
            return False, "%s: warm_from %s -> %s, predicted +1" % (
                name, a["issue"]["warm_from"], b["issue"]["warm_from"])
        b["issue"]["warm_from"] -= 1
        if a != b:
            f = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
            return False, "%s differs beyond warm_from: %s (other)" % (name, f)
    return True, ("%d arms: every field identical except warm_from +1 on "
                  "every arm, and _src_sha256 different" % len(o["arms"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="dev")
    ap.add_argument("--new", default="HEAD")
    ap.add_argument("--sweep", nargs=2, metavar=("OLD_JSON", "NEW_NCYC1_JSON"),
                    help="old's record, and the new revision's record run at "
                         "NCYC + 1")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    banner("iverilog", "vvp")
    old_rev, new_rev = git(["rev-parse", "--short", a.old]), git(
        ["rev-parse", "--short", a.new])
    print()
    print("=" * 78)
    print("RESET-SHIFT -- full traces, %s (old) vs %s (new)" % (old_rev, new_rev))
    print("=" * 78)
    scratch = tempfile.mkdtemp(prefix="pe_shift_")
    with open(os.path.join(scratch, "shift_dump.v"), "w") as fh:
        fh.write(DUMP)
    wts = []
    rows, red = [], []          # rows: (record, class, verdict, note)
    try:
        wo = prepare(old_rev, scratch, "old"); wts.append(wo)
        wn = prepare(new_rev, scratch, "new"); wts.append(wn)
        jobs = []
        for side, wt in (("old", wo), ("new", wn)):
            jobs.append((side, "tb_smoke", "smoke", wt,
                         ["+IMG=test/smoke_image.hex", "+NCYC=%d" % (
                             SMOKE_NCYC + (side == "new"))]))
            for img in IMAGES:
                with open(os.path.join(wt, "test", img)) as fh:
                    nb = len(fh.read().split())
                jobs.append((side, "tb_lock", img, wt,
                             ["+IMG=test/%s" % img, "+NBYTES=%d" % nb,
                              "+NCYC=%d" % LOCK_NCYC]))
        jobs.append(("new", "tb_smoke", "smoke@record", wn,
                     ["+IMG=test/smoke_image.hex", "+NCYC=%d" % SMOKE_NCYC]))
        vvp = {(s, tb): build(wt, tb, scratch, s) for s, wt in
               (("old", wo), ("new", wn)) for tb in ("tb_smoke", "tb_lock")}
        with ThreadPoolExecutor(6) as ex:
            res = dict(zip([(s, tb, n) for s, tb, n, _w, _a in jobs],
                           ex.map(lambda j: sim(j[3], vvp[(j[0], j[1])], j[4]),
                                  jobs)))

        print("\n  %-30s %-10s %-8s %-9s %s" % ("trace", "expected", "reload",
                                               "frames", "verdict"))
        reload_seen, lat = 0, []
        traces = [("tb_smoke", "smoke")] + [("tb_lock", i) for i in IMAGES]
        for tb, name in traces:
            ot, odp, _ = res[("old", tb, name)]
            nt, ndp, _ = res[("new", tb, name)]
            p = release(ot)
            nrl = reloads(ot, p) if p is not None else 0
            reload_seen += nrl
            why = check_shift(ot, nt)
            # the serial stream, decoded: same frames, same payloads
            fo, fn = frames(ot), frames(nt)
            nfr = "%d/%d" % (len(fo), len(fn))
            if why is None and [f[1] for f in fo] != [f[1] for f in fn][:len(fo)]:
                why = "serial frames differ in payload (%s)" % nfr
            elif why is None and len(fn) != len(fo):
                why = "serial frame count %s" % nfr
            # HOST_INTERFACE: PROG low -> eng_run -> the engine's first action
            r = start(ot)
            fa = lambda t: next((x for x in range(r + 1, len(t))
                                 if t[x][ENG] != t[r][ENG]), None)
            lat.append((name, r - p, fa(ot) - p if fa(ot) else None,
                        fa(nt) - p if fa(nt) else None))
            label = "%s/%s abs" % (tb, name)
            print("  %-30s %-10s %-8s %-9s %s" % (label, "+1", nrl, nfr,
                                             "ok" if why is None else "*** " + why))
            rows.append((label, "+1", why, REASON_ABS))
            if tb == "tb_lock":
                why = check_identical(odp, ndp)
                label = "%s/%s from primed" % (tb, name)
                print("  %-30s %-10s %-8s %-9s %s" % (label, "identical", "-",
                                                 "-", "ok" if why is None else "*** " + why))
                rows.append((label, "identical", why, REASON_REL))

        # HOST_INTERFACE: the start-up latency, measured on every trace
        print("\n  --- HOST_INTERFACE: PROG low (last high cycle) -> engine ---")
        ks = {(k, x, y) for _n, k, x, y in lat}
        for k, x, y in sorted(ks, key=str):
            names = [n for n, kk, xx, yy in lat if (kk, xx, yy) == (k, x, y)]
            print("    eng_run after %s cycle(s); engine's first action: old %s, "
                  "new %s cycles  (%d trace(s))" % (k, x, y, len(names)))
        if any(x is None or y != x + 1 for _n, _k, x, y in lat):
            red.append("start-up latency is not old + 1 on every trace")
        elif len({k for _n, k, _x, _y in lat}) == 1:
            # the first VISIBLE action follows the header load, which is
            # program-dependent -- so the uniform claim is the +1, not a number
            print("    HOST_INTERFACE latency line: PROG sampled low -> eng_run "
                  "%d cycles (unchanged); the engine then starts ONE cycle "
                  "later than before -- its first visible action +1 on all "
                  "%d traces (%d..%d -> %d..%d, program-dependent)" % (
                      lat[0][1], len(lat), min(x for _n, _k, x, _y in lat),
                      max(x for _n, _k, x, _y in lat),
                      min(y for _n, _k, _x, y in lat),
                      max(y for _n, _k, _x, y in lat)))
        else:
            red.append("PROG -> eng_run is not the same on every trace")

        # cj_measured.txt: the one-cycle-longer run must reproduce old's counts
        print("\n  --- test/cj_measured.txt (tb_smoke counters, %d-cycle window) ---"
              % SMOKE_NCYC)
        oc = smoke_counts(res[("old", "tb_smoke", "smoke")][2])
        n1 = smoke_counts(res[("new", "tb_smoke", "smoke")][2])
        nr = smoke_counts(res[("new", "tb_smoke", "smoke@record")][2])
        print("    old @%d     : %s" % (SMOKE_NCYC, oc))
        print("    new @%d     : %s" % (SMOKE_NCYC + 1, n1))
        print("    new @%d     : %s   <- what the re-record writes" % (
            SMOKE_NCYC, nr))
        why = None
        if None in list(oc.values()) + list(n1.values()) + list(nr.values()):
            why = "a counter was not printed"
        elif (n1["jobs"], n1["svc_cycles"]) != (oc["jobs"], oc["svc_cycles"]) \
                or n1["hdr_cyc"] != oc["hdr_cyc"] + 1:
            why = "the +1 run does not reproduce old's counts (other)"
        else:
            # what new's extra window cycle (4001) holds = old's last one
            dj, ds = n1["jobs"] - nr["jobs"], n1["svc_cycles"] - nr["svc_cycles"]
            print("    new's window cycle %d (old's last, one cycle later) "
                  "carries: jobs %+d, svc_cycles %+d" % (SMOKE_NCYC + 1, dj, ds))
            if nr["hdr_cyc"] != oc["hdr_cyc"] + 1 or dj not in (0, 1) \
                    or ds not in (0, 1):
                why = "re-record values are not old's shifted by one cycle"
        print("    %s" % ("ok -- every count is old's, one cycle later"
                          if why is None else "*** " + why))
        rows.append(("test/cj_measured.txt", "+1", why,
                     "tb_smoke's window starts at the PROG release"))

        # sweep_w.json
        print("\n  --- model/a2/sweep_w.json (window (hdr_done + WARMUP, NCYC]; "
              "new run at NCYC + 1) ---")
        if not a.sweep:
            why = "no --sweep records supplied -- NOT CHECKED"
        else:
            ok, msg = sweep_check(a.sweep, [wo, wn])
            why = None if ok else msg
            print("    %s" % msg)
        rows.append(("model/a2/sweep_w.json", "+1", why,
                     "window opens at hdr_done + WARMUP, closes at a fixed "
                     "NCYC (RECLASSIFIED from identical -- see the docstring)"))

        # must-fires, on copies of a real old trace
        print("\n  --- must-fires (planted on copies of real traces) ---")
        ot = res[("old", "tb_lock", "smoke_image.hex")][0]
        odp = res[("old", "tb_lock", "smoke_image.hex")][1]
        good = plant(ot, 1)
        if check_shift(ot, good) is not None:
            red.append("the planting harness itself is wrong: %s"
                       % check_shift(ot, good))
        two = plant(ot, 2)
        minus = plant(ot, -1) + [ot[-1]] * 2     # long enough to be compared
        flip = list(good)
        r = start(ot)
        f = r + 3 * (len(good) - r) // 4
        r0 = flip[f]
        flip[f] = ("%02x" % (int(r0[0], 16) ^ 1),) + r0[1:]
        rel_plus = [re.sub(r"^([DP]) (\d+)", lambda m: "%s %d" % (
            m.group(1), int(m.group(2)) + 1), l) for l in odp]
        # the serial view's own two: on an image that sends frames on both
        # sides of the engine start (the smoke image sends none after it)
        ht = res[("old", "tb_lock", "half_image.hex")][0]
        hr = start(ht)
        hq = ser_idle(ht, hr)
        pre = [f for f in frames(ht) if f[0] < hr]
        post = [f for f in frames(ht) if f[0] > hq]
        if not pre or not post:
            red.append("half_image has no frame on one side of the start -- "
                       "MF5/MF6 cannot be planted")
            mf5 = mf6 = None
        else:
            # MF5: the last PRE-engine frame moved +1 (inserted before it)
            mf5 = check_shift(ht, plant(ht, 1, host_at=pre[-1][0] - 1))
            # MF6: the post-engine frames left where they were
            mf6 = check_shift(ht, plant(ht, 1, host_k=0))
        for name, why in (
                ("MF5 a pre-engine frame shifted +1", mf5),
                ("MF6 post-engine frames unshifted", mf6),
                ("MF1 a 2-cycle shift", check_shift(ot, two)),
                ("MF2 a -1 shift (earlier)", check_shift(ot, minus)),
                ("MF3 +1 on a byte-identical trace", check_identical(odp, rel_plus)),
                ("MF4 correct +1, one bit flipped later", check_shift(ot, flip))):
            print("    %-40s %s" % (name, "red ok -- " + why if why else
                                    "*** STAYED GREEN"))
            if not why:
                red.append("%s stayed green" % name)
    finally:
        if not a.keep:
            for w in wts:
                subprocess.run(["git", "worktree", "remove", "--force", w],
                               cwd=ROOT, capture_output=True)
            shutil.rmtree(scratch, ignore_errors=True)

    ident = [r for r in rows if r[1] == "identical" and r[2] is None]
    shifted = [r for r in rows if r[1] == "+1" and r[2] is None]
    other = [r for r in rows if r[2] is not None]
    print()
    if reload_seen == 0:
        print("  reload path: not exercised by any recorded trace; covered by "
              "tb_reload")
    else:
        print("  reload path: %d reload(s) in the recorded traces, checked "
              "under the +1 rule above" % reload_seen)
    print("  shifted +1 because: %s" % REASON_ABS)
    print("  identical because : %s" % REASON_REL)
    for r in other:
        print("  *** OTHER: %s (expected %s): %s" % (r[0], r[1], r[2]))
    for r in red:
        print("  *** %s" % r)
    print()
    print("RESET-SHIFT: %d identical, %d shifted +1, %d other"
          % (len(ident), len(shifted), len(other)))
    ok = not other and not red
    print("RESET-SHIFT: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
