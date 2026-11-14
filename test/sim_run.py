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

⭐ AND IT ENFORCES (queue 3b, Wilson: "bound exists but isn't enforced is half
a guarantee"). When exactly one image of a run has a bound record, its
`+A2SLACK` is APPENDED to the run unless the command already carries one (the
sweep's arms, a2_run.sh's deliberately light arm). Two different bounded
images in one run are refused as ambiguous. The rewire commit only checked,
because point 5 forbade changing outputs there; this one changes them on
purpose, arm by arm, against a stamped prediction
(probe_reports/a2slack_injection_prediction.txt).

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
    "run_fpga_loader": {
        "script": "fpga/sim/run_fpga_loader.py", "pattern": "ldmf_*.hex",
        "clocked": True,
        "why": "F1.5 (Wilson 11-09): the board's UART image with its v2 MAGIC "
               "corrupted, booted by the FPGA glue -- judged by the CHIP's "
               "refusal (bad_magic, CONFIG_ERR, no frames back), not by the "
               "A2 gap; it never runs",
        "v3": {"no_v3_layer": "fpga/sim/tb_fpga_loader.v"}},
    "gate_clock_cross": {
        "script": "model/gate_clock_cross.py", "pattern": "probe_xclk_*.hex",
        "clocked": True,
        "why": "the shipped programs assembled at BOTH targets' clocks (Wilson "
               "11-03), run on tb_xclock with no peer and judged in "
               "nanoseconds against each other -- not the A2 gap",
        "v3": {"no_v3_layer": "test/tb_xclock.v"}},
    "make_smoke_image --ckhalf": {
        "script": "test/make_smoke_image.py", "pattern": "probe_*.hex",
        "clocked": True,
        "why": "the F1 phase instrument with every lane HALF_HIGH, for "
               "phases_run.sh / gate_um10204: it measures t_HIGH / t_LOW / "
               "t_SU;DAT / t_HD;DAT against UM10204, not the A2 gap",
        "v3": ["phases_run: probe_ckhalf.hex"]},
    "run_ckack": {
        "script": "test/run_ckack.py", "pattern": "ckack*.hex",
        "clocked": True,
        "why": "the clocked I2C random read against a stretching peer "
               "(ruling ACK): judged by chip bytes == sigrok bytes at every "
               "stretch, and by its v3_table row",
        "v3": ["run_ckack: ckack.hex", "run_ckack: ckack_half.hex"]},
    "run_cktx": {
        "script": "test/run_cktx.py", "pattern": "cktx.hex",
        "clocked": True,
        "why": "TX4's clocked widths 1..8 image: judged by Layer V2/V3 "
               "against its v3_table row",
        "v3": ["run_cktx: cktx.hex"]},
    "run_reload": {
        "script": "test/run_reload.py", "pattern": "i2c_write.hex",
        "clocked": True,
        "why": "tb_reload's I2C write program: judged by the FRAM bytes "
               "written across a reload, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_reload.v"}},
    "gate_v2_equiv": {
        "script": "model/gate_v2_equiv.py", "pattern": "v2eq_*.hex",
        "clocked": True,
        "why": "v2 step 2's equivalence gate: translate(v1 image) variants --"
               " falloff, the cleared-magic refusal, the encoding must-fires --"
               " judged by v1 == v2 on tb_equiv's decoded dispatch + pin"
               " stream, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_equiv.v"}},
    "run_branch_check": {
        "script": "test/run_branch_check.py", "pattern": "brchk_*.hex",
        "clocked": True,
        "why": "v2 primitive 1's branch corpus (test/branch_corpus.py) and its"
               " packed-past-the-encoder refusal arms: judged by"
               " branch_check.vh's PC / head / stall counters on tb_equiv,"
               " not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_equiv.v"}},
    "run_arm2": {
        "script": "test/run_arm2.py", "pattern": "arm2_*.hex",
        "clocked": True,
        "why": "v2 primitive 3 bundle 1: the two-pin level ARM's scenario"
               " images, judged cycle for cycle against run_arm2's golden"
               " (fire = max(armed, last drive + 2), out = fire + the edge"
               " ARM's K) on tb_arm2, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_arm2.v"}},
    "run_pair": {
        "script": "test/run_pair.py", "pattern": "pair_*.hex",
        "clocked": True,
        "why": "v2 primitive 3 bundle 2: the pin pair / SHIFTI / self-timed byte"
               " images, judged cycle for cycle against run_pair's golden"
               " waveform on tb_pair, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_pair.v"}},
    "run_usbbuf": {
        "script": "test/run_usbbuf.py", "pattern": "usbbuf_*.hex",
        "clocked": True,
        "why": "v2 primitive 3 bundle 5: the response buffer / READY / IN-DATA-ACK"
               " images, judged by the device's packets bit for bit against"
               " run_usbbuf's golden on tb_usbbuf, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_usbbuf.v"}},
    "run_usbaddr": {
        "script": "test/run_usbaddr.py", "pattern": "usbaddr_*.hex",
        "clocked": True,
        "why": "v2 primitive 3 bundle 6: the USB device program (address, token"
               " check, decisions after the packet), judged by the device's"
               " packets bit for bit and its address/READY changes against"
               " usbdev's golden on tb_usbdev, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_usbdev.v"}},
    "run_usbrst": {
        "script": "test/run_usbrst.py", "pattern": "usbrst_*.hex",
        "clocked": True,
        "why": "v2 primitive 3 bundle 6: the bus reset / fence / reset notice"
               " images, judged against usbdev's golden on tb_usbdev, not by"
               " the A2 gap",
        "v3": {"no_v3_layer": "test/tb_usbdev.v"}},
    "run_usbcrc": {
        "script": "test/run_usbcrc.py", "pattern": "usbcrc_*.hex",
        "clocked": True,
        "why": "v2 primitive 3 bundle 4: the USB RX CRC16 + virtual-pin flags image,"
               " judged by its ACK/NAK decisions and branch flags against"
               " run_usbcrc's golden on tb_usbrx, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_usbrx.v"}},
    "run_usbrx": {
        "script": "test/run_usbrx.py", "pattern": "usbrx_*.hex",
        "clocked": True,
        "why": "v2 primitive 3 bundle 3: the USB receive images (NRZI, unstuffing,"
               " re-anchoring), judged byte for byte against run_usbrx's golden"
               " decode of the host line it drives on tb_usbrx, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_usbrx.v"}},
    "gate_usb_sweep": {
        "script": "model/gate_usb_sweep.py", "pattern": "usbsweep_*.hex",
        "clocked": True,
        "why": "Wilson 11-13 condition 4: usb_nostall / usb_j2_nb / usb_br1_window measured"
               " on the admissible sweep (bytes, J <= 2, no stall, the 31-cycle window bound),"
               " judged by run_usbrx's golden on tb_usbrx, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_usbrx.v"}},
    "run_pit_capture": {
        "script": "test/run_pit_capture.py", "pattern": "pitcap_*.hex",
        "clocked": True,
        "why": "v2 PIT chunk 1: SNIFF images (the SN magic, a wire mask, an empty"
               " store) whose capture is judged byte for byte against"
               " model/pit_capture_golden.py, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_pit.v"}},
    "run_pit_rt": {
        "script": "test/run_pit_rt.py", "pattern": "rt_*_emu.hex",
        "clocked": True,
        "why": "v2 PIT item 2, the round trip (Wilson 11-06): the EMULATOR"
               " image pe_asm assembles from an emitted spec (SPI / I2C"
               " master), run on tb_rt beside a sniffing chip and judged by"
               " the sniffer's regenerated record against the original's"
               " claims, not by the A2 gap",
        "v3": {"no_v3_layer": "test/tb_rt.v"}},
}
# ⛔⛔ `v3` IS REQUIRED ON EVERY CLOCKED ENTRY (S1g, 10-22): the GENERATED
# names in model/v3_table.py that register this generator's images, or the
# bench that loads them and has no V3 layer (its include closure carries no
# clocked_conform.vh -- gate_wire_feed verifies that). `--ckhalf` had no row,
# V3-ID stopped both CE1 arms FATAL, and nothing static said so.

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
    return lookup(images)[0]


