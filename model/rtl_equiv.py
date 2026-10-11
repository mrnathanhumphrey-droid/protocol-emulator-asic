"""RTL EQUIVALENCE -- the standing witness for a change that must move nothing.

Wilson's ruling (replacing the netlist-hash witness): a declaration-only RTL
change is proven by FORMAL EQUIVALENCE, not by hashing the netlist.
⛔ WHY NOT THE HASH. yosys's private net names follow DECLARATION ORDER, so the
portability fix (declarations moved ahead of first use) changed the
source-location-free netlist hash 989b0158 -> 96d09e6c while the cell
statistics stayed identical: the witness Wilson first named could not certify
the very change it was named for.

CONDITIONS (Wilson):
  * SCOPE: the whole `tt_um_protocol_emulator` top, flattened, both sides
    synthesised exactly as test/local_netlist.sh -- every output and every flop
    matched, not just pe_engine.
  * STRICTNESS: the verdict is yosys's `equiv_status -assert` exit status; one
    unproven $equiv cell fails the run. Counts printed are informative only.
  * MUST-FIRE: `--must-fire` plants a one-bit functional change (one term
    inverted, in project.v) and the run must FAIL with unproven cells.

Usage:  python model/rtl_equiv.py --base <git rev> [--must-fire]
Writes only under formal/build/ (gitignored).
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["pe_store.v", "pe_engine.v", "project.v"]
PLANT = ("wire miso_oe_d = e_pin_oe[MISO_PIN] & run & ~uio_q1[CS_PIN];",
         "wire miso_oe_d = e_pin_oe[MISO_PIN] & run &  uio_q1[CS_PIN];")

YS = """\
{reads_gold}
hierarchy -top tt_um_protocol_emulator
synth -top tt_um_protocol_emulator -flatten
rename tt_um_protocol_emulator gold
design -stash gold
{reads_gate}
hierarchy -top tt_um_protocol_emulator
synth -top tt_um_protocol_emulator -flatten
rename tt_um_protocol_emulator gate
design -stash gate
design -copy-from gold -as gold gold
design -copy-from gate -as gate gate
equiv_make gold gate equiv
hierarchy -top equiv
async2sync
equiv_simple -seq 5
equiv_induct -seq 5
equiv_status -assert
"""


def wsl_path(p):
    p = os.path.abspath(p)
    d, rest = os.path.splitdrive(p)
    return "/mnt/%s%s" % (d[0].lower(), rest.replace("\\", "/"))


def run_yosys(script_path, log_path):
    # ruling V: the one resolver (PE_YOSYS, then PATH), never a bare lookup
    sys.path.insert(0, os.path.join(ROOT, "test"))
    from toolchain import tool_or_none
    native = tool_or_none("yosys")
    if native and os.name != "nt":
        cmd = [native, "-s", script_path]
    else:
        # this box: yosys lives in WSL (the pinned resolver, ci/tools.sh).
        # ⛔ A SCRIPT FILE, NOT `bash -c`: inline quoting through wsl.exe lost
        # `$YS` on the first run (exit 127, yosys never ran).
        sh = os.path.join(os.path.dirname(script_path), "run_yosys.sh")
        with open(sh, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("cd %s || exit 2\n. ci/tools.sh\ntool_banner yosys\n"
                     "\"$YS\" -s %s\n" % (wsl_path(ROOT), wsl_path(script_path)))
        cmd = ["wsl.exe", "--", "bash", wsl_path(sh)]
    with open(log_path, "w", encoding="utf-8") as fh:
        r = subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--must-fire", action="store_true")
    a = ap.parse_args()
    base = subprocess.run(["git", "rev-parse", "--short", a.base], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    if not base:
        raise SystemExit("bad --base %s" % a.base)
    tag = "%s_vs_%s" % (base, "mustfire" if a.must_fire else "worktree")
    out = os.path.join(ROOT, "formal", "build", "equiv_" + tag)
    gold, gate = os.path.join(out, "gold"), os.path.join(out, "gate")
    for d in (gold, gate):
        os.makedirs(d, exist_ok=True)
    for f in FILES:
        txt = subprocess.run(["git", "show", "%s:src/%s" % (base, f)], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8").stdout
        if not txt:
            raise SystemExit("cannot read %s:src/%s" % (base, f))
        with open(os.path.join(gold, f), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)
        with open(os.path.join(ROOT, "src", f), encoding="utf-8") as fh:
            cur = fh.read()
        if a.must_fire and f == "project.v":
            if PLANT[0] not in cur:
                raise SystemExit("must-fire plant site not found in src/project.v")
            cur = cur.replace(PLANT[0], PLANT[1], 1)
        with open(os.path.join(gate, f), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(cur)

    def reads(d):
        return "\n".join("read_verilog %s" % wsl_path(os.path.join(d, f))
                         if os.name == "nt" else "read_verilog %s" % os.path.join(d, f)
                         for f in FILES)
    ys = os.path.join(out, "equiv.ys")
    with open(ys, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(YS.format(reads_gold=reads(gold), reads_gate=reads(gate)))
    log = os.path.join(out, "equiv.log")
    print("RTL EQUIVALENCE -- %s (gold) vs %s (gate), top tt_um_protocol_emulator"
          % (base, "worktree src/ + PLANTED one-bit inversion" if a.must_fire
             else "worktree src/"))
    rc = run_yosys(ys, log)
    tail = [l.strip() for l in open(log, encoding="utf-8", errors="replace")
            if "equiv cells" in l or "Of those cells" in l
            or "successfully proven" in l or "ERROR" in l]
    for l in tail[-3:]:
        print("  " + l)
    text = open(log, encoding="utf-8", errors="replace").read()
    import re
    # yosys reached equiv_status: a pass prints the summary; an -assert
    # failure prints ONLY "ERROR: Found N unproven $equiv cells in
    # 'equiv_status -assert'" (the first parser missed it and called a real red
    # "never ran")
    m = re.findall(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
    fa = re.findall(r"Found (\d+) unproven \$equiv cells in 'equiv_status -assert'", text)
    if fa and not m:
        m = [("?", fa[-1])]
    # ⛔⛔ WILSON: A VERDICT IS AN EXPLICIT POSITIVE TOKEN FROM THE TOOL, never
    # the absence of a failure. Both false greens here had that shape (yosys
    # never ran; an error line missed). PASS needs the yosys version banner AND
    # "Equivalence successfully proven"; RED (the must-fire) needs the banner AND
    # yosys's own -assert failure line. A missing token is neither.
    # the version banner: `tool_banner yosys` prints it first on every run;
    # yosys's own end-of-run line carries it only on success
    banner = re.search(r"Yosys \d+\.\d+ \(git sha1 [0-9a-f]+", text) is not None
    ran = bool(m) and banner   # ⛔ yosys ran, and reached equiv_status
    proven = (rc == 0 and ran and "Equivalence successfully proven" in text)
    print("  equiv_status -assert exit: %d%s" % (
        rc, "" if ran else "  *** equiv_status NEVER RAN -- this is not a verdict"))
    if a.must_fire:
        # ⛔⛔ POSITIVE EVIDENCE ONLY. The first version counted ANY non-zero
        # exit as "red", and yosys not running at all (exit 127) passed the
        # must-fire: a guard passing because of the defect. Red now means
        # equiv_status RAN and reported unproven cells.
        ok = (ran and bool(fa) and int(fa[-1]) > 0 and rc != 0
              and "Equivalence successfully proven" not in text)
        print("  MUST-FIRE: %s" % ("red  ok -- the planted inversion left cells "
                                   "unproven" if ok else
                                   "*** STAYED GREEN -- the witness cannot see a "
                                   "one-bit change"))
    else:
        ok = proven
        print("  RTL EQUIVALENCE: %s" % ("PROVEN -- the change moves nothing"
                                         if ok else "*** NOT PROVEN"))
    print("  log: %s" % log)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
