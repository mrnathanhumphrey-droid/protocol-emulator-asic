"""EVERY ARRAY ACCESS INDEXED BY A PROGRAM-CONTROLLED FIELD IS GUARDED.

⛔⛔ WHY THIS GATE EXISTS: THE SAME DEFECT THREE TIMES. `PINW = 4` addresses
pins 0..15 while only `N_PINS = 12` exist, so any array indexed by a pin field
a PROGRAM chooses can be driven out of range. It has happened three times, each
found separately, each fixed separately:

  1. the WRITE side -- `pin_out[12]`, fixed with `pin_real` and `clk_real`
     after it shipped;
  2. the RX SAMPLE -- `pin_in[a_pin]` read unguarded, so `OP_SHIFTIN` on
     PIN_NONE put X into `l_rx`, then `rx_data`, then the serial readback, and
     the X LEFT THE CHIP on `ser_d`;
  3. the EDGE SELECT -- `pin_rise[l_armpin[gi]]`, found by the sweep this gate
     is, and measured: with the ARM pin at PIN_NONE, `arm_hit` was X for all
     198 armed cycles of a probe program against 0 for the same program on a
     real pin.

Two instances is a coincidence; three is a class. "Fix one axis, miss the
parallel one" will keep recurring until something enumerates the family, so
this gate does.

⭐⭐ IT IS KEYED ON (FILE, ARRAY, INDEX) AND NOT ON LINE NUMBERS. That is
deliberate and it is the second lesson folded in: a line-keyed table drifts the
moment anything above it is edited, which cost a red CI run earlier the same
day. Keyed this way, a NEW access with the same array and index is
automatically held to the same guard, and a new (array, index) PAIR is
unclassified and fails. Nothing to re-anchor, ever.

⚠ WHAT IT CHECKS, STATED HONESTLY. For each site it requires the site's OWN
declared guard token to be USED within a 60-line window above it -- as
`if (g)`, `g ?`, or `& g`. That is a scope approximation, not a proof that the
guard dominates the access:
  * the window is 60 because the measured worst case in this file is 48 (the
    `OP_SHIFT` arm, whose comment block is long), so it is derived rather
    than picked;
  * it demands the SPECIFIC token, because a generic "some guard is nearby"
    search found `clk_real` 30 lines above a deliberately UNGUARDED mutant arm
    and would have passed it;
  * a site inside an `ifdef M_*` arm is a DECLARED MUTATION, not a defect, and
    is reported as such -- those arms exist to be unguarded.
What it closes is a new unguarded access appearing without anyone noticing.
Whether a guard is correctly placed is the mutants' claim, not this gate's.
"""

from __future__ import annotations

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

SOURCES = ("src/pe_engine.v", "src/pe_store.v", "src/project.v")
WINDOW = 60          # derived: measured worst case is 48 lines

#: ⛔ INDEX EXPRESSIONS A PROGRAM CAN SET -- out of an action or a header field.
#: Lane and slot indices (`cur`, `pl`, `hl`, `gi`, `i`) are bounded by their own
#: counters and are NOT program-controlled; including them would bury the real
#: family in noise.
PROGRAM_INDEX = (
    (r"a_pin", "a_pin"),
    (r"l_clkpin\[[a-z_0-9]+\]", "l_clkpin[*]"),
    (r"l_pin\[[a-z_0-9]+\]", "l_pin[*]"),
    (r"l_armpin\[[a-z_0-9]+\]", "l_armpin[*]"),
    (r"hsh_n\[[^\]]*\]", "hsh_n[*]"),
)
IDX_RE = "(?:" + "|".join(p for p, _n in PROGRAM_INDEX) + ")"
ACCESS = re.compile(r"([a-z_][a-z_0-9]*)\s*\[\s*(" + IDX_RE + r")\s*\]")

