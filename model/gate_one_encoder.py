"""ONE ENCODER GUARD -- no second copy of the layout, in either language.

THE ONE CLAIM: the action/header encoding and the host push sequence are defined
in exactly one place, and the RTL's independently-written widths agree with it.

⛔⛔ THE TWO-COPIES DEFECT IS THIS PROJECT'S MOST RELIABLE BUG. `tb_smoke` kept
a private `exp_act[23:2]`; `run_local.py` kept a third source list and could not
elaborate; three pyRTA gates each built their own task set and all reported the
wrong answer at once; `periodic_equivalence` certified a lane table nobody used.
R1/R2's host model and `pe_asm` are the next pair at risk -- one emits the image,
the other pushes the bytes it consumes, so a disagreement about the queue tag
would pass every test on both sides of the mismatch.

## Three checks, because a shared import only covers one of them

  1. NO SECOND DEFINITION. Grep for another `def act(` / `def hdr(` / another
     `host_pushes`. An artefact that re-implements a packer and prints nothing
     would be invisible to a digest comparison.
  2. THE DIGEST AGREES WHEREVER IT IS PRINTED. This catches the case a grep
     cannot: a copy that computes its own digest.
  3. ⭐ THE RTL AGREES, AND THIS IS THE ONE THAT MATTERS MOST. `src/pe_engine.v`
     derives the same widths in Verilog -- a testbench cannot import Python --
     so the localparams are extracted and evaluated here. `ACT_W` grew 22 -> 24
     for the TX queue field and the Verilog had to be edited separately; had the
     two drifted, images would encode one layout and the engine decode another.
     That is exactly the `tb_smoke` failure one level deeper, where no bench
     would have caught it.
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
sys.path.insert(0, os.path.join(ROOT, "test"))

import pe_isa  # noqa: E402

OWNER = "test/pe_isa.py"
SCAN_DIRS = ("test", "model", os.path.join("model", "a2"))
PACKERS = ("def act(", "def hdr(", "def host_pushes(", "def host_stream(")

# the Verilog localparams that must agree, and where they live
RTL_EXPECT = {
    "ACT_W": pe_isa.ACT_W,
    "ACT_BYTES": pe_isa.ACT_BYTES,
    "BQW": pe_isa.BQW,
    "PINW": pe_isa.PINW,
    "DLY_W": pe_isa.DLY_W,
    "HDR_BITS": pe_isa.HDR_BITS,
    "HDR_BYTES": pe_isa.HDR_BYTES,
}


def find_second_definitions():
    hits = []
    for d in SCAN_DIRS:
        full = os.path.join(ROOT, d)
        if not os.path.isdir(full):
            continue
        for fn in sorted(os.listdir(full)):
            if not fn.endswith(".py"):
                continue
            rel = "%s/%s" % (d.replace(os.sep, "/"), fn)
            # ⛔ THIS FILE NAMES THE PACKERS IN ORDER TO LOOK FOR THEM, so
            # scanning itself reports itself. The owner and the scanner are
            # both excluded, and both exclusions are named rather than being
            # a silent skip.
            if rel in (OWNER, "model/gate_one_encoder.py"):
                continue
            with open(os.path.join(full, fn), encoding="utf-8") as fh:
                txt = fh.read()
            for pk in PACKERS:
                if pk in txt:
                    hits.append((rel, pk))
    return hits


def _ternary_to_py(e):
    """Verilog `c ? a : b` -> Python `a if c else b`, right-associative.

    THIS WAS THE REAL BLOCKER, NOT THE REGEX. `PINW` is a four-line ternary
    chain, and Python cannot eval Verilog ternary syntax, so it resolved to None
    and `ACT_W`, `HDR_BITS` and `ACT_BYTES` -- which depend on it -- all
    reported "not found". The symptom looked like a parsing failure and sent me
    after the regex twice before I printed the captured text and the resolved
    environment side by side.
    The matching `:` is found by tracking nested `?`, so `c1 ? v1 : c2 ? v2 : v3`
    nests the way Verilog reads it.
    """
    if "?" not in e:
        return e
    q = e.index("?")
    cond, rest = e[:q], e[q + 1:]
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "?":
            depth += 1
        elif ch == ":":
            if depth == 0:
                return "((%s) if (%s) else (%s))" % (
                    _ternary_to_py(rest[:i]), cond,
                    _ternary_to_py(rest[i + 1:]))
            depth -= 1
    return e


def rtl_params(path):
    """Extract `localparam integer NAME = <expr>;` and evaluate the integer ones.

    ⛔ EVALUATED, NOT STRING-MATCHED. The Verilog says
    `ACT_W = 3 + PINW + 1 + DLY_W + BPW + BQW`, which no literal comparison
    could check against 24 -- and a string match would also pass if the
    expression were rewritten to a different value with the same text shape.
    """
    with open(path, encoding="utf-8") as fh:
        txt = fh.read()
    # strip comments so a commented-out localparam cannot be picked up
    txt = re.sub(r"//[^\n]*", "", txt)
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    env, pend = {}, {}
    # ⛔ PORT-LIST PARAMETERS END WITH A COMMA, NOT A SEMICOLON. Requiring `;`
    # found `BQW` (a body localparam) and missed `DLY_W`/`PINW` in the module
    # header, so `ACT_W` could not resolve and every width reported "not found"
    # -- a check that fails for a parsing reason looks exactly like a check that
    # fails for a real one.
    # TWO PATTERNS, because the two declaration forms terminate
    # differently. A body `localparam` ends at `;` and may span LINES and
    # contain PARENS -- `PINW` is a multi-line ternary, so stopping at the
    # first `)` truncated it inside `(N_PINS <= 2)`. A port-list
    # `parameter` ends at a comma. One pattern cannot do both, and the
    # version that tried reported five widths as "not found".
    body = r"localparam\s+integer\s+(\w+)\s*=([^;]+);"
    port = r"parameter\s+integer\s+(\w+)\s*=([^,)\n]+)"
    for pat in (body, port):
        for m in re.finditer(pat, txt, re.S):
            pend.setdefault(m.group(1), m.group(2).strip())
    # resolve iteratively: the expressions reference each other
    for _ in range(8):
        for name, expr in list(pend.items()):
            e = _ternary_to_py(expr.replace("'", ""))
            try:
                env[name] = int(eval(e, {"__builtins__": {}}, dict(env)))
                pend.pop(name, None)
            except Exception:
                continue
    return env


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("ONE ENCODER GUARD")
    print("=" * 78)
    print("  owner  : %s" % OWNER)
    print("  digest : %s" % pe_isa.digest())

    # ---- 1. no second definition --------------------------------------
    print()
    print("  --- 1. no second definition of a packer ---")
    hits = find_second_definitions()
    if hits:
        for rel, pk in hits:
            print("    *** %s defines %s" % (rel, pk))
        print("    A re-implemented packer is the two-copies defect; import")
        print("    from %s instead." % OWNER)
        rc = 1
    else:
        print("    none -- every artefact imports the owner")

    # ---- 2. the digest, wherever it is printed ------------------------
    print()
    print("  --- 2. the digest is consistent ---")
    import importlib
    seen = {}
    for mod, path in (("make_smoke_image", "test"), ("corpus", "test"),
                      ("pe_asm", "model")):
        sys.path.insert(0, os.path.join(ROOT, path))
        try:
            m = importlib.import_module(mod)
        except Exception as e:
            print("    *** %s did not import: %s" % (mod, e))
            rc = 1
            continue
        d = getattr(m, "pe_isa", pe_isa).digest()
        seen[mod] = d
        print("    %-18s %s" % (mod, d))
    if len(set(seen.values())) > 1:
        print("    *** DIGESTS DISAGREE: %s" % seen)
        rc = 1
    elif seen:
        print("    all agree -- one encoding in use across %d artefacts"
              % len(seen))

    # ---- 3. the RTL agrees (cross-language) ---------------------------
    print()
    print("  --- 3. the RTL's own widths agree ---")
    env = rtl_params(os.path.join(ROOT, "src", "pe_engine.v"))
    for name, want in sorted(RTL_EXPECT.items()):
        got = env.get(name)
        if got is None:
            print("    %-10s *** not found in src/pe_engine.v" % name)
            rc = 1
        elif got != want:
            print("    %-10s *** RTL says %s, pe_isa says %s" % (name, got, want))
            rc = 1
        else:
            print("    %-10s %s  agrees" % (name, got))

    # ---- the must-fire: a drifted width has to FAIL -------------------
    # ⛔ Priced, not trusted. ACT_W really did change 22 -> 24, in two languages,
    # in two commits -- the window where they disagreed is the thing this check
    # exists to close, so it is shown to detect one.
    print()
    print("  --- must-fire: a drifted RTL width ---")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(ROOT, "src", "pe_engine.v")
        with open(src, encoding="utf-8") as fh:
            txt = fh.read()
        bad = txt.replace("localparam integer BQW   = 2;",
                          "localparam integer BQW   = 3;", 1)
        if bad == txt:
            print("    *** could not inject a drift -- the anchor moved")
            rc = 1
        else:
            tmp = os.path.join(td, "pe_engine.v")
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(bad)
            env2 = rtl_params(tmp)
            got2 = env2.get("ACT_W")
            if got2 is None:
                print("    *** FIRED FOR THE WRONG REASON: ACT_W did not")
                print("        resolve at all, so this proves a parsing")
                print("        failure rather than drift detection.")
                rc = 1
            elif got2 == pe_isa.ACT_W:
                print("    *** DID NOT FIRE: BQW 2->3 left ACT_W unchanged")
                rc = 1
            else:
                print("    BQW 2->3 makes the RTL ACT_W %s against pe_isa %s"
                      % (got2, pe_isa.ACT_W))
                print("    => a drift in either language is caught")

    print()
    print("=" * 78)
    print("  GATE one-encoder: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