def lookup(images):
    """(stamp, the +A2SLACK plusarg to INJECT or None). Queue 3b (Wilson
    10-19): a bound that exists is ENFORCED -- when exactly one image of a run
    has a bound record, its plusarg is returned for the run; two different
    bounded images in one run are REFUSED as ambiguous."""
    if images is None or isinstance(images, (str, bytes)):
        raise TypeError("sim_run: `images` must be a LIST of image paths "
                        "([] for a run that loads no program image)")
    import benchset
    by_path, by_sha = _universe_index()
    req, notes, args = [], [], set()
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
            args.add(arg)
    if len(args) > 1:
        raise SimRefused("sim_run REFUSED: %d bounded clocked images in one run "
                         "(%s) -- which bound to enforce is ambiguous"
                         % (len(args), ", ".join(req)))
    names = [os.path.basename(_rel(i)) for i in images]
    stamp = "sim_run: images=%s bound=%s%s" % (
        ",".join(names) or "-",
        ("ok(%s)" % ",".join(req)) if req else "not-required",
        (" " + " ".join(notes)) if notes else "")
    return stamp, (next(iter(args)) if args else None)


def argv(cmd, images, must_fire=None, arm=None):
    """`cmd` after the lookup -- with the run's A2 bound APPENDED when exactly
    one of its images has one and `cmd` carries no +A2SLACK yet (queue 3b) --
    wrapped in the monitor judge (`wrap`). THE function every run takes its
    command from."""
    stamp, inject = lookup(images)
    cmd = list(cmd)
    if inject and not any(isinstance(c, str) and c.startswith("+A2SLACK=")
                          for c in cmd):
        cmd.append(inject)
        stamp += " a2=injected"
    # ⛔ STDOUT, the caller's own stream: on stderr (unbuffered) beside the
    # caller's block-buffered stdout, a stamp landed MID-LINE in the combined
    # log -- measured, 1 of 301 in the identity run; on a pass-token line that
    # would turn a gate red. Same stream = same order, whole lines.
    print(stamp, flush=True)
    return wrap(cmd, must_fire, arm)


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


