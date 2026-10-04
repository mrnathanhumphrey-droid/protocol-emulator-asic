"""BENCH INDEX GUARD -- no testbench recomputes an RTL-internal index.

THE RULE (Wilson, ruling 4): benches observe RTL state through hierarchical
references to the RTL's own wires. They never recompute RTL-internal indices.

⛔⛔ WHY, FROM FOUR DEFECTS IN ONE SITTING. The engine's head-slot index
`ln*2 + (l_sel[ln] ? 1 : 0)` was written out at TEN sites in `pe_engine.v` and
collapsed into one wire (`hix`). Four MORE copies were then found in the
benches, one at a time, in two files:

  1. `tb_jlane` head index declared [2:0] -- `NSLOT = 10` needs 4 bits, so
     lane 4's slots (8, 9) aliased onto lane 0's;
  2. `tb_smoke` buffer-swap invariant -- at SPL = 1, `lk*2` reads lane 2's slot
     when checking lane 1: 3207 invariant failures on a CORRECT design;
  3. `tb_jlane` again, widened to 4 bits but still `lane*2` -- reported a
     per-interval sum of 1870 against a bound of 9;
  4. `tb_smoke`'s steady-stall reconstruction -- the number the single-vs-double
     buffer comparison was built from, so a published column had to be
     retracted;
  and `tb_witness` carried a 3-bit copy as well.

⭐ EVERY COPY SILENTLY ASSUMED `SPL = 2`, AND EVERY ONE BROKE THE MOMENT
`SPL = 1` EXISTED. That is the generic detector and it is why the companion
ruling is to sweep the parameter point (`test/run_param_points.py`). This gate
is the other half: vigilance found them one at a time, and a structural check
finds the class.

TWO CHECKS:
  A. every index into `l_act`/`l_actv` is a bare identifier or a hierarchical
     reference -- never an expression containing `*`, `+` or `?`;
  B. every bench wire assigned from `hix`/`six` is at least `SIW` bits wide,
     because defect 1 was a correct source truncated by the destination.
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
TESTDIR = os.path.join(ROOT, "test")

# ⛔ READ FROM THE TOOLS, NOT ASSUMED. `SIW` is the engine's own slot-index
# width; a hard-coded 4 here would be this gate keeping its own copy of an RTL
# constant, which is the exact defect it exists to forbid.
def rtl_siw():
    # ⭐ THE EXISTING DUMP, IMPORTED. `gate_one_encoder.dump_iverilog()`
    # already elaborates `test/param_dump.v` and returns every resolved
    # parameter, so writing a second elaboration here would be a private copy
    # of the thing this gate exists to forbid. My first attempt did exactly
    # that and failed on an include path it did not need.
    sys.path.insert(0, HERE)
    try:
        import gate_one_encoder as goe
    except Exception as e:                      # pragma: no cover
        return None, "cannot import gate_one_encoder: %s" % e
    vals, err = goe.dump_iverilog()
    if vals is None:
        return None, err
    if "SIW" not in vals:
        return None, ("the dump has no SIW -- add it to test/param_dump.v so "
                      "the width comes from the elaborator")
    return vals["SIW"], None


# the slot arrays whose indices must not be computed in a bench
ARRAYS = ("l_actv", "l_act")
# an index that is a bare name, or a hierarchical reference like
# dut.u_eng.hix[lane] -- anything with arithmetic or a ternary is a RECOMPUTE
BAD_IN_INDEX = re.compile(r"[*+?]|\s-\s")


def find_indices(text):
    """[(array, index_expr, line_no)] for every l_act/l_actv index, skipping
    comments. ⚠ Comment lines are skipped deliberately: this file and the
    benches DESCRIBE the forbidden pattern in prose, and a guard that fires on
    its own documentation would have to be silenced to pass."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("//", 1)[0]
        for arr in ARRAYS:
            for m in re.finditer(re.escape(arr) + r"\s*\[", code):
                i = m.end()
                depth, start = 1, i
                while i < len(code) and depth:
                    if code[i] == "[":
                        depth += 1
                    elif code[i] == "]":
                        depth -= 1
                    i += 1
                if depth == 0:
                    out.append((arr, code[start:i - 1].strip(), n))
    return out


