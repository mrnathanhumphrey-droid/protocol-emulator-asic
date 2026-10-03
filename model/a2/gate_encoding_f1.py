"""RULING F1 -- separate the PROGRAM from the PAYLOAD, then size the store.

THE ONE CLAIM: the store was never too small. The encoding was spending it on
data. With a shift/repeat action and a host data channel, one transaction on each
required protocol fits inside the EXISTING 64-byte store -- and the fix that was
proposed instead (AW = 9) would have cost most of the tile budget.

⛔⛔ MY F1 DIAGNOSIS WAS THE SYMPTOM, NOT THE CAUSE, AND THE FIX I PROPOSED WAS
THE EXPENSIVE ONE. I reported "the program store is an order of magnitude too
small, recommend AW >= 8" from a correct count: a 3-byte action word, 21 actions
in 64 bytes, 44 actions needed. Every number right, root cause missed.

THE ROOT CAUSE: the action word carries a LEVEL BIT, so the program spells out
the data -- one action per bit. That makes program size grow LINEARLY WITH
MESSAGE LENGTH, which means the chip is a WAVEFORM PLAYER rather than a protocol
emulator. The brief contrasts exactly those two things: the protocol should be
implemented in firmware with data flowing THROUGH it. A 10-action UART frame is
not a store-size problem, it is the design telling us the payload is in the wrong
place.

⛔ AND "AREA IS FREE AT 6.28%" WAS WRONG, WHICH IS WHY THE CAUSE MATTERED. 6.28%
is DIE-AREA utilisation including filler, not a cell budget. Derived from the
shipped cell inventory below, the 64-byte store already costs about 2,000 of the
design's 2,946 logic cells. AW = 9 is 8x the bits, so it is tens of thousands of
cells against a 6x4 tile budget -- the whole chip, to hold data that should never
have been in the store.

⭐ THE FIX, AND WHY IT IS FREE IN THE TASK MODEL. A shift/repeat action says
"emit N bits from this lane's data register at period T, LSB- or MSB-first". The
ENGINE STILL SCHEDULES ONE JOB PER BIT EDGE -- the arrival curve, the response
times and every margin in A2 are untouched. Only the REPRESENTATION compresses.
That is the whole reason this is an encoding change and not a re-derivation:
`run_a2.py`'s digest is identical before and after.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import response_time_b                                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LANES = lane_digest.shipped()
N_LANES = len(LANES)
# ⛔⛔ WAS `N_PINS = 8` WITH THE COMMENT "tt_um_* gives 8 uio" -- stale from the
# moment the two-bank pin ruling put 4 push-pull protocol outputs on `uo_out`.
# At 8 the action word's pin field is bits_for(7) = 3, and A PROGRAM CANNOT NAME
# THE uo_out PROTOCOL PINS AT ALL. Now DERIVED from the ruled pin map, in one
# place, so a future pin ruling cannot leave it behind.
from gate_pin_subsets import addressable_pins                      # noqa: E402
N_PINS = addressable_pins()
AW_TODAY = 6
STORE_BYTES = 2 ** AW_TODAY

# ---- shipped silicon, from docs/SILICON_EVIDENCE.md's cell inventory -----
CELLS_TOTAL = 2946
FLOPS_TOTAL = 535
STORE_BITS_TODAY = 512          # mem: 64 x 8
MUX2_CELLS = 515                # "the 64-entry readback mux tree"
TIEHI_CELLS = 512
HOLDFIX_CELLS = 555             # dlygate4sd3_1
# tile geometry, ARCH_PREREG_01 s110: 167 x 108 um per tile, 6x4 = 24 tiles
TILE_UM2 = 167 * 108
TILES = 24
CORE_UM2 = 902_417
UTIL_PCT = 6.28


def bits_for(n: int) -> int:
    b = 1
    while (1 << b) <= n:
        b += 1
    return b


# ============================================================================
# 1. WHAT A STORED BIT ACTUALLY COSTS
# ============================================================================
def store_cost() -> dict:
    """Cells per stored bit, from the INVENTORY rather than one division.

    ⛔ Dividing total cells by store bits (2946/512 = 5.75) attributes the whole
    design to the store and is an upper bound. The inventory lets the store's
    own share be itemised, which is the number that scales.
    """
    # the store's identifiable share
    flop_share = STORE_BITS_TODAY                       # one dfrbpq_1 per bit
    mux_share = MUX2_CELLS                              # named as the readback tree
    tie_share = TIEHI_CELLS                             # one per bit, by count
    hold_share = int(HOLDFIX_CELLS * STORE_BITS_TODAY / FLOPS_TOTAL)
    itemised = flop_share + mux_share + tie_share + hold_share
    return {"flop": flop_share, "mux": mux_share, "tie": tie_share,
            "hold": hold_share, "itemised": itemised,
            "per_bit_itemised": itemised / STORE_BITS_TODAY,
            "per_bit_naive": CELLS_TOTAL / STORE_BITS_TODAY,
            "non_store": CELLS_TOTAL - itemised}


def budget() -> dict:
    """Two independent estimates of the cell budget, because they disagree."""
    # (a) from the tile geometry in the pre-reg
    area_tiles = TILE_UM2 * TILES
    # (b) from the shipped utilisation: 2946 cells occupy 6.28% of the core
    cell_um2 = (CORE_UM2 * UTIL_PCT / 100.0) / CELLS_TOTAL
    cells_at_100 = CORE_UM2 / cell_um2
    return {"tile_area_um2": area_tiles,
            "core_um2": CORE_UM2,
            "cell_um2": cell_um2,
            "cells_at_100pct": cells_at_100,
            "cells_practical": cells_at_100 * 0.65}


# ============================================================================
# 2. THE TWO ENCODINGS
# ============================================================================
def action_word(delay_bits: int, with_clock_pin: bool, with_count: bool) -> dict:
    """(bits, bytes, the field list) for one program action."""
    f = [("opcode", 3), ("pin", bits_for(N_PINS - 1)), ("level/dir", 1),
         ("delay/period", delay_bits)]
    if with_clock_pin:
        # ⛔⛔ CUT FROM THE SHIPPED WORD BY S2, AS A DUPLICATE. The original
        # rationale was right about the MECHANISM and wrong about the SCOPE:
        # "a clocked protocol needs the shifter to drive its OWN clock, or the
        # data and clock become two actions that must stay in lockstep -- which
        # is P-ORDER on every bit". True. But that says the SHIFT ACTION must
        # DRIVE a clock; it does not say the clock pin must be named PER ACTION.
        # ⭐ The clock pin is a LANE property, and the per-lane image header
        # ALREADY CARRIES IT. A lane cannot drive two different clocked buses --
        # the ruled pin map gives SPI-tx exactly one SCLK -- so the per-action
        # copy can never differ from the header's.
        # ⇒ This is the same cut 1.5 already made once, when "shift reg" and
        #   "data register" turned out to be one register under two names and
        #   listing both cost 60 flops for nothing. S2's rule is that a field
        #   must trace to a ruling AND not duplicate another field.
        # ⚠ Kept as an OPTION so the comparison below can price it, never in
        #   the shipped call.
        f.append(("clock pin", bits_for(N_PINS - 1)))
    if with_count:
        f.append(("bit count N", bits_for(8)))
    bits = sum(b for _n, b in f)
    return {"bits": bits, "bytes": -(-bits // 8), "fields": f}


# transaction cost in ACTIONS, both encodings.
# ⛔ The per-bit column is not a guess: it is one action per EDGE, which is what
# the current encoding's level bit forces.
TRANSACTIONS = [
    # name,                per-bit actions,            shift/repeat actions, why
    ("UART tx frame (8N1)", 10,  3,
     "start, SHIFT 8 @ T=434, stop"),
    ("SPI byte (CS + 8 bits)", 16 + 2, 3,
     "CS low, SHIFT 8 with clock pin, CS high"),
    ("I2C write txn (addr+data)", 2 * (8 + 1) * 2 + 4, 8,
     "START, SHIFT 8 addr, ACK read, SHIFT 8 data, ACK read, STOP (+2 setup)"),
]


def image_layout(delay_bits: int, dtol_in_image: bool) -> dict:
    """The whole program image: per-lane header + the action stream.

    ⛔ THE HEADER IS NOT FREE AND I LEFT IT OUT OF THE FIRST F1 COUNT. The image
    has to carry the per-lane descriptor init -- which pin, which clock pin, C_i,
    D_sched -- and, per ruling F3, D_tol as loader metadata. Counting only the
    action stream understates the image by the header.
    """
    hdr_fields = [("pin", bits_for(N_PINS - 1)),
                  ("clock pin", bits_for(N_PINS - 1)),
                  ("drive mode", 1),
                  ("C_i", bits_for(8)),
                  ("D_sched", bits_for(max(l.D for l in LANES)))]
    if dtol_in_image:
        hdr_fields.append(("D_tol (F3: image, not silicon)",
                           bits_for(max(l.D_tol for l in LANES))))
    hdr_bits = sum(b for _n, b in hdr_fields)
    hdr_bytes = -(-hdr_bits // 8) * N_LANES

    aw = action_word(delay_bits, with_clock_pin=False, with_count=True)
    acts = sum(s for _n, _p, s, _w in TRANSACTIONS)
    prog_bytes = acts * aw["bytes"]
    return {"hdr_fields": hdr_fields, "hdr_bits": hdr_bits,
            "hdr_bytes": hdr_bytes, "action": aw, "actions": acts,
            "prog_bytes": prog_bytes, "total": hdr_bytes + prog_bytes}


# ============================================================================
# 3. THE RUN-MODE PIN MAP (flag-back)
# ============================================================================
PIN_MAP = [
    ("ui_in[7]", "prog_mode", "UNCHANGED -- hard constraint: mode select never "
     "comes from uio"),
    ("ui_in[6]", "prog: WR strobe / run: TX payload PUSH",
     "one strobe, two meanings by mode; the prog-mode behaviour is untouched"),
    ("ui_in[5]", "prog: ptr reset / run: RX payload POP",
     "same reuse; pointer reset stays a dedicated input"),
    ("ui_in[4:1]", "TX payload NIBBLE (4 bits)",
     "a byte takes 2 pushes; at 115200 baud a byte is 87 us, so 2 strobes is "
     "not a rate problem"),
    ("ui_in[0]", "uo_out view select: 0 = RX payload byte, 1 = STATUS byte",
     "buys 8 bits of status without spending an output pin"),
    ("uo_out[7:0]", "RX payload byte OR status (per ui_in[0])",
     "status carries sticky ovr, TX-underrun, TX-full, RX-valid"),
    ("uio[7:0]", "PROTOCOL PINS ONLY -- UART 2 + SPI 4 + I2C 2 = 8",
     "⛔ zero uio pins spent on the data channel, which is the constraint that "
     "made this a pin-map question at all"),
]


# ============================================================================
def main() -> int:
    print()
    print("=" * 78)
    print("RULING F1 -- program vs payload, and the store sized afterwards")
    print("=" * 78)
    lane_digest.announce(
        "gate_encoding_f1.py (F1)", LANES,
        variant=None)
    rc = 0

    # ---- 1. the area the proposed fix would have cost -------------------
    sc = store_cost()
    bg = budget()
    print()
    print("  --- 1. WHAT A STORED BIT COSTS (so 'area is free' can be retired) ---")
    print("    the 64-byte store's identifiable share of %d logic cells:" % CELLS_TOTAL)
    print("      %-28s %d" % ("flip-flops (dfrbpq_1)", sc["flop"]))
    print("      %-28s %d   <- inventory names it 'the 64-entry readback mux tree'"
          % ("mux2_1", sc["mux"]))
    print("      %-28s %d" % ("tiehi", sc["tie"]))
    print("      %-28s %d   (pro-rata of %d hold-fix buffers)"
          % ("dlygate4sd3_1 share", sc["hold"], HOLDFIX_CELLS))
    print("      %-28s %d cells  =  %.2f cells per stored bit"
          % ("ITEMISED TOTAL", sc["itemised"], sc["per_bit_itemised"]))
    print("      leaving %d cells for everything that is not the store"
          % sc["non_store"])
    print("    (dividing totals gives %.2f/bit; that attributes the whole design"
          % sc["per_bit_naive"])
    print("     to the store and is an upper bound. Both are used below.)")
    print()
    print("    %-8s %-10s %-14s %-14s %s"
          % ("AW", "bits", "cells @%.2f" % sc["per_bit_itemised"],
             "cells @%.2f" % sc["per_bit_naive"], "vs budget"))
    for aw in (6, 8, 9, 10):
        bits = 8 * 2 ** aw
        lo = bits * sc["per_bit_itemised"]
        hi = bits * sc["per_bit_naive"]
        frac = lo / bg["cells_practical"] * 100
        print("    %-8d %-10d %-14.0f %-14.0f %.0f%%-%.0f%% of a practical budget"
              % (aw, bits, lo, hi, frac, hi / bg["cells_practical"] * 100))
    print()
    print("    budget, two ways because they DISAGREE and I am not picking one:")
    print("      (a) pre-reg tile geometry: %d tiles x %d um^2 = %d um^2"
          % (TILES, TILE_UM2, bg["tile_area_um2"]))
    print("      (b) shipped utilisation: %d cells at %.2f%% of a %d um^2 core"
          % (CELLS_TOTAL, UTIL_PCT, CORE_UM2))
    print("          -> %.1f um^2/cell -> ~%.0f cells at 100%%, ~%.0f at a"
          % (bg["cell_um2"], bg["cells_at_100pct"], bg["cells_practical"]))
    print("          routable 65%")
    print("      ⚠ (a) and (b) describe different areas (the hardened die is")
    print("        %d um^2 against %d um^2 of 6x4 tiles), so the budget is a"
          % (bg["core_um2"], bg["tile_area_um2"]))
    print("        RANGE, not a number. ⭐ The ruling survives either: AW = 9 is")
    print("        thousands of cells to store data that should not be there.")
    print("    ⛔ MY 'area is free at 6.28%' WAS WRONG. That is DIE-AREA")
    print("       utilisation INCLUDING FILLER (68,161 of 71,107 instances), not")
    print("       a cell budget. The store already costs ~%d of %d cells."
          % (sc["itemised"], CELLS_TOTAL))

    # ---- 2. the encoding ------------------------------------------------
    print()
    print("  --- 2. THE ROOT CAUSE: the level bit puts payload in the program ---")
    print("    %-28s %-12s %-14s %s"
          % ("transaction", "per-bit", "shift/repeat", "how"))
    tot_bit = tot_sh = 0
    for name, per_bit, sh, why in TRANSACTIONS:
        tot_bit += per_bit
        tot_sh += sh
        print("    %-28s %-12d %-14d %s" % (name, per_bit, sh, why))
    print("    %-28s %-12d %-14d" % ("TOTAL actions", tot_bit, tot_sh))
    print()
    print("    ⭐ AND THE REAL POINT IS THE SLOPE, NOT THE CONSTANT: under the")
    print("    per-bit encoding a longer message needs a longer PROGRAM, so the")
    print("    chip plays a recorded waveform. Under shift/repeat the program is")
    print("    the PROTOCOL and the message flows through it -- an M-byte UART")
    print("    transfer is still 3 actions. That is the distinction the brief")
    print("    draws, and it is why this was never a store-size question.")

    # ---- 3. does it fit? the pre-registered magnitude -------------------
    print()
    print("  --- 3. PRE-REGISTERED: does one txn each fit <= %d B at AW = %d? ---"
          % (STORE_BYTES, AW_TODAY))
    print("    ⛔ The image is a HEADER plus the action stream. My first F1 count")
    print("       left the header out; it carries the per-lane descriptor init")
    print("       and (ruling F3) D_tol as loader metadata.")
    print()
    print("    %-13s %-9s %-10s %-9s %-9s %-7s %s"
          % ("delay bits", "act bits", "act bytes", "hdr B", "prog B", "total", "fits"))
    best = None
    for db in (16, 12, 10, 9):
        L = image_layout(db, dtol_in_image=True)
        ok = L["total"] <= STORE_BYTES
        if ok and best is None:
            best = (db, L)
        print("    %-13d %-9d %-10d %-9d %-9d %-7d %s"
              % (db, L["action"]["bits"], L["action"]["bytes"], L["hdr_bytes"],
                 L["prog_bytes"], L["total"], "YES" if ok else "no"))
    print()
    if best is None:
        print("    *** DOES NOT FIT at any delay width. Per the ruling, the next")
        print("        step is SRAM (the TT IHP SRAM examples), NOT more flops.")
        rc = 1
    else:
        db, L = best
        print("    ⭐ FITS at delay = %d bits: %d bytes of %d used, %d spare."
              % (db, L["total"], STORE_BYTES, STORE_BYTES - L["total"]))
        print("    header %d B (%d bits x %d lanes), program %d B (%d actions x %d B)"
              % (L["hdr_bytes"], L["hdr_bits"], N_LANES, L["prog_bytes"],
                 L["actions"], L["action"]["bytes"]))
        print("    action fields: %s"
              % ", ".join("%s:%d" % (n, b) for n, b in L["action"]["fields"]))
        print()
        print("    ⭐⭐ AND THE %d BITS COME FROM 1.5's OWN HEADROOM. 1.5 derived"
              % db)
        print("    that the timestamp floor is 9 bits (spread + max r = 211) and")
        print("    called 16 'headroom with 7 bits to give back'. This is what")
        print("    the 7 bits were for. ⛔ Note the two widths are NOT the same")
        print("    object: the timestamp REGISTER stays %d bits for the wrap-safe"
              % 16)
        print("    compare; the program's DELAY FIELD is %d. A long delay is" % db)
        print("    still chained (Ruling 2), just into more chunks.")
        print("    ⚠ THIN MARGIN, SAID PLAINLY: %d spare bytes is %d actions. A"
              % (STORE_BYTES - L["total"],
                 (STORE_BYTES - L["total"]) // L["action"]["bytes"]))
        print("    second I2C transaction does not fit. The pre-registered")
        print("    magnitude is MET and the headroom is ~zero, so SRAM is the")
        print("    next step for anything beyond one txn each -- which is the")
        print("    ruling's own trigger, reached on the first real program.")

    # ---- 4. schedulability is unchanged, and that is CHECKED ------------
    print()
    print("  --- 4. A2 IS UNTOUCHED, because only the representation changed ---")
    print("    Each bit edge is still its own job: a shift/repeat action of N")
    print("    bits RELEASES N (or 2N, clocked) events at period T. The arrival")
    print("    curve, r_i and every margin are the same objects.")
    print("    %-20s %-7s %s" % ("lane", "r_i", "margin"))
    for l in LANES:
        rr = response_time_b(l, LANES)
        print("    %-20s %-7d %d" % (l.name, rr["r"], rr["margin"]))
    print("    digest unchanged (see the LANE-DIGEST line above) -- the same")
    print("    five lanes, so this is an encoding change and not a re-derivation.")
    print()
    print("    ⛔ THE ONE THING THE RULING REQUIRES ME TO STATE: does the")
    print("    shift/advance fit inside C = 2? The per-event work is")
    print("      (1) drive pin <- data_reg[bit_ptr]   (2) bit_ptr++, reload the")
    print("      next-action timestamp")
    print("    Both are REGISTER-ONLY: a mux select off a 3-bit pointer, an")
    print("    increment, and an add. No store access -- the descriptor is")
    print("    already in the per-lane registers (Ruling 1 (i)). So C = 2 holds")
    print("    for the same reason the pipelined point does.")
    print("    ⚠ It is an ESTIMATE until Phase 2 measures it, and the frontier")
    print("    already prices the overrun: at C = 3 the minimum margin is 11.")

    # ---- 5. the pin map, flagged back ----------------------------------
    print()
    print("  --- 5. THE DATA CHANNEL AND ITS PIN MAP (flag-back) ---")
    print("    ⛔ The constraint that makes this hard: in RUN mode all 8 uio are")
    print("       protocol pins (UART 2 + SPI 4 + I2C 2), so the channel must")
    print("       come out of ui_in / uo_out alone.")
    print()
    for pin, use, why in PIN_MAP:
        print("    %-13s %s" % (pin, use))
        print("                  %s" % why)
    print()
    print("    ⭐ NO LANE-SELECT FIELD, AND THAT IS THE SAME TRICK RUNG 1 USED.")
    print("    With 5 lanes a host-side lane select would need 3 more input pins")
    print("    we do not have. It is unnecessary: the SHIFT ACTION NAMES ITS")
    print("    LANE, so the host pushes bytes into ONE FIFO and the engine routes")
    print("    them as the program consumes them. Rung 1 deleted the address bus")
    print("    by auto-increment; this deletes the lane select by letting the")
    print("    program do the addressing.")
    print()
    print("    ⚠ WHAT THIS COSTS, so it is not read as free:")
    print("      * a byte is 2 pushes (4-bit nibbles). At 115200 baud a byte is")
    print("        87 us; at SPI 1 MHz it is 8 us. Both are thousands of cycles,")
    print("        so the channel is not the bottleneck -- but it IS a new")
    print("        liveness obligation on the host (see 1.6).")
    print("      * uo_out is now dual-view, so the PROG-MODE readback and the")
    print("        RX payload share it. The existing readback test keeps its")
    print("        meaning in prog mode; in run mode it moves behind ui_in[0].")
    print("      * a TX underrun (the shifter needs a bit, the register is")
    print("        empty) must be a STICKY FLAG, not a stall -- a stall would")
    print("        make C unbounded, which is the clock-stretch failure again.")

    print()
    print("=" * 78)
    print("  GATE F1: %s" % ("PASSED -- payload separated, one txn each fits in "
                             "the EXISTING store, A2 unchanged"
                             if rc == 0 else "FAILED -- see the SRAM trigger"))
    print("  ⛔ FLAG-BACK: the run-mode pin map above, and the dual-view uo_out.")
    print("  -> 1.5 fields: shift/repeat action (bit count N, clock pin,")
    print("     LSB/MSB dir), per-lane DATA register, TX-underrun sticky flag")
    print("  -> 1.6 condition: the host must keep the TX data registers fed;")
    print("     underrun is observable and sticky")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
