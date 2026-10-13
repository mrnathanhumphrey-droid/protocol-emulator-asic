"""RUNNER REGISTRY GATE -- no script runs a bench outside the one registry.

⛔⛔ WHY (Wilson, WF2 #8 follow-up): the unknown-image sweep missed runners
outside the CI gate list twice in one day. `test/runner_registry.py` is the
one enumeration (the CI list and the A2 suite are READ from their own files;
everything else is declared with a kind and a reason). This gate:

  1. every script under test/, model/, ci/ that invokes a bench (names a
     simulator and a `tb_*`) is in the registry -- an unregistered runner is
     RED, so the next one cannot hide;
  2. every registered path exists, and both read lists are non-empty;
  3. a declared "helper" is actually named by the caller it claims, and every
     declared owner exists.

MUST-FIRES (on in-memory copies, never the tree): a planted unregistered
runner is red; a CI runner deleted from run_gates.sh's list is red (the
registry reads the real list, not a copy of it).
Verdict: `RUNNER REGISTRY: PASSED` or `*** FAIL ...`.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "test"))
import runner_registry as RR          # noqa: E402


def check(invokers, reg, declared, root=ROOT):
    p = []
    for path in sorted(invokers):
        if path not in reg:
            p.append("%s invokes a bench and is in no registry -- add it to "
                     "the CI list, the A2 suite, or runner_registry.DECLARED "
                     "with its kind and reason" % path)
    for path in sorted(reg):
        if not os.path.exists(os.path.join(root, path)):
            p.append("%s is registered but not on disk" % path)
    for path, (kind, owner, _why) in sorted(declared.items()):
        op = os.path.join(root, owner)
        if not os.path.exists(op):
            p.append("%s: its owner %s does not exist" % (path, owner))
        elif kind == "helper":
            with open(op, encoding="utf-8", errors="replace") as fh:
                if os.path.splitext(os.path.basename(path))[0] not in fh.read():
                    p.append("%s is declared a helper of %s, which never "
                             "names it" % (path, owner))
    return p


def main():
    print("RUNNER REGISTRY -- every script that runs a bench, enumerated once")
    ci, a2 = RR.ci_list(), RR.a2_list()
    reg = RR.registry()
    inv = RR.bench_invokers()
    kinds = {}
    for k in reg.values():
        kinds[k] = kinds.get(k, 0) + 1
    print("  registry: %d runner(s) -- %s" % (len(reg), ", ".join(
        "%s %d" % kv for kv in sorted(kinds.items()))))
    print("  scripts that invoke a bench: %d" % len(inv))
    probs = check(inv, reg, RR.DECLARED)
    if len(ci) < 20 or len(a2) < 20:
        probs.append("the CI list (%d) or the A2 suite (%d) parsed short -- "
                     "the registry cannot be trusted" % (len(ci), len(a2)))
    for q in probs:
        print("  *** " + q)

    # ---- must-fires ---------------------------------------------------------
    ok = True
    planted = dict(inv)
    # (text only, never run: names a simulator and a bench, as a runner does)
    planted["test/probe_mf_runner.py"] = "# runs vvp on tb_mf"
    red1 = bool(check(planted, reg, RR.DECLARED))
    print("  must-fire  a planted unregistered runner              %s"
          % ("red" if red1 else "*** NOT RED"))
    gates = RR._read(RR.GATES_SH)
    victim = "test/run_reload.py"
    cut = gates.replace("  " + victim + "\n", "", 1)
    reg2 = {p: "ci" for p in RR.ci_list(cut)}
    reg2.update({p: "a2" for p in a2})
    for p, (k, _o, _w) in RR.DECLARED.items():
        reg2.setdefault(p, k)
    red2 = cut != gates and bool(check(inv, reg2, RR.DECLARED))
    print("  must-fire  %s deleted from the CI list       %s"
          % (victim, "red" if red2 else "*** NOT RED%s" % (
              "" if cut != gates else " (the deletion did not apply)")))
    ok = red1 and red2

    if not probs and ok:
        print("RUNNER REGISTRY: PASSED")
        return 0
    print("*** FAIL runner_registry: %d problem(s)%s"
          % (len(probs), "" if ok else "; a must-fire did not fire"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