# ---------------------------------------------------------------------------
# THE CLASSIFICATION: (file, array, normalised index) -> (guard token, reason)
# ⛔ An access whose (array, index) pair is not here FAILS.
# ---------------------------------------------------------------------------
CLASSIFIED = {
    ("src/pe_engine.v", "pin_in", "a_pin"): (
        "pin_real",
        "THE RX SAMPLE, and it shipped unguarded. `OP_SHIFTIN`/`OP_READBIT` on "
        "the reserved index read `pin_in[15]` against a [11:0] vector; the X "
        "went into `l_rx`, then `rx_data`, then the serial readback, and left "
        "the chip on `ser_d` while `ser_v` was high. Now one guarded wire "
        "`rx_bit = pin_real ? pin_in[a_pin] : 1'b0` serves all three sample "
        "sites, so a fourth cannot copy the unguarded form from a neighbour. "
        "Priced by `M_UNGUARDED_SAMPLE`: 0 serial X guarded, 112 without."),
    ("src/pe_engine.v", "pin_out", "a_pin"): (
        "pin_real",
        "The data-pin WRITE. This is the original instance of the family -- "
        "an out-of-range `pin_out[12]` -- and the reason `pin_real` exists at "
        "all. Both the OP_LEVEL/START/STOP arm and the OP_SHIFT arm sit under "
        "`if (pin_real)`."),
    ("src/pe_engine.v", "pin_oe", "a_pin"): (
        "pin_real",
        "The data pin's output ENABLE, written beside `pin_out` in every arm "
        "and guarded by the same condition. ⚠ It needs naming separately "
        "because an open-drain lane drives `pin_oe` and holds `pin_out` at 0, "
        "so a guard on the data write alone would leave the enable exposed."),
    ("src/pe_engine.v", "pin_pp", "a_pin"): (
        "pin_real",
        "The per-pin drive class, READ in the data-pin write to mask an "
        "open-drain lane's 1. A read is as exposed as a write: an "
        "out-of-range read is X in simulation and an UNSPECIFIED synthesised "
        "value in silicon, and `a_lvl & pin_pp[15]` would carry that straight "
        "to the pin."),
    ("src/pe_engine.v", "pin_out", "l_clkpin[*]"): (
        "clk_real",
        "The CLOCK-pin write. ⛔ It needed its own guard, separate from "
        "`pin_real`: the clock pin is a different header field from the data "
        "pin, so a lane may name a real data pin and a non-real clock -- which "
        "an SPI TARGET does deliberately, naming PIN_NONE because the master "
        "supplies SCK."),
    ("src/pe_engine.v", "pin_oe", "l_clkpin[*]"): (
        "clk_real",
        "The clock pin's output enable, under the same `if (clk_real)`. Same "
        "reasoning as the data pin's enable: open-drain drives the enable, not "
        "the level."),
    ("src/pe_engine.v", "pin_pp", "l_clkpin[*]"): (
        "clk_real",
        "The clock pin's drive class, read inside the clock write to mask an "
        "open-drain 1. Guarded by `clk_real` with the write it feeds."),
    ("src/pe_engine.v", "pin_rise", "l_armpin[*]"): (
        "arm_real",
        "THE EDGE SELECT -- the third instance, and the one this gate's sweep "
        "found. `l_armpin[cur] <= a_pin` is written straight from the action's "
        "pin field with nothing refusing it, and `pin_rise` is [11:0]. "
        "MEASURED: with the ARM pin at PIN_NONE, `arm_hit` was X for all 198 "
        "armed cycles of a probe program, against 0 for the same program on a "
        "real pin. ⚠ `ready` did NOT go X -- the other terms masked it -- so "
        "it was NOT shown to reach the scheduler; guarded anyway, because an X "
        "at a flop's input surviving on which terms happen to mask it is not a "
        "property to rely on. Priced by `M_UNGUARDED_ARMPIN`: 0 X guarded, "
        "198 without."),
    ("src/pe_engine.v", "pin_fall", "l_armpin[*]"): (
        "arm_real",
        "The falling-edge half of the same select, in the same conditional "
        "expression and under the same guard. Both arms of the `?:` index the "
        "same program field, so guarding one would leave the other open -- "
        "which is the asymmetry that made D2 a defect."),
    ("src/pe_engine.v", "pin_pp", "hsh_n[*]"): (
        "< N_PINS",
        "The HEADER-TIME write of the drive class, indexed by a raw header "
        "field before any dispatch has validated it. Guarded inline with an "
        "explicit `< N_PINS` comparison rather than a named wire, because the "
        "value being tested is a bit-slice of the shift register and there is "
        "no per-lane register to hang a wire on yet. A header may legitimately "
        "name the reserved index, so this must skip rather than refuse."),
    ("src/pe_engine.v", "pin_rise", "l_clkpin[*]"): (
        "< N_PINS",
        "THE FOURTH INSTANCE OF THE CLASS, arriving with the self-clocked "
        "SHIFTIN. `ck_hit` watches the lane's CLOCK pin for the rise that says "
        "the peer has released it, and `l_clkpin` comes from a header field "
        "that may legitimately name PIN_NONE -- an SPI TARGET declares exactly "
        "that, because the master supplies the clock. `pin_rise` is [11:0], so "
        "an unguarded read would be `pin_rise[15]`. Guarded by an explicit "
        "`< N_PINS` on `ckp_real`, and `ck_hit = 0` is the RIGHT meaning rather "
        "than merely the safe one: a self-clocked shift is impossible without a "
        "real clock pin, so this capture can never legitimately fire on one."),
    ("src/pe_engine.v", "pin_in", "l_pin[*]"): (
        "< N_PINS",
        "THE SAMPLED DATA PIN, guarded SEPARATELY from the clock pin above, and "
        "the separation is the point: a lane may name a real clock and a "
        "RESERVED data pin, so the two guards answer different questions. "
        "Reading `pin_in[15]` would latch X into `l_cksamp` and carry it into "
        "the RX accumulator and the serial readback -- the identical path "
        "`pinnone_image.hex` was built to catch on the UNCLOCKED sample, which "
        "is why this one is guarded at birth instead of after a measurement."),
}