def vvp(args, images, must_fire=None):
    """`[vvp] + args`, after the lookup -- the ONLY place a `vvp` command is
    built (gate_sim_runs: `tool("vvp")` anywhere else is red). `must_fire`:
    this arm's id in MONITOR_MUST_FIRE when it is red ON PURPOSE."""
    from toolchain import tool
    return argv([tool("vvp")] + list(args), images, must_fire)


# =============================================================================
# THE MONITOR JUDGE (Wilson 11-14, coverage step 2 item 3). A monitor a bench
# `include`s (progress.vh layer A, clocked_conform, rx_e2e, the s12
# assertions, ...) prints `*** FAIL` / `*** ASSERT` into the run's output --
# and NOTHING READ IT: run_usbbuf / run_usbaddr / run_usbrst printed
# progress.vh[A] FAILs on every run and stayed green, because each runner
# parses only its own result lines. A per-runner rule rots the way the
# orphaned runners did, so the judging is HERE, on the one path every run takes:
#   * every run's command is wrapped in `sim_run.py judge` -- the simulator's
#     stdout / stderr pass through UNCHANGED and its exit code is kept, so no
#     caller's parse or output moves -- and every monitor FAIL line is written
#     to a LEDGER under the run's SCOPE (the top-level runner, or the gate
#     ci/run_gates.sh is running);
#   * a monitor FAIL is RED unless the arm is declared in MONITOR_MUST_FIRE
#     (ONE list) AND the FAIL is exactly the declared one; a declared arm whose
#     expected FAIL does NOT appear is red too (it must prove it fired);
#   * the verdict: the top-level Python runner's exit (an `atexit` hook, so no
#     runner is edited to get it) and ci/run_gates.sh per gate (`sim_run.py
#     verdict`), which also covers the shell runners (`sim_exec` wraps too).
# Runners keep parsing their own result lines on top of this.
# =============================================================================
import re as _re_m


