"""CDC-Q: a raw qualified pin changes NO state unless the synchronised WR edge is up (Wilson 11-10).

⛔⛔ WHY. gate_cdc judged the TX nibble / tag pins (`ui_in[5:0]`, sampled, not
synchronised) by a LIST OF FLOP NAMES they may reach (`tx_asm`, `tx_tag`,
`tx_mem`). Bundles 5 and 6 added capture sites -- the response buffer's length,
endpoint and store rows, the control channel's pending address and fence, the
refusal flag -- every one gated on the same synchronised edge (`nib_lo`), and
the list did not know them, so gate_cdc went red and the red hid in a shard that
was already red. A list of names has to be kept by hand; this proves the
PROPERTY instead, for every flop, so the next capture site needs no edit.

THE PROOF (yosys equiv_make / equiv_simple / equiv_induct, the pinned suite):
two copies of the chip, `gold` and `gate`. Each pin of gate_cdc.QUALIFIED is
cut: gold sees the pad; gate sees the pad while `push_rise` (= run & the
synchronised WR edge, the superset of every capture qualifier) is high, and a
FREE input `ui_alt` while it is low. Everything else is shared. The two copies'
FLOPS -- and only their flops -- are matched, so the induction hypothesis is
"same state", and the claim proven is: from ANY state (not only reachable ones),
one step later every flop agrees. A flop that a raw pin reaches while the
qualifier is low cannot agree, and stays UNPROVEN.

⛔⛔ ONLY STATE IS MATCHED -- the first prototype was VACUOUS. equiv_make matches
wires by name and REWIRES the gate copy's fan-out onto the merged signal (gold's
value); matching the internal `ui_in` made every downstream proof assume the
pins equal: 17,280 "proven", saying nothing. Every non-flop name is
blacklisted, and two guards make the class visible: COVERAGE (flop bits in the
gate copy == $equiv cells, so no flop goes unmatched) and the ALLOWED set must
actually appear UNPROVEN (the declared synchroniser of a qualified pin samples
it raw -- if that cell proves, the cut did not reach the gate copy).

THE BUILD: test/Makefile's PROJECT_SOURCES with NO defines -- pe_store's
default MEM_TYPE "sram", the SHIPPED arm (write buffer, arbitration), with the
RAM as its inline behavioural model (`mem`, so the RAM's contents are state the
proof compares). ⚠ Corrected 11-11: the first version of this text and commit
6b4f5ec called this "the flop store"; it never was. The bound IHP macro
(PE_SRAM_MACRO) is a black box no property sees into; its inputs have their
own rule -- no raw pin reaches them at all (model/gate_macro_inputs.py).

ARMS (in parallel by default -- PE_CDCQ_JOBS -- ~11 min each, ~3 GB each):
  clean              unproven == ALLOWED exactly, coverage full -> PASS
  M_CDC_UB_UNGATED   ub_len samples the raw nibble every cycle   -> ub_len UNPROVEN
  M_CDC_RAW_WR       one capture qualified by the RAW WR pad     -> beyond ALLOWED
ALLOWED = the declared synchronizer first flop (gate_cdc.SYNC) of each
qualified pin, bit 0. A verdict is read from equiv_status, never an exit code;
no status line is red; a missing tool is COULD NOT RUN, red.
POSITIVE TOKEN: `GATE cdc-qual: PASSED`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import gate_formal_miters as FM          # noqa: E402  (the suite resolver)
import gate_cdc as CDC                    # noqa: E402  (QUALIFIED, SYNC)

TOP = "tt_um_protocol_emulator"
BS = "\\"
STATUS = re.compile(r"Of those cells (\d+) are proven and (\d+) are unproven")
UNPROVEN = re.compile(r"Unproven \$equiv \S+ \\(\S+)_gold(?: \[(\d+)\])?")

#: (arm, define, expect, a name the arm must leave unproven or None)
ARMS = (("clean", None, "PASS", None),
        ("ub_ungated", "M_CDC_UB_UNGATED", "FAIL", "ub_len"),
        ("raw_wr", "M_CDC_RAW_WR", "FAIL", None))


def qualified_bits():
    bits = sorted(i for (port, i) in CDC.QUALIFIED if port == "ui_in")
    if not bits:
        raise ValueError("gate_cdc.QUALIFIED names no ui_in pin")
    return bits


def allowed():
    """{'name[0]'}: each qualified pin's declared synchronizer first flop."""
    return {"%s[0]" % CDC.SYNC[("ui_in", i)] for i in qualified_bits()
            if ("ui_in", i) in CDC.SYNC}


