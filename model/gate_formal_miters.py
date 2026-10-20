"""THE DISPATCH-SELECT PROOFS RUN ON EVERY PUSH (Wilson, queue 4).

⛔⛔ WHY. Two SymbiYosys miters prove the dispatch select equal to what it
replaced, ON THE SHIPPED TEXT (each generator lifts the lines verbatim from
`src/pe_engine.v`):
  * `formal/argmin_equiv.sby`    ruling TF4 -- the tree five-way select == the
                                 serial loop, and `winner_oh` names exactly the
                                 binary winner (TF2-R5);
  * `formal/preselect_equiv.sby` ruling C2 -- the flat AND-OR pick == the
                                 indexed mux, the clock-pin pick included (PR2).
Both were run BY HAND. A proof that runs by hand proves the tree it last ran
on; an RTL edit after it is unproved and nothing says so. Six runs cost 3 s,
so they belong here.

ARMS (each generator, then `sby -f`):
  argmin clean -> PASS        argmin --mutate / --mutate-oh -> FAIL
  preselect clean -> PASS     preselect --mutate / --mutate-ck -> FAIL
⛔ A PASS IS read from the log, never the exit code alone: `DONE (PASS, rc=0)`
  AND `successful proof by k-induction.`
⛔ A FAIL MUST BE A COUNTEREXAMPLE: `DONE (FAIL, rc=2)`, a `counterexample
  trace` line, and the assertion the mutant breaks among the failed ones
  (looked up by source line in the generated miter). A FAIL for any other
  reason -- an elaboration error, a missing file, a dead solver -- is red: a
  mutant "caught" by a broken run catches nothing.
⛔ A MISSING TOOL IS `COULD NOT RUN`, and red: a proof that did not run has not
  passed.

TOOL (ruling V's shape, for a tool `toolchain.py` does not cover): `PE_SBY`
first, then `sby` on PATH; on this box, neither, so it is delegated to WSL
(`PE_SBY_WSL`, default the pinned suite). The suite's own bin directory goes
on PATH FOR THE SBY RUN ONLY, so its yosys and yices are the ones that prove
-- nothing else in the gate run sees them. CI names it in `PE_SBY`.

MUST-FIRES (scratch copies, never the tree): L1 the argmin BEGIN marker gone
-> the generator refuses; L2 the preselect `hix` landmark edited -> refused;
L3 the preselect block's last line gone -> refused; V1 a FAIL log with no
counterexample -> red; V4 a counterexample on another assertion than the
mutant's -> red; V2 a PASS log without the induction line -> red; V3 a
log cut off before `DONE` -> red; T1 `PE_SBY` naming no file -> COULD NOT RUN.
POSITIVE TOKEN: `GATE formal-miters: PASSED`.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FORMAL = os.path.join(ROOT, "formal")
SBY_WSL = os.environ.get("PE_SBY_WSL",
                         "/opt/oss-cad-suite-2026-09-30/bin/sby")

#: (label, generator, flag, sby file, expected, assertion the mutant breaks)
ARMS = (
    ("argmin clean", "argmin", None, "argmin_equiv.sby", "PASS", None),
    ("argmin --mutate", "argmin", "--mutate", "argmin_equiv_mut.sby",
     "FAIL", "assert (winner == s_winner);"),
    ("argmin --mutate-oh", "argmin", "--mutate-oh", "argmin_equiv_mut.sby",
     "FAIL", "assert (winner_oh =="),
    ("preselect clean", "preselect", None, "preselect_equiv.sby", "PASS", None),
    ("preselect --mutate", "preselect", "--mutate", "preselect_equiv_mut.sby",
     "FAIL", "assert (w_act   =="),
    ("preselect --mutate-ck", "preselect", "--mutate-ck",
     "preselect_equiv_mut.sby", "FAIL", "assert (w_ck    =="),
)

DONE = re.compile(r"\] DONE \((PASS|FAIL|ERROR|UNKNOWN|TIMEOUT), rc=(\d+)\)")
FAILED_AT = re.compile(r"summary:\s+failed assertion \S+ at (\S+?\.sv):(\d+)\.")


class CouldNotRun(Exception):
    pass


def resolve():
    """('native', path) or ('wsl', path); CouldNotRun if neither exists."""
    env = os.environ.get("PE_SBY")
    if env:
        p = shutil.which(env) or (env if os.path.isfile(env) else None)
        if not p:
            raise CouldNotRun("PE_SBY=%s does not exist" % env)
        return "native", os.path.abspath(p)
    p = shutil.which("sby")
    if p:
        return "native", os.path.abspath(p)
    if os.name == "nt" and shutil.which("wsl.exe"):
        r = subprocess.run(["wsl.exe", "--", "test", "-x", SBY_WSL])
        if r.returncode == 0:
            return "wsl", SBY_WSL
        raise CouldNotRun("PE_SBY is not set, sby is not on PATH, and the WSL "
                          "side has no %s" % SBY_WSL)
    raise CouldNotRun("PE_SBY is not set and sby is not on PATH")


def wslpath(path):
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    return "/mnt/%s%s" % (drive[0].lower(), rest.replace("\\", "/"))


def sby_argv(how, sby, *args):
    """The argv that runs the suite's `sby`, its bin dir first on PATH."""
    bindir = sby.rsplit("/", 1)[0] if how == "wsl" else os.path.dirname(sby)
    if how == "wsl":
        return ["wsl.exe", "--cd", wslpath(FORMAL), "--", "env",
                "PATH=%s:/usr/bin:/bin" % bindir, sby] + list(args), None
    env = dict(os.environ)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    return [sby] + list(args), env


