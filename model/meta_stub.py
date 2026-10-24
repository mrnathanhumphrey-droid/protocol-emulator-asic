"""Run ONE gate with ONE check function replaced by an always-pass stub.

    python model/meta_stub.py <gate path> <module>.<function> <policy>

THE META-TEST'S INJECTOR (must-fire audit, 10-23). The stub is CONSTANT PASS:
the real function still runs, and its verdict is overwritten with what a check
that ALWAYS PASSES would answer -- an empty problem list, True, None, "no
exception" -- chosen per seam by a declared POLICY (gate_meta.SEAMS). So every
must-fire that hands the function a planted defect gets "fine" back, and if the
must-fire really exercises this function the gate must exit non-zero. A gate
that stays green has a check no must-fire prices -- what gate_meta finds.

⛔ NOT RECORD-AND-REPLAY, which the first version was: replay the first call's
answer assumed the first call was the clean one, and it is not always --
gate_dmin_clocked sweeps admissible(1..399), so the first answer was False and
the replayed "pass" emptied the sweep; pe_asm's first check_zero_spacing call
was a PLANT, so the replay rejected the real data instead of passing the plants.
A declared pass value has no such ordering dependence.

The stub is installed on the defining module AND on every module that imported
the function object by name (`from x import f`), found by identity.

Exit code: the gate's own. The last line is `META-STUB <gate> <seam> calls=<n>`
-- calls=0 means the seam was never reached, which gate_meta reports as its
own problem (a registry entry that names a function the gate does not call).
"""
from __future__ import annotations

import functools
import importlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _paths():
    for d in ("model", os.path.join("model", "a2"), "test", "ci"):
        p = os.path.join(ROOT, d)
        if p not in sys.path:
            sys.path.insert(0, p)


def _short(v):
    if isinstance(v, (list, tuple, dict, set, str)):
        return "%s(len %d)" % (type(v).__name__, len(v))
    return "%s:%s" % (type(v).__name__, repr(v)[:24])


def _empty(x):
    return type(x)() if isinstance(x, (list, dict, set)) else x


#: THE "ALWAYS PASS" ANSWER, per return contract (gate_meta.SEAMS names one per
#: seam). Each takes the real call's answer -- or the exception it raised --
#: and returns what a check that ALWAYS PASSES would have said instead.
def _pass(policy, v, exc, last):
    if policy == "NORAISE":           # raises on a defect, returns on success
        return last
    if exc is not None:
        raise exc
    if policy == "E":                 # problems (or a tuple of problem lists)
        return tuple(_empty(x) for x in v) if isinstance(v, tuple) else _empty(v)
    if policy == "E0":                # (problems, rows/summary)
        return (_empty(v[0]),) + tuple(v[1:])
    if policy == "Z0":                # (rc, rows)
        return (0,) + tuple(v[1:])
    if policy == "E1":                # (hits, bad)
        return (v[0], _empty(v[1])) + tuple(v[2:])
    if policy == "T":
        return True
    if policy == "Z":
        return 0
    if policy == "NONE":
        return None
    if policy == "PRE":               # (ok, message, label)
        return (True, "") + tuple(v[2:])
    if policy == "P1NONE":            # (doc, error)
        return (last[0] if last else v[0], None)
    if policy == "CE5":               # (ran ok, changed paths)
        return (True, [])
    if policy == "JV":                # (status, info, bad bits)
        return ("ok", v[1], [])
    if policy == "REASON":            # {kind: [problems]}
        return {k: _empty(x) for k, x in v.items()}
    if policy == "NOTNONE":           # an index, or None when the guard is absent
        return v if v is not None else 1
    if policy == "RXOK":              # (n, declared, need, width_ok, kind_ok) or None
        return v if v is None else tuple(v[:3]) + (True, True)
    raise SystemExit("meta_stub: unknown policy %r" % policy)


def install(modname, fn, policy):
    """Replace modname.fn by an ALWAYS-PASS stub (`policy`); return its state.

    The real function still RUNS -- the stub needs its answer's shape and
    the gate's other side effects -- and its verdict is then overwritten."""
    mod = importlib.import_module(modname)
    real = getattr(mod, fn)
    state = {"calls": 0, "seen": [], "last": None}
    record = os.environ.get("PE_META_RECORD") == "1"

    @functools.wraps(real)
    def stub(*a, **k):
        state["calls"] += 1
        try:
            v, exc = real(*a, **k), None
        except Exception as e:          # handed to the policy, never swallowed silently
            v, exc = None, e
        if record:
            state["seen"].append("RAISE " + type(exc).__name__ if exc
                                 else _short(v))
            if exc is not None:
                raise exc
            return v
        if exc is None and policy in ("NORAISE", "P1NONE") and (
                policy == "NORAISE" or v[1] is None):
            state["last"] = v
        return _pass(policy, v, exc, state["last"])

    for m in list(sys.modules.values()):
        try:
            for name, obj in list(vars(m).items()):
                if obj is real:
                    setattr(m, name, stub)
        except TypeError:
            continue
    return state


def main(argv) -> int:
    if len(argv) != 4 or "." not in argv[2]:
        print("usage: meta_stub.py <gate path> <module>.<function> <policy>")
        return 2
    gate, seam, policy = argv[1], argv[2], argv[3]
    modname, fn = seam.rsplit(".", 1)
    _paths()
    os.chdir(ROOT)
    gmod = os.path.splitext(os.path.basename(gate))[0]
    sys.argv = [gate]
    g = importlib.import_module(gmod)          # the gate as a module, not __main__
    state = install(modname, fn, policy)
    if not hasattr(g, "main"):
        print("META-STUB %s %s: the gate has no main()" % (gate, seam))
        return 2
    try:
        rc = g.main()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    rc = 0 if rc is None else rc
    if state["seen"]:
        import collections
        c = collections.Counter(state["seen"])
        print("META-RECORD %s %s %s" % (gate, seam, " ; ".join(
            "%dx %s" % (n, v) for v, n in c.most_common(4))))
    print("META-STUB %s %s calls=%d rc=%s" % (gate, seam, state["calls"], rc))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
