"""LN1 -- the Lean replay gate: JLane.step against the RTL, on every push.

Wilson's LN1: "re-run the Lean trace replay (step vs RTL) on every RTL change;
divergence = red". Requirements (Lean agent, relayed by Nathan 2026-10-10):

  * EXPORT FROM THE COMMIT UNDER TEST. Every trace is simulated here from the
    checked-out RTL into a fresh directory; no stored CSV is ever replayed, so
    an RTL change cannot hide behind an old trace.
  * EVERY ARM HAS A PINNED SIGNATURE, failures included. A must-fire counts
    only if it fails for its EXPECTED reason (M_BUF_SWAP: sel0 at row 2 -> 3;
    M_PFETCH_NOWAIT: pst at row 5 -> 6; M_TF1_LATE: not_ready > 0 and
    wc_viol > 0). A parse error or a crashed export is not a kill.
  * THE SCOPE DECISION IS PINNED TOO. The 10 lockstep images that leave scope
    at row 0 must still do so, with the same row-0 `oos` value and the same
    start report; the other two images must stay in scope exactly as long.
  * THE PROOFS, NOT ONLY THE REPLAY: after `lake build`, `#print axioms` on
    dstar, dstar29 and dstar39 must say exactly [propext, Quot.sound] -- a
    stray `sorry` (sorryAx) or `native_decide` (Lean.ofReduceBool) is red.

⚠ The row-0 `oos` of the 10 images is 4 = BIT 2 (value 4: a live lane's head is
a chaining re-arm, widened at OOS GO), NOT bit 4 (value 16: an armed lane).
The relayed spec said "oos bit 4"; measured on 985c42a it is value 4. The gate
pins the measured value.

Usage:  python ci/ln1_replay.py [--rows N] [--out DIR]
  --rows  rows per trace (default 20000: every push; 200000 = the full run)
  --out   parent directory (default probe_ln1/); each run writes a NEW
          subdirectory <rtl>-<rows>-<time>, so no earlier trace is reused.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "test"))
sys.path.insert(0, os.path.join(ROOT, "ci"))
import run_w_sweep as w                                   # noqa: E402
from run_lockstep import IMAGES                           # noqa: E402
from toolchain import banner, tool, PINNED_WSL_VERILATOR  # noqa: E402
import sim_run                                            # noqa: E402

LEAN = os.path.join(ROOT, "lean", "JLane")
THEOREMS = ["JLane.dstar", "JLane.dstar29", "JLane.dstar39"]
AXIOMS_OK = "[propext, Quot.sound]"

# The 56 synthetic five-lane arms of run_w_sweep --full at d = 20..60 (the
# d = 19 family is below D* and not in the spec).
FAMILIES = {"u": lambda d: (d,) * 5,
            "m": lambda d: (d, d + 1, d + 2, d + 3, d + 4),
            "mb": lambda d: (d, d, d, d, d + 4),
            "mc": lambda d: (d, d + 4, d, d + 4, d),
            "adv": lambda d: (d, d, d, d, 100),
            "advk": lambda d: (d, d, d, d, 1000),
            "drift": lambda d: (d, d + 1, d + 2, d + 3, 100),
            "driftk": lambda d: (d, d + 1, d + 2, d + 3, 1000)}
DS = (20, 21, 22, 25, 30, 40, 60)

# Images that leave scope at row 0: (row-0 oos value, start report).
IMG_OOS0 = {
    "smoke_image": (4, "lane2-not-full lane3-not-full lane4-not-full"),
    "stress_image": (4, "lane2-not-full lane3-not-full lane4-not-full"),
    "half_image": (4, "lane2-not-full lane3-not-full lane4-not-full"),
    "census_image": (4, "lane2-not-full lane3-not-full lane4-not-full"),
    "corpus_i2c": (4, "lane1-not-full lane2-not-full lane3-not-full lane4-not-full"),
    "i2caddr_image": (4, "lane1-not-full lane2-not-full lane3-not-full lane4-not-full"),
    "i2cframe_image": (4, "lane1-not-full lane2-not-full lane3-not-full lane4-not-full"),
    "rxfast_image": (4, "lane1-not-full lane2-not-full lane3-not-full lane4-not-full"),
    "ckod_image": (4, "lane4-not-full"),
    "ckread_image": (4, "lane1-not-full lane2-not-full lane3-not-full lane4-not-full"),
}
# Images replayed in scope until the first out-of-scope row: (oos_at).
IMG_INSCOPE = {"ckfive_image": 1, "ckheavy_image": 7}

MF_MISMATCH = {
    "MF_bufswap_m20": "row 2 -> 3: sel0: model true, rtl false",
    "MF_nowait_m20": "row 5 -> 6: pst: model JLane.PState.wait, rtl JLane.PState.cap",
}

LINE = re.compile(
    r"^(ok|FAIL) .*?trace_(\S+)\.csv: fmt=(\S+) checked=(\d+) oos_at=(\S+) "
    r"mismatch=(.*) parse=(.*) not_ready=(\d+) wc_viol=(\d+) stalls=(\d+) "
    r"br1_issues=(\d+) start=(.*)$")
KEYS = ["status", "arm", "fmt", "checked", "oos_at", "mismatch", "parse",
        "not_ready", "wc_viol", "stalls", "br1", "start"]


def run(cmd, cwd=ROOT, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


BENCH = ["src/pe_engine.v", "src/pe_store.v", "src/project.v", "test/tb_w.v",
         "test/tr_mon.v", "test/ln1_vl.sh"]


def rtl_label(worktree):
    """The commit, or (--worktree, local only) commit + a content hash."""
    rtl = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    dirty = run(["git", "status", "--porcelain", "--"] + BENCH).stdout.strip()
    if not dirty:
        return rtl
    if not worktree:
        raise SystemExit("*** LN1: the RTL or the trace bench is dirty; the "
                         "rtl= label would lie. Commit first (or --worktree "
                         "for a labelled local run).\n" + dirty)
    import hashlib
    h = hashlib.sha256()
    for f in BENCH:
        h.update(open(os.path.join(ROOT, f), "rb").read().replace(b"\r\n", b"\n"))
    return "%s+worktree-%s" % (rtl, h.hexdigest()[:10])


def build(out, tag, defines):
    vvp = os.path.join(out, "tr_%s.vvp" % tag)
    r = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", "tb_w", "-s", "tr_mon"]
            + ["-D" + d for d in defines] + ["test/tb_w.v", "test/tr_mon.v"]
            + [os.path.join(ROOT, "src", s) for s in w.SRCS])
    if r.returncode != 0:
        raise SystemExit("*** LN1: build %s failed\n%s" % (tag, r.stdout + r.stderr))
    return vvp


def five(out, name, delays):
    import make_smoke_image as m
    from pe_isa import write_image
    p = os.path.join(out, "%s.hex" % name)
    write_image(p, m.build_five(list(delays)))
    return p


# ⚠ Two lockstep images are GITIGNORED (made by `make_smoke_image --all`), so a
# fresh checkout lacks them: built here into the run directory with the same
# builder calls as `--all`, never written into test/.
GENERATED = {"stress_image.hex": lambda m: m.build_stress(25, 31),
             "census_image.hex": lambda m: m.build_census()}


def image(out, name):
    if name not in GENERATED:
        return os.path.join(ROOT, "test", name)
    import make_smoke_image as m
    from pe_isa import write_image
    p = os.path.join(out, name)
    write_image(p, GENERATED[name](m))
    return p


def nbytes(hexp):
    with open(hexp, encoding="ascii") as fh:
        return len([t for t in fh.read().split() if not t.startswith("//")])


def vl_native():
    return os.name != "nt"


def vpath(p):
    full = os.path.abspath(p)
    if vl_native():
        return full
    drive, rest = os.path.splitdrive(full)
    return "/mnt/%s%s" % (drive[0].lower(), rest.replace("\\", "/"))


def export(out, rows, rtl):
    vvp = {"clean": build(out, "clean", []),
           "bufswap": build(out, "bufswap", ["M_BUF_SWAP"]),
           "tf1late": build(out, "tf1late", ["M_TF1_LATE"])}
    jobs = []
    for d in DS:
        for f, fn in FAMILIES.items():
            n = "%s%d" % (f, d)
            jobs.append((n, "clean", five(out, n, fn(d))))
    jobs += [("img_" + i[:-4], "clean", image(out, i)) for i in IMAGES]
    m20 = five(out, "m20", (20, 21, 22, 23, 24))
    jobs += [("MF_bufswap_m20", "bufswap", m20),
             ("MF_tf1late_m20", "tf1late", m20)]

    def one(j):
        name, tag, hexp = j
        img = os.path.relpath(hexp, ROOT).replace(os.sep, "/")
        trace = os.path.join(out, "trace_%s.csv" % name).replace(os.sep, "/")
        r = run(sim_run.vvp([vvp[tag], "+IMG=" + img, "+NBYTES=%d" % nbytes(hexp),
                             "+NCYC=%d" % (rows + 5000), "+WARMUP=0", "+TRACE=" + trace,
                             "+MAXROWS=%d" % rows, "+META=%s rtl=%s" % (name, rtl)],
                            images=[img]))
        return name, r.returncode

    with ThreadPoolExecutor(3) as ex:
        rcs = dict(ex.map(one, jobs))
    # Verilator arms: M_PFETCH_NOWAIT + its clean control
    sc = os.path.join(ROOT, "test", "ln1_vl.sh")
    args = [vpath(out), vpath(m20), str(rows), rtl]
    if vl_native():
        cmd = ["bash", sc] + args
    else:
        cmd = ["wsl.exe", "--", "env", "PE_VERILATOR=%s" % PINNED_WSL_VERILATOR,
               "bash", vpath(sc)] + args
    r = run(cmd)
    print(r.stdout.rstrip())
    rcs["VL"] = r.returncode
    return rcs


def check_axioms(out):
    """lake build, then #print axioms on each theorem -> list of problems."""
    lake = shutil.which("lake")
    if not lake:
        return ["lake is not on PATH -- the proofs cannot be checked (RED)"]
    r = run([lake, "build"], cwd=LEAN)
    if r.returncode != 0:
        return ["lake build failed:\n" + (r.stdout + r.stderr)[-3000:]]
    src = os.path.join(out, "Axioms.lean")
    with open(src, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("import JLane\n" + "".join("#print axioms %s\n" % t for t in THEOREMS))
    r = run([lake, "env", "lean", src], cwd=LEAN)
    text = r.stdout + r.stderr
    probs = [] if r.returncode == 0 else ["lean exited %d" % r.returncode]
    for t in THEOREMS:
        m = re.search(r"'%s' depends on axioms: (\[[^\]]*\])" % re.escape(t), text)
        got = m.group(1) if m else "(no axioms line)"
        print("  axioms %-15s %s" % (t, got))
        if got != AXIOMS_OK:
            probs.append("%s: axioms %s, expected exactly %s" % (t, got, AXIOMS_OK))
    if probs:
        probs.append("lean output:\n" + text[-2000:])
    return probs


def row0_oos(path):
    with open(path, encoding="ascii") as fh:
        fh.readline(), fh.readline()
        return int(fh.readline().split(",")[21])


def expected_arms():
    arms = ["%s%d" % (f, d) for d in DS for f in FAMILIES]
    arms += ["img_" + i[:-4] for i in IMAGES]
    arms += ["MF_bufswap_m20", "MF_tf1late_m20", "VL_m20", "MF_nowait_m20"]
    return arms


def judge(arm, r, rows, out):
    """Problems with one replay result against its pinned signature."""
    p = []

    def want(k, v):
        if r[k] != v:
            p.append("%s=%r, expected %r" % (k, r[k], v))

    want("fmt", "TR-2/40")
    want("parse", "none")
    zero = ("not_ready", "wc_viol", "stalls", "br1")
    if arm.startswith("img_") and arm[4:] in IMG_OOS0:
        oos, start = IMG_OOS0[arm[4:]]
        want("status", "FAIL"); want("oos_at", "0"); want("checked", "0")
        want("mismatch", "none"); want("start", start)
        for k in zero: want(k, "0")
        got = row0_oos(os.path.join(out, "trace_%s.csv" % arm))
        if got != oos:
            p.append("row-0 oos=%d, expected %d" % (got, oos))
    elif arm.startswith("img_") and arm[4:] in IMG_INSCOPE:
        k0 = str(IMG_INSCOPE[arm[4:]])
        want("status", "ok"); want("oos_at", k0); want("checked", k0)
        want("mismatch", "none"); want("start", "ok")
        for k in zero: want(k, "0")
    elif arm in MF_MISMATCH:
        want("status", "FAIL"); want("mismatch", MF_MISMATCH[arm])
        want("oos_at", "never"); want("start", "ok")
        for k in zero: want(k, "0")
    elif arm == "MF_tf1late_m20":
        want("status", "FAIL"); want("mismatch", "none"); want("oos_at", "never")
        want("start", "ok"); want("checked", str(rows - 1))
        for k in ("not_ready", "wc_viol"):
            if int(r[k]) <= 0:
                p.append("%s=%s, expected > 0" % (k, r[k]))
    else:   # the 56 synthetic arms and the Verilator clean control
        want("status", "ok"); want("oos_at", "never"); want("mismatch", "none")
        want("start", "ok"); want("checked", str(rows - 1))
        for k in zero: want(k, "0")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--out", default=os.path.join(ROOT, "probe_ln1"))
    ap.add_argument("--worktree", action="store_true",
                    help="local only: label a dirty bench with a content hash")
    ap.add_argument("--record", default=None,
                    help="on GREEN, write what this run read (model/gate_ln1_record.py)")
    a = ap.parse_args()
    rtl = rtl_label(a.worktree)
    # absolute: the proofs step runs Lean with cwd = lean/JLane
    out = os.path.join(os.path.abspath(a.out), "%s-%d-%s" % (rtl, a.rows, time.strftime("%Y%m%d%H%M%S")))
    os.makedirs(out)
    print("LN1 -- Lean replay of JLane.step against the RTL at %s, %d rows/arm"
          % (rtl, a.rows))
    print("  out %s" % out)
    banner("iverilog", "vvp")
    problems = []

    print("--- proofs ---")
    problems += ["PROOF: " + s for s in check_axioms(out)]

    print("--- export (from the checkout, fresh directory) ---")
    rcs = export(out, a.rows, rtl)
    for k, v in rcs.items():
        if v != 0:
            problems.append("EXPORT %s: exit %d" % (k, v))
    arms = expected_arms()
    for arm in arms:
        f = os.path.join(out, "trace_%s.csv" % arm)
        if not os.path.isfile(f):
            problems.append("EXPORT %s: no trace" % arm)
            continue
        with open(f, encoding="ascii") as fh:
            head = fh.readline()
            n = sum(1 for _ in fh) - 1
        if "rtl=%s " % rtl not in head + " ":
            problems.append("EXPORT %s: header not labelled rtl=%s" % (arm, rtl))
        if n != a.rows:
            problems.append("EXPORT %s: %d rows, expected %d" % (arm, n, a.rows))
    print("  %d arms exported" % len(arms))

    print("--- replay ---")
    lake = shutil.which("lake")
    r = run([lake, "exe", "replay", out], cwd=LEAN) if lake else None
    res = {}
    if r is None:
        problems.append("REPLAY: lake is not on PATH")
    else:
        for ln in r.stdout.splitlines():
            m = LINE.match(ln.strip())
            if m:
                res[m.group(2)] = dict(zip(KEYS, m.groups()))
        tail = [ln for ln in r.stdout.splitlines() if " traces, " in ln]
        print("  " + (tail[-1] if tail else "(no summary line)"))
        if not tail:
            problems.append("REPLAY: no summary line\n" + (r.stdout + r.stderr)[-2000:])
    extra = sorted(set(res) - set(arms))
    if extra:
        problems.append("REPLAY: unexpected traces %s" % extra)
    for arm in arms:
        if arm not in res:
            problems.append("REPLAY %s: no result" % arm)
            continue
        for s in judge(arm, res[arm], a.rows, out):
            problems.append("REPLAY %s: %s" % (arm, s))
    kinds = {"clean": 0, "must-fire": 0, "oos0": 0, "in-scope img": 0}
    for arm in arms:
        if arm.startswith("MF_"):
            kinds["must-fire"] += 1
        elif arm.startswith("img_") and arm[4:] in IMG_OOS0:
            kinds["oos0"] += 1
        elif arm.startswith("img_"):
            kinds["in-scope img"] += 1
        else:
            kinds["clean"] += 1
    print("  arms: %s" % ", ".join("%d %s" % (v, k) for k, v in kinds.items()))

    if problems:
        # ⭐ v2 (Wilson 10-26): the image replays' row-0 alignment is reworked
        # when Lean is updated for the first primitives. Until then a red made
        # ONLY of image-replay rows, on inputs moved inside step 2's change set,
        # is the declared STALE -- a must-fire or clean-arm problem stays RED.
        if all(s.startswith("REPLAY img_") for s in problems):
            sys.path.insert(0, os.path.join(ROOT, "model"))
            import stale_records as SR
            v, why = SR.stale_verdict("ci/ln1_replay.py", SR.moved(BENCH))
            print("\n  stale_records: %s -- %s (%d image-replay row(s))"
                  % (v, why, len(problems)))
            if v == "STALE":
                print("LN1: STALE (declared: %s)" % why)
                return 0
        print("\n*** LN1 RED -- %d problem(s):" % len(problems))
        for s in problems:
            print("  *** " + s)
        return 1
    print("\nLN1: GREEN -- %d arms each matched their pinned signature at %s; "
          "%s each depend on exactly %s"
          % (len(arms), rtl, ", ".join(THEOREMS), AXIOMS_OK))
    if a.record:
        rec = write_record(a.record, a.rows, len(arms))
        print("  record: %d input files, set hash %s... -> %s"
              % (len(rec["inputs"]["files"]), rec["inputs"]["sha256"][:12], a.record))
    return 0


def ln1_inputs():
    """⭐ WHAT THIS RUN READ (Wilson R4: LN1 bound to its inputs like the
    harden), as tracked paths: the trace benches, every tracked Lean file but
    its README, the tracked lockstep images, and every REPO MODULE this process
    actually imported -- taken from sys.modules, never typed, so a new import
    is in the list the moment it is used."""
    import blobhash
    tracked = set(blobhash._git(["ls-files"])[1].decode().splitlines())
    mods = set()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and os.path.abspath(f).startswith(ROOT + os.sep):
            mods.add(os.path.relpath(os.path.abspath(f), ROOT).replace(os.sep, "/"))
    lean = {p for p in tracked if p.startswith("lean/JLane/")
            and not p.endswith(".md")}
    imgs = {"test/" + i for i in IMAGES}
    return sorted(p for p in set(BENCH) | lean | (imgs & tracked) | mods
                  if p in tracked)


def write_record(path, rows, n_arms):
    import json
    import blobhash
    files = ln1_inputs()
    rec = {"sha": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
           "run": os.environ.get("GITHUB_RUN_ID", "local"), "rows": rows,
           "arms": n_arms, "verdict": "GREEN",
           "inputs": {"files": files, "sha256": blobhash.set_hash(files)}}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=1)
        fh.write("\n")
    return rec


if __name__ == "__main__":
    sys.exit(main())
