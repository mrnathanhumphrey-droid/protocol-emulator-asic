"""A RECORDED NUMBER MUST NOT DEPEND ON WHICH SIMULATOR PRODUCED IT.

⛔⛔ AUDIT #3. Every gate and record here runs on iverilog, and iverilog had
been resolving the bench races one particular way -- so the records were right,
but only because of a simulator's choice. Under Verilator the smoke bench read
`hdr_done` 94 / `jobs` 344 (the reset network's +1 cycle swallowed), the edge
bench's latencies moved a cycle, and the reload bench reported a push that
never happened. `model/gate_bench_race.py` keeps the known SHAPE out; this
gate checks the OUTCOME: every arm of every record-feeding bench, under both
simulators, must print the same thing.

THE BENCHES: `gate_bench_race.RECORD_BENCHES` -- ONE list for both gates, so
they cannot drift apart. Arms come from `test/benchset.py`, fully resolved,
exactly as the bench sweep runs them. `tb_v2win` has no bench-set arm; its
gate (`run_v2window.py`) is re-run here whole: the dry run's slots and the
taken bit at every lead must agree.
COMPARED: each arm's printed output, minus the simulators' own `$finish` and
report lines. ⚠ The printed output, not a waveform: a difference no check
prints is not seen here (`gate_corpus_trace` compares full pin traces).
VERSIONS: both are printed; Verilator must be the pinned release (ruling V),
so a toolchain change that moves a result is red with its cause in the log.
MUST-FIRE: the smoke bench with its original rising-edge engine start (the
PROG fall) restored in a scratch copy must DISAGREE -- the known real race,
94/344 vs 95/343. The same plant as `gate_bench_race`'s must-fire.
"""
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner, tool                     # noqa: E402
import benchset                                        # noqa: E402
import gate_corpus_trace as gct                        # noqa: E402  vrun/vpath/pin
from gate_bench_race import (RECORD_BENCHES,           # noqa: E402
                             RECORD_ARMS, MF_FIXED, MF_RACY)

#: inside the checkout (`probe_*` is gitignored), so one RELATIVE path reaches
#: it from both simulators
TMP = os.environ.get("PE_XSIM_TMP") or os.path.join(ROOT, "probe_xsim")
SEEN_VL = []
FINISH = re.compile(r"\$finish|Verilog \$finish|^- |S i m u l a t i o n|"
                    r"Verilator:|VCD info|^\s*$")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=ROOT)


def norm(txt):
    return [l.rstrip() for l in txt.splitlines() if not FINISH.search(l)]


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


#: ⭐ EVERY LINE IN EXACT ORDER, NO SPECIAL CASE. `clocked_conform.vh`'s layer
#: banners once printed in simulator-chosen order when two layers first fired
#: on the same edge ([R]/[B] swapped on corpus_spim25); they now come from one
#: reporting block in a fixed order, stamped with the cycle, so the bench --
#: not this comparison -- removed the ambiguity.
def first_diff(a, b):
    for k, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return "line %d: %r vs %r" % (k + 1, x[:70], y[:70])
    return "" if len(a) == len(b) else "length %d vs %d" % (len(a), len(b))


def both(top, srcs, gparams, arms, tag):
    """Run `arms` [(label, plusargs)] of one build under both simulators.
    -> {label: (iverilog lines, verilator lines)} or a string on failure."""
    srcs = [s.replace("\\", "/") for s in srcs]
    d = os.path.join(TMP, tag)
    os.makedirs(d, exist_ok=True)
    vvp = os.path.join(d, "sim.vvp")
    b = run([tool("iverilog"), "-g2012", "-I", "test", "-I", ".", "-o", vvp,
             "-s", top] + ["-P%s.%s=%s" % (top, k, v) for k, v in gparams.items()]
            + srcs)
    if b.returncode:
        return "iverilog build failed: " + (b.stdout + b.stderr)[-300:]
    armsf = os.path.join(d, "arms.txt")
    with open(armsf, "w", encoding="utf-8", newline="\n") as fh:
        for label, args in arms:
            fh.write("%s %s\n" % (label, " ".join(args)))
    r = gct.vrun("xsim_run.sh", gct.vpath(ROOT), gct.vpath(d), top,
                 gct.vpath(armsf), " ".join(srcs),
                 " ".join("-G%s=%s" % (k, v) for k, v in gparams.items()))
    gct._pin_check(r.stdout, "xsim_run.sh")
    # ⭐ THE VERSION IN THE LOG, once: a toolchain change that moves a result
    # must be red with its cause readable right here
    vline = next((l.strip() for l in r.stdout.splitlines()
                  if l.strip().startswith("tool verilator")), None)
    if vline and not SEEN_VL:
        SEEN_VL.append(vline)
        print("  %s" % vline)
    if r.returncode:
        return "verilator side failed: " + (r.stdout + r.stderr)[-300:]
    out = {}
    for label, args in arms:
        iv = run([tool("vvp"), vvp] + list(args)).stdout
        vp = os.path.join(d, label + ".vl.txt")
        vl = open(vp, encoding="utf-8", errors="replace").read() \
            if os.path.exists(vp) else ""
        out[label] = (norm(iv), norm(vl))
    return out


