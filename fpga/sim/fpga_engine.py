"""THE FPGA BENCHES' ENGINE SWITCH -- iverilog (certifying) or Verilator (development).

    PE_SIM=verilator python fpga/sim/run_fpga_loader.py      (likewise _i2c, _onewire)

⛔⛔ WHY (Wilson 11-10). The loader gate took 47m49s in CI -- four iverilog
simulations of the whole FPGA core at the board clock -- over the meta-test's
30-min seam limit, so its stub row had to leave SEAMS as a DEBT. The benches
are not too long; the ENGINE is slow. Verilator runs the same bench, unedited,
in seconds (one loader scenario: 13 s against ~11 min on iverilog).

⇒ Verilator is the DEVELOPMENT engine, as for the PIT benches (Wilson 11-05,
  `test/run_pit_capture.py`): iverilog stays the default here and the
  CERTIFYING engine at the lock. Nothing in a bench changes: frames, idle
  times, scenarios are the same text on both engines.
⇒ Parameters: iverilog takes the bench's own parameters with `-P` and the
  core's (`dut.X`) through a second root module of `defparam`s. Verilator
  allows ONE top, so a generated wrapper `vtop` instantiates the bench under
  its own name and carries every override as a `defparam` -- the same
  hierarchical names, the same values.
⇒ The binary: the pinned Verilator (toolchain: `PE_VERILATOR`, else the
  pinned WSL build). Native where this machine has one (CI), else WSL. Each
  build is cached by the sources' hash + top + overrides + Verilator, so a
  rerun builds nothing.
⇒ The run: through `sim_run.argv` (the one place a run's command is made),
  from the repository root, so the benches' relative image paths resolve the
  same on both engines.
"""
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "test"))
import sim_run                                   # noqa: E402
import toolchain                                 # noqa: E402

SIM = os.environ.get("PE_SIM", "iverilog")
if SIM not in ("iverilog", "verilator"):
    raise SystemExit("*** PE_SIM=%r: want iverilog or verilator" % SIM)

VL_FLAGS = ["--binary", "--timing", "-O3", "-j", "8", "-Wno-fatal", "-Wno-lint", "-Wno-style"]
#: every source a bench build can read: hashed into the cache key
_SRC_DIRS = ("src", os.path.join("fpga", "sim"), os.path.join("fpga", "rtl"), "test")


def iverilog_only(bench, why):
    """⛔ A bench that is NOT bit-exact on Verilator refuses it, loudly.
    PE_SIM=verilator is shared with the PIT benches (a development run sets it
    for the whole suite); without this, such a run would turn this gate red
    for a reason that is the engine's, not the design's."""
    if SIM == "verilator":
        raise SystemExit("*** %s: PE_SIM=verilator refused -- %s. This bench "
                         "runs on iverilog only (unset PE_SIM)." % (bench, why))


def _native_vl():
    return toolchain.tool_or_none("verilator")


def _wsl(p):
    p = os.path.abspath(p).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def _vl():
    """(verilator path, shell prefix, path translator)"""
    v = _native_vl()
    if v:
        return v, [], lambda p: os.path.abspath(p).replace("\\", "/")
    return toolchain.PINNED_WSL_VERILATOR, ["wsl", "-d", "Ubuntu", "--exec"], _wsl


def banner_line():
    v, pre, _t = _vl()
    print("  engine   : %s  (%s)  %s" % (SIM, v if not pre else "WSL " + v,
                                         toolchain.version_of(pre + [v, "--version"])))


def _key(top, srcs, overrides, v):
    h = hashlib.sha256()
    for d in _SRC_DIRS:
        for f in sorted(os.listdir(os.path.join(ROOT, d))):
            if f.endswith((".v", ".vh")):
                h.update(f.encode() + b"\0" + open(os.path.join(ROOT, d, f), "rb").read())
    h.update(repr((top, list(srcs), sorted(overrides.items()), v, VL_FLAGS)).encode())
    return h.hexdigest()[:16]


def vl_build(top, srcs, overrides, subs=()):
    """Build `top` on Verilator with `overrides` {hierarchical name below the
    bench (`X` or `dut.X`): value text}; return the binary's path (as the
    runner's shell sees it).

    `subs` [(source, landmark, replacement)]: an override of a parameter the
    bench ALREADY connects on the instance line (`#(.IMG("..."))`). iverilog's
    defparam wins over that connection; Verilator refuses it ("Duplicate
    parameter connection"). So the build compiles a SCRATCH COPY of that
    source with the one connection substituted (toolchain.scratch_sub: the
    landmark exactly once, in live code) -- the tracked bench is untouched and
    the value is the defparam's."""
    v, pre, tr = _vl()
    srcs = list(srcs)
    for src, a, b in subs:
        txt = open(os.path.join(ROOT, src), encoding="utf-8").read()
        new = toolchain.scratch_sub(txt, a, b, "fpga_engine %s" % src)
        d = os.path.join(ROOT, "probe_fpga_vl")
        os.makedirs(d, exist_ok=True)
        cp = os.path.join(d, "%s_%s" % (hashlib.sha256(new.encode()).hexdigest()[:12],
                                       os.path.basename(src)))
        with open(cp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
        srcs[srcs.index(src)] = os.path.relpath(cp, ROOT).replace("\\", "/")
    key = _key(top, srcs, overrides, v)
    wrap = ["`timescale 1ns / 1ps", "module vtop;", "  %s %s ();" % (top, top)]
    wrap += ["  defparam %s.%s = %s;" % (top, k, val) for k, val in sorted(overrides.items())]
    wrap += ["endmodule", ""]
    root = tr(ROOT)
    sh = ('set -e; B="$HOME/vlcache_fpga/%s"; if [ ! -x "$B/vtb" ]; then '
          'rm -rf "$B.p$$"; mkdir -p "$B.p$$"; cat > "$B.p$$/vtop.v" <<\'VTOP\'\n%s\nVTOP\n'
          'cd %s; %s %s -I. --top-module vtop -Mdir "$B.p$$" -o vtb "$B.p$$/vtop.v" %s '
          '> "$B.p$$/build.log" 2>&1 || { tail -30 "$B.p$$/build.log"; exit 1; }; '
          'mv -T "$B.p$$" "$B" 2>/dev/null || rm -rf "$B.p$$"; fi; echo "$B/vtb"') % (
        key, "\n".join(wrap), root, v, " ".join(VL_FLAGS), " ".join(srcs))
    r = subprocess.run(pre + ["bash", "-c", sh], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("*** verilator build failed (%s)\n%s" % (top, (r.stdout + r.stderr)[-1500:]))
    return r.stdout.strip().splitlines()[-1]


def vl_run(binary, images, log):
    """Run a Verilator build from the repository root; its output -> `log`."""
    _v, pre, tr = _vl()
    cmd = (pre[:-1] + ["--cd", tr(ROOT), "--exec"] if pre else []) + [binary]
    r = subprocess.run(sim_run.argv(cmd, images), cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    with open(log, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(r.stdout + r.stderr)
    return r
