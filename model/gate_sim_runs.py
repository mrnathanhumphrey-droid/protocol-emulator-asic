"""EVERY SIMULATION RUN GOES THROUGH test/sim_run.py (Wilson 10-19, option 2).

⛔⛔ WHY. `test/sim_run.py` does the bound lookup (a clocked image with no A2
bound is refused, naming it) inside the one function a run takes its command
from. That makes skipping the lookup impossible only if NO run is built any
other way -- which is what this gate holds.

WHAT IS A RUN (red outside the helper):
  * Python: `tool("vvp")` -- the vvp command is built ONLY by `sim_run.vvp`.
    Also a bare "vvp" / "vvp.exe" string used as a command element, and a
    Verilator-built "*.sim" path that is not a compile's `-o` output unless it
    sits inside a `sim_run.` call on that line.
  * shell: at a COMMAND position (line start, after `(`, `;`, `&&`, `||`, `|`,
    `$(`, or a `timeout N` / `nice -n N` / `exec` prefix): `vvp`, `"$VVP"`, or
    a Verilator-built binary -- `./x.sim`, `"$dir/x.sim"`, `"$bin"`,
    `"$OBJ/<name>"`, `"$PRE/obj/<name>"`. A shell run is legal only as the
    argument of `sim_exec "<images>" ...` (ci/tools.sh).
  * cocotb (test/test.py): the program image is read in Python by `read_hex`,
    which must call `sim_run.check`.
NOT A RUN (allowed raw): building -- `iverilog`, `"$IV"`, `verilator`, `"$VL"`,
  `make -C ... -f V*.mk`; `tool_banner`; version queries. `[ -x "$b/x.sim" ]`
  tests a file, it does not run it.
DEFINITION SITES (allowlisted, with reasons): see ALLOW.
SCOPE: every .py / .sh the runner registry walks (`runner_registry.SCAN_TOPS`)
plus test/test.py; comments and Python docstrings skipped.

MUST-FIRES (scratch text, never the tree): a Python raw `tool("vvp")` run ->
red naming file and line; a shell `./x.sim` run -> red naming file and line;
a raw `iverilog` compile -> stays GREEN; test.py without the read_hex check
-> red.
IMAGES OUTSIDE THE UNIVERSE (Wilson 10-19), on the real helper: M4 a renamed
byte-identical copy takes the universe image's bound; M5 a one-byte-modified
copy with no generator is refused, naming it (under the universe image's own
name); M6 an unregistered generator cannot record, and its image is refused;
M7 a registered-pattern file in the committed tree is refused even with a
forged manifest (written to a fresh fpga/mf_committed_tree_probe/ and
removed); control: the same bytes recorded by a registered generator under
scratch this run pass. The registry is printed on every run.
SCRATCH = IGNORED + UNTRACKED (ruling 2): each scratch pattern is gitignored;
no tracked file matches an ignore pattern; M8 the real tracked
model/ta02/probe_band_edge.py gets no scratch pass; M8b a scratch path, once
tracked, gets none. CLASSIFIER (4b): M9 a forced exception on one image
refuses the run, naming it. HIDDEN LOADS (ruling 1): every bench that loads an
image without a plusarg ($readmemh literal, plusarg default, literal
pe_fpga_core IMG) -- parsed here, independently of the helper -- is matched
EXACTLY by what its callers name; M10 an altered caller list goes red, naming
the bench and the caller.
INJECTION (queue 3b): I1 one bounded image -> its exact +A2SLACK appended; I2
a run already carrying one is untouched; I3 a non-clocked image -> nothing
appended; I4 two bounded images -> refused as ambiguous.
POSITIVE TOKEN: `GATE sim-runs: PASSED`.
"""
from __future__ import annotations

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
import runner_registry as RR                                      # noqa: E402

#: path -> why it may name the tools without being a run
ALLOW = {
    "test/sim_run.py": "THE helper: the one place a run's command is built",
    "test/toolchain.py": "resolves and banners the tools (`tool()`, "
                         "`banner()`); launches no simulation",
    "ci/tools.sh": "resolves $IV / $VVP / $VL and defines `sim_exec`, the "
                   "shell side of the helper",
    "model/gate_sim_runs.py": "this gate names the patterns it looks for",
    "model/gate_tool_pinning.py": "its must-fire plants a raw `tool(\"vvp\")` "
                                  "command as scratch TEXT; it runs nothing",
}
COCOTB = "test/test.py"

