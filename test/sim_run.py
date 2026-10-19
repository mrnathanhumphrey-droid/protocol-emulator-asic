"""sim_run -- THE ONE PATH A SIMULATION RUN TAKES (Wilson 10-19, option 2).

⛔⛔ WHY. The bench lookup that refuses a clocked image with no A2 bound
(`benchset.a2_slack_arg`, fail-closed since 23daef3) was called by 4 of the
35 scripts that load an image into a bench that reads the bound; the other 29
ran their images with nobody asking. Detecting the 29 was not enough (Wilson):
skipping the lookup must be IMPOSSIBLE BY CONSTRUCTION. So every simulation
RUN -- `vvp`, a Verilator-built binary, cocotb's image load -- takes its
command from this module, and `model/gate_sim_runs.py` is red on any run that
does not. Building (iverilog / verilator compile) is not a run: it loads no
program image.

THE CONTRACT:
  vvp(args, images) -> [vvp] + args, after the lookup (the only place a vvp
  command is built); argv(cmd, images) -> cmd, UNCHANGED, after the lookup,
  for any other run. `images` is REQUIRED:
  a list of image paths (repo-relative or absolute); [] = "this run loads no
  program image". Per image, at run time, from the shared classification:
    * no clocked open-drain lane -> passes ("bound not required")
    * clocked, with a bound in test/clocked_a2_bounds.json -> passes
    * clocked, NO bound, not in benchset.A2_UNBOUNDED_EXEMPT -> REFUSED:
      `SimRefused`, naming the image, before anything runs
  The caller keeps its own subprocess call, so a run's output cannot change;
  the Python form adds ONE stamp line on the CALLER's stdout per run (never
  in the simulation's captured output). The shell form is silent on a pass.

⚠ IT CHECKS, IT DOES NOT INJECT. A clocked image WITH a bound still runs
without +A2SLACK unless the caller passes it (as benchset's sweep does):
injecting would change direct runners' outputs, which the rewire commit may
not do (Wilson point 5). Stated for the follow-up.

SHELL: `python test/sim_run.py check [--bench TOP] [+PLUSARG ...] [image ...]`
(exit 3 naming the image on a refusal; no argument = loads no image).
`ci/tools.sh` wraps it as `sim_exec "<images>" <command...>`.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)


class SimRefused(RuntimeError):
    """A clocked image with no A2 bound: the run is refused."""


def _rel(p):
    a = p if os.path.isabs(p) else os.path.join(ROOT, p)
    try:
        return os.path.relpath(a, ROOT).replace(os.sep, "/")
    except ValueError:
        return a


# ---------------------------------------------------------------------------
# IMAGES OUTSIDE THE UNIVERSE (Wilson 10-19): resolved by CONTENT and by
# PROVENANCE, never by name.
#   * a byte-identical copy of a universe image (clean_room / check_reset_shift
#     temp copies, a renamed file) takes THAT image's bound, whatever its name;
#   * any other image is a SCRATCH image. Not clocked -> passes. Clocked ->
#     passes only if a REGISTERED generator created it THIS RUN, under scratch
#     (`scratch_image` below writes the provenance); else refused, naming it.
# ⛔ The basename record lookup alone was a naming loophole: a scratch file
#   called like a universe image would have borrowed that image's bound.
# ---------------------------------------------------------------------------
import fnmatch as _fn
import hashlib as _hl
import json as _js
import tempfile as _tf

#: ⛔⛔ THE SCRATCH-IMAGE REGISTRY, per GENERATOR (Wilson 10-19). Only a
#: generator listed here may produce a CLOCKED image that runs without an A2
#: bound, and only under scratch, this run. Measured, not guessed: the entries
#: come from the record-mode pass (probe_reports/launch_helper_prediction.txt).
#:   id -> {"script": the generating script, "pattern": output basename glob,
#:          "clocked": True, "why": the reason it runs without a bound}
SCRATCH_GENERATORS: dict = {
    "make_smoke_image --ckhalf": {
        "script": "test/make_smoke_image.py", "pattern": "probe_*.hex",
        "clocked": True,
        "why": "the F1 phase instrument with every lane HALF_HIGH, for "
               "phases_run.sh / gate_um10204: it measures t_HIGH / t_LOW / "
               "t_SU;DAT / t_HD;DAT against UM10204, not the A2 gap"},
    "run_ckack": {
        "script": "test/run_ckack.py", "pattern": "ckack*.hex",
        "clocked": True,
        "why": "the clocked I2C random read against a stretching peer "
               "(ruling ACK): judged by chip bytes == sigrok bytes at every "
               "stretch, and by its v3_table row"},
    "run_cktx": {
        "script": "test/run_cktx.py", "pattern": "cktx.hex",
        "clocked": True,
        "why": "TX4's clocked widths 1..8 image: judged by Layer V2/V3 "
               "against its v3_table row"},
    "run_reload": {
        "script": "test/run_reload.py", "pattern": "i2c_write.hex",
        "clocked": True,
        "why": "tb_reload's I2C write program: judged by the FRAM bytes "
               "written across a reload, not by the A2 gap"},
}

TOKEN_ENV = "SIM_RUN_TOKEN"
MANIFEST = ".sim_run_scratch.json"


def run_token():
    """This run's token. Set once and EXPORTED to the environment, so every
    process this run starts (generators, shell scripts, their checks) shares
    it; ci/tools.sh sets it for shell scripts sourced first."""
    t = os.environ.get(TOKEN_ENV)
    if not t:
        t = "%d-%s" % (os.getpid(), _hl.sha256(os.urandom(16)).hexdigest()[:12])
        os.environ[TOKEN_ENV] = t
    return t


#: path-component prefixes that are scratch by .gitignore: `probe_*` (the
#: project's scratch rule) and `test/sim_build*` (the runners' build dirs)
SCRATCH_PREFIXES = ("probe_", "sim_build")


_GIT = []


def _git(*args):
    """Run git in ROOT -> CompletedProcess or None. `git`, then `git.exe`: WSL's
    own git cannot read a Windows worktree's .git file, the Windows one can."""
    import subprocess
    for exe in ([_GIT[0]] if _GIT else ["git", "git.exe"]):
        root = ROOT
        if exe == "git.exe" and ROOT.startswith("/"):
            # Windows git needs the Windows form of a /mnt/<drive> path
            try:
                w = subprocess.run(["wslpath", "-w", ROOT], capture_output=True,
                                   text=True)
            except OSError:
                continue
            if w.returncode:
                continue
            root = w.stdout.strip()
        try:
            r = subprocess.run([exe, "-C", root] + list(args),
                               capture_output=True, text=True)
        except OSError:
            continue
        if r.returncode in (0, 1) and "not a git repository" not in r.stderr:
            if not _GIT:
                _GIT.append(exe)
            return r
    return None


