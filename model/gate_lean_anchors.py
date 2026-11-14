"""gate_lean_anchors -- every RTL anchor quoted in the Lean library must still be in the RTL.

The Lean model (lean/JLane) cites `src/pe_engine.v` by SUBSTRING ("anchor `...`"), the way
gate_j_proof_anchors.py checks docs/J_LANE_PROOF.md: a line number is layout, a substring is
design. A model whose anchors have left the RTL reads as settled and is not. This gate finds every
backticked anchor after the word "anchor"/"anchors" in lean/JLane/JLane/*.lean and requires it
in the RTL (whitespace-normalised).

PENDING lists an anchor known to be stale, with the work that retires it. A pending anchor that
is back in the RTL, or one no longer quoted, is itself a failure (the list must not outlive it).

  must-fire M_LA_PLANTED   an anchor that is not in the RTL     -> rejected
  must-fire M_LA_PENDING   a PENDING entry that is not stale    -> rejected
Static, < 1 s. Usage: python model/gate_lean_anchors.py
"""
from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RTL = os.path.join(ROOT, "src", "pe_engine.v")
LEAN = os.path.join(ROOT, "lean", "JLane", "JLane")

#: anchor text -> why it is stale and what retires it
PENDING = {
    "if (winner_v_q && l_live[winner_q] && !l_actv[hix[winner_q]]) begin":
        "Step.br1 models the pre-batch branch 1 (winner_q); the batch reads pf_q (l.3264). "
        "Retired by the pf_q port model (agent 2 item 3, Nate 11-14).",
}


def _norm(t):
    return re.sub(r"\s+", " ", t).strip()


def anchors(text):
    for m in re.finditer(r"[Aa]nchors? ((?:`[^`]+`(?:,\s*)?)+)", text):
        line = text[:m.start()].count("\n") + 1
        for a in re.findall(r"`([^`]+)`", m.group(1)):
            yield line, a


def check(rtl_text, lean_files, pending):
    R = _norm(rtl_text)
    missing, quoted = [], set()
    for f in lean_files:
        s = open(f, encoding="utf-8").read()
        for line, a in anchors(s):
            quoted.add(_norm(a))
            if _norm(a) not in R and a not in pending:
                missing.append("%s:%d %s" % (os.path.basename(f), line, a))
    bad_pending = [a for a in pending if _norm(a) in R or _norm(a) not in quoted]
    return missing, bad_pending, len(quoted)


def main():
    rtl = open(RTL, encoding="utf-8").read()
    files = sorted(glob.glob(os.path.join(LEAN, "*.lean")))
    missing, bad_pending, n = check(rtl, files, PENDING)
    print("gate_lean_anchors: %d distinct anchors in %d Lean files" % (n, len(files)))
    for m in missing:
        print("  MISSING  %s" % m)
    for a in bad_pending:
        print("  PENDING entry not stale (back in the RTL or no longer quoted): %s" % a)
    for a, why in PENDING.items():
        if a not in bad_pending:
            print("  pending  %s\n           %s" % (a, why))
    ok = not missing and not bad_pending
    # must-fires
    kills = []
    fake = "-- anchor `this text is not in the RTL at all 0xDEAD`\n"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fp = os.path.join(td, "Planted.lean")
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(fake)
        m2, _b, _n = check(rtl, files + [fp], PENDING)
    kills.append(("M_LA_PLANTED", bool(m2), "an anchor not in the RTL"))
    _m, b3, _n = check(rtl, files, dict(PENDING, **{"localparam": "planted: present in the RTL"}))
    kills.append(("M_LA_PENDING", bool(b3), "a PENDING entry that is not stale"))
    for name, killed, what in kills:
        print("  must-fire %-14s %s  %s" % (name, "RED (killed)" if killed else "SURVIVED", what))
    teeth = all(k for _n2, k, _w in kills)
    verdict = "PASSED" if ok and teeth else ("FAILED (must-fire survived)" if not teeth else "FAILED")
    print("GATE lean-anchors: %s" % verdict)
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