PY_RUN = re.compile(r"""tool\(\s*["']vvp["']\s*\)|["']vvp(?:\.exe)?["']\s*[,\]]""")
#: a Verilator-built binary named as a command element in Python (a "*.sim"
#: string that is NOT the `-o` output of a compile). Found by hand after the
#: first count: race_remeasure runs `ra1.sim` from Python.
PY_VBIN = re.compile(r"""(?<!"-o", )["'][\w./-]*\.sim["']""")
_CMDPOS = r"""(?:^|[;(|]|&&|\|\||\$\()\s*(?:(?:timeout\s+\d+|nice\s+-n\s+\d+|exec)\s+)*"""
_TARGET = (r"""(?:vvp|"?\$\{?VVP\}?"?|\./[\w.-]+\.sim|"?\$\{?\w+\}?/[\w./-]*\.sim"?"""
           r"""|"\$\{?bin\}?"|"\$\{?OBJ\}?/\w+"|"\$\{?PRE\}?/obj/\w+")""")
SH_RUN = re.compile(_CMDPOS + _TARGET + r"""(?=\s|$|\))""")


def _logical_sh(text):
    """Shell text as LOGICAL lines: a `\\`-continued command is one line
    (numbered by its first physical line), so `sim_exec "<imgs>" \\` before
    the run's own line counts."""
    out, buf, start = [], "", None
    for i, ln in enumerate(text.splitlines(), 1):
        if start is None:
            start = i
        if ln.rstrip().endswith("\\") and not ln.strip().startswith("#"):
            buf += ln.rstrip()[:-1] + " "
            continue
        out.append((start, buf + ln))
        buf, start = "", None
    if buf:
        out.append((start, buf))
    return out


def code_lines(path, text):
    if not path.endswith(".py"):
        for i, ln in _logical_sh(text):
            if not ln.strip().startswith("#"):
                yield i, ln
        return
    in_doc = False
    for i, ln in enumerate(text.splitlines(), 1):
        s = ln.strip()
        if path.endswith(".py"):
            q = s.count('"""') + s.count("'''")
            if q == 1:
                in_doc = not in_doc
                continue
            if in_doc or s.startswith("#") or q >= 2:
                continue
        elif s.startswith("#"):
            continue
        yield i, ln


def raw_runs(path, text):
    """[(line no, text)] of runs outside the helper in one file."""
    out = []
    for i, ln in code_lines(path, text):
        if path.endswith(".py"):
            if PY_RUN.search(ln) or (PY_VBIN.search(ln)
                                     and "sim_run." not in ln):
                out.append((i, ln.strip()))
        else:
            for m in SH_RUN.finditer(ln):
                if "sim_exec" not in ln[:m.end()]:
                    out.append((i, ln.strip()))
                    break
    return out


def cocotb_ok(text):
    """read_hex must call the helper's lookup."""
    m = re.search(r"^def read_hex\(.*?(?=^def |\Z)", text, re.S | re.M)
    return bool(m) and "sim_run.check(" in m.group(0)


def scan(files):
    """{path: [(line, text)]} for every file with a raw run."""
    bad = {}
    for p, t in sorted(files.items()):
        if p in ALLOW:
            continue
        r = raw_runs(p, t)
        if r:
            bad[p] = r
    return bad


def tree():
    files = dict(RR.bench_invokers())
    for top in RR.SCAN_TOPS:
        for dp, dn, fn in os.walk(os.path.join(ROOT, top)):
            dn[:] = [d for d in dn if not d.startswith(
                ("sim_build", "probe", "__pycache__", "build", "fixtures"))]
            for f in fn:
                if f.endswith((".py", ".sh")) and not f.startswith("probe"):
                    p = os.path.relpath(os.path.join(dp, f), ROOT).replace(
                        "\\", "/")
                    if p not in files:
                        files[p] = RR._read(os.path.join(ROOT, p))
    files[COCOTB] = RR._read(os.path.join(ROOT, COCOTB))
    return files