_TRACKED = []


def _tracked():
    """The set of tracked paths (repo-relative, '/'), or None if git cannot
    answer."""
    if not _TRACKED:
        r = _git("ls-files", "-z")
        _TRACKED.append(None if r is None or r.returncode
                        else set(p for p in r.stdout.split("\0") if p))
    return _TRACKED[0]


def is_scratch(path, tracked=None):
    """Under the system temp dir; or under the repo on a scratch path
    component (SCRATCH_PREFIXES) that git confirms is IGNORED and NOT TRACKED
    (Wilson 10-19). Anything else in the repo is the committed tree and gets no
    scratch pass -- and so does everything in it if git cannot answer (fail
    closed). `tracked` is for the must-fires."""
    a = os.path.normcase(os.path.abspath(path))
    tmp = os.path.normcase(os.path.abspath(_tf.gettempdir()))
    if a.startswith(tmp + os.sep):
        return True
    root = os.path.normcase(os.path.abspath(ROOT))
    if not a.startswith(root + os.sep):
        return False
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(ROOT))
    if not any(c.startswith(SCRATCH_PREFIXES) for c in rel.split(os.sep)):
        return False
    tr = _tracked() if tracked is None else tracked
    if tr is None or rel.replace(os.sep, "/") in tr:
        return False
    r = _git("check-ignore", "-q", "--", rel.replace(os.sep, "/"))
    return r is not None and r.returncode == 0


def _content(path):
    try:
        with open(path, encoding="ascii") as fh:
            return bytes(int(t, 16) for t in fh.read().split())
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _sha(path):
    b = _content(path)
    return None if b is None else _hl.sha256(b).hexdigest()


_UIDX = []


