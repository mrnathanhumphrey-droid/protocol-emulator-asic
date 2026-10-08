"""RULING E -- no Python handler may swallow an exception without a verdict.

THE CLAIM, over every `.py` under model/ and test/ (probe_* excluded):
  E1a  no bare `except:`;
  E1b  no `except Exception` / `except BaseException` (alone or in a tuple)
       that neither RE-RAISES nor is ALLOWLISTED BY NAME with a reason that
       says where the verdict is recorded.
One STRUCTURAL class is allowed without a name: the console-encoding idiom,
a `try` whose whole body is `sys.stdout.reconfigure(...)`. A failure there
changes how characters print, never what a gate decides.

⛔⛔ WHY (ruling E). Three checks in this arc could not fire, and one was a
swallowed `NameError`: `measure_phases.py` turned it into `None`, and a
`None` read as "nothing to report". The audit for this gate then found four
more live ones, all fixed in the same commit, not allowlisted:
  * `measure_phases.py` turned a corrupt phases file into `{}` and WROTE IT
    BACK with one record -- deleting every other image's phases, silently;
  * `gate_stored_numbers.py` SKIPPED a .py that failed to parse, and
    replaced a failed unparse with "" -- numbers leaving the audit unseen;
  * `gate_one_encoder.py` caught EVERYTHING while resolving RTL parameters;
    MEASURED, only NameError and SyntaxError ever occur, so it now catches
    exactly those;
  * `gate_a2_program.py` §1b SKIPPED an admissible lane whose own recurrence
    had raised (`r_ours = None`) -- the lane left the ours >= pyRTA check.
    Not an `except` here; downstream of one in `program_a2.py`, whose
    allowlist entry below now names the check that fails on it.

KEYS are (file, enclosing function, the handler's first statement) -- not
line numbers, which drift with every comment. A key that no longer exists is
a FAILURE (stale), so the allowlist cannot outlive the code it excuses.
MUST-FIRES (planted sources, parsed in memory): the pre-fix measure_phases
shape (`except Exception: return None`) is red; a bare `except:` is red; a
stale allowlist key is red; a handler that re-raises is green.
"""

from __future__ import annotations

import ast
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BROAD = {"Exception", "BaseException"}

# (file, function, first statement of the handler) -> where the verdict goes
ALLOW = {
    ("model/a2/gate_dmin_clocked.py", "main",
     "print('    *** FAIL could not import the UM10204 table: %s' % exc)"):
        "prints `*** FAIL` and sets rc = 1 on the next line.",
    ("model/a2/program_a2.py", "queue_slot",
     "out[str(r['lane'])] = {'r': None, 'T': r['T'], 'ok': False, 'why': 'own recurrence raised %s' % type(exc).__name__}"):
        "records the lane as ok = False with the exception named in `why`; "
        "`gate_admissible_images` reads ok = False as a QUEUE violation.",
    ("model/a2/program_a2.py", "derive",
     "ours = None"):
        "records `r_ours = None` and the exception in `why`; since ruling E "
        "`gate_a2_program` §1b FAILS an admissible lane with a pyRTA bound "
        "and no `r_ours` (it used to skip it).",
    ("model/a2/program_a2.py", "lane_responses",
     "out[r['lane']] = (None, 'own recurrence raised %s' % type(exc).__name__)"):
        "returns (None, why) per lane; callers treat a None response as no "
        "bound and report the reason.",
    ("model/gate_bench_indices.py", "rtl_siw",
     "return (None, 'cannot import gate_one_encoder: %s' % e)"):
        "returns (None, err); the caller prints `***` and fails on None.",
    ("model/gate_one_encoder.py", "main",
     "print('    *** %s did not import: %s' % (mod, e))"):
        "prints `***` and sets rc = 1.",
    ("model/gate_sda_hold.py", "main",
     "print('  *** %s claims a mode but the mode floor REJECTS it: %s' % (img, str(e)[:80]))"):
        "prints `***` and sets rc = 1.",
    ("model/macro_harden_gate.py", "read_config",
     "return (None, 'src/config.json does not parse: %s' % e)"):
        "returns (None, err); `main` fails on a None config.",
    ("test/benchset.py", "corpus_arms",
     "return (None, 'corpus.py did not import: %s' % exc)"):
        "returns (None, err); the sweep fails on it.",
    ("test/benchset.py", "base_images",
     "return ['clean_room.GENERATORS did not import (%s) -- the sweep has no image recipes and must not improvise a copy' % exc]"):
        "returns the import failure AS a problem; a non-empty list fails.",
    ("test/run_rxbw.py", "main",
     "print('    *** could not import the lane table: %s' % e)"):
        "prints `***` and returns 1.",
    ("test/toolchain.py", "version_of",
     "return MISSING"):
        "returns the MISSING sentinel; run_gates reports a missing tool as "
        "COULD NOT RUN, which it states is not a pass.",
    ("test/toolchain.py", "probe",
     "out[name] = MISSING"):
        "records MISSING for that tool; as above.",
}


