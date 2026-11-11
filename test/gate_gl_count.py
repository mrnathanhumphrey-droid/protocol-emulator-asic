"""GATE gl-count: a gate-level run that ran fewer tests than test/test.py holds is RED.

    python test/gate_gl_count.py test/results.xml     (CI, after the gl_test action)
    python test/gate_gl_count.py                       (the suite: its must-fires only)

⛔⛔ WHY (Wilson 11-10). Gate-level simulation of the SRAM design had NEVER
RUN until the ttihp27a baseline: the netlist instantiates the IHP macro, and
test/Makefile's GATES branch gave the simulator no model for it, so iverilog
stopped at "Unknown module type" before any test. (No result existed: CI's last
gds ran 10-22, before the SRAM store.) The fix put the model in; THIS gate makes
the class impossible to miss: a run that elaborated nothing, collected nothing,
or lost a test is red -- "0 tests, no failure" is not a pass.

The expected count is DERIVED, never typed: the `@cocotb.test` decorators in
test/test.py. Red when: results.xml is missing or unreadable; the tests run !=
the tests declared (or none declared); any test failed, errored or was skipped.
Token: GATE gl-count: PASSED
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TESTS = os.path.join(HERE, "test.py")


def declared(text=None):
    """the number of cocotb tests test/test.py declares"""
    if text is None:
        text = open(TESTS, encoding="utf-8").read()
    return len(re.findall(r"^@cocotb\.test\b", text, re.M))


def problems(xml_text, want):
    """[problem] for one results.xml's text (None = the file is missing)."""
    if want <= 0:
        return ["test/test.py declares no cocotb test -- nothing to count against"]
    if xml_text is None:
        return ["results.xml is missing: the gate-level run produced no results "
                "(elaboration failed, or the simulator never ran)"]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return ["results.xml does not parse: %s" % e]
    cases = list(root.iter("testcase"))
    out = []
    if len(cases) != want:
        out.append("%d test(s) ran, test/test.py declares %d" % (len(cases), want))
    for c in cases:
        for kind in ("failure", "error", "skipped"):
            if c.find(kind) is not None:
                out.append("%s: %s" % (c.get("name"), kind))
    return out


def _xml(n, bad=None):
    rows = []
    for i in range(n):
        inner = "<%s message='x'/>" % bad if (bad and i == 0) else ""
        rows.append("<testcase classname='test' name='t%d' time='1'>%s</testcase>" % (i, inner))
    return "<testsuites><testsuite name='all'>%s</testsuite></testsuites>" % "".join(rows)


def must_fires():
    """[(label, red?)]: every defect must be red, the clean run green."""
    w = declared()
    return [("results.xml missing (nothing elaborated)", bool(problems(None, w))),
            ("0 tests ran", bool(problems(_xml(0), w))),
            ("one test fewer than declared", bool(problems(_xml(w - 1), w))),
            ("one test more than declared", bool(problems(_xml(w + 1), w))),
            ("a failure", bool(problems(_xml(w, "failure"), w))),
            ("an error", bool(problems(_xml(w, "error"), w))),
            ("a skip", bool(problems(_xml(w, "skipped"), w))),
            ("not XML", bool(problems("<testsuites>", w))),
            ("no test declared", bool(problems(_xml(0), 0)))], not problems(_xml(w), w)


def main():
    w = declared()
    print("GATE gl-count: the gate-level run ran every test test/test.py declares (%d)" % w)
    rc = 0
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        p = args[0]
        txt = open(p, encoding="utf-8", errors="replace").read() if os.path.isfile(p) else None
        probs = problems(txt, w)
        n = len(list(ET.fromstring(txt).iter("testcase"))) if txt and not any(
            "parse" in x for x in probs) else 0
        print("  %s: %d test(s) ran" % (p, n))
        for x in probs:
            print("  *** " + x)
        rc |= 1 if probs else 0
    print("  --- must-fires ---")
    mf, clean = must_fires()
    for label, red in mf:
        print("  must-fire: %-40s %s" % (label, "red  ok" if red else "*** STAYED GREEN"))
        rc |= 0 if red else 1
    print("  control:   %-40s %s" % ("%d tests, all passing" % w, "green ok" if clean else "*** RED"))
    rc |= 0 if clean else 1
    print()
    print("  GATE gl-count: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