def _universe_index():
    """({abs path: name}, {content sha: abs path}) of the shared universe,
    built WITHOUT running its generators (an absent generated arm is simply
    not indexed)."""
    if not _UIDX:
        sys.path.insert(0, os.path.join(ROOT, "model"))
        import image_universe as U
        u = U.scan(generate=False)
        by_path, by_sha = {}, {}
        for n, p in u.items():
            by_path[os.path.normcase(os.path.abspath(p))] = n
            s = _sha(p)
            if s:
                by_sha.setdefault(s, os.path.abspath(p))
        _UIDX.append((by_path, by_sha))
    return _UIDX[0]


def scratch_image(generator, path):
    """Record that registered `generator` created scratch image `path` THIS
    RUN. Called by the generator right after it writes the file. Raises if the
    generator is not registered, the name is not its pattern, or the path is
    not scratch."""
    g = SCRATCH_GENERATORS.get(generator)
    if g is None:
        raise SimRefused("sim_run: %s is not a registered scratch-image "
                         "generator (SCRATCH_GENERATORS)" % generator)
    name = os.path.basename(path)
    if not _fn.fnmatch(name, g["pattern"]):
        raise SimRefused("sim_run: %s does not match generator %s's pattern "
                         "%s" % (name, generator, g["pattern"]))
    if not is_scratch(path):
        raise SimRefused("sim_run: %s is not under scratch -- a registered "
                         "generator's output may not live in the committed "
                         "tree" % path)
    a = os.path.abspath(path)
    mf = os.path.join(os.path.dirname(a), MANIFEST)
    try:
        with open(mf, encoding="utf-8") as fh:
            m = _js.load(fh)
    except (OSError, ValueError):
        m = {}
    m[os.path.normcase(a)] = {"generator": generator, "sha": _sha(a),
                              "token": run_token()}
    with open(mf, "w", encoding="utf-8") as fh:
        _js.dump(m, fh, indent=1, sort_keys=True)
    return a


def provenance(path):
    """The registered generator that created `path` THIS RUN, under scratch,
    with its CURRENT content -- or None."""
    a = os.path.abspath(path)
    if not is_scratch(a):
        return None
    try:
        with open(os.path.join(os.path.dirname(a), MANIFEST),
                  encoding="utf-8") as fh:
            e = _js.load(fh).get(os.path.normcase(a))
    except (OSError, ValueError):
        return None
    if not e or e.get("token") != os.environ.get(TOKEN_ENV):
        return None
    g = SCRATCH_GENERATORS.get(e.get("generator"))
    if g is None or not _fn.fnmatch(os.path.basename(a), g["pattern"]):
        return None
    if e.get("sha") != _sha(a):
        return None
    return e["generator"]


def _classify(benchset, path):
    """Does `path` have a clocked open-drain lane? ⛔ ANY exception REFUSES the
    run, naming the image (Wilson 10-19, 4b): a classifier that cannot decide
    must never read as "not clocked". The pre-fix rule raised
    ZeroSpacingError on run_wirefeed_mf's delay-0 image; only the record-mode
    recorder (scratch copy) ever saw it, and it swallowed it."""
    try:
        return benchset.has_clocked_od_lane(path)
    except Exception as exc:                         # noqa: BLE001  re-raised
        raise SimRefused("sim_run REFUSED: classifying %s failed (%s: %s) -- "
                         "an image that cannot be classified does not run"
                         % (path, type(exc).__name__, exc)) from exc


# set at IMPORT, before the importing script starts any generator, so the
# generator's children and the later check share it
run_token()


def check(images):
    """Run the lookup on every image; return the stamp text. Raises
    SimRefused on a clocked image with no bound and no registered
    provenance."""
    if images is None or isinstance(images, (str, bytes)):
        raise TypeError("sim_run: `images` must be a LIST of image paths "
                        "([] for a run that loads no program image)")
    import benchset
    by_path, by_sha = _universe_index()
    req, notes = [], []
    for img in images:
        a = os.path.abspath(img if os.path.isabs(img)
                            else os.path.join(ROOT, img))
        name = os.path.basename(a)
        if os.path.normcase(a) in by_path:
            target = a                               # a universe image
        else:
            twin = by_sha.get(_sha(a))
            if twin is not None:                     # a copy: ITS bound
                target = twin
                notes.append("%s=copy-of:%s" % (name, os.path.basename(twin)))
            else:                                    # a scratch image
                if not _classify(benchset, a):
                    continue
                gen = provenance(a)
                if gen is None:
                    raise SimRefused(
                        "sim_run REFUSED: %s has a clocked open-drain lane, is "
                        "not a universe image or a copy of one, and was not "
                        "created this run under scratch by a registered "
                        "generator (sim_run.SCRATCH_GENERATORS)" % a)
                notes.append("%s=scratch:%s" % (name, gen))
                continue
        try:
            arg = benchset.a2_slack_arg(_rel(target))
        except RuntimeError as exc:
            raise SimRefused("sim_run REFUSED: %s" % exc) from None
        except Exception as exc:                     # noqa: BLE001  re-raised
            raise SimRefused("sim_run REFUSED: the bound lookup for %s failed "
                             "(%s: %s) -- a lookup that cannot finish refuses"
                             % (a, type(exc).__name__, exc)) from exc
        if arg is not None:
            req.append(name)
    names = [os.path.basename(_rel(i)) for i in images]
    return "sim_run: images=%s bound=%s%s" % (
        ",".join(names) or "-",
        ("ok(%s)" % ",".join(req)) if req else "not-required",
        (" " + " ".join(notes)) if notes else "")


