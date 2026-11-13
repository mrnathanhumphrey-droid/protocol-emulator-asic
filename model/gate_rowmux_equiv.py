"""THE ROW-READ TREE'S TWO DESCRIPTIONS ARE ONE BLOCK (Wilson 11-02).

⛔⛔ WHY. `pe_rowmux` (src/pe_store.v) is written twice: a FLAT vector under
`ifdef SYNTHESIS` -- the text every canary hardened -- and an UNPACKED node array
for simulation, ~6.7x faster in iverilog (one PIT stage-0 sim 1,212.7 s flat,
182.0 s unpacked, byte-identical output). Two descriptions of one block drift
the first time someone edits one and forgets the other, so the proof that they
are equal runs on EVERY push, not once.

THE PROOF: Yosys `equiv_make` / `equiv_simple` / `equiv_induct` on the two texts,
read from the SHIPPED file (the module is lifted verbatim, then elaborated with
and without `SYNTHESIS`), at every SW the chip and the benches use.
⛔ THE SIZES ARE FOUND, NEVER STORED (the stored-number audit, 11-02): a list
typed here goes stale the day a bench adds a size. The CHIP's is elaborated --
yosys `hierarchy` on info.yaml's top and sources, because there SW is AW - WB_W,
an expression -- and each BENCH's is read from its `.SW(n)`; iverilog benches use
`$random`, which yosys cannot read. A bench instance whose SW is not a literal is
red, not skipped. (At 11-02: the chip 7; tb_rowmux 7, 4, 3.)
The tree is combinational, so the proof is complete -- every input, not a sample.

ARMS, per SW:  clean -> PROVEN (every $equiv cell proven, none unproven, and at
least the 8 output bits matched);  M_ROWMUX_NODE on the simulation text -> NOT
PROVEN (the must-fire: one level-1 node's children reversed).
⛔ A VERDICT IS READ FROM `equiv_status`, never the exit code alone; a log with no
status line is red (a run that did not reach the check proved nothing).
⛔ A MISSING TOOL IS `COULD NOT RUN`, and red. The tool is the pinned suite's
yosys, found the way gate_formal_miters finds its sby (`PE_SBY`, PATH, WSL).
POSITIVE TOKEN: `GATE rowmux-equiv: PASSED`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import gate_formal_miters as FM          # noqa: E402  (the suite resolver)

STORE = os.path.join(ROOT, "src", "pe_store.v")
INST = re.compile(r"\bpe_rowmux\s*#\s*\(")
LITERAL = re.compile(r"\bpe_rowmux\s*#\s*\(\s*\.SW\s*\(\s*(\d+)\s*\)\s*\)")
PARAMOD = re.compile(r"\$paramod\\pe_rowmux\\SW=s?32'([01]+)")
STATUS = re.compile(r"Of those cells (\d+) are proven and (\d+) are unproven")
FOUND = re.compile(r"Found (\d+) \$equiv cells")

SCRIPT = """read_verilog -sv -DSYNTHESIS rowmux.v
hierarchy -top pe_rowmux -chparam SW {sw}
proc
rename -top gold
design -stash gold
read_verilog -sv {defs} rowmux.v
hierarchy -top pe_rowmux -chparam SW {sw}
proc
rename -top gate
design -stash gate
design -copy-from gold -as gold gold
design -copy-from gate -as gate gate
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
equiv_induct
equiv_status
"""


def lift(text):
    """The `pe_rowmux` module, verbatim, from the shipped file."""
    i = text.find("module pe_rowmux")
    if i < 0:
        raise ValueError("no `module pe_rowmux` in src/pe_store.v")
    j = text.find("endmodule", i)
    if j < 0:
        raise ValueError("pe_rowmux has no `endmodule`")
    body = text[i:j + len("endmodule")]
    if "`ifdef SYNTHESIS" not in body or "`else" not in body:
        raise ValueError("pe_rowmux no longer has its two descriptions "
                         "(`ifdef SYNTHESIS ... `else)")
    return body + "\n"


def verdict(log, expect):
    """(ok, why) for one yosys run, read from equiv_status."""
    st = STATUS.findall(log)
    if not st:
        return False, "no `equiv_status` line -- the proof did not run to its check"
    proven, unproven = (int(x) for x in st[-1])
    found = FOUND.findall(log)
    n = int(found[-1]) if found else proven + unproven
    if expect == "PROVEN":
        if unproven == 0 and proven >= 8:
            return True, "PROVEN: %d of %d $equiv cells" % (proven, n)
        return False, "%d proven, %d UNPROVEN of %d" % (proven, unproven, n)
    if unproven > 0:
        return True, "NOT PROVEN, as required: %d unproven of %d" % (unproven, n)
    return False, "the mutant PROVED EQUAL (%d of %d) -- the proof cannot see a " \
                  "reversed node" % (proven, n)


def yosys_argv(how, sby, workdir, script):
    ydir = sby.rsplit("/", 1)[0] if how == "wsl" else os.path.dirname(sby)
    if how == "wsl":
        return ["wsl.exe", "--cd", FM.wslpath(workdir), "--", ydir + "/yosys",
                "-s", script]
    return [os.path.join(ydir, "yosys"), "-s", script]


def chip_sizes(how, sby, work):
    """The SWs the chip builds pe_rowmux at: info.yaml's top and sources,
    elaborated (`hierarchy` only), read from yosys's parameterised names."""
    info = open(os.path.join(ROOT, "info.yaml"), encoding="utf-8").read()
    top = re.search(r'^\s*top_module:\s*"([^"]+)"', info, re.M)
    block = re.search(r"^\s*source_files:\s*\n((?:\s*-\s*\"[^\"]+\"\s*\n)+)",
                      info, re.M)
    if not top or not block:
        raise ValueError("info.yaml: no top_module / source_files")
    path = (lambda p: FM.wslpath(p)) if how == "wsl" else (lambda p: p)
    files = [path(os.path.join(ROOT, "src", f)).replace("\\", "/")
             for f in re.findall(r'"([^"]+)"', block.group(1))]
    with open(os.path.join(work, "chip_sw.ys"), "w", encoding="utf-8",
              newline="\n") as fh:
        # ⭐ -DPE_MEM_LATCH (11-13): since Wilson 11-07 the default store is the
        # SRAM macro and pe_rowmux exists only in the LATCH fallback, which stays
        # selectable -- so the sizes are read from that build. With no define the
        # elaboration has no pe_rowmux at all and this gate went red (CI, 11-07 on).
        fh.write("read_verilog -sv -DPE_MEM_LATCH %s\nhierarchy -top %s\n" % (
            " ".join(files), top.group(1)))
    r = subprocess.run(yosys_argv(how, sby, work, "chip_sw.ys"), cwd=work,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    sws = {int(b, 2) for b in PARAMOD.findall(r.stdout + r.stderr)}
    if r.returncode or not sws:
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        raise ValueError("the chip's elaboration found no pe_rowmux size "
                         "(rc %d): %s" % (r.returncode, " | ".join(tail)))
    return sws


def bench_sizes():
    """{sw: [bench]} from every test/*.v that instantiates pe_rowmux; an
    instance whose SW is not a literal raises (red, not skipped)."""
    out = {}
    tdir = os.path.join(ROOT, "test")
    for f in sorted(os.listdir(tdir)):
        if not f.endswith(".v"):
            continue
        text = open(os.path.join(tdir, f), encoding="utf-8").read()
        n, lits = len(INST.findall(text)), LITERAL.findall(text)
        if n != len(lits):
            raise ValueError("test/%s: %d pe_rowmux instances, %d with a "
                             "literal .SW(n)" % (f, n, len(lits)))
        for sw in lits:
            out.setdefault(int(sw), []).append(f)
    return out


def mustfires_verdict():
    """The verdict reader itself: a log with no status line, and an unproven
    clean log, are both red."""
    bad = 0
    for label, log, expect in (
            ("no status line", "Found 8 $equiv cells in equiv:\n", "PROVEN"),
            ("unproven clean", "Found 8 $equiv cells\n Of those cells 7 are "
                               "proven and 1 are unproven.\n", "PROVEN"),
            ("mutant proved", "Found 8 $equiv cells\n Of those cells 8 are "
                              "proven and 0 are unproven.\n", "NOT PROVEN")):
        ok, _why = verdict(log, expect)
        print("  verdict must-fire: %-16s %s" % (label, "red ok" if not ok
                                                 else "*** GREEN"))
        bad += ok
    return bad


def main() -> int:
    print("GATE rowmux-equiv: pe_rowmux's synthesis text == its simulation text")
    bad = mustfires_verdict()
    try:
        how, sby = FM.resolve()
    except FM.CouldNotRun as e:
        print("  *** COULD NOT RUN: %s -- no proof ran, so none passed" % e)
        print("GATE rowmux-equiv: COULD NOT RUN")
        return 1
    try:
        body = lift(open(STORE, encoding="utf-8").read())
    except ValueError as e:
        print("  *** %s" % e)
        print("GATE rowmux-equiv: FAILED (1)")
        return 1
    work = tempfile.mkdtemp(prefix="pe_rowmux_equiv_")
    with open(os.path.join(work, "rowmux.v"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(body)
    try:
        chip, benches = chip_sizes(how, sby, work), bench_sizes()
    except ValueError as e:
        print("  *** %s" % e)
        print("GATE rowmux-equiv: FAILED (1)")
        return 1
    for sw in sorted(chip | set(benches), reverse=True):
        print("  SW=%d used by: %s" % (sw, ", ".join(
            (["the chip"] if sw in chip else []) + benches.get(sw, []))))
    for sw in sorted(chip | set(benches), reverse=True):
        for arm, defs, expect in (("clean", "", "PROVEN"),
                                  ("M_ROWMUX_NODE", "-DM_ROWMUX_NODE", "NOT PROVEN")):
            name = "sw%d_%s.ys" % (sw, arm.lower())
            with open(os.path.join(work, name), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(SCRIPT.format(sw=sw, defs=defs))
            r = subprocess.run(yosys_argv(how, sby, work, name), cwd=work,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            log = r.stdout + r.stderr
            ok, why = verdict(log, expect)
            print("  %s SW=%d %-14s expect %-10s: %s" % (
                "ok " if ok else "***", sw, arm, expect, why))
            if not ok:
                bad += 1
                for ln in log.strip().splitlines()[-6:]:
                    print("      | " + ln)
    if bad:
        print("GATE rowmux-equiv: FAILED (%d)" % bad)
        return 1
    print("GATE rowmux-equiv: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