def strip_comment(line: str) -> str:
    i = line.find("//")
    return line if i < 0 else line[:i]


def normalise(idx: str) -> str:
    for pat, name in PROGRAM_INDEX:
        if re.fullmatch(pat, idx):
            return name
    return idx


def mutant_depth(lines, upto):
    """Names of the `M_*` defines whose arm actually encloses `upto`.

    ⛔ A SITE INSIDE A MUTANT ARM IS A DECLARED MUTATION. Those arms exist to
    reproduce the defect, so demanding a guard inside one would make the gate
    red on the very code that prices the guard.

    ⛔⛔ BUT `else` MUST BE TRACKED, AND THE FIRST VERSION DID NOT TRACK IT.
    It treated everything between `ifdef M_X` and `endif` as inside the arm --
    including the `else` branch, which is the NORMAL path. Nine of the
    twenty-four sites were then excused as "unguarded by design" when they are
    the real, `clk_real`-guarded clock writes, so the gate passed them WITHOUT
    CHECKING THEIR GUARD AT ALL. A gate that passes because of a parsing flaw
    is the exact class this file exists to catch, and it was in the file.
    ⇒ `ifdef M_X` body = the mutation; its `else` = normal. `ifndef M_X` is
    inverted: body normal, `else` the mutation.
    """
    stack = []          # (name, in_mutation_arm)
    for i in range(upto):
        t = lines[i].strip()
        m = re.match(r"`(ifdef|ifndef)\s+([A-Za-z_][A-Za-z_0-9]*)", t)
        if m:
            stack.append([m.group(2), m.group(1) == "ifdef"])
            continue
        if t.startswith("`else"):
            if stack:
                stack[-1][1] = not stack[-1][1]
            continue
        if t.startswith("`endif"):
            if stack:
                stack.pop()
            continue
    return [n for n, inmut in stack if n.startswith("M_") and inmut]


def sites():
    out = []
    for rel in SOURCES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        for n, raw in enumerate(lines, 1):
            code = strip_comment(raw)
            for m in ACCESS.finditer(code):
                out.append({"file": rel, "line": n, "array": m.group(1),
                            "index": normalise(m.group(2)),
                            "text": code.strip(),
                            "mutant": mutant_depth(lines, n - 1),
                            "lines": lines})
    return out


#: a `case` arm label: `OP_SHIFT:`, `OP_ARM, OP_REARM:`, `default:`
ARM_LABEL = re.compile(r"^\s*(?:[A-Z_][A-Z_0-9]*\s*,\s*)*"
                       r"(?:[A-Z_][A-Z_0-9]*|default)\s*:")