def _broad(h):
    if h.type is None:
        return "bare"
    nodes = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
    names = {n.id if isinstance(n, ast.Name) else getattr(n, "attr", "")
             for n in nodes}
    return "broad" if BROAD & names else None


def _is_reconfigure(tr):
    if len(tr.body) != 1 or not isinstance(tr.body[0], ast.Expr):
        return False
    c = tr.body[0].value
    return (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr == "reconfigure")


def _reraises(h):
    return any(isinstance(n, ast.Raise)
               for n in ast.walk(ast.Module(body=h.body, type_ignores=[])))


def scan(rel, src):
    """-> [(kind, key, lineno)] for every broad/bare handler not excused
    structurally. `key` is (file, function, first statement)."""
    out = []
    tree = ast.parse(src, filename=rel)

    def walk(node, func):
        for ch in ast.iter_child_nodes(node):
            f = ch.name if isinstance(ch, (ast.FunctionDef,
                                           ast.AsyncFunctionDef)) else func
            if isinstance(ch, ast.Try):
                for h in ch.handlers:
                    k = _broad(h)
                    if not k or _is_reconfigure(ch) or (k == "broad"
                                                        and _reraises(h)):
                        continue
                    first = ast.unparse(h.body[0]).splitlines()[0]
                    out.append((k, (rel, f, first), h.lineno))
            walk(ch, f)
    walk(tree, "<module>")
    return out


def audit(found, allow):
    probs = []
    seen = set()
    for kind, key, line in found:
        if kind == "bare":
            probs.append("%s:%d bare `except:` (%s)" % (key[0], line, key[1]))
        elif key in allow:
            seen.add(key)
        else:
            probs.append("%s:%d `except Exception` in %s swallows without a "
                         "verdict: %s" % (key[0], line, key[1], key[2][:70]))
    for key in sorted(set(allow) - seen):
        probs.append("STALE allowlist entry, no such handler: %s / %s / %s"
                     % (key[0], key[1], key[2][:60]))
    return probs


def files():
    out = []
    for d in ("model", "test"):
        for p in sorted(glob.glob(os.path.join(ROOT, d, "**", "*.py"),
                                  recursive=True)):
            if not os.path.basename(p).startswith("probe_"):
                out.append(p)
    return out


PLANT_PRE_FIX = '''
def measure(trace):
    try:
        return lane_phase(trace)
    except Exception:
        return None
'''
PLANT_BARE = '''
def f():
    try:
        g()
    except:
        pass
'''
PLANT_RERAISE = '''
def f():
    try:
        g()
    except Exception as e:
        raise RuntimeError("context") from e
'''


def main() -> int:
    print()
    print("=" * 78)
    print("  E -- NO EXCEPTION SWALLOWED WITHOUT A VERDICT (model/, test/)")
    print("=" * 78)
    found, n_files = [], 0
    for p in files():
        rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
        with open(p, encoding="utf-8") as fh:
            found += scan(rel, fh.read())
        n_files += 1
    probs = audit(found, ALLOW)
    print("  %d files; %d broad/bare handler(s) needing a name; %d allowlisted"
          % (n_files, len(found), len(ALLOW)))
    rc = 0
    for p in probs:
        print("    *** %s" % p)
        rc = 1
    if not probs:
        print("    every one re-raises, is the console-encoding idiom, or is")
        print("    named in ALLOW with where its verdict is recorded")

    print("  --- must-fires (planted, parsed in memory) ---")
    checks = [
        ("the pre-fix measure_phases shape (NameError -> None)",
         audit(scan("plant.py", PLANT_PRE_FIX), {}), True),
        ("a bare `except:`", audit(scan("plant.py", PLANT_BARE), {}), True),
        ("a stale allowlist entry",
         audit([], {("x.py", "f", "pass"): "gone"}), True),
        ("a handler that re-raises", audit(scan("plant.py", PLANT_RERAISE), {}),
         False),
    ]
    for what, p, want_red in checks:
        ok = bool(p) == want_red
        print("    %-52s %s" % (what, ("red  ok" if want_red else "green  ok")
                                if ok else "*** WRONG"))
        if not ok:
            rc = 1
    print()
    print("  GATE except: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