def _monitor_tags():
    """Every `*** FAIL <tag>` a test/*.vh monitor prints -- read from the
    files, so a new monitor joins by itself."""
    import glob
    tags = set()
    for f in glob.glob(os.path.join(HERE, "*.vh")):
        with open(f, encoding="utf-8", errors="replace") as fh:
            tags |= set(_re_m.findall(r"\*\*\* FAIL ([A-Za-z0-9_.]+)", fh.read()))
    return tags


MONITOR_TAGS = _monitor_tags()
#: a monitor line: `*** FAIL <a monitor's tag>` or the RTL's `*** ASSERT `
_MON_RE = _re_m.compile(r"^\s*\*\*\* (?:ASSERT |FAIL (?:%s)(?![A-Za-z0-9_]))"
                        % "|".join(sorted(_re_m.escape(x) for x in MONITOR_TAGS)))


def monitor_fails(text):
    """The monitor FAIL / ASSERT lines in a run's output."""
    return [ln.strip() for ln in text.splitlines() if _MON_RE.match(ln)]


#: THE ONE DECLARATION LIST (Wilson 11-14, option (b)): the must-fire arms,
#: keyed on each arm's IDENTITY. `test/monitor_mustfire.py` holds the data
#: (MUST_FIRE, CLEAN_BUILD_EXCEPTIONS); this module judges it. Each entry:
#:   runner   repo-relative script the arm runs under (the gate, or the script
#:            that built the command)
#:   build    the EXACT compiled-bench basename -- a mutant / variant build is
#:            named for what it was built with -- never a pattern
#:   define   the define that build carries (checked to exist in the sources
#:            and to be named by the runner); None ONLY for a
#:            CLEAN_BUILD_EXCEPTIONS id
#:   plusargs plusargs that must ALL be present (a plusarg-selected arm)
#:   image    the exact image basename, optional
#:   expect   a regex EVERY monitor line of the run must match (>= 1 must)
#:   why      why the arm is red on purpose
#: NARROW BY CONSTRUCTION: no build and no plusargs is red (over-broad), a
#: clean-build entry outside the listed exceptions is red (the guard), and an
#: entry no run matched in a full gate pass is STALE, red.
import monitor_mustfire as _MMF                                   # noqa: E402
MONITOR_MUST_FIRE = _MMF.MUST_FIRE
CLEAN_BUILD_EXCEPTIONS = _MMF.CLEAN_BUILD_EXCEPTIONS
RUNNER_ENV = "SIM_RUN_RUNNER"

#: "record" writes the ledger and reports; "enforce" also turns the scope red.
#: ENFORCE since the full inventory landed (Wilson 11-14); SIM_RUN_MONITORS=record for an inventory run.
MONITOR_MODE = os.environ.get("SIM_RUN_MONITORS", "enforce")   # ENFORCE (Wilson 11-14): the full inventory landed
SCOPE_ENV, LEDGER_ENV = "SIM_RUN_SCOPE", "SIM_RUN_LEDGER"


def _ledger_path(scope):
    """The scope's ledger DIRECTORY: one record file per run."""
    import tempfile
    return os.environ.get(LEDGER_ENV) or os.path.join(
        tempfile.gettempdir(), "sim_run_ledger_%s" % scope)


_OWN_SCOPE = []


def _scope():
    """This run's judging scope: inherited from a parent runner / gate, else
    opened here -- and then THIS process judges it at exit."""
    s = os.environ.get(SCOPE_ENV)
    if not os.environ.get(RUNNER_ENV):
        os.environ[RUNNER_ENV] = _caller()
    if not s:
        s = "py%d-%s" % (os.getpid(), _hl.sha256(os.urandom(8)).hexdigest()[:8])
        os.environ[SCOPE_ENV] = s
        _OWN_SCOPE.append(s)
        import atexit
        atexit.register(_judge_at_exit, s)
    return s