def sources():
    """test/Makefile's PROJECT_SOURCES -- the RTL build every bench runs."""
    mk = open(os.path.join(ROOT, "test", "Makefile"), encoding="utf-8").read()
    m = re.search(r"^PROJECT_SOURCES\s*=\s*(.+)$", mk, re.M)
    if not m:
        raise ValueError("test/Makefile has no PROJECT_SOURCES")
    return m.group(1).split()


def inject(base, role):
    """gold/gate RTLIL text from the flattened base netlist."""
    m = re.search(r"^(\s*)wire width 8 input (\d+) \\ui_in\s*$", base, re.M)
    if not m:
        raise ValueError("the flattened netlist has no 8-bit ui_in port")
    if not re.search(r"\\push_rise\b", base):
        raise ValueError("the flattened netlist has no push_rise (kept wire)")
    nxt = max(int(x) for x in re.findall(r"(?:input|output|inout) (\d+) ", base)) + 1
    ind = m.group(1)
    t = base[:m.start()] + (
        ind + "wire width 8 " + BS + "ui_in\n"
        + ind + "wire width 8 input " + m.group(2) + " " + BS + "ui_pad\n"
        + ind + "wire width 8 input " + str(nxt) + " " + BS + "ui_alt") + base[m.end():]
    q = set(qualified_bits())
    body = []
    for i in range(8):
        if role == "gate" and i in q:
            body.append("  cell $mux $cdcq_inject_%d\n    parameter %sWIDTH 1\n"
                        "    connect %sA %sui_alt [%d]\n    connect %sB %sui_pad [%d]\n"
                        "    connect %sS %spush_rise\n    connect %sY %sui_in [%d]\n  end\n"
                        % (i, BS, BS, BS, i, BS, BS, i, BS, BS, BS, BS, i))
        else:
            body.append("  connect %sui_in [%d] %sui_pad [%d]\n" % (BS, i, BS, i))
    k = t.rindex("\nend")
    t = t[:k] + "\n" + "".join(body) + t[k + 1:]
    return t.replace("module " + BS + TOP, "module " + BS + role)


def blacklist(base):
    """every wire that is not (part of) a flop output, plus ui_in: the names
    equiv_make must NOT match (a matched wire is a cut point -- see WHY)."""
    wires = set(re.findall(r"^\s*wire (?:width \d+ )?(?:(?:input|output|inout) \d+ )?"
                           r"(?:upto )?(?:signed )?\\(\S+)\s*$", base, re.M))
    state = set()
    for c in re.finditer(r"^\s*cell \$\w*dff\w* \S+\n(.*?)^\s*end\s*$", base, re.M | re.S):
        qc = re.search(r"^\s*connect \\Q (.+)$", c.group(1), re.M)
        if qc:
            state.update(re.findall(r"\\(\S+)", qc.group(1)))
    ports = set(re.findall(r"^\s*wire (?:width \d+ )?input \d+ \\(\S+)", base, re.M))
    return sorted((wires - state - ports) | {"ui_in"})


# ⭐ -purge_lib (11-13): the SRAM binding file (in info.yaml's source_files, so
# in the Makefile list this gate reads) carries an unused (* blackbox *) module;
# kept in base.il it is defined twice once gold and gate are read together, and
# the proof never reached equiv_status.
BASE_YS = """{reads}
hierarchy -top {top}
setattr -mod -unset keep_hierarchy *
proc
flatten
setattr -set keep 1 w:push_rise
hierarchy -top {top} -purge_lib
write_rtlil base.il
"""
EQUIV_YS = """read_rtlil gold.il
read_rtlil gate.il
memory -nomap gold gate
memory_map gold gate
opt_clean gold gate
async2sync gold gate
tee -o dffbits.txt stat -width gate
equiv_make -blacklist black.txt gold gate equiv
hierarchy -top equiv
tee -o ncells.txt select -count t:$equiv
equiv_simple -seq 2
equiv_induct -seq 2
tee -o status.txt equiv_status
"""