def main() -> int:
    print()
    print("=" * 78)
    print("  EVERY SIMULATION RUN GOES THROUGH test/sim_run.py")
    print("=" * 78)
    rc = 0

    def say(ok, what):
        nonlocal rc
        print("    %-64s %s" % (what, "ok" if ok else "*** FAIL"))
        if not ok:
            rc = 1

    files = tree()
    bad = scan(files)
    n = sum(len(v) for v in bad.values())
    print("  scanned %d scripts; %d allowlisted definition site(s):"
          % (len(files), len(ALLOW)))
    for p, why in sorted(ALLOW.items()):
        print("    %-26s %s" % (p, why))
    for p, rows in bad.items():
        for i, s in rows:
            print("    *** %s:%d raw run: %s" % (p, i, s[:80]))
    say(n == 0, "no run outside the helper (%d raw run line(s) in %d file(s))"
        % (n, len(bad)))
    for p in ALLOW:
        say(os.path.isfile(os.path.join(ROOT, p)), "allowlisted %s exists" % p)
    say(cocotb_ok(files[COCOTB]), "cocotb's read_hex takes the helper's lookup")

    print()
    print("  --- must-fires (RED) and the control (GREEN) ---")
    f1 = {"test/probe_mf_raw.py": 'x = 1\nr = run([tool("vvp"), v, "+IMG=a"])\n'}
    b1 = scan(f1)
    say(b1.get("test/probe_mf_raw.py", [(0, "")])[0][0] == 2,
        "M1 scratch Python raw vvp run -> red, at test/probe_mf_raw.py:2")
    f2 = {"test/probe_mf_raw.sh": 'cd x\n( cd "$OUT" && ./trace.sim +IMG=a )\n'}
    b2 = scan(f2)
    say(b2.get("test/probe_mf_raw.sh", [(0, "")])[0][0] == 2,
        "M2 scratch shell ./x.sim run -> red, at test/probe_mf_raw.sh:2")
    f3 = {"test/probe_mf_build.sh":
          '"$IV" -g2012 -o "$O/t.vvp" -s tb_x test/tb_x.v\n'
          '"$VL" --binary -o trace.sim --top-module tb_trace $SRCS\n'
          '[ -x "$b/trace.sim" ] || exit 1\n',
          "test/probe_mf_build.py":
          'b = run([tool("iverilog"), "-o", v, "test/tb_x.v"])\n'}
    say(not scan(f3), "control: raw iverilog / verilator COMPILE -> green")
    f4 = "def read_hex(name):\n    return open(name).read()\n"
    say(not cocotb_ok(f4), "M3 test.py read_hex without the lookup -> red")

    print()
    print("  --- images outside the universe (Wilson 10-19: provenance, content)")
    import sim_run as S
    for gid, g in sorted(S.SCRATCH_GENERATORS.items()):
        print("    generator %-26s %-14s %s" % (gid, g["pattern"], g["why"][:60]))
    say(all(g.get("why") and g.get("pattern") and g.get("script")
            and os.path.isfile(os.path.join(ROOT, g["script"]))
            for g in S.SCRATCH_GENERATORS.values()),
        "every registered generator names its script, pattern and reason")
    _provenance_mustfires(S, say)
    _scratch_git_checks(S, say)
    _classifier_mustfire(S, say)
    _hidden_load_crosscheck(S, say)
    _injection_mustfires(S, say)
    _completion_mustfires(S, say)
    print()
    print("GATE sim-runs: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


def bench_truth(vpath):
    """The images a bench loads WITHOUT a plusarg, parsed here independently
    of the helper: `$readmemh("x.hex")` literals, the plusarg-default image
    (`imgfile = "x.hex"`), and a literal `pe_fpga_core #(.IMG("x.hex"))`."""
    src = RR._read(os.path.join(ROOT, vpath))
    out = re.findall(r'\$readmem[hb]\s*\(\s*"([^"]+\.hex)"', src)
    out += re.findall(r'\b(?:imgfile|img0)\s*=\s*"([^"]+\.hex)"', src)
    out += re.findall(r'pe_fpga_core\s*#\(\s*\.IMG\(\s*"([^"]+\.hex)"\s*\)', src)
    return set(out)


def _const(path, name):
    """A module-level literal constant, read with ast (no import, no side
    effects)."""
    import ast
    tree = ast.parse(RR._read(os.path.join(ROOT, path)))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    return None


#: the FPGA twins name their compile-bound images as typed constants:
#: bench -> (runner, constant, how the constant becomes the list)
FPGA_CALLERS = {
    "fpga/sim/tb_fpga_loader.v": ("fpga/sim/run_fpga_loader.py", "LOADER_IMGS",
                                  lambda v: set(v)),
    "fpga/sim/tb_fpga_onewire.v": ("fpga/sim/run_fpga_onewire.py", "OW_IMG",
                                   lambda v: {v}),
}


def hidden_problems(callers=None):
    """Ruling 1 (Wilson 10-19): for every bench with a hidden image load, the
    images its callers pass to the helper EXACTLY match what the bench loads.
    `callers` overrides FPGA_CALLERS' constants (must-fire)."""
    import sim_run as S
    probs = []
    benches = sorted(
        ["test/" + f for f in os.listdir(os.path.join(ROOT, "test"))
         if f.startswith("tb_") and f.endswith(".v")]
        + ["fpga/sim/" + f for f in os.listdir(os.path.join(ROOT, "fpga", "sim"))
           if f.startswith("tb_") and f.endswith(".v")])
    rows = []
    for b in benches:
        truth = bench_truth(b)
        if not truth:
            continue
        if b in FPGA_CALLERS:
            runner, const, conv = FPGA_CALLERS[b]
            val = (callers or {}).get(b, _const(runner, const))
            got = conv(val) if val is not None else set()
            who = "%s %s" % (runner, const)
        elif b.startswith("test/"):
            got = set(S.hardcoded_images(os.path.basename(b)[:-2]))
            who = "sim_run.hardcoded_images(%s)" % os.path.basename(b)[:-2]
        else:
            got, who = None, "no runner"
        rows.append((b, truth, who, got))
        if got is not None and got != truth:
            probs.append("%s loads %s but %s passes %s"
                         % (b, sorted(truth), who, sorted(got)))
    return probs, rows


def _hidden_load_crosscheck(S, say):
    print()
    print("  --- hidden image loads: caller's images= == what the bench loads")
    probs, rows = hidden_problems()
    for b, truth, who, got in rows:
        print("    %-30s %d image(s)  <- %s%s" % (
            os.path.basename(b), len(truth), who,
            "" if got is not None else " (no runner: not run, not checked)"))
    for q in probs:
        print("    *** %s" % q)
    say(not probs, "every hidden-load bench: the caller's list matches exactly")
    # tb_fpga_i2c binds IMG from its runner's own constant: one expression on
    # both sides, checked in the runner's source
    src = RR._read(os.path.join(ROOT, "fpga", "sim", "run_fpga_i2c.py"))
    say("\"IMG\": '\"%s\"' % rel(IMG)" in src and "images=[rel(IMG)]" in src,
        "tb_fpga_i2c: the IMG it is built with == the image named to the helper")
    alt = list(_const("fpga/sim/run_fpga_loader.py", "LOADER_IMGS"))[:-1]
    mf, _r = hidden_problems({"fpga/sim/tb_fpga_loader.v": alt})
    say(any("tb_fpga_loader.v" in q and "LOADER_IMGS" in q for q in mf),
        "M10 a caller's images= altered -> red, naming bench and caller")


def _completion_mustfires(S, say):
    """⛔ F3 (meta-test, 10-23): R3/R4's completion checks priced IN the suite.
    sim_run.trace_incomplete (Python) and ci/tools.sh trace_completed (shell)
    were proven only by out-of-suite plant runs. Each form is fed the same
    four logs: a finished run passes; a FATAL, a short count and a missing
    end line are refused -- and a command with no +NCYC is refused too."""
    import subprocess
    import tempfile
    print()
    print("  --- run completion (R3/R4): a verdict counts only if the run finished")
    done = "  layer: ok -- 9 thing(s)\ntb_trace: 8000 cycles -> t.txt\n"
    cases = (("finished", done, None),
             ("a FATAL stop", "tb_trace: FATAL -- +NBYTES=<n> is required.\n"
              + done, "FATAL"),
             ("a short count (the Verilator post-$finish line)",
              "*** FAIL x\ntb_trace: 5000 cycles -> t.txt\n", "5000 of"),
             ("no end line (iverilog stopped)", "*** FAIL x\n", "did not reach"))
    cmd = ["sim", "+NCYC=8000"]   # only +NCYC matters
    for what, out, want in cases:
        why = S.trace_incomplete(out, cmd)
        say((why is None) if want is None else (bool(why) and want in why),
            "C trace_incomplete: %-46s %s" % (what, "passes" if want is None
                                               else "refused"))
    say(bool(S.trace_incomplete(done, ["sim"])),
        "C trace_incomplete: a command with no +NCYC is refused")
    # ⚠ a REPO-RELATIVE scratch dir: on Windows `bash` may resolve to WSL's,
    # which cannot open a C:/ temp path (measured: the finished log read as
    # refused); a relative path from cwd=ROOT works under both
    import shutil
    d = tempfile.mkdtemp(prefix="probe_complete_", dir=ROOT)
    try:
        for k, (what, out, want) in enumerate(cases):
            log = os.path.join(d, "r%d.log" % k)
            with open(log, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(out)
            # ⚠ THE RESOLVED bash, never bare "bash": Windows' process search
            # finds System32's WSL launcher first, which also mangles $0
            # (measured: the finished log never reached the function)
            r = subprocess.run([shutil.which("bash") or "bash", "-c",
                                '. ci/tools.sh >/dev/null 2>&1; '
                                'trace_completed "$0" 8000 mf',
                                os.path.relpath(log, ROOT).replace("\\", "/")],
                               cwd=ROOT, capture_output=True, text=True)
            ok = (r.returncode == 0) if want is None else (r.returncode != 0)
            say(ok, "C trace_completed (shell): %-38s %s"
                % (what, "passes" if want is None else "refused"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _injection_mustfires(S, say):
    """Queue 3b: a bound that exists is ENFORCED on the run."""
    import benchset
    print()
    print("  --- +A2SLACK injection (queue 3b)")
    want = benchset.a2_slack_arg("test/ckod_image.hex")
    got = S.argv(["sim", "+IMG=test/ckod_image.hex"], ["test/ckod_image.hex"])
    say(got[-1] == want and got.count(want) == 1,
        "I1 one bounded image -> its +A2SLACK appended, exactly (%s)" % want)
    keep = ["sim", "+A2SLACK=1,2,3,4,5"]
    got = S.argv(list(keep), ["test/ckod_image.hex"])
    say(got == keep, "I2 a run already carrying +A2SLACK is untouched")
    got = S.argv(["sim"], ["test/tx_image.hex"])
    say(got == ["sim"], "I3 a non-clocked image -> nothing appended")
    why = _refused(S, ["test/ckod_image.hex", "test/corpus_i2c.hex"])
    say(bool(why) and "ambiguous" in why,
        "I4 two bounded clocked images in one run -> refused as ambiguous")


def _scratch_git_checks(S, say):
    print()
    print("  --- scratch = ignored + untracked (Wilson 10-19, ruling 2)")
    for sample in ("probe_mfdir/x.hex", "test/probe_mf.hex",
                   "test/sim_build_mf/x.hex"):
        r = S._git("check-ignore", "-q", "--", sample)
        say(r is not None and r.returncode == 0,
            "the scratch pattern is gitignored: %s" % sample)
    r = S._git("ls-files", "-i", "-c", "--exclude-standard")
    bad = [p for p in (r.stdout.split("\n") if r else []) if p.strip()]
    say(r is not None and not bad,
        "no tracked file matches an ignore pattern%s"
        % ("" if not bad else ": " + ", ".join(bad[:5])))
    say(S.is_scratch("model/ta02/probe_band_edge.py") is False,
        "M8 a real TRACKED probe_ file (model/ta02/probe_band_edge.py) -> "
        "no scratch pass")
    say(S.is_scratch("test/sim_build_reload/i2c_write.hex",
                     tracked={"test/sim_build_reload/i2c_write.hex"}) is False,
        "M8b the same scratch path, once tracked -> no scratch pass")


def _classifier_mustfire(S, say):
    import shutil
    import tempfile
    import benchset
    tmp = tempfile.mkdtemp(prefix="probe_simrun_cls_")
    real = benchset.has_clocked_od_lane
    try:
        p = os.path.join(tmp, "unclassifiable.hex")
        words = RR._read(os.path.join(ROOT, "test", "tx_image.hex")).split()
        words[-1] = "%02x" % (int(words[-1], 16) ^ 1)
        with open(p, "w", encoding="ascii") as fh:
            fh.write("\n".join(words) + "\n")

        def boom(img):
            if os.path.basename(img) == "unclassifiable.hex":
                raise RuntimeError("forced classifier failure")
            return real(img)
        benchset.has_clocked_od_lane = boom
        why = _refused(S, [p])
        say(bool(why) and "unclassifiable.hex" in why and "forced" in why,
            "M9 the classifier raises on one image -> refused, naming it")
    finally:
        benchset.has_clocked_od_lane = real
        shutil.rmtree(tmp, ignore_errors=True)


def _refused(S, imgs):
    try:
        S.check(imgs)
        return None
    except S.SimRefused as exc:
        return str(exc)


def _provenance_mustfires(S, say):
    import shutil
    import tempfile
    src = os.path.join(ROOT, "test", "corpus_i2c.hex")   # clocked, bounded
    tmp = tempfile.mkdtemp(prefix="probe_simrun_mf_")
    tree = os.path.join(ROOT, "fpga", "mf_committed_tree_probe")
    try:
        # M4 a renamed byte-identical copy resolves to the universe bound
        cp = os.path.join(tmp, "renamed_anything.hex")
        shutil.copyfile(src, cp)
        st = S.check([cp])
        say("copy-of:corpus_i2c.hex" in st and "ok(" in st,
            "M4 renamed identical copy -> corpus_i2c's bound (%s)"
            % st.split(" bound=")[-1][:40])
        # M5 a one-byte-modified copy, no generator -> refused, naming it;
        # under the universe image's OWN name, so a name match cannot help
        words = open(src, encoding="ascii").read().split()
        words[-1] = "%02x" % (int(words[-1], 16) ^ 1)
        mod = os.path.join(tmp, "corpus_i2c.hex")
        with open(mod, "w", encoding="ascii") as fh:
            fh.write("\n".join(words) + "\n")
        why = _refused(S, [mod])
        say(bool(why) and mod in why,
            "M5 1-byte-modified copy, no generator -> refused, naming it")
        # M6 a clocked scratch image from an UNREGISTERED generator
        try:
            S.scratch_image("probe_unregistered_generator", mod)
            m6 = False
        except S.SimRefused:
            m6 = bool(_refused(S, [mod]))
        say(m6, "M6 unregistered generator: cannot record, image refused")
        # M7 a registered-pattern file in the COMMITTED tree: no pass, even
        # with a manifest naming a registered generator and this run's token
        os.makedirs(tree, exist_ok=True)
        inrepo = os.path.join(tree, "ckack.hex")         # run_ckack's pattern
        shutil.copyfile(mod, inrepo)
        try:
            S.scratch_image("run_ckack", inrepo)
            reg_refused = False
        except S.SimRefused:
            reg_refused = True
        with open(os.path.join(tree, S.MANIFEST), "w", encoding="utf-8") as fh:
            import json
            json.dump({os.path.normcase(os.path.abspath(inrepo)): {
                "generator": "run_ckack", "sha": S._sha(inrepo),
                "token": S.run_token()}}, fh)
        say(reg_refused and bool(_refused(S, [inrepo])),
            "M7 registered-pattern file in the committed tree -> refused")
        # control: the SAME bytes, recorded by a registered generator under
        # scratch this run -> passes
        ok = os.path.join(tmp, "ckack.hex")
        shutil.copyfile(mod, ok)
        S.scratch_image("run_ckack", ok)
        say(_refused(S, [ok]) is None,
            "control: registered generator, scratch, this run -> passes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