def _caller():
    """This process's script, repo-relative (the runner that builds a command)."""
    a = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    try:
        return os.path.relpath(a, ROOT).replace(os.sep, "/")
    except ValueError:
        return a.replace(os.sep, "/")


def entry_matches(e, r):
    """True if ledger record `r` is the arm entry `e` names (exact identity)."""
    if e.get("runner") not in (r.get("runner"), r.get("caller")):
        return False
    if e.get("build") and e["build"] not in r.get("builds", []):
        return False
    if e.get("image") and e["image"] != r.get("image"):
        return False
    pa = set(r.get("plusargs", []))
    if any(x not in pa for x in e.get("plusargs") or ()):
        return False
    return bool(e.get("build") or e.get("plusargs"))


def _src_text():
    import glob
    out = []
    for pat in (os.path.join(ROOT, "src", "*.v"), os.path.join(HERE, "*.v"),
                os.path.join(HERE, "*.vh"), os.path.join(ROOT, "model", "*.v")):
        for f in glob.glob(pat):
            with open(f, encoding="utf-8", errors="replace") as fh:
                out.append(fh.read())
    return "\n".join(out)


def guard_problems(entries=None, clean_ok=None, src_text=None):
    """[problem] for the declaration list itself (Wilson's guard): an entry with
    no build and no plusargs is OVER-BROAD; a clean-build entry (no define) is
    red unless its id is one of the listed exceptions; a declared define must
    exist in the sources and be named by its runner."""
    entries = MONITOR_MUST_FIRE if entries is None else entries
    clean_ok = CLEAN_BUILD_EXCEPTIONS if clean_ok is None else clean_ok
    src_text = _src_text() if src_text is None else src_text
    out = []
    for k, e in sorted(entries.items()):
        if not isinstance(e, dict):
            continue                     # a must_fire-id (legacy) entry
        if not (e.get("build") or e.get("plusargs")):
            out.append("%s: OVER-BROAD -- no build and no plusargs, it would cover every "
                       "arm of %s" % (k, e.get("runner")))
            continue
        if not e.get("expect") or not e.get("why"):
            out.append("%s: no expect / why" % k)
        d = e.get("define")
        if d is None:
            if k not in clean_ok:
                out.append("%s: a CLEAN-BUILD entry (no define) that is not one of the "
                           "listed exceptions -- it could cover a shipped image's clean arm" % k)
            continue
        # what a build was built WITH: an `ifdef` / -D macro in the sources, a
        # scratch source patch `S_*` (test/scratch_heads.py or the runner's own
        # table), or `patch:<function>` -- a patching function the runner defines
        name = d.split("=")[0]
        rp = os.path.join(ROOT, e.get("runner", ""))
        rtext = ""
        if os.path.isfile(rp):
            with open(rp, encoding="utf-8", errors="replace") as fh:
                rtext = fh.read()
        else:
            out.append("%s: runner %s does not exist" % (k, e.get("runner")))
        if name.startswith("patch:"):
            if not _re_m.search(r"^def %s\(" % _re_m.escape(name[6:]), rtext, _re_m.M):
                out.append("%s: %s -- the runner defines no such patch" % (k, d))
            continue
        known = _re_m.search(r"\b%s\b" % _re_m.escape(name), src_text)
        if not known and name.startswith("S_"):
            sh = os.path.join(HERE, "scratch_heads.py")
            known = name in rtext or (os.path.isfile(sh) and name in open(sh, encoding="utf-8").read())
        if not known:
            out.append("%s: define %s is in no source file and no scratch patch" % (k, d))
        if rtext and name not in rtext and not name.startswith("S_"):
            out.append("%s: runner %s never names define %s" % (k, e["runner"], name))
    for k in sorted(set(clean_ok) - set(entries)):
        out.append("CLEAN_BUILD_EXCEPTIONS names %s, which is not an entry" % k)
    return out