def yosys_argv(how, sby, work, script):
    ydir = sby.rsplit("/", 1)[0] if how == "wsl" else os.path.dirname(sby)
    if how == "wsl":
        return ["wsl.exe", "--cd", FM.wslpath(work), "--", ydir + "/yosys",
                "-q", "-l", script + ".log", "-s", script]
    return [os.path.join(ydir, "yosys"), "-q", "-l", script + ".log", "-s", script]


def flop_bits(stat):
    return sum(int(n) * int(w) for n, w in
               re.findall(r"^\s+(\d+)\s+\$\w*dff\w*_(\d+)\s*$", stat, re.M))


def judge(arm, status, bits, cells, must=None, allow=None):
    """[problem] for one arm. `status` = equiv_status text (None = missing)."""
    allow = allowed() if allow is None else allow
    if status is None or not STATUS.search(status):
        return ["%s: no equiv_status line -- the proof did not reach its check" % arm]
    if bits <= 0 or bits != cells:
        return ["%s: COVERAGE -- %d flop bits, %d $equiv cells: a flop the proof "
                "never compared" % (arm, bits, cells)]
    unp = {"%s[%s]" % (n, b) if b else n for n, b in UNPROVEN.findall(status)}
    out = []
    missing = sorted(allow - unp)
    if missing:
        out.append("%s: the declared synchronizer(s) %s PROVED equal -- the cut "
                   "never reached the gate copy (vacuous)" % (arm, ", ".join(missing)))
    extra = sorted(unp - allow)
    if must is None and arm == "clean":
        if extra:
            out.append("%s: a raw qualified pin reaches %d flop bit(s) while the "
                       "qualifier is low: %s" % (arm, len(extra), ", ".join(extra[:8])))
    else:
        if not extra:
            out.append("%s: the mutant PROVED -- the property cannot see it" % arm)
        elif must and not any(x.split("[")[0] == must for x in extra):
            out.append("%s: red, but not on %s (%s)" % (arm, must, ", ".join(extra[:4])))
    return out


