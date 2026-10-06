"""RE-ANCHOR the coverage gate's line numbers by MEASURED shift.

⛔⛔ WHY THIS IS A TOOL AND NOT A HABIT. `test/gate_coverage.py` keys every
classification and every anchor on a LINE NUMBER, with the source text recorded
beside it so drift is detectable. That design is right -- it caught a
mis-anchoring in CI once already -- but applying the shift BY HAND is a
recurring manual step over dozens of entries, and the one time it was done from
a remembered statement instead of the measured shift, it landed on the wrong
line and CI caught it. A mechanical step done by hand repeatedly is an error
waiting for a tired afternoon.

WHAT IT WILL DO: for each recorded anchor whose text no longer sits on its line,
find where that exact text IS, and rewrite the entry's line number -- in the
CLASSIFIED keys, the ANCHOR_TEXT keys, and the full-case line list together, so
the three cannot drift apart.

⛔ WHAT IT REFUSES TO DO, which is the whole safety of it:
  * if an anchor's text appears NOWHERE, it stops. That is not a shift, it is a
    deleted or edited line, and it needs a human decision about whether the
    classification still means anything.
  * if the text appears several times, it resolves duplicates ONLY by preserving
    the recorded order of the entries -- the same text at lines a < b maps to
    candidates a' < b'. If the counts differ, it stops.
  * it never invents, removes or reclassifies an entry. A NEW uncovered point
    still has to be adjudicated by hand, with a written reason, which is the
    part that should never be automated.
"""
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE = os.path.join(ROOT, "test", "gate_coverage.py")


def main(apply_it):
    sys.path.insert(0, os.path.join(ROOT, "test"))
    import gate_coverage as G

    src = {}
    for f in sorted({k[0] for k in G.ANCHOR_TEXT}):
        path = os.path.join(ROOT, f)
        if not os.path.isfile(path):
            print("  *** source missing: %s" % f)
            return 1
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            src[f] = fh.read().splitlines()

    # group the recorded anchors by (file, text) so duplicates can be ordered
    want = {}
    for (f, ln), txt in G.ANCHOR_TEXT.items():
        want.setdefault((f, txt.strip()), []).append(ln)
    moves, stuck, ambiguous = [], [], []
    for (f, txt), lns in sorted(want.items()):
        lns = sorted(lns)
        here = [i + 1 for i, l in enumerate(src[f]) if l.strip() == txt]
        if not here:
            stuck.append((f, lns, txt, "the text appears NOWHERE"))
            continue
        if len(here) != len(lns):
            if all(l in here for l in lns):
                continue            # already correct, extra copies elsewhere
            # ⭐⭐ RESOLVED BY THE GLOBAL SHIFT, not by guessing. A duplicated
            # anchor text with MORE copies than records is the common case --
            # `if (clk_real) begin` has three occurrences and two of them are
            # classified -- and it recurred on every run. The shift is a
            # PROPERTY OF THE EDIT, measurable from the anchors that ARE
            # unambiguous, so each record maps to the candidate nearest
            # `old + shift`, order preserved and no candidate used twice.
            # ⛔ IT STILL REFUSES when that mapping is not consistent: if a
            # chosen target is further than `TOL` from the expected shift, the
            # text has moved for some reason other than the edit's shift, and
            # that is a human call again.
            ambiguous.append((f, lns, txt, here))
            continue
        for old, new in zip(lns, here):
            if old != new:
                moves.append((f, old, new, txt))

    # the global shift, from the records that needed no guessing
    TOL = 40
    if ambiguous:
        deltas = sorted(n - o for _f, o, n, _t in moves)
        shift = deltas[len(deltas) // 2] if deltas else 0
        for f, lns, txt, here in ambiguous:
            used, ok = set(), True
            picks = []
            for old_ln in lns:
                cands = [h for h in here if h not in used and h >= (picks[-1] if picks else 0)]
                if not cands:
                    ok = False
                    break
                best = min(cands, key=lambda h: abs(h - (old_ln + shift)))
                if abs(best - (old_ln + shift)) > TOL:
                    ok = False
                    break
                used.add(best)
                picks.append(best)
            if not ok:
                stuck.append((f, lns, txt,
                              "%d recorded vs %d found, and the global shift "
                              "of %+d does not resolve it within %d lines"
                              % (len(lns), len(here), shift, TOL)))
                continue
            for old_ln, new_ln in zip(lns, picks):
                if old_ln != new_ln:
                    moves.append((f, old_ln, new_ln, txt))
        print("  (global shift measured at %+d from the unambiguous anchors)"
              % shift)

    print("  --- measured anchor shifts ---")
    for f, old, new, txt in moves:
        print("    %-16s %5d -> %-5d  %s" % (f.split("/")[-1], old, new,
                                             txt[:40]))
    if not moves:
        print("    none -- every anchor sits on its recorded line")
    if stuck:
        print()
        print("  *** STOPPED, %d anchor(s) cannot be shifted mechanically:"
              % len(stuck))
        for f, lns, txt, why in stuck:
            print("    %s %s: %s" % (f, lns, why))
            print("        %s" % txt[:60])
        print("    ⛔ A vanished or ambiguous anchor is NOT a shift. It means a")
        print("       line was edited or deleted, and whether the")
        print("       classification still means anything is a human call.")
        return 1
    if not apply_it:
        print()
        print("  (dry run; pass --apply to rewrite test/gate_coverage.py)")
        return 0

    with io.open(GATE, encoding="utf-8", newline="") as fh:
        text = fh.read()
    # ⛔ HIGHEST LINE FIRST, so a rewrite cannot collide with a number that is
    # itself about to move onto it.
    for f, old, new, _t in sorted(moves, key=lambda m: -m[1]):
        a = '("%s", %d, ' % (f, old)
        b = '("%s", %d, ' % (f, new)
        text = text.replace(a, b)
        a2 = '("%s", %d):' % (f, old)
        b2 = '("%s", %d):' % (f, new)
        text = text.replace(a2, b2)
    # the full-case line list travels with them
    m = re.search(r"for line in \(([\d, ]+)\):", text)
    if m:
        nums = [int(x) for x in m.group(1).replace(" ", "").split(",") if x]
        mapping = {old: new for _f, old, new, _t in moves}
        new_nums = [mapping.get(n, n) for n in nums]
        if new_nums != nums:
            text = text.replace(m.group(0),
                                "for line in (%s):"
                                % ", ".join(str(n) for n in new_nums))
            print("    full-case lines %s -> %s" % (nums, new_nums))
    with io.open(GATE, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print()
    print("  rewrote %d anchor(s) in test/gate_coverage.py" % len(moves))
    print("  ⛔ NOW RE-RUN THE GATE. This tool moves numbers; it does not")
    print("     adjudicate a point, and a NEW uncovered point still needs a")
    print("     written reason by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