def judge_records(records, stale_for=None):
    """[problem] for ledger records (dicts) -- pure, so the must-fires price it.
    `stale_for`: runners for which these records are a FULL gate pass, so an
    entry of theirs that matched no run is STALE."""
    probs = []
    used, fired = set(), set()
    for r in records:
        mf, fails, what = r.get("must_fire"), r.get("fails", []), r.get("cmd", "")
        if mf:
            d = MONITOR_MUST_FIRE.get(mf)
            if d is None:
                probs.append("%s: must-fire id %r is not in MONITOR_MUST_FIRE" % (what, mf))
                continue
            rx = _re_m.compile(d["expect"] if isinstance(d, dict) else d[0])
            used.add(mf)
            if not any(rx.search(f) for f in fails):
                probs.append("%s: declared must-fire %s did NOT produce its FAIL (%s)"
                             % (what, mf, rx.pattern))
            probs += ["%s: must-fire %s produced an UNDECLARED monitor FAIL: %s"
                      % (what, mf, f) for f in fails if not rx.search(f)]
            continue
        hits = [k for k, e in MONITOR_MUST_FIRE.items()
                if isinstance(e, dict) and entry_matches(e, r)]
        if not hits:
            probs += ["%s: UNDECLARED monitor FAIL: %s" % (what, f) for f in fails]
            continue
        used.update(hits)
        rxs = [_re_m.compile(MONITOR_MUST_FIRE[k]["expect"]) for k in hits]
        # one mutant build runs several scenarios and only some trip a monitor
        # (the rest are judged by the runner's own lines): the entry must fire
        # at least ONCE over the pass, and no run may carry another FAIL
        if fails:
            fired.update(k for k, x in zip(hits, rxs) if any(x.search(f) for f in fails))
        probs += ["%s: must-fire %s produced an UNDECLARED monitor FAIL: %s"
                  % (what, "/".join(hits), f) for f in fails
                  if not any(x.search(f) for x in rxs)]
    for k in sorted(used - fired):
        if isinstance(MONITOR_MUST_FIRE.get(k), dict):
            probs.append("%s: declared must-fire matched its arm but NEVER produced its FAIL "
                         "(%s)" % (k, MONITOR_MUST_FIRE[k]["expect"]))
    for k, e in sorted(MONITOR_MUST_FIRE.items()):
        if (isinstance(e, dict) and stale_for and e.get("runner") in stale_for
                and k not in used):
            probs.append("%s: STALE -- no run of %s matched it in this gate pass"
                         % (k, e["runner"]))
    return probs


def ledger(scope, path=None):
    """The ledger records written under `scope`: one FILE per run in the
    scope's directory. ⛔ Not one appended file: runners that simulate in a
    POOL (run_pit_gcd) interleaved concurrent appends and corrupted a record
    (measured, 11-14) -- and a record nobody can read is a run nobody judged,
    so an unreadable record is itself reported as a monitor FAIL."""
    import glob
    import json
    d = path or _ledger_path(scope)
    out = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, ValueError) as exc:
            r = {"scope": scope, "must_fire": None, "cmd": os.path.basename(f),
                 "fails": ["*** FAIL sim_run ledger: unreadable record (%s)" % exc]}
        if r.get("scope") == scope:
            out.append(r)
    return out


def _report(scope, stale_for=None):
    probs = judge_records(ledger(scope), stale_for)
    if probs:
        print("*** sim_run monitors [%s]: %d monitor FAIL problem(s)%s:"
              % (MONITOR_MODE, len(probs),
                 "" if MONITOR_MODE == "enforce" else " (RECORD mode: not yet red)"),
              flush=True)
        for q in probs[:40]:
            print("    " + q, flush=True)
    return probs


def _judge_at_exit(scope):
    if scope not in _OWN_SCOPE:
        return
    probs = _report(scope)
    if probs and MONITOR_MODE == "enforce":
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)


def wrap(cmd, must_fire=None, arm=None):
    """`cmd` wrapped in the judge (the scope opened if this is the first run)."""
    _scope()
    return ([sys.executable, os.path.abspath(__file__), "judge", must_fire or "-",
             "--caller=" + _caller()] + (["--arm=" + arm] if arm else []) + ["--"]
            + list(cmd))