def guard_used(lines, site_line, token):
    """Is this site's OWN guard token used at or inside its own case arm?

    ⛔⛔ THE SEARCH STOPS AT A CASE-ARM LABEL, and the first version did not --
    which made the must-fire almost useless. With `OP_SHIFT: if (pin_real)`
    deleted, the sites under it searched back 60 lines, found the OP_LEVEL
    arm's OWN `if (pin_real)` 57 lines further up, and reported themselves
    guarded: removing a guard exposed ONE site where five depend on it.
    ⇒ A guard in a DIFFERENT arm guards nothing here. The label line itself is
    included, because that is where this file puts the guard
    (`OP_SHIFT: if (pin_real) begin`).
    """
    if token == "< N_PINS":
        pat = re.compile(r"<\s*N_PINS")
    else:
        t = re.escape(token)
        pat = re.compile(r"(if\s*\(\s*%s\b|%s\s*\?|&\s*%s\b)" % (t, t, t))
    for d in range(0, WINDOW + 1):
        i = site_line - 1 - d
        if i < 0:
            break
        code = strip_comment(lines[i])
        if pat.search(code):
            return d
        if d > 0 and ARM_LABEL.match(code):
            return None          # crossed out of this site's own arm
    return None


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("PROGRAM-INDEX GUARD AUDIT -- the same defect three times")
    print("=" * 78)
    found = sites()
    if not found:
        print("  *** NO SITES FOUND AT ALL, which is a finding rather than a")
        print("      pass: the engine indexes pin arrays by action fields by")
        print("      construction, so either the scan no longer matches how")
        print("      they are written or the sources moved.")
        return 1
    pairs = sorted({(s["file"], s["array"], s["index"]) for s in found})
    print("  sites: %d   distinct (file, array, index) pairs: %d"
          % (len(found), len(pairs)))
    print("  window: %d lines (measured worst case 48)" % WINDOW)

    print()
    print("  --- every pair is classified ---")
    for key in pairs:
        if key in CLASSIFIED:
            print("    %-18s %-9s [%-14s] guard: %s"
                  % (key[0], key[1], key[2], CLASSIFIED[key][0]))
        else:
            print("    *** UNCLASSIFIED  %s %s[%s]" % key)
            print("        ⛔ A NEW array access indexed by a program-")
            print("           controlled field. `PINW` addresses 0..15 and")
            print("           only N_PINS pins exist, so this can be driven")
            print("           out of range by a program. Give it a range")
            print("           guard and classify it, or write the reason it")
            print("           needs none.")
            rc = 1

    print()
    print("  --- each site's own guard is used above it ---")
    n_mut = 0
    for s in sorted(found, key=lambda x: (x["file"], x["line"])):
        key = (s["file"], s["array"], s["index"])
        if s["mutant"]:
            n_mut += 1
            print("    %-5d %-9s [%-14s] MUTANT ARM (%s) -- unguarded by design"
                  % (s["line"], s["array"], s["index"], ",".join(s["mutant"])))
            continue
        if key not in CLASSIFIED:
            continue
        token = CLASSIFIED[key][0]
        d = guard_used(s["lines"], s["line"], token)
        if d is None:
            print("    *** %-5d %-9s [%-14s] NO `%s` within %d lines"
                  % (s["line"], s["array"], s["index"], token, WINDOW))
            print("        %s" % s["text"][:62])
            print("        ⛔ The access is classified as guarded by `%s` and"
                  % token)
            print("           that guard is not used above it. Either the")
            print("           guard was removed or the access moved out of")
            print("           its scope.")
            rc = 1
        else:
            print("    %-5d %-9s [%-14s] `%s` at -%d"
                  % (s["line"], s["array"], s["index"], token, d))
    if n_mut:
        print("    (%d site(s) inside mutant arms, reported not required)" % n_mut)

    print()
    print("  --- the reasons ---")
    short = [k for k, (_g, why) in CLASSIFIED.items()
             if len((why or "").strip()) < 80]
    for k in short:
        print("    *** REASON TOO SHORT  %s %s[%s]" % k)
        rc = 1
    stale = sorted(set(CLASSIFIED) - set(pairs))
    for k in stale:
        print("    *** CLASSIFIED BUT NOT PRESENT  %s %s[%s]" % k)
        print("        The access is gone. Remove the entry, or the table")
        print("        describes code that no longer exists.")
        rc = 1
    if not short and not stale:
        print("    %d entries, every reason substantive, none stale"
              % len(CLASSIFIED))

    rc |= selftest()
    print()
    print("=" * 78)
    print("  GATE program-index: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means every program-indexed access is classified and")
    print("      its declared guard is used above it. It does NOT prove the")
    print("      guard dominates the access -- that is the mutants' claim")
    print("      (`M_UNGUARDED_SAMPLE`, `M_UNGUARDED_ARMPIN`).")
    return rc


