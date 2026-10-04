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

    # ---- what the `armed` gap means in the RTL, CHECKED not asserted ----
    # ⛔⛔ THE NEW FINDING, AND IT IS NOT JUST A MISSING FREEZE ROW. `armed` was
    # not on S3's list of five; this gate found it from the spec side. Chased
    # into the RTL it is worse than a descriptor gap, so the two facts that
    # make it real are scanned for rather than described.
    print()
    print("  --- `armed` chased into the RTL (scan, not argument) ---")
    eng = open(os.path.join(os.path.dirname(HERE), "src", "pe_engine.v"),
               encoding="utf-8").read()
    top = open(os.path.join(os.path.dirname(HERE), "src", "project.v"),
               encoding="utf-8").read()
    # (a) is OP_ARM's case body empty?
    arm_noop = "OP_ARM, OP_REARM: ;" in eng or "OP_ARM,OP_REARM: ;" in eng
    # (b) is there ANY edge detect on a protocol input pin? The loader's own
    #     write strobe (`wr_sync`/`wr_rise` on ui_in) does not count -- that is
    #     the HOST interface, not a peer protocol pin.
    has_pin_sync = ("pin_in_q" in eng or "pin_sync" in eng
                    or "pin_in_d" in eng or "pin_prev" in eng)
    loader_only = ("wr_rise" in top and not has_pin_sync)
    print("    OP_ARM's case body is empty (a no-op)      : %s" % arm_noop)
    print("    any edge capture on a PROTOCOL input pin   : %s"
          % ("none found" if not has_pin_sync else "yes"))
    print("    only edge detect is the loader's wr_rise   : %s" % loader_only)
    if arm_noop and not has_pin_sync:
        print()
        print("    ⛔⛔ SO A REACTIVE LANE CANNOT BE RELEASED BY ITS PEER.")
        print("    UART-rx and SPI-target are both REACTIVE -- their releases")
        print("    come from a peer edge (a start bit, a CS fall) -- and the")
        print("    engine has no edge capture, no armed state, and an ARM that")
        print("    does nothing. Those two lanes would run OPEN-LOOP on their")
        print("    programmed delays and drift against the peer.")
        print("    ⚠ THE SCHEDULING ANALYSIS IS NOT INVALIDATED: it bounds")
        print("    release-to-completion GIVEN a release, and models reactive")
        print("    releases as an arrival curve, which is sound. What is absent")
        print("    is the mechanism that makes a release HAPPEN.")
        print("    ⛔ AND IT IS THE SECOND DAY-ONE COMMITMENT FOUND UNBUILT.")
        print("    ARCH_PREREG_01 commitment 1 is 'edge timestamping on input")
        print("    pins -- cheap, and the entire substrate for protocol")
        print("    discovery. Built even though nothing consumes it yet.'")
        print("    Commitment 3 was this golden model. Neither existed.")

    # ⭐ THE MUST-FIRE. This gate is only evidence if it CAN find a gap, and
    # the gap it should find is already known independently: S3 named five
    # fields the freeze lacks. If the run reports NONE, the field-access
    # recording is not working and a green result means nothing.
    print()
    print("  --- must-fire: the known-missing fields MUST be reported ---")
    known = {"program counter", "program base"}
    found = known & set(m.missing)
    print("    known missing (from S3, independently): %s" % sorted(known))
    print("    reported by this run                  : %s" % sorted(found))
    ok = (found == known)
    print("    must-fire: %s"
          % ("PASS -- the mechanism detects fields known to be absent"
             if ok else
             "*** FAIL -- it did not report fields that are KNOWN absent, so "
             "the field-access recording is not working and a 'none' result "
             "would be meaningless ***"))

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
