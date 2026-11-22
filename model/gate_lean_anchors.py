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
    # (retired 11-14: Step.br1's branch-1 anchor now quotes the batch's pf_q line -- item 3)
}

#: Wilson 11-22 (slot buffer piece 2, ruling 2): the port lines Step.lean quotes are rewritten
#: by the slot buffer; agent 2 re-anchors them to `portNextB` at piece 5. While these -- and ONLY
#: these -- are missing, the gate reads STALE (model/stale_records.py), not PASSED.
STALE_ANCHORS = (
    "if (pf_v_q && l_live[pf_q] && !l_actv[hix[pf_q]] && !ft_flush[pf_q]) begin",
    "end else if (l_live[prr] && want_fetch(prr) && !ft_flush[prr]) begin",
)
GATE = "model/gate_lean_anchors.py"


def _stale_records():
    sys.path.insert(0, HERE)
    import stale_records
    return stale_records


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
    # the STALE scope: only the declared anchors are excused, never a planted one
    SR = _stale_records()
    raw = sorted(set(_norm(m.split(" ", 1)[1]) for m in missing))
    st_list = [_norm(a) for a in STALE_ANCHORS]
    sc_ok, _l = SR.anchor_stale(GATE, "lean-anchors", st_list + ["planted 0xDEAD"], st_list)
    kills = [("M_LA_STALE_SCOPE", not sc_ok, "a missing anchor off the stale list is excused")]
    for name, killed, what in kills:
        print("  must-fire %-14s %s  %s" % (name, "RED (killed)" if killed else "SURVIVED", what))
    teeth = teeth and not sc_ok
    stale_line = None
    if missing and not bad_pending and teeth:
        st_ok, why = SR.anchor_stale(GATE, "lean-anchors", raw, st_list)
        if st_ok:
            stale_line = why
        else:
            print("  *** %s" % why)
    elif not missing:
        back = [a for a in st_list if a in _norm(rtl)]
        if back:
            print("  *** STALE_ANCHORS entry back in the RTL (retire it): %s" % back[0])
            ok = False
    if stale_line:
        print(stale_line)
        return 0
    verdict = "PASSED" if ok and teeth else ("FAILED (must-fire survived)" if not teeth else "FAILED")
    print("GATE lean-anchors: %s" % verdict)
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