def judge(name, res, problems):
    if isinstance(res, str):
        problems.append("%s: %s" % (name, res))
        print("    *** %-26s %s" % (name, res[:90]))
        return
    for label, (iv, vl) in sorted(res.items()):
        d = first_diff(iv, vl)
        if not iv or not vl:
            d = d or "empty output"
            d = "EMPTY on %s" % ("iverilog" if not iv else "verilator")
        print("    %-12s %-16s %5d lines  %s" % (
            name, label, len(iv), "agree" if not d else "*** DIFFER -- " + d))
        if d:
            problems.append("%s/%s: %s" % (name, label, d))


def v2win(problems):
    import run_v2window as V
    img = rel(V.image(os.path.join(TMP, "v2win.hex")))
    srcs = ["test/tb_v2win.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
    dry = both("tb_v2win", srcs, {}, [("dry", ["+IMG=" + img, "+DRY=1"])], "tb_v2win_dry")
    if isinstance(dry, str):
        judge("tb_v2win", dry, problems)
        return
    judge("tb_v2win", dry, problems)
    slots = [int(c) for c in re.findall(r"^SLOT \d+ WB (\d+)", "\n".join(dry["dry"][0]), re.M)]
    if len(slots) <= V.SLOT:
        problems.append("tb_v2win: the dry run found %d slot(s)" % len(slots))
        return
    arms = [("lead%02d" % k, ["+IMG=" + img, "+AT=%d" % slots[V.SLOT], "+LEAD=%d" % k])
            for k in V.LEADS]
    judge("tb_v2win", both("tb_v2win", srcs, {}, arms, "tb_v2win_leads"), problems)


def main() -> int:
    print("=" * 78)
    print("XSIM -- every record-feeding bench agrees under both simulators")
    print("=" * 78)
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    recs, probs = benchset.plan()
    problems = list("benchset: " + p for p in probs)
    for top in RECORD_BENCHES:
        if top == "tb_v2win":
            v2win(problems)
            continue
        arms = [r for r in recs if r["top"] == top]
        if not arms:
            problems.append("%s: no benchset arm and no special runner" % top)
            print("    *** %s has no arm to run" % top)
            continue
        for key in sorted({r["build"] for r in arms}):
            group = [r for r in arms if r["build"] == key]
            res = both(top, group[0]["srcs"], group[0]["gparams"],
                       [(r["label"], r["args"]) for r in group], key)
            judge(top, res, problems)
    for top, label in RECORD_ARMS:
        arm = [r for r in recs if r["top"] == top and r["label"] == label]
        if not arm:
            problems.append("%s/%s: no such benchset arm" % (top, label))
            print("    *** %s/%s has no benchset arm" % (top, label))
            continue
        judge(top, both(top, arm[0]["srcs"], arm[0]["gparams"],
                        [(label, arm[0]["args"])], "%s_%s" % (top, label)),
              problems)

    # ⛔ MUST-FIRE: the known real race, restored in a scratch copy
    # ⚠ THE ENGINE START, not the reset release: restoring the rising-edge
    # reset release alone left both simulators agreeing (measured); the PROG
    # fall is the write that moved `hdr_done` 95 -> 94 under Verilator.
    smoke = open(os.path.join(HERE, "tb_smoke.v"), encoding="utf-8").read()
    fixed = MF_FIXED
    mf_ok = False
    if smoke.count(fixed) == 1:
        d = os.path.join(TMP, "mf")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "tb_smoke.v"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(smoke.replace(fixed, MF_RACY))
        arm = next(r for r in recs if r["top"] == "tb_smoke" and r["label"] == "default")
        srcs = [rel(os.path.join(d, "tb_smoke.v"))] + [s for s in arm["srcs"]
                                                       if not s.replace("\\", "/").endswith("tb_smoke.v")]
        res = both("tb_smoke", srcs, {}, [("mf", arm["args"])], "mf_build")
        if not isinstance(res, str):
            iv, vl = res["mf"]
            mf_ok = bool(iv and vl and first_diff(iv, vl))
            print("    must-fire (smoke bench, rising-edge engine start restored): %s -- %s"
                  % ("RED" if mf_ok else "*** AGREED", first_diff(iv, vl) or "identical"))
        else:
            print("    *** must-fire did not run: %s" % res[:90])
    else:
        print("    *** must-fire landmark not found in tb_smoke.v")
    if not mf_ok:
        problems.append("must-fire did not disagree")
    problems += gct.PIN_PROBLEMS
    for p in gct.PIN_PROBLEMS:
        print("    *** %s" % p)
    print()
    print("  GATE xsim: %s" % ("PASSED" if not problems else
                               "FAILED (%d problem(s))" % len(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
