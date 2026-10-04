"""REVERSE TRACEABILITY -- every census program executed on the golden model.

THE ONE CLAIM: traceability is run in BOTH directions. S2 checks that every
frozen field traces to a ruling; this checks that every RULED BEHAVIOUR has a
field to live in -- by executing the S1 census on an executable semantics and
recording what state it actually needed.

⛔⛔ WHY THE OTHER DIRECTION WAS NOT ENOUGH, IN THE PROJECT'S OWN WORDS. S3
found FIVE fields the S2 freeze did not have -- per-lane program counter,
per-lane prefetch word, per-lane program base, a loop, and drive mode in the
image -- and the S2 gate could not have caught any of them, because
"traceability detects a field with no ruling, not a ruling with no field". It
found them the expensive way: by writing RTL and watching it fail, three
registered-read off-by-ones and a drive-mode bug later.

⭐ THIS IS THE CHEAP DIRECTION. The census already enumerates every action every
required program needs. Running those programs through a semantics built from
the FROZEN TABLE makes a missing field a mechanical result rather than a
discovery, and `golden.FieldSet` records the access instead of quietly working.

⛔ AND IT IS A REAL CHECK, NOT A RESTATEMENT, because the golden model is
written from the SPEC -- the census vocabulary, F1's word layout, S2's field
table -- and NOT from `pe_engine.v`. A model transcribed from the RTL would
agree with the engine on every bug they share.

SECOND CLAIM: OPCODE COVERAGE. `gate_cj_bounds` reports C_max derived for all 8
action types with only 2 EXERCISED by the smoke bench -- SHIFT, SHIFTIN,
READBIT, START, STOP and ARM were unmeasured. Executing the census exercises
every opcode the required protocols use, so "unexercised" stops being a
standing caveat on six of eight.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "a2"))

import golden                                                      # noqa: E402
from golden import Action, Machine                                 # noqa: E402
from gate_program_census import (ARM, LEVEL, PROGRAMS, READBIT,    # noqa: E402
                                 SHIFT, SHIFTIN, START, STOP, WAIT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ALL_OPS = [LEVEL, SHIFT, SHIFTIN, READBIT, START, STOP, ARM, WAIT]

# How each census program's lane is configured. ⭐ Pin numbers are arbitrary
# here: this gate asks whether the ISA can EXPRESS the program and what state
# that costs, not whether the pin map is right -- `gate_pin_subsets` owns that.
LANE_CFG = {
    "UART-tx":    dict(pin=0, clkpin=None, mode=1, period=434, d_sched=218),
    "UART-rx":    dict(pin=1, clkpin=None, mode=1, period=414, d_sched=215),
    "SPI-tx":     dict(pin=2, clkpin=3, mode=1, period=25, d_sched=25),
    "I2C":        dict(pin=4, clkpin=5, mode=0, period=45, d_sched=17),
    "SPI-target": dict(pin=6, clkpin=7, mode=1, period=25, d_sched=20),
}


def to_actions(spec, cfg):
    """The census's (opcode, why) pairs as decodable action words.

    ⛔ THE COUNT COMES FROM THE OPCODE, NOT FROM A GUESS: every SHIFT/SHIFTIN
    in the census is annotated "8 bits", and READBIT is one bit by definition.
    A census line that needed a different N would have to say so, and this
    would have to be re-read -- which is the point of enumerating actions
    rather than totalling them.
    """
    out = []
    for op, why in spec:
        n = 8 if op in (SHIFT, SHIFTIN) else (1 if op == READBIT else 0)
        lvl = 0
        if op == LEVEL:
            lvl = 1          # the census's LEVELs are both polarities; see note
        out.append(Action(op, pin=cfg["pin"], level=lvl,
                          delay=cfg["period"], count=n, note=why))
    # ⭐ Every required program is PERIODIC, so it must end by looping. The
    # census does not list a trailing WAIT because its job is to count the
    # actions a TRANSACTION costs -- but a program that never repeats is not a
    # protocol, and S3 found exactly this by watching a PC fall off the end.
    out.append(Action(WAIT, pin=cfg["pin"], level=1, delay=cfg["period"],
                      note="loop to the lane's program base (periodic)"))
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("REVERSE TRACEABILITY -- the census executed on the golden model")
    print("=" * 78)
    print("  frozen fields: %d" % len(golden.FROZEN))
    print("  census programs: %d   opcodes in the vocabulary: %d"
          % (len(PROGRAMS), len(ALL_OPS)))

    m = Machine(strict=False)
    per_prog = []
    for name, lane_name, builder in PROGRAMS:
        cfg = LANE_CFG[lane_name]
        acts = to_actions(builder(), cfg)
        m.add_lane("%s/%s" % (lane_name, name), acts, **cfg)
        per_prog.append((name, lane_name, len(acts)))

    print()
    print("  --- programs loaded ---")
    print("    %-28s %-12s %s" % ("program", "lane", "actions"))
    for name, lane_name, n in per_prog:
        print("    %-28s %-12s %d" % (name[:28], lane_name, n))

    events = m.run(horizon=200000, max_actions=20000)

    # ---- opcode coverage ------------------------------------------------
    print()
    print("  --- OPCODE COVERAGE (the 6 that gate_cj_bounds calls unexercised) ---")
    print("    %-10s %-10s %s" % ("opcode", "executed", ""))
    unexercised = []
    for op in ALL_OPS:
        n = m.ops_executed.get(op, 0)
        if n == 0:
            unexercised.append(op)
        print("    %-10s %-10d %s" % (op, n, "" if n else "*** NEVER RUN ***"))
    print("    pin events produced: %d" % len(events))
    if unexercised:
        print("    *** %d opcode(s) in the vocabulary are never executed by any")
        print("        census program: %s" % ", ".join(unexercised))
        print("        Either a required program needs one and the census")
        print("        missed it, or the opcode is not needed by the required")
        print("        protocols and its place in the ISA needs a reason.")
    else:
        print("    ⭐ ALL %d opcodes exercised by the required programs, so"
              % len(ALL_OPS))
        print("    'unexercised' is no longer a standing caveat on six of eight.")

    # ---- THE REVERSE-TRACEABILITY RESULT --------------------------------
    print()
    print("  --- ⛔ BEHAVIOURS WITH NO FIELD (the reverse direction) ---")
    if not m.missing:
        print("    none -- every piece of state the semantics needed is in the")
        print("    frozen table.")
    else:
        print("    %d field(s) the semantics REQUIRED and the S2 freeze does"
              % len(m.missing))
        print("    NOT contain:")
        for k in sorted(m.missing):
            print()
            print("      ⛔ %s" % k)
            for line in _wrap(m.missing[k], 66):
                print("         %s" % line)

    # ---- `armed` chased into the RTL, and then CLOSED ------------------
    # ⛔⛔ THIS SECTION ONCE REPORTED THE OPPOSITE, AND THE STALENESS IS A
    # FINDING IN ITSELF. The first version scanned for `pin_sync` / `pin_in_q`
    # and concluded "no edge capture on any protocol input pin" -- correctly, at
    # the time. Edge capture was then BUILT, with different names
    # (`uio_q2`, `pin_rise`/`pin_fall`, `arm_hit`, `l_armed`), and the scan went
    # on reporting the absence because it was looking for identifiers nobody had
    # written. ⇒ A grep for a MECHANISM is a grep for the names you expected the
    # mechanism to have, and it fails in BOTH directions: it missed the absence
    # first (the RTL said `OP_ARM, OP_REARM: ;` for a release and nothing
    # noticed), then missed the presence. It now checks for every name the
    # mechanism actually uses and REPORTS WHICH ONES IT FOUND, so a future
    # rename produces a partial match -- visible -- rather than a clean wrong
    # answer.
    print()
    print("  --- `armed` in the RTL: scanned, and the names are listed ---")
    eng = open(os.path.join(os.path.dirname(HERE), "src", "pe_engine.v"),
               encoding="utf-8").read()
    top = open(os.path.join(os.path.dirname(HERE), "src", "project.v"),
               encoding="utf-8").read()
    marks = [
        ("3rd sync stage (uio_q2)",        "uio_q2" in top),
        ("edge detect rise",               "uio_rise" in top),
        ("edge detect fall",               "uio_fall" in top),
        ("engine port pin_rise",           "pin_rise" in eng),
        ("engine port pin_fall",           "pin_fall" in eng),
        ("arm hit term",                   "arm_hit" in eng),
        ("armed state",                    "l_armed" in eng),
        ("armed pin latch",                "l_armpin" in eng),
        ("edge polarity latch",            "l_armedge" in eng),
        ("no-timeout encoding",            "l_notmo" in eng),
        ("sticky TIMEOUT flag",            "l_timeout" in eng),
        ("rebase on edge",                 "l_timestamp[i] <= now" in eng),
    ]
    for name, present in marks:
        print("    %-26s %s" % (name, "found" if present else "*** ABSENT"))
    n_found = sum(1 for _n, p in marks if p)
    print("    %d of %d mechanism markers present" % (n_found, len(marks)))
    if n_found == len(marks):
        print()
        print("    ⭐⭐ THE GAP IS CLOSED. `OP_ARM` releases the lane on a chosen")
        print("    pin's chosen edge, the timestamp REBASES to the edge so the")
        print("    grid anchors to the peer rather than to a timeout instant,")
        print("    and a silent peer HALTS the lane with a sticky flag instead")
        print("    of letting it invent a frame.")
        print("    ⛔ RECORDED: this was the SECOND day-one commitment found")
        print("    unbuilt. ARCH_PREREG_01 commitment 1 is 'edge timestamping")
        print("    on input pins -- cheap, and the entire substrate for")
        print("    protocol discovery. Built even though nothing consumes it")
        print("    yet.' Commitment 3 was the golden model. Neither existed,")
        print("    and three I2C rulings plus two reactive lanes had been")
        print("    resting on the first one.")
        print("    ⚠ Behavioural evidence is tb_edge's 4 must-fires, not this")
        print("    scan: a name being present is not a mechanism working.")
    elif n_found == 0:
        print()
        print("    ⛔⛔ NO EDGE CAPTURE AT ALL -- reactive lanes cannot be")
        print("    released by their peer. UART-rx, SPI-target and three I2C")
        print("    rulings depend on it.")
    else:
        print()
        print("    *** PARTIAL: %d of %d markers. Either the mechanism is half"
              % (n_found, len(marks)))
        print("        built or something was renamed. A partial match is")
        print("        reported rather than rounded to present or absent.")

    # ⭐⭐ THE MUST-FIRE IS NOW SYNTHETIC, AND THE CHANGE IS THE POINT.
    # It used to assert that `program counter` and `program base` -- the two
    # fields S3 named independently -- were reported missing. That worked while
    # the freeze was stale, and it would have gone VACUOUS the moment the gap
    # was closed: the guard would have depended, for its own strength, on the
    # defect it exists to find never being fixed.
    # ⛔ The gap IS now closed -- `gate_spec_freeze_s2` carries all five S3
    # fields plus the five ARM fields, 36 fields all traced -- so the probe
    # injects a field name that is deliberately absent instead. A guard priced
    # by an INJECTED defect keeps working after the real one is repaired.
    print()
    print("  --- must-fire: an absent field MUST be reported (injected) ---")
    probe = golden.FieldSet("probe", strict=False)
    sentinel = "__a_field_that_is_deliberately_not_frozen__"
    probe.need(sentinel, "injected by the must-fire")
    probe.need("program counter", "a field that IS frozen, as the control")
    caught = sentinel in probe.missing
    control_clean = "program counter" not in probe.missing
    print("    injected absent field reported : %s" % ("yes" if caught else "NO"))
    print("    a FROZEN field stays unreported: %s"
          % ("yes" if control_clean else "NO -- it flags everything"))
    ok = caught and control_clean
    print("    must-fire: %s"
          % ("PASS -- the recorder distinguishes absent from present, so a "
             "'none' result above means something"
             if ok else
             "*** FAIL -- the recorder either misses an absent field or flags "
             "a present one, and in both cases a 'none' result is "
             "meaningless ***"))
    if m.missing:
        print()
        print("    ⚠ %d behaviour(s) STILL have no field (listed above). Those"
              % len(m.missing))
        print("    are real findings, not failures of this gate.")
    else:
        print()
        print("    ⭐ AND THE REAL GAP IS CLOSED: every piece of state the")
        print("    census needs is now in the freeze. S3 found five of these by")
        print("    writing RTL and watching it fail; this found them -- plus")
        print("    `armed`, which S3's list did not have -- by executing the")
        print("    census against the spec.")

    print()
    print("=" * 78)
    print("  GATE reverse-trace: %s" % ("PASSED" if ok else "FAILED"))
    print("    * %d census programs executed on an ISA semantics written from"
          % len(PROGRAMS))
    print("      the SPEC, not from the RTL")
    print("    * %d of %d opcodes exercised"
          % (len(ALL_OPS) - len(unexercised), len(ALL_OPS)))
    print("    * %d behaviour(s) with no field, reported" % len(m.missing))
    print("    ⛔ S2 finds a field with no ruling; this finds a ruling with no")
    print("      field. S3 found five of these by writing RTL and watching it")
    print("      fail -- this is the cheaper direction.")
    return 0 if ok else 1


def _wrap(text, width):
    out, cur = [], ""
    for w in str(text).split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    if cur:
        out.append(cur)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