def check_file(path, siw):
    """(recomputes, narrow) findings for one bench."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    recomputes = []
    for arr, expr, n in find_indices(text):
        if BAD_IN_INDEX.search(expr):
            recomputes.append((n, arr, expr))
    narrow = []
    # B: a wire holding a slot index must be wide enough for it
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("//", 1)[0]
        if "hix[" not in code and "six[" not in code:
            continue
        m = re.search(r"\b(?:wire|reg)\s*\[\s*(\d+)\s*:\s*0\s*\]", code)
        if m and (int(m.group(1)) + 1) < siw:
            narrow.append((n, int(m.group(1)) + 1, code.strip()[:60]))
    return recomputes, narrow


def benches():
    return sorted(os.path.join(TESTDIR, f) for f in os.listdir(TESTDIR)
                  if f.endswith(".v"))


def selftest(siw):
    """⛔ PRICE IT (standing rule 3). Both checks must reject the real
    historical defects, written out verbatim, and accept the real fix."""
    import tempfile
    rc = 0
    cases = (
        # (name, snippet, expect_recompute, expect_narrow)
        ("defect 2/4: a recomputed index",
         "  wire x = dut.u_eng.l_actv[lk*2 + (dut.u_eng.l_sel[lk] ? 1 : 0)];",
         True, False),
        ("defect 4: the winner form",
         "  win_slot = dut.u_eng.winner * 2 + 1;\n"
         "  wire y = dut.u_eng.l_actv[win_slot2 + 1];",
         True, False),
        ("defect 1: a 3-bit destination",
         "  wire [2:0] l_head = dut.u_eng.hix[lane];",
         False, True),
        ("the fix: hierarchical ref, wide enough",
         "  wire [3:0] l_head = dut.u_eng.hix[lane];\n"
         "  wire z = dut.u_eng.l_actv[l_head];",
         False, False),
        ("a comment describing the pattern must NOT fire",
         "  // it used to read l_actv[lk*2 + (l_sel[lk] ? 1 : 0)] here\n"
         "  wire w = dut.u_eng.l_actv[l_head];",
         False, False),
    )
    print("  --- must-fire: the checks reject the real defects ---")
    d = tempfile.mkdtemp(prefix="pe_bi_")
    for name, snippet, want_r, want_n in cases:
        p = os.path.join(d, "t.v")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("module t;\n" + snippet + "\nendmodule\n")
        rec, nar = check_file(p, siw)
        got_r, got_n = bool(rec), bool(nar)
        ok = (got_r == want_r and got_n == want_n)
        print("    %-46s %s" % (name, "as expected" if ok else
                                "*** recompute=%s narrow=%s, wanted %s/%s"
                                % (got_r, got_n, want_r, want_n)))
        if not ok:
            rc = 1
    return rc


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("BENCH INDEX GUARD -- no bench recomputes an RTL-internal index")
    print("=" * 78)
    siw, err = rtl_siw()
    if siw is None:
        print("  *** could not resolve SIW from the RTL: %s" % err)
        print("      The width check needs the engine's own slot-index width;")
        print("      hard-coding it here would be this gate keeping a private")
        print("      copy of an RTL constant.")
        return 1
    print("  SIW (slot-index width, from the elaborator) : %d" % siw)
    print()
    files = benches()
    print("  benches checked : %d" % len(files))
    for p in files:
        rec, nar = check_file(p, siw)
        name = os.path.basename(p)
        if not rec and not nar:
            print("    %-16s clean" % name)
            continue
        for n, arr, expr in rec:
            print("    *** %s:%d  %s[%s]" % (name, n, arr, expr))
            print("        RECOMPUTED INDEX. Read `dut.u_eng.hix[<lane>]`")
            print("        instead -- four copies of this expression have")
            print("        already produced four wrong measurements.")
            rc = 1
        for n, w, code in nar:
            print("    *** %s:%d  %d-bit destination for a %d-bit index: %s"
                  % (name, n, w, siw, code))
            print("        TRUNCATED. lane 4's slots wrap onto lane 0's.")
            rc = 1

    print()
    if selftest(siw):
        rc = 1
    print()
    print("=" * 78)
    print("  BENCH INDEX GUARD: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ IT CHECKS THE USE SITE, not every possible way a bench could")
    print("      arrive at a slot number. A bench that computed one into an")
    print("      integer variable several lines earlier and indexed with the")
    print("      bare name would pass -- so the companion check is the")
    print("      PARAMETER SWEEP (`test/run_param_points.py`), which catches")
    print("      a hidden SPL = 2 assumption by making SPL vary.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