def unwrap(cmd):
    """The simulator command inside a `wrap` (for checks that compare it)."""
    cmd = list(cmd)
    if len(cmd) > 4 and cmd[2] == "judge" and "--" in cmd:
        return cmd[cmd.index("--") + 1:]
    return cmd


def _judge_main(args):
    """`judge <must_fire|-> -- cmd...`: run cmd, pass its output through
    unchanged, keep its exit code, and ledger its monitor FAIL lines."""
    import json
    import subprocess
    import threading
    mf = None if args[0] == "-" else args[0]
    caller = next((a.split("=", 1)[1] for a in args[1:args.index("--")]
                   if a.startswith("--caller=")), "")
    arm = next((a.split("=", 1)[1] for a in args[1:args.index("--")]
                if a.startswith("--arm=")), None)
    cmd = args[args.index("--") + 1:]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    fails = []

    def pump(src, dst):
        for raw in iter(src.readline, b""):
            dst.write(raw)
            dst.flush()
            if _MON_RE.match(raw.decode("utf-8", "replace")):
                fails.append(raw.decode("utf-8", "replace").strip())

    ts = [threading.Thread(target=pump, args=(proc.stdout, sys.stdout.buffer)),
          threading.Thread(target=pump, args=(proc.stderr, sys.stderr.buffer))]
    for th in ts:
        th.start()
    for th in ts:
        th.join()
    rc = proc.wait()
    scope = os.environ.get(SCOPE_ENV, "unscoped")
    # the arm's identity: the simulator, its compiled bench (a mutant build is
    # named for its define), and the image / scenario plusargs
    sims = [os.path.basename(str(c)) for c in cmd[1:3]
            if str(c).endswith((".vvp", ".sim", ".exe")) or os.sep in str(c) or "/" in str(c)]
    what = (os.path.basename(str(cmd[0])) + " " + " ".join(sims[:1]) + " " + " ".join(
        str(c) for c in cmd[1:] if str(c).startswith(("+IMG", "+SCEN", "+CASE", "+HOST")))).strip()
    # the arm's IDENTITY (Wilson 11-14): every plusarg, every file argument's
    # basename (the compiled bench -- a mutant build is named for its define),
    # the image, the gate (`runner`) and the script that built the command
    plus = [str(c) for c in cmd[1:] if str(c).startswith("+")]
    builds = [os.path.basename(str(c).replace("\\", "/")) for c in cmd[1:]
              if not str(c).startswith(("+", "-"))
              and ("/" in str(c) or "\\" in str(c) or "." in os.path.basename(str(c)))]
    if arm:
        builds.insert(0, arm)     # the runner's own name for this build
    img = next((os.path.basename(x.split("=", 1)[1].replace("\\", "/"))
                for x in plus if x.startswith("+IMG=")), None)
    try:
        d = _ledger_path(scope)
        os.makedirs(d, exist_ok=True)
        rec = os.path.join(d, "%d-%s.json" % (os.getpid(), _hl.sha256(os.urandom(8)).hexdigest()[:8]))
        with open(rec + ".tmp", "w", encoding="utf-8") as fh:
            json.dump({"scope": scope, "must_fire": mf, "fails": fails,
                       "cmd": what, "rc": rc, "runner": os.environ.get(RUNNER_ENV, ""),
                       "caller": caller, "builds": builds, "plusargs": plus,
                       "image": img}, fh)
        os.replace(rec + ".tmp", rec)       # the whole record or none
    except OSError as exc:
        print("*** sim_run judge: could not write the ledger (%s)" % exc,
              file=sys.stderr, flush=True)
        return rc or 98
    return rc