def selftest() -> int:
    """⛔ PRICE IT: drop a guard and the gate must fail."""
    rc = 0
    print()
    print("  --- must-fire: drop a guard, the gate fails ---")
    path = os.path.join(ROOT, "src", "pe_engine.v")
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    # the OP_SHIFT arm's `if (pin_real)` is the furthest guard from its sites
    # (48 lines), so removing it is the hardest case for the window.
    victim = None
    for n, raw in enumerate(lines, 1):
        if re.search(r"OP_SHIFT:\s*if\s*\(\s*pin_real\s*\)", strip_comment(raw)):
            victim = n
            break
    if victim is None:
        print("    *** could not find the OP_SHIFT guard to remove, so this")
        print("        must-fire cannot run -- and an unpriced gate has")
        print("        unknown strength.")
        return 1
    mutated = list(lines)
    mutated[victim - 1] = "            OP_SHIFT: begin"
    # ⛔⛔ EVERY `pin_real` GUARD INSIDE THE OP_SHIFT ARM, NOT JUST THE LABEL'S.
    # Removing only `OP_SHIFT: if (pin_real)` reported "0 sites exposed" the
    # moment the self-clocked arm landed, because the clocked and unclocked
    # data writes each carry a LOCAL `if (pin_real)` -- so dropping one of three
    # guards leaves the other two doing the work, and the must-fire was
    # measuring a guard that had stopped being load-bearing.
    # ⭐ A MUST-FIRE THAT STOPS EXPOSING SITES IS NOT A PASS; it is the signal
    # that what it mutates no longer matters. So the mutant removes the WHOLE
    # family: if ANY `pin_real` in this arm still covers these writes, the gate
    # must not be able to call them guarded.
    for n in range(victim, len(mutated)):
        code = strip_comment(mutated[n])
        if ARM_LABEL.match(code) and n != victim - 1:
            break                       # left the OP_SHIFT arm
        if re.match(r"^\s*if\s*\(\s*pin_real\s*\)\s*begin\s*$", code):
            mutated[n] = re.sub(r"if\s*\(\s*pin_real\s*\)\s*begin",
                                "begin", mutated[n])
    # the sites that depended on it must now report no guard
    bad = 0
    for n, raw in enumerate(mutated, 1):
        code = strip_comment(raw)
        for mm in ACCESS.finditer(code):
            arr, idx = mm.group(1), normalise(mm.group(2))
            key = ("src/pe_engine.v", arr, idx)
            if key not in CLASSIFIED:
                continue
            if mutant_depth(mutated, n - 1):
                continue
            if guard_used(mutated, n, CLASSIFIED[key][0]) is None:
                bad += 1
    print("    %-52s %s (%d site(s) exposed)"
          % ("removing the OP_SHIFT pin_real guard is caught",
             "ok" if bad > 0 else "*** MISSED", bad))
    if bad == 0:
        rc = 1
    # and the clean tree must NOT report any
    clean_bad = 0
    for n, raw in enumerate(lines, 1):
        code = strip_comment(raw)
        for mm in ACCESS.finditer(code):
            key = ("src/pe_engine.v", mm.group(1), normalise(mm.group(2)))
            if key not in CLASSIFIED or mutant_depth(lines, n - 1):
                continue
            if guard_used(lines, n, CLASSIFIED[key][0]) is None:
                clean_bad += 1
    print("    %-52s %s" % ("the unmutated tree reports none",
                            "ok" if clean_bad == 0 else "*** %d" % clean_bad))
    if clean_bad:
        rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