def run_arm(how, sby, arm, define, result):
    work = tempfile.mkdtemp(prefix="cdcq_%s_" % arm)
    try:
        path = (lambda p: FM.wslpath(p)) if how == "wsl" else (lambda p: p)
        da = ("-D %s " % define) if define else ""
        reads = "\n".join("read_verilog -sv %s%s" % (da, path(os.path.join(ROOT, "src", f)).replace("\\", "/"))
                          for f in sources())
        open(os.path.join(work, "base.ys"), "w", newline="\n").write(BASE_YS.format(reads=reads, top=TOP))
        r = subprocess.run(yosys_argv(how, sby, work, "base.ys"), cwd=work,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode or not os.path.isfile(os.path.join(work, "base.il")):
            result[arm] = ["%s: yosys build failed (rc %d): %s" % (arm, r.returncode,
                           (r.stdout + r.stderr).strip().splitlines()[-1:] )]
            return
        base = open(os.path.join(work, "base.il"), encoding="utf-8").read()
        for role in ("gold", "gate"):
            open(os.path.join(work, role + ".il"), "w", newline="\n").write(inject(base, role))
        open(os.path.join(work, "black.txt"), "w", newline="\n").write("\n".join(blacklist(base)) + "\n")
        open(os.path.join(work, "equiv.ys"), "w", newline="\n").write(EQUIV_YS)
        subprocess.run(yosys_argv(how, sby, work, "equiv.ys"), cwd=work,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        rd = lambda f: open(os.path.join(work, f), encoding="utf-8").read() \
            if os.path.isfile(os.path.join(work, f)) else None
        status, stat, nc = rd("status.txt"), rd("dffbits.txt") or "", rd("ncells.txt") or ""
        bits = flop_bits(stat)
        m = re.search(r"(\d+) objects", nc)
        cells = int(m.group(1)) if m else -1
        result[arm] = (status, bits, cells)
    # anything else escapes the thread: the arm has NO result, and main reds it
    except (OSError, ValueError, subprocess.SubprocessError) as e:   # red, never skipped
        result[arm] = ["%s: %r" % (arm, e)]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def must_fires():
    """the judge itself, on planted equiv_status texts: [(label, red?)]"""
    a = allowed()
    ok = "Found 10 $equiv cells in equiv:\n  Of those cells 9 are proven and 1 are unproven.\n" + \
         "".join("  Unproven $equiv $x: \\%s_gold [0] \\%s_gate [0]\n" % (n[:-3], n[:-3]) for n in a)
    extra = ok.replace("9 are proven and 1", "8 are proven and 2") + \
        "  Unproven $equiv $y: \\ub_len_gold [0] \\ub_len_gate [0]\n"
    none = "Found 10 $equiv cells in equiv:\n  Of those cells 10 are proven and 0 are unproven.\n"
    return [("no status line", bool(judge("clean", "Found 10\n", 10, 10, allow=a))),
            ("missing status file", bool(judge("clean", None, 10, 10, allow=a))),
            ("coverage gap (a flop unmatched)", bool(judge("clean", ok, 11, 10, allow=a))),
            ("clean with an extra unproven flop", bool(judge("clean", extra, 10, 10, allow=a))),
            ("clean with the synchronizer proved (vacuous cut)", bool(judge("clean", none, 10, 10, allow=a))),
            ("mutant fully proved", bool(judge("ub_ungated", ok, 10, 10, "ub_len", allow=a))),
            ("mutant red on the wrong flop", bool(judge("ub_ungated", extra.replace("ub_len", "tx_asm"), 10, 10, "ub_len", allow=a)))], \
        not judge("clean", ok, 10, 10, allow=a)


def main():
    print("GATE cdc-qual: a raw qualified pin changes no flop unless the synchronised WR edge is up")
    rc = 0
    try:
        print("  qualified pins : ui_in%s (gate_cdc.QUALIFIED)" % qualified_bits())
        print("  allowed raw    : %s (their gate_cdc.SYNC first flops)" % sorted(allowed()))
        print("  build          : %s (test/Makefile PROJECT_SOURCES: the SRAM arm, RAM inline)" % " ".join(sources()))
    except (OSError, ValueError) as e:      # the spec could not be read: red
        print("  *** %r" % e)
        print("\n  GATE cdc-qual: FAILED")
        return 1
    print("  --- judge must-fires ---")
    mf, control = must_fires()
    for label, red in mf:
        print("  must-fire: %-48s %s" % (label, "red  ok" if red else "*** STAYED GREEN"))
        rc |= 0 if red else 1
    print("  control:   %-48s %s" % ("allowed set only, full coverage", "green ok" if control else "*** RED"))
    rc |= 0 if control else 1
    try:
        how, sby = FM.resolve()
    except FM.CouldNotRun as e:
        print("  *** COULD NOT RUN: %s" % e)
        print("\n  GATE cdc-qual: FAILED")
        return 1
    print("  tool           : %s (%s) -- yosys from the same suite" % (sby, how))
    # PE_CDCQ_JOBS: arms run at once (default 3, CI). A shared machine whose
    # WSL takes one CPU job at a time runs it with 1 (~3x the wall time).
    jobs = max(1, int(os.environ.get("PE_CDCQ_JOBS", "3")))
    print("  arms at once   : %d (PE_CDCQ_JOBS)" % jobs)
    result, pending = {}, list(ARMS)
    while pending:
        batch, pending = pending[:jobs], pending[jobs:]
        threads = [threading.Thread(target=run_arm, args=(how, sby, a, d, result))
                   for a, d, _e, _m in batch]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
    print("  --- arms ---")
    for arm, define, expect, must in ARMS:
        r = result.get(arm, ["%s: no result" % arm])
        if isinstance(r, list):
            probs, desc = r, "build"
        else:
            status, bits, cells = r
            if expect == "PASS":
                probs = judge(arm, status, bits, cells)
            else:
                probs = judge(arm, status, bits, cells, must=must or "")
            unp = UNPROVEN.findall(status or "")
            desc = "%d flop bits, %d cells, %d unproven" % (bits, cells, len(set(unp)))
        good = not probs
        print("  %-11s %-17s %-6s %-42s %s" % (arm, define or "-", expect, desc,
                                              "ok" if good else "***"))
        for p in probs:
            print("    *** " + p)
        rc |= 0 if good else 1
    print("\n  GATE cdc-qual: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