def run(argv, env=None):
    return subprocess.run(argv, cwd=FORMAL, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def banner(how, sby):
    argv, env = sby_argv(how, sby, "--version")
    v = (run(argv, env).stdout.strip().splitlines() or ["MISSING"])[0]
    yices = sby.rsplit("/", 1)[0] + "/yices-smt2" if how == "wsl" else \
        os.path.join(os.path.dirname(sby), "yices-smt2")
    argv = (["wsl.exe", "--", yices, "--version"] if how == "wsl"
            else [yices, "--version"])
    try:
        y = (run(argv).stdout.strip().splitlines() or ["MISSING"])[0]
    except OSError:
        y = "MISSING"
    print("  tool sby      : %s (%s)  %s" % (sby, how, v))
    print("  tool yices    : %s  %s" % (yices, y))


def verdict(log, rc, expect, miter_lines, breaks):
    """(ok, why) for one sby run, read from its log."""
    done = DONE.findall(log)
    if not done:
        return False, "no `DONE` line -- the run did not finish (rc=%d)" % rc
    st, drc = done[-1]
    if st != expect or int(drc) != rc:
        return False, "DONE (%s, rc=%s), process rc=%d; expected %s" % (
            st, drc, rc, expect)
    if expect == "PASS":
        if "successful proof by k-induction." not in log:
            return False, "PASS without `successful proof by k-induction.`"
        return True, "PASS, proof by k-induction"
    if "counterexample trace" not in log:
        return False, "FAIL WITHOUT A COUNTEREXAMPLE -- not a refutation"
    failed = sorted({int(n) for _f, n in FAILED_AT.findall(log)})
    texts = [miter_lines[n - 1].strip() for n in failed
             if 0 < n <= len(miter_lines)]
    if not any(t.startswith(breaks) for t in texts):
        return False, "counterexample, but `%s` is not among the failed " \
                      "assertions %s" % (breaks, texts)
    return True, "FAIL by counterexample, failed: %s" % " | ".join(texts)


def load_generator(name):
    path = os.path.join(FORMAL, "make_%s_miter.py" % name)
    spec = importlib.util.spec_from_file_location("make_%s_miter" % name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def generate(name, flag):
    """Run the generator in-process; return (rc, output, miter path)."""
    mod = load_generator(name)
    saved = sys.argv
    sys.argv = [mod.__file__] + ([flag] if flag else [])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main()
    finally:
        sys.argv = saved
    out = mod.OUT.replace(".sv", "_mut.sv") if flag else mod.OUT
    return rc, buf.getvalue().strip(), out


def main() -> int:
    print("GATE formal-miters: the dispatch-select proofs on the shipped RTL")
    bad = mustfires()
    try:
        how, sby = resolve()
    except CouldNotRun as e:
        print("  *** COULD NOT RUN: %s -- no proof ran, so none passed" % e)
        print("GATE formal-miters: COULD NOT RUN")
        return 1
    banner(how, sby)
    for label, gen, flag, sbyf, expect, breaks in ARMS:
        rc, msg, miter = generate(gen, flag)
        if rc != 0:
            print("  *** %-22s generator refused: %s" % (label, msg))
            bad += 1
            continue
        argv, env = sby_argv(how, sby, "-f", sbyf)
        r = run(argv, env)
        log = r.stdout + r.stderr
        with open(miter, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        ok, why = verdict(log, r.returncode, expect, lines, breaks)
        print("  %s %-22s expect %s: %s" % ("ok " if ok else "***", label,
                                            expect, why))
        if not ok:
            bad += 1
            for ln in log.strip().splitlines()[-6:]:
                print("      | " + ln)
    if bad:
        print("GATE formal-miters: FAILED (%d)" % bad)
        return 1
    print("GATE formal-miters: PASSED")
    return 0


def mustfires():
    bad = 0

    def say(ok, what):
        nonlocal bad
        print("  %s must-fire %s" % ("red ok" if ok else "*** NOT RED:", what))
        bad += 0 if ok else 1

    tmp = tempfile.mkdtemp(prefix="pe_formal_mf_")
    try:
        rtl = open(os.path.join(ROOT, "src", "pe_engine.v"),
                   encoding="utf-8").read()

        def refused(name, text, needle):
            mod = load_generator(name)
            mod.RTL = os.path.join(tmp, "pe_engine.v")
            mod.OUT = os.path.join(tmp, "build", "%s_miter.sv" % name)
            with open(mod.RTL, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            saved, sys.argv = sys.argv, [mod.__file__]
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rc = mod.main()
            finally:
                sys.argv = saved
            return rc != 0 and needle in buf.getvalue() \
                and not os.path.exists(mod.OUT)

        am = load_generator("argmin")
        pm = load_generator("preselect")
        say(rtl.count(am.BEGIN) == 1 and refused(
            "argmin", rtl.replace(am.BEGIN, "---- (marker removed) ----"),
            "FAIL argmin markers"),
            "L1 argmin BEGIN marker gone -> generator refuses")
        say(rtl.count(pm.HIX) == 1 and refused(
            "preselect", rtl.replace(pm.HIX, pm.HIX.replace("gs * SPL",
                                                            "gs*SPL")),
            "landmark 'hix'"),
            "L2 preselect `hix` landmark edited -> generator refuses")
        say(rtl.count(pm.BLOCK_LAST) == 1 and refused(
            "preselect", rtl.replace(pm.BLOCK_LAST + "\n", ""),
            "landmark 'last'"),
            "L3 preselect block's last line gone -> generator refuses")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fail_log = ("SBY 0 [x] summary:   failed assertion m._w_ at m.sv:1.5-1.9\n"
                "SBY 0 [x] DONE (FAIL, rc=2)\n")
    say(not verdict(fail_log, 2, "FAIL", ["assert (a == b);"],
                    "assert (a ==")[0],
        "V1 FAIL log with no counterexample -> red")
    say(not verdict("counterexample trace [basecase]: t.vcd\n" + fail_log, 2,
                    "FAIL", ["assert (a == b);"], "assert (c ==")[0],
        "V4 counterexample on another assertion than the mutant's -> red")
    say(not verdict("SBY 0 [x] DONE (PASS, rc=0)\n", 0, "PASS", [], None)[0],
        "V2 PASS log without the induction line -> red")
    say(not verdict("SBY 0 [x] summary: successful proof by k-induction.\n",
                    0, "PASS", [], None)[0],
        "V3 log cut off before DONE -> red")
    saved = os.environ.get("PE_SBY")
    os.environ["PE_SBY"] = os.path.join(ROOT, "no_such_dir", "sby")
    try:
        resolve()
        t1 = False
    except CouldNotRun:
        t1 = True
    finally:
        if saved is None:
            os.environ.pop("PE_SBY", None)
        else:
            os.environ["PE_SBY"] = saved
    say(t1, "T1 PE_SBY naming no file -> COULD NOT RUN")
    return bad


if __name__ == "__main__":
    sys.exit(main())