def argv(cmd, images):
    """`cmd` unchanged, after the lookup. THE function every run takes its
    command from."""
    stamp = check(images)
    # ⛔ STDOUT, the caller's own stream: on stderr (unbuffered) beside the
    # caller's block-buffered stdout, a stamp landed MID-LINE in the combined
    # log -- measured, 1 of 301 in the identity run; on a pass-token line that
    # would turn a gate red. Same stream = same order, whole lines.
    print(stamp, flush=True)
    return list(cmd)


def images_in(args):
    """The `+IMG=` images in a run's own argument list -- for callers whose
    arguments arrive as an opaque list, so the images passed are exactly the
    ones the run will load. ⚠ An image a bench `$readmemh`s by a HARDCODED
    path, or binds at compile time, is not in any plusarg; such callers name
    it themselves."""
    # +IMG= everywhere; tb_reload also reads +IMG0= (its first program)
    return [a.split("=", 1)[1] for a in args
            if isinstance(a, str) and a.startswith(("+IMG=", "+IMG0="))]


def hardcoded_images(bench):
    """Images a testbench `$readmemh`s by a HARDCODED path (no plusarg), read
    from its source -- so a caller running it names them without typing them.
    `bench` is a top name (`tb_edge`) or a repo-relative path to the .v."""
    import re
    if not bench.endswith(".v"):
        bench = os.path.join("test", bench + ".v")
    p = bench if os.path.isabs(bench) else os.path.join(ROOT, bench)
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    # (1) `$readmemh("x.hex", ...)` literals; (2) the image a bench falls back
    # to when no +IMG / +IMG0 is given (`imgfile = "x.hex"`). (2) is named even
    # when the caller does pass +IMG -- over-approximate, the safe direction.
    lits = re.findall(r'\$readmem[hb]\s*\(\s*"([^"]+\.hex)"', src)
    dflt = re.findall(r'\b(?:imgfile|img0)\s*=\s*"([^"]+\.hex)"', src)
    return lits + [d for d in dflt if d not in lits]


def vvp(args, images):
    """`[vvp] + args`, after the lookup -- the ONLY place a `vvp` command is
    built (gate_sim_runs: `tool("vvp")` anywhere else is red)."""
    from toolchain import tool
    return argv([tool("vvp")] + list(args), images)


def cli_images(items):
    """The shell form's image list: `--bench TOP` adds that bench's hardcoded
    / default images; an item starting with `+` is a run plusarg whose
    `+IMG=` / `+IMG0=` value is taken (`images_in`); anything else is an
    image path."""
    out, it = [], iter(items)
    plus = []
    for a in it:
        if a == "--bench":
            out += hardcoded_images(next(it, ""))
        elif a.startswith("+"):
            plus.append(a)
        else:
            out.append(a)
    return out + images_in(plus)


def main(args):
    if not args or args[0] != "check":
        print("usage: sim_run.py check [--bench TOP] [+PLUSARG ...] [image ...]",
              file=sys.stderr)
        return 2
    # ⛔ SILENT ON A PASS in the shell form: the run's own redirection
    # (`> log 2>&1`) wraps sim_exec, so a stamp here would land INSIDE the
    # simulation's output and change it -- measured: every gate_xsim
    # comparison differed at line 1. A refusal is loud (exit 3, the image
    # named) and the run never starts.
    try:
        check(cli_images(args[1:]))
    except SimRefused as exc:
        print("*** %s" % exc, file=sys.stderr, flush=True)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