def _verdict_dry(args):
    """Judge a ledger directory (one record per file) or an old appended .jsonl
    (corrupt lines tolerated and counted) AS IF enforcing; `runner` fills the
    records that lack one. Exit 1 on any problem."""
    import glob
    import json
    src = args[0]
    runner = args[1] if len(args) > 1 else None
    recs, bad = [], 0
    # a DIRECTORY is the per-run ledger (even when it carries a legacy
    # `.jsonl` name, as the inventory drivers' ledgers do); a FILE is the old
    # appended format
    files = (sorted(glob.glob(os.path.join(src, "*.json"))) if os.path.isdir(src)
             else [src])
    for f in files:
        with open(f, encoding="utf-8") as fh:
            lines = fh.readlines() if f.endswith(".jsonl") else [fh.read()]
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                bad += 1
                continue
            if runner and not r.get("runner"):
                r["runner"] = runner
            recs.append(r)
    stale = {runner} if runner else {r.get("runner") for r in recs if r.get("runner")}
    probs = guard_problems() + judge_records(recs, stale)
    print("verdict-dry %s: %d run(s), %d unreadable, %d problem(s)"
          % (os.path.basename(src.rstrip("/\\")), len(recs), bad, len(probs)))
    for q in probs[:60]:
        print("    " + q)
    return 1 if probs or bad else 0


def trace_incomplete(out, cmd):
    """None if a tb_trace run FINISHED, else why not. ⛔⛔ R3 (10-23): every
    layer's verdict line prints from a `final` block, which runs on ANY
    $finish, so a run stopped a third of the way through still prints
    "ok --" lines (MEASURED: 10-15 per arm). Finished means no FATAL line and
    tb_trace's normal-path line with the cycles that RAN equal to the run's
    own `+NCYC` -- read from `cmd`, the very list handed to the bench, so the
    check can never carry a second constant. The shell form is ci/tools.sh's
    `trace_completed`. `*** FAIL` lines are NOT judged: a must-fire arm is red
    on purpose."""
    import re as _re
    ncyc = [a.split("=", 1)[1] for a in cmd if str(a).startswith("+NCYC=")]
    if not ncyc:
        return "no +NCYC on the command line, so completion is undefined"
    if "FATAL" in out:
        return "the bench stopped FATAL: %s" % next(
            l.strip() for l in out.splitlines() if "FATAL" in l)[:120]
    m = _re.search(r"^tb_trace: (\d+) cycles", out, _re.M)
    if m is None:
        return "no 'tb_trace: N cycles' line -- the bench did not reach its end"
    if m.group(1) != ncyc[-1]:
        return "ran %s of its planned %s cycles" % (m.group(1), ncyc[-1])
    return None


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
    if args and args[0] == "judge":
        return _judge_main(args[1:])
    if args and args[0] == "verdict":
        # ci/run_gates.sh, per gate: judge the gate's scope -- a FULL gate pass,
        # so the gate's own entries that matched nothing are STALE
        g = os.environ.get(RUNNER_ENV)
        probs = guard_problems() + judge_records(ledger(args[1]), {g} if g else None)
        if probs:
            print("*** sim_run monitors [%s]: %d problem(s)%s:" % (
                MONITOR_MODE, len(probs),
                "" if MONITOR_MODE == "enforce" else " (RECORD mode: not yet red)"))
            for q in probs[:40]:
                print("    " + q)
        return 1 if (probs and MONITOR_MODE == "enforce") else 0
    if args and args[0] == "verdict-dry":
        # `verdict-dry <ledger dir | old .jsonl> [runner]`: judge AS IF enforcing
        return _verdict_dry(args[1:])
    if not args or args[0] != "check":
        print("usage: sim_run.py check [--bench TOP] [+PLUSARG ...] [image ...]",
              file=sys.stderr)
        return 2
    # ⛔ SILENT ON A PASS in the shell form: the run's own redirection
    # (`> log 2>&1`) wraps sim_exec, so a stamp here would land INSIDE the
    # simulation's output and change it -- measured: every gate_xsim
    # comparison differed at line 1. A refusal is loud (exit 3, the image
    # named) and the run never starts.
    # (queue 3b) the ONE thing printed on a pass: the +A2SLACK plusarg to
    # inject, on stdout, which `sim_exec` CAPTURES -- so it never reaches the
    # run's log; it appends it unless the command already carries one.
    try:
        _stamp, inject = lookup(cli_images(args[1:]))
    except SimRefused as exc:
        print("*** %s" % exc, file=sys.stderr, flush=True)
        return 3
    if inject:
        print(inject, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
