"""S2 -- THE SPEC FREEZE. 1.5 re-closed on every ruling that landed after it.

THE ONE CLAIM: every field the engine carries TRACES TO A NAMED RULING, no
field duplicates another, and the ones that do neither are CUT. The gate's teeth
are the traceability check, not the field list.

⛔⛔ WHY 1.5 HAD TO BE RE-CLOSED. It froze a descriptor, and then six rulings
moved its ground: the two-bank pin map, the RX serialiser, the load-mode pin
safety fix, reset-high, 1.6r's async-clear release, and the S1 census choosing
`AW`. A freeze that is not re-closed after its inputs move is not a freeze, it
is a stale document with authority.

⭐⭐ AND RE-CLOSING IT FOUND A FUNCTIONAL BREAK AND A DUPLICATE, WHICH IS
EXACTLY WHAT A FREEZE IS FOR:

  (1) ⛔ `N_PINS = 8` WAS HARDCODED IN TWO GATES with the comment "tt_um_*
      gives 8 bidirectional uio" -- true before the two-bank ruling, FALSE
      after. The ruling put 4 push-pull protocol outputs on `uo_out`, so the
      program must address 12 pins, not 8. At `bits_for(7) = 3` the action word
      CANNOT NAME THE uo_out PROTOCOL PINS AT ALL. Not a sizing nicety: the
      chip could not have driven UART TX, SCLK, MOSI or CS from a program.
      ⇒ now DERIVED from the pin map (`addressable_pins()`), in one place.

  (2) ⛔ THE ACTION WORD'S `clock pin` FIELD WAS A DUPLICATE. Its rationale was
      right about the mechanism and wrong about the scope: a SHIFT must DRIVE a
      clock, but the clock pin is a LANE property and the per-lane header
      already carries it. A lane cannot drive two clocked buses -- the ruled pin
      map gives SPI-tx exactly one SCLK -- so the per-action copy can never
      differ. CUT.
      ⭐ This is the second time this exact cut has been made: 1.5 already
      merged "shift reg" with "data register" and "bit counter" with "bit
      pointer", which had cost 60 flops for two names for one thing.

⭐ THE TWO CANCEL, AND THAT IS A RESULT NOT A COINCIDENCE WORTH HIDING. +1 bit
on each of two pin fields, -4 bits for the cut clock pin: the action word is
22 bits = 3 bytes either way, so S1's AW = 8 and F1's 62-of-64 both SURVIVE --
and F1 now fits at delay = 12 bits where it previously needed 10, so the cut
bought 2 bits of delay range for free.
⛔ HAD ONLY THE FIX LANDED, the word would have been 4 bytes, the demo 229 B,
and `AW` would have gone to 9 = 54% of the cell budget on the HEADROOM RULE
ALONE. Had only the cut landed, the chip could not name its own output pins.

=============================================================================
⛔⛔ QUARANTINE, AND IT COVERS THE ENGINE -- NOT JUST THE MACRO FIX
=============================================================================
The engine of Part 1, and every file in this repo, is built with NO REFERENCE
to the other entrant's repository or pull-request content. A paraphrase of
their PDN diagnosis and fix reached this session through a web-search summary;
it was not opened, is not recorded, and must not be reconstructed from memory
of that summary. S0(a) and S0(b) of SPEC v4 were deliberately NOT PERFORMED for
the same reason.

⭐ AND THE RESULTING POSITION IS STATED PLAINLY, because it is defensible:
SRAM IS BLOCKED FOR US BY THE INTEGRITY CONSTRAINT, NOT BY PHYSICS.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import L_SYNC, OUT_REG                                 # noqa: E402
from gate_encoding_f1 import action_word, bits_for, store_cost, budget  # noqa: E402
from gate_pin_subsets import (N_UIO, N_UO, N_SERIAL, bank_need,    # noqa: E402
                              addressable_pins)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LANES = lane_digest.shipped()
N_LANES = len(LANES)
N_PINS = addressable_pins()
DELAY_BITS = 10
TS_W = 16                       # timestamp width shipped; floor is derived
AW = 8                          # S1 census
MEM_TYPE = "flops"              # S0 = SRAM-BLOCKED
# ⛔ `RX_SERIAL = 1` WAS FROZEN HERE AND IS NOW DELETED BY RULING. The freeze's
# own rationale was "the sweep must be able to turn it off to price it"; the
# coverage sweep measured that no arm ever did, and nothing overrode it. The
# parameter and its dead `else` are gone from src/project.v. ⚠ A frozen row
# must not vanish without a trace, so the deletion is recorded rather than
# simply erased -- a freeze that quietly loses entries is not a freeze.

# ---------------------------------------------------------------------------
# THE FROZEN FIELD TABLE.
#   (name, bits, where, ruling, note)
# `where`: lane-reg | prog | global | image | hw   ("hw" = dedicated logic,
#          not a descriptor field, listed so its cost is visible)
# ⛔ A field with ruling None is UNTRACED and the gate CUTS it.
# ---------------------------------------------------------------------------
def frozen_fields():
    d_w = bits_for(max(l.D for l in LANES))
    dt_w = bits_for(max(l.D_tol for l in LANES))
    return [
        # ---- per-lane state ------------------------------------------
        ("pin index", bits_for(N_PINS - 1), "lane-reg", "pin-map ruling",
         "⭐ %d addressable pins = %d uio + %d uo_out push-pull. DERIVED from "
         "the map; was 3 bits and could not name the uo_out pins"
         % (N_PINS, N_UIO, bank_need(LANES)[1])),
        ("drive mode", 1, "lane-reg", "1.5 drive mode / F5",
         "push-pull vs open-drain"),
        ("data/shift register", 8, "lane-reg", "F1",
         "⭐ THE PAYLOAD LIVES HERE, not in the program. One register; 1.5's "
         "'shift reg' and F1's 'data register' were merged"),
        ("bit pointer", bits_for(8), "lane-reg", "F1",
         "0..8; merged with 1.5's 'bit counter'"),
        ("next-action timestamp", TS_W, "lane-reg", "Ruling 2",
         "ABSOLUTE counter compare; floor derived at 9 bits, ships %d" % TS_W),
        ("C_i", bits_for(8), "lane-reg", "1.5 per-lane C_i",
         "1..8; frontier admits C <= 6"),
        ("D_sched (EDF key)", d_w, "lane-reg", "R2 + Ruling 1",
         "⛔ REGISTER not store (Ruling 1): without it the pipeline register "
         "lands after the mux it was added to avoid"),
        ("TX underrun (sticky)", 1, "lane-reg", "F1 + 1.6n",
         "⛔ sticky FLAG, never a stall -- a stall makes C unbounded"),
        # ---- ⭐⭐ THE FIELDS THE FREEZE WAS MISSING, FOLDED IN ----------
        # ⛔⛔ THIS TABLE WAS STALE FROM S3 UNTIL NOW, and the reverse-
        # traceability gate is what established it mechanically rather than by
        # someone remembering. S3 found FIVE fields by writing RTL and watching
        # it fail; `model/gate_reverse_trace.py` found them again by executing
        # the census on an ISA semantics built from THIS table, plus one S3's
        # list did not have (`armed`). Forward traceability cannot find these --
        # it detects a field with no ruling, never a ruling with no field.
        ("program counter", AW, "lane-reg", "S3 + Ruling 2",
         "⛔ which action is NEXT. Without it a lane cannot execute a SEQUENCE, "
         "and nothing in the original freeze held it"),
        ("program base", AW, "lane-reg", "S3 loop / OP_REARM level=1",
         "⛔ the loop target. A PC advanced linearly falls off the end, so a "
         "PERIODIC protocol could not repeat -- found by the PC running past "
         "the program"),
        ("action buffer + valid (x2)", 2 * (action_word(DELAY_BITS, False, True)["bits"] + 1),
         "lane-reg", "Ruling 1 C=2 + double buffer",
         "⭐ DOUBLED by the double buffer: head + spare, so a dispatch never "
         "waits on a fetch. 169 flops measured, against a ~110 estimate that "
         "counted the words and forgot the pointers"),
        ("fetch pointer", AW, "lane-reg", "double buffer",
         "runs AHEAD of the PC; loop-aware, so a looping re-arm is prefetched "
         "from `program base` rather than flushing both slots"),
        ("buffer select", 1, "lane-reg", "double buffer",
         "which slot is the head. Flips at writeback -- M_BUF_SWAP proves the "
         "FLIP, not merely the second slot, is what buys the J reduction"),
        # ---- the REACTIVE release (Wilson's ARMED ruling) --------------
        ("armed", 1, "lane-reg", "ARMED ruling (edge capture)",
         "⛔ THE FIELD THAT WAS NOT ON S3'S LIST. It is also the EDGE LATCH: an "
         "edge arriving before ARM dispatches has nothing holding it, which is "
         "Ruling 3's policy by construction rather than by an explicit clear"),
        ("armed pin", bits_for(N_PINS - 1), "lane-reg", "ARMED ruling",
         "⛔ FULL WIDTH, not a choice of {pin, clkpin}: SPI-target needs THREE "
         "pins -- MISO, SCK and CS -- so narrowing it would erode 'pins are "
         "assigned per program' for 15 flops"),
        ("armed edge polarity", 1, "lane-reg", "ARMED ruling",
         "the action's EXISTING level bit. The three reactive releases do not "
         "agree on a polarity: UART-rx arms on a start-bit FALL, SPI-target on "
         "CS FALL, I2C on the SCL RISE"),
        ("no-timeout", 1, "lane-reg", "ARMED ruling 2",
         "ARM with delay == 0 waits indefinitely (UART-rx idling). An encoding "
         "in an existing field, not a new one"),
        ("TIMEOUT (sticky)", 1, "lane-reg", "ARMED ruling 2",
         "⛔ A TIMEOUT IS AN ERROR, NEVER A SUCCESS. Without a flag a program "
         "cannot tell 'the peer answered' from 'the peer never answered' and "
         "would read a frame out of an idle line"),
        ("RX overflow (sticky)", 1, "lane-reg", "1.6p",
         "⛔ must be FRAMED INTO THE SERIAL STREAM: a host that stopped "
         "reading cannot be told by a pin it is not reading"),
        # ---- the program ----------------------------------------------
        ("action opcode", 3, "prog", "1.5 + Ruling 2 + F1",
         "level / shift / shift-in / read-bit / start / stop / arm / "
         "no-op re-arm = 8 of 8"),
        ("action pin", bits_for(N_PINS - 1), "prog", "pin-map ruling",
         "same width as the lane field, same reason"),
        ("action level/dir", 1, "prog", "ARCH_PREREG + F1",
         "the level to drive, or LSB/MSB-first for a shift"),
        ("action delay", DELAY_BITS, "prog", "Ruling 2 C2 + F1",
         "⛔ ADDS TO THE STORED TIMESTAMP, never to `now` -- the relative form "
         "drifts k*(r-C), 15,260 cycles on a 1 s delay, INVISIBLE at k=1"),
        ("shift bit count N", bits_for(8), "prog", "F1", "emit/sample 1..8"),
        # ---- global ----------------------------------------------------
        ("global time counter", TS_W, "global", "Ruling 2",
         "ONE incrementer, not %d decrementers" % N_LANES),
        ("sticky ovr", 1, "global", "1.5 sticky ovr",
         "set-only until reset; framed into the stream (1.6p)"),
        # ---- image, not silicon ----------------------------------------
        ("D_tol", dt_w, "image", "R2 + F3",
         "⛔ NOT a silicon register: loader metadata for the 5.3 load-time "
         "screen. 40 flops not spent"),
        ("clock pin (per lane)", bits_for(N_PINS - 1), "image",
         "F1, scope-corrected by S2",
         "⭐ a LANE property. The per-ACTION copy was CUT as a duplicate"),
        ("MEM_TYPE", 0, "image", "part-1 contract + S0",
         "build parameter, default \"%s\" because S0 = SRAM-BLOCKED" % MEM_TYPE),
        ("AW", 0, "image", "S1 census",
         "build parameter = %d; demo is 178 B of %d" % (AW, 2 ** AW)),
        # ---- dedicated hardware, costed so it is not invisible ---------
        ("primed (one-shot)", 1, "global", "prime-before-release (Ruling 1a)",
         "⭐ LATCHED, not continuous: 'every lane wants nothing fetched' is true "
         "at start-up and false again one cycle after every writeback, so a "
         "continuous gate froze `now` and produced ZERO EDGES"),
        ("input sync chain + edge detect", 3 * N_UIO, "hw",
         "ARCH_PREREG commitment 1 + ARMED ruling",
         "⛔ THE SECOND DAY-ONE COMMITMENT FOUND UNBUILT. 3 stages per uio pin; "
         "`rise = q1 & ~q2` is combinational off the chain, so the edge detect "
         "costs no flops and only the third stage does. L_sync = 3 and "
         "uncertainty 1 are now DERIVED from this structure "
         "(gate_edge_capture.py) rather than assumed by A2"),
        ("uio_oe[MISO] async-clear flop", 1, "hw", "1.6r",
         "⛔ CS rising ASYNC-CLEARS it; assert path synchronised. Release = "
         "pad + clear delay, not %d cycles" % (L_SYNC + OUT_REG)),
        ("RX serialiser (off the engine)", 0, "hw", "product call + 1.6p",
         "⛔ as a LANE it would take a slot, enter every interference sum and "
         "become max{C_j-1} for all of them. Dedicated: ZERO budget"),
        ("load-mode output hold", 0, "hw", "1.6q",
         "⛔ protocol outputs held at IDLE in load mode; readback goes out "
         "bit-serially. A constructed 64 B image clocked WREN+WRITE = 4 FRAM "
         "WRITES"),
        ("reset-high on protocol outputs", 0, "hw", "1.6q",
         "⛔ FORCED not chosen: uo_out cannot go high-Z and pin roles are per "
         "program, so reset cannot know which pin is CS. HIGH is "
         "simultaneously inactive for every role; program start asserts CS "
         "LAST"),
    ]


# ⛔ Fields PROPOSED and CUT. Kept visible: a freeze that only lists what
# survived cannot be audited for what it dropped.
CUT_FIELDS = [
    ("clock pin (per action)", "DUPLICATE of the per-lane header field. A lane "
     "cannot drive two clocked buses, so the copies can never differ. -4 bits "
     "per action = -51 bytes on the demo, and it bought F1 2 more delay bits",
     "S2"),
    ("D_tol as a silicon register", "moved to the image (F3) -- 40 flops", "F3"),
    ("separate 'shift reg' and 'data register'", "one register, two specs -- "
     "60 flops across 5 lanes", "1.5"),
    ("separate 'bit counter' and 'bit pointer'", "one counter, two names",
     "1.5"),
    ("P-ATOMIC mask + data (2 x N_PINS per action)", "⭐ ONE shared group "
     "suffices: non-preemptive scheduling means exactly one job is in service, "
     "so no two atomic groups are ever open at once (INV-ATOMIC-1)", "1.5"),
    ("per-lane countdown timers", "Ruling 2 replaced %d decrementers with one "
     "absolute counter" % N_LANES, "Ruling 2"),
    ("parallel RX byte view on uo_out", "the pin map left %d spare of %d and a "
     "nibble+valid needs 5; time-multiplexing against a protocol output would "
     "glitch SCLK (F2)" % (N_UO - bank_need(LANES)[1] - N_SERIAL, N_UO),
     "product call"),
    ("digital CS filter before the async clear", "needs the CLOCK, so it "
     "re-introduces the release lag the async clear removes: contends N-1 "
     "cycles. Trades a 1-bit corruption for a multi-cycle contention window",
     "1.6r"),
]


def main() -> int:
    print()
    print("=" * 78)
    print("S2 -- THE SPEC FREEZE: 1.5 re-closed on every later ruling")
    print("=" * 78)
    lane_digest.announce("gate_spec_freeze_s2.py (S2)", LANES)
    rc = 0

    f = frozen_fields()

    # ---- 1. traceability IS the gate ------------------------------------
    print()
    print("  --- 1. ⭐ THE GATE: every field traces to a ruling ---")
    untraced = [x for x in f if not x[3]]
    print("    fields: %d; untraced: %d" % (len(f), len(untraced)))
    if untraced:
        print("    *** UNTRACED FIELDS -- these are CUT, not shipped:")
        for n, b, w, _r, _note in untraced:
            print("      %-34s %d bits in %s" % (n, b, w))
        rc = 1
    else:
        print("    ⭐ all %d trace to a named ruling. ⛔ That is the whole test:"
              % len(f))
        print("    a descriptor grows by accretion unless something forces each")
        print("    field to name the decision that put it there.")

    # ---- 2. duplicate detection ----------------------------------------
    print()
    print("  --- 2. ⭐ AND NO FIELD DUPLICATES ANOTHER ---")
    print("    ⛔ This check exists because the freeze found TWO duplicate")
    print("    pairs in 1.5 (60 flops) and a THIRD in the action word (the")
    print("    per-action clock pin). Duplicates are not caught by")
    print("    traceability -- both copies trace to a real ruling.")
    seen, dups = {}, []
    for n, b, w, r, note in f:
        key = n.split("(")[0].strip().lower()
        if key in seen and seen[key] != w:
            dups.append((n, w, seen[key]))
        seen[key] = w
    if dups:
        print("    *** same name in two places:")
        for n, w1, w2 in dups:
            print("      %-34s %s and %s" % (n, w1, w2))
        rc = 1
    else:
        print("    none -- and the per-action clock pin is in CUT_FIELDS, not")
        print("    here, which is what the cut means.")

    # ---- 3. the frozen table -------------------------------------------
    print()
    print("  --- 3. THE FROZEN FIELDS ---")
    for where in ("lane-reg", "prog", "global", "image", "hw"):
        rows = [x for x in f if x[2] == where]
        tot = sum(x[1] for x in rows)
        label = {"lane-reg": "PER-LANE REGISTER (x %d lanes)" % N_LANES,
                 "prog": "PROGRAM WORD",
                 "global": "GLOBAL",
                 "image": "IMAGE / BUILD PARAM -- not silicon",
                 "hw": "DEDICATED HARDWARE -- costed, not a descriptor field"}
        print()
        print("    %s   %d bits%s"
              % (label[where], tot,
                 " x %d = %d flops" % (N_LANES, tot * N_LANES)
                 if where == "lane-reg" else ""))
        for n, b, _w, r, note in rows:
            print("      %-32s %2d b  [%s]" % (n, b, r))
            print("          %s" % note)

    lane_bits = sum(x[1] for x in f if x[2] == "lane-reg")
    prog_bits = sum(x[1] for x in f if x[2] == "prog")
    glob_bits = sum(x[1] for x in f if x[2] == "global")

    # ---- 4. the action word, reconciled --------------------------------
    print()
    print("  --- 4. THE ACTION WORD, reconciled with the program word ---")
    aw = action_word(DELAY_BITS, with_clock_pin=False, with_count=True)
    print("    action_word() (F1)      %d bits = %d bytes"
          % (aw["bits"], aw["bytes"]))
    print("    S2 program-word fields  %d bits" % prog_bits)
    if aw["bits"] != prog_bits:
        print("    *** THE TWO DISAGREE by %d bits. The encoding gate and the"
              % abs(aw["bits"] - prog_bits))
        print("        freeze must describe ONE word, or the RTL will be built")
        print("        from whichever file its author opened.")
        rc = 1
    else:
        print("    ⭐ AGREE. ⛔ And this check is not ceremony: before S2 they")
        print("    disagreed, because F1 carried a clock-pin field the")
        print("    descriptor did not and both hardcoded N_PINS = 8.")

    # ---- 5. the flop budget --------------------------------------------
    print()
    print("  --- 5. THE FLOP/CELL BUDGET, with the store from S1 ---")
    sc = store_cost()
    bg = budget()
    store_bits = 8 * 2 ** AW
    store_cells = store_bits * sc["per_bit_itemised"]
    state_flops = lane_bits * N_LANES + glob_bits
    print("    %-36s %s" % ("per-lane state", "%d bits x %d = %d flops"
                            % (lane_bits, N_LANES, lane_bits * N_LANES)))
    print("    %-36s %d flops" % ("global state", glob_bits))
    print("    %-36s %d flops" % ("engine STATE total", state_flops))
    print("    %-36s %d bits = %.0f cells (%.1f%% of budget)"
          % ("program store, MEM_TYPE=%s, AW=%d" % (MEM_TYPE, AW),
             store_bits, store_cells,
             100.0 * store_cells / bg["cells_practical"]))
    print()
    print("    ⚠⚠ THE ENGINE'S *LOGIC* IS STILL NOT PRICED. %d flops of STATE"
          % state_flops)
    print("    is not the engine's cell count -- the comparators, the EDF mux,")
    print("    the shifters and the fetch pipeline are all unbuilt. ⛔ Adding")
    print("    state flops to store cells and calling it 'the chip' would be")
    print("    the 6.28-percent error in a new costume. S3 MEASURES it.")
    print("    ⇒ known: store %.0f of %.0f practical cells; %.0f remain for"
          % (store_cells, bg["cells_practical"],
             bg["cells_practical"] - store_cells))
    print("      logic AND the %d state flops." % state_flops)

    # ---- 6. what was cut ------------------------------------------------
    print()
    print("  --- 6. ⭐ WHAT WAS CUT, and by which ruling ---")
    print("    ⛔ A freeze that lists only survivors cannot be audited for what")
    print("    it dropped.")
    for n, why, r in CUT_FIELDS:
        print("      %-44s [%s]" % (n, r))
        print("          %s" % why)

    # ---- 7. build parameters -------------------------------------------
    print()
    print("  --- 7. THE BUILD PARAMETERS S3 MUST EXPOSE ---")
    params = [("N_LANES", N_LANES, "lane-count sweep + 1.6o"),
              ("AW", AW, "S1 census; 178 B demo in %d B" % 2 ** AW),
              ("N_PINS", N_PINS, "DERIVED from the pin map, not written twice"),
              ("TS_W", TS_W, "floor 9 derived; ships %d" % TS_W),
              ("DLY_W", DELAY_BITS, "F1's fit"),
              ("D_W", bits_for(max(l.D for l in LANES)), "deadline spread"),
              ("MEM_TYPE", MEM_TYPE, "⛔ default FLOPS: S0 = SRAM-BLOCKED. The "
               "sram path stays a parameter for the predictive-node tier"),
              # `RX_SERIAL` was the next row; deleted by ruling, see the
              # constant block at the top of this file.
              ]
    for n, v, why in params:
        print("      %-11s = %-7s %s" % (n, v, why))

    # ---- 8. the quarantine, in the record ------------------------------
    print()
    print("  --- 8. ⛔⛔ QUARANTINE -- IT COVERS THE ENGINE, NOT JUST THE PDN ---")
    print("    The Part 1 engine and every file in this repo are built with NO")
    print("    REFERENCE to the other entrant's repository or pull-request")
    print("    content. A paraphrase of their PDN diagnosis and fix reached")
    print("    this session through a web-search summary; it was not opened, is")
    print("    not recorded, and must not be reconstructed from memory of that")
    print("    summary. SPEC v4's S0(a) and S0(b) were deliberately NOT")
    print("    PERFORMED for the same reason.")
    print("    ⭐ And the resulting position is stated plainly, because it is")
    print("    defensible in public and it matches how this entry has been run:")
    print("    ⇒ SRAM IS BLOCKED FOR US BY THE INTEGRITY CONSTRAINT, NOT BY")
    print("      PHYSICS.")

    print()
    print("=" * 78)
    print("  GATE spec-freeze-S2: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * %d fields, all traced, no duplicates" % len(f))
    print("    * %d fields CUT, each with the ruling that cut it"
          % len(CUT_FIELDS))
    print("    * action word %d bits = %d B, agreeing with F1"
          % (prog_bits, aw["bytes"]))
    print("    * MEM_TYPE=%s @ AW=%d (%.1f%% of budget, STORE ONLY)"
          % (MEM_TYPE, AW, 100.0 * store_cells / bg["cells_practical"]))
    print("    * engine state %d flops; LOGIC unpriced until S3" % state_flops)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
