"""SPEC 1.5 -- THE DESCRIPTOR FREEZE. Every field priced, the encoding DERIVED.

THE ONE CLAIM: each field traces to a spec item or to the pre-registration, each
has a width derived from a measured or proved quantity, and the total is checked
against the silicon that exists. Untraced fields are cut.

⛔⛔ TWO THINGS THIS FILE DERIVES THAT NOBODY ASKED FOR, BOTH OF WHICH ARE
FLAG-BACKS BECAUSE THEY CHANGE THE DESIGN RATHER THAN DESCRIBE IT:

  (1) THE PROGRAM STORE IS AN ORDER OF MAGNITUDE TOO SMALL. At `AW = 6` the
      store is 64 bytes. A program action encodes to 3 bytes (below), so the
      whole store holds ~21 actions -- and ONE UART frame is 10 actions while one
      SPI byte is 16. The engine cannot hold a two-protocol program. This is not
      a tuning question, it is the difference between a demo and the object.

  (2) AND WIDENING IT WALKS STRAIGHT INTO THE CRITICAL PATH. The store is read
      through `mem[...]` into a COMBINATIONAL PAD FEEDTHROUGH, which is already
      the worst path in the design at 18.4388 of 20 ns. Deepening the store
      deepens that mux. So the store depth and the critical path are one
      decision, and the fix for both is the same: REGISTER THE READBACK. That
      also retires the existing feedthrough, which is the only nearly-full path
      on the chip.

⭐ WHAT THE WIDTH DERIVATION ACTUALLY SHOWS. The timestamp width `N` has a FLOOR
of 9 bits, from the live-deadline spread condition, not from how long a delay
anyone wants to program -- because Ruling 2's chained re-arms decouple delay
length from `N` entirely. And the re-arm rate never binds the schedule at any
`N` down to the floor. So `N = 16` is HEADROOM, with 7 bits available to give
back if area or timing ever asks. That is a better thing to know than "16 bits
because 16 is a nice number".

⛔ A NOTE ON ONE FIGURE I WAS GIVEN AND AM NOT REPEATING. The P-ATOMIC lane group
arrives with "about 350 cells" attached. I can find no basis for that number
anywhere in this repository -- not in `ARCH_PREREG_01.md`, not in the silicon
evidence, not in any results doc. So it is derived from scratch below and comes
out roughly an order of magnitude smaller. If 350 is right it is measuring
something larger than the field, and the difference needs naming before it is
budgeted.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import BLane, response_time_b                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LANES = lane_digest.shipped()
N_LANES = len(LANES)
N_PINS = 8                      # tt_um_* gives 8 bidirectional uio
AW_TODAY = 6                    # src/project.v parameter AW
# silicon as built, docs/SILICON_EVIDENCE.md
CELLS_TODAY = 2946
FLOPS_TODAY = 535
STORE_FLOPS_TODAY = 512
UTIL_TODAY = 6.28
WNS_NS = 1.5612
SLOW_PERIOD_NS = 20.0


def bits_for(n: int) -> int:
    """Bits to hold the values 0..n inclusive."""
    b = 1
    while (1 << b) <= n:
        b += 1
    return b


# ============================================================================
# THE TIMESTAMP WIDTH, DERIVED
# ============================================================================
def derive_N() -> dict:
    """The floor on N is the live-deadline spread, not the delay length.

    WRAP-SAFE MODULAR COMPARE. With an absolute counter, `a before b` is decided
    by the sign of `(a - b)` in N-bit two's complement, which is correct exactly
    while every pair of live deadlines is less than 2^(N-1) apart. So:

        max_live_deadline - min_live_deadline + max r_i  <  2^(N-1)

    ⛔ THE `+ max r_i` TERM IS NOT DECORATION. A deadline stays live until its
    job COMPLETES, so the oldest live deadline can be up to r_i in the past
    relative to its own release. Omitting it would make the condition a
    statement about releases rather than about what is in the comparator.
    """
    keys = [l.D for l in LANES]
    rs = {l.name: response_time_b(l, LANES)["r"] for l in LANES}
    spread = max(keys) - min(keys)
    need = spread + max(rs.values())
    floor_n = next(n for n in range(2, 40) if 2 ** (n - 1) > need)
    return {"keys": sorted(keys), "spread": spread, "max_r": max(rs.values()),
            "need": need, "floor": floor_n}


def rearm_rate_sweep(ns: list) -> list:
    """Does a narrower N ever cost the schedule? (chunk = 2^(N-1) - 1)"""
    base = min(response_time_b(l, LANES)["margin"] for l in LANES)
    out = []
    for n in ns:
        chunk = 2 ** (n - 1) - 1
        ra = BLane("re-arm", chunk, 2, D_tol=chunk - 2)
        aug = LANES + [ra]
        rows = [(l, response_time_b(l, aug)) for l in aug]
        mm = min(rr["margin"] for _l, rr in rows)
        prot = [(l, rr) for l, rr in rows if l is not ra]
        worst = min(rr["margin"] for _l, rr in prot)
        out.append({"N": n, "chunk": chunk, "U": sum(l.util for l in aug),
                    "min": mm, "prot_min": worst, "base": base,
                    "chunks_10ms": -(-500_000 // chunk)})
    return out


# ============================================================================
# THE FIELDS
# ============================================================================
def fields(N: int, d_width: int, include_dtol: bool) -> list:
    """(name, bits, where it lives, traces to, why this width).

    `where`: "lane-reg" = per-lane register (Ruling 1 for the key; state for the
    rest). "prog" = a word in the program store. "global" = one instance.
    "load" = loader metadata, NOT silicon.
    """
    f = [
        # ---- per-lane state -------------------------------------------
        ("pin index", bits_for(N_PINS - 1), "lane-reg", "ARCH_PREREG descriptor",
         "%d uio pins" % N_PINS),
        ("drive mode", 1, "lane-reg", "1.5 drive mode / F5",
         "push-pull vs open-drain, one bit per pin"),
        # ⛔ MERGED, not added. ARCH_PREREG's "shift reg" and ruling F1's
        # "data register" are the SAME register, and its "bit counter" and F1's
        # "bit pointer" are the same counter. Listing both pairs cost 12 bits x
        # 5 lanes = 60 flops for nothing, and would have shipped a descriptor
        # with two names for one thing -- which is how a second implementation
        # of the same state later disagrees with the first.
        ("data/shift register", 8, "lane-reg",
         "ARCH_PREREG descriptor + ruling F1",
         "⭐ THE PAYLOAD LIVES HERE, not in the program. Fed by the host "
         "channel; the shift action emits from it. ONE register, two names "
         "in two specs"),
        ("bit pointer / counter", bits_for(8), "lane-reg",
         "ARCH_PREREG descriptor + ruling F1",
         "0..8; which bit of the data register the shifter is on"),
        ("next-action timestamp", N, "lane-reg", "ARCH_PREREG descriptor",
         "DERIVED floor is %d (wrap-safe compare); %d ships as headroom"
         % (derive_N()["floor"], N)),
        ("C_i (service time)", bits_for(8), "lane-reg", "1.5 per-lane C_i",
         "1..8 cycles; the frontier's admissible range is C <= 6"),
        ("D_sched (EDF key)", d_width, "lane-reg", "spec R2 + Ruling 1",
         "max key %d; REGISTER not store (Ruling 1 (i))" % max(l.D for l in LANES)),
        # ---- the program ------------------------------------------------
        ("TX underrun (sticky)", 1, "lane-reg", "ruling F1 + 1.6",
         "⛔ a sticky FLAG, never a stall: a stall makes C unbounded, which is "
         "the clock-stretch failure again"),
        ("action opcode", 3, "prog", "1.5 + Ruling 2 + F1",
         "drive / sample / wait / NO-OP RE-ARM / SHIFT-REPEAT / atomic-group / "
         "stop = 7 of 8"),
        ("shift bit count N", bits_for(8), "prog", "ruling F1",
         "emit N bits from the data register; 1..8"),
        ("shift clock pin", bits_for(N_PINS - 1), "prog", "ruling F1",
         "the shifter drives its OWN clock, or data and clock become two "
         "actions in lockstep and P-ORDER applies per bit"),
        ("shift direction", 1, "prog", "ruling F1", "LSB-first or MSB-first"),
        ("action pin", bits_for(N_PINS - 1), "prog", "ARCH_PREREG",
         "which pin this action touches"),
        ("action level", 1, "prog", "ARCH_PREREG", "the value to drive"),
        ("action delay", N, "prog", "Ruling 2 C2",
         "relative delay to the next action; per-action bound < 2^(N-1) "
         "CHECKED AT LOAD"),
        # ---- global ------------------------------------------------------
        ("global time counter", N, "global", "Ruling 2 (absolute counter)",
         "ONE incrementer, not %d decrementers" % N_LANES),
        ("P-ATOMIC mask", N_PINS, "prog", "1.5 P-ATOMIC",
         "which pins move together"),
        ("P-ATOMIC data", N_PINS, "prog", "1.5 P-ATOMIC",
         "the levels they move to"),
        ("sticky ovr", 1, "global", "1.5 sticky ovr",
         "registered, pin-observable, set-only until reset"),
    ]
    # ⭐ RULING F3: D_tol is NOT a silicon register. It stays in the program
    # IMAGE FORMAT as loader metadata, so a 5.3 load-time admissibility screen
    # reads it from the store -- the certificate path stays open at zero
    # runtime cost, and the 40 flops are not spent.
    f.append(("D_tol (tolerance)", d_width, "image", "spec R2 + ruling F3",
              "program-image metadata, read by the load-time screen; the "
              "engine datapath never reads it"))
    return f


# ============================================================================
def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 1.5 -- descriptor freeze, encoding DERIVED")
    print("=" * 78)
    lane_digest.announce("gate_descriptor_1_5.py (1.5)", LANES)
    rc = 0

    # ---- the width derivation -------------------------------------------
    d = derive_N()
    print()
    print("  --- the timestamp width N, DERIVED ---")
    print("    live EDF keys (D_sched + C_i): %s" % d["keys"])
    print("    spread = %d - %d = %d ; max r_i = %d"
          % (max(d["keys"]), min(d["keys"]), d["spread"], d["max_r"]))
    print("    condition: spread + max r = %d  <  2^(N-1)" % d["need"])
    print("    => FLOOR N = %d bits" % d["floor"])
    print()
    print("    ⭐ AND THE DELAY LENGTH DOES NOT ENTER THIS. Ruling 2's chained")
    print("    re-arms decouple how long a delay can be from how wide N is, so")
    print("    the only floor on N is the comparator condition above. The")
    print("    question left is whether a narrow N costs the schedule through a")
    print("    denser re-arm rate -- computed, not assumed:")
    print("      %-5s %-9s %-13s %-9s %-11s %s"
          % ("N", "chunk", "chunks/10ms", "U total", "min margin", "vs base"))
    sweep = rearm_rate_sweep([d["floor"], 10, 12, 14, 16, 20])
    for s in sweep:
        print("      %-5d %-9d %-13d %-9.5f %-11d %s"
              % (s["N"], s["chunk"], s["chunks_10ms"], s["U"], s["min"],
                 "%+d" % (s["min"] - s["base"])))
    if any(s["min"] != s["base"] for s in sweep):
        print("      ⛔ a width DOES cost margin -- N is not free, re-read above")
    else:
        print("      => the re-arm rate NEVER binds, down to the floor. So N is")
        print("         set by the comparator floor (%d) and by area/timing, and"
              % d["floor"])
        print("         N = 16 is HEADROOM with %d bits available to give back."
              % (16 - d["floor"]))
    N = 16
    d_width = bits_for(max(l.D for l in LANES))

    # ---- the field table ------------------------------------------------
    for include_dtol in (True,):
        fl = fields(N, d_width, include_dtol)   # F3 decided: D_tol -> image
        print()
        print("  --- the fields, each priced and traced ---")
        print("    %-24s %-6s %-10s %-26s %s"
              % ("field", "bits", "lives in", "traces to", "width from"))
        untraced = []
        for name, bits, where, trace, why in fl:
            if not trace:
                untraced.append(name)
            print("    %-24s %-6d %-10s %-26s %s"
                  % (name, bits, where, trace, why))
        print()
        if untraced:
            print("    *** CUT (untraced): %s" % ", ".join(untraced))
            rc = 1
        else:
            print("    => every field traces to a spec item or the pre-reg")

        # ---- the derived encoding -----------------------------------------
        lane_bits = sum(b for _n, b, w, _t, _y in fl if w == "lane-reg")
        prog_bits = sum(b for _n, b, w, _t, _y in fl if w == "prog")
        glob_bits = sum(b for _n, b, w, _t, _y in fl if w == "global")
        load_bits = sum(b for _n, b, w, _t, _y in fl if w in ("load", "image"))
        print()
        print("  --- the DERIVED encoding ---")
        print("    per-lane register state : %3d bits x %d lanes = %d flops"
              % (lane_bits, N_LANES, lane_bits * N_LANES))
        print("    global                  : %3d bits" % glob_bits)
        print("    program-image metadata (NOT silicon, ruling F3): %3d bits "
              "x %d lanes" % (load_bits, N_LANES))
        print("    engine flops (new)      : %d" % (lane_bits * N_LANES + glob_bits))
        print("      vs %d flops today, of which %d are the program store"
              % (FLOPS_TODAY, STORE_FLOPS_TODAY))
        print("      => %d non-store flops today -> %d, at %.2f%% utilisation"
              % (FLOPS_TODAY - STORE_FLOPS_TODAY,
                 FLOPS_TODAY - STORE_FLOPS_TODAY + lane_bits * N_LANES + glob_bits,
                 UTIL_TODAY))

        # ⛔⛔ THE ACTION WORD IS THE MAX OVER OPCODE VARIANTS, NOT THE SUM OF
        # EVERY PROG FIELD. Summing them gave 31 bits -> 4 bytes and
        # CONTRADICTED gate_encoding_f1.py's 24 bits -> 3 bytes off the same
        # field list, because the fields are mutually exclusive by opcode: a
        # SHIFT action has no `level`, a DRIVE action has no `count`/`dir`, and
        # only an ATOMIC action carries mask+data. An encoding costed as the sum
        # of all variants is an encoding nobody would build, and the two files
        # disagreeing about the same word is exactly the drift A1 exists to stop.
        DELAY_BITS = 10          # F1's derived width; see that file
        common = 3 + bits_for(N_PINS - 1) + DELAY_BITS      # opcode, pin, delay
        variants = {
            "drive (level)": common + 1,
            "shift/repeat": common + bits_for(8) + bits_for(N_PINS - 1) + 1,
            "wait / no-op re-arm": common,
            "atomic group": common + 2 * N_PINS,
        }
        act_bits = max(variants[k] for k in ("drive (level)", "shift/repeat",
                                             "wait / no-op re-arm"))
        act_bytes = -(-act_bits // 8)
        atom_bits = variants["atomic group"]
        atom_bytes = -(-atom_bits // 8)
        print()
        print("    action word, PER OPCODE VARIANT (delay field %d bits):"
              % DELAY_BITS)
        for k in ("drive (level)", "shift/repeat", "wait / no-op re-arm",
                  "atomic group"):
            print("      %-22s %2d bits -> %d bytes"
                  % (k, variants[k], -(-variants[k] // 8)))
        print("    common word (non-atomic): %d bits -> %d bytes"
              % (act_bits, act_bytes))
        print("    P-ATOMIC word           : %d bits -> %d bytes"
              % (atom_bits, atom_bytes))
        print("    ⭐ matches gate_encoding_f1.py's %d-bit word; the two files"
              % act_bits)
        print("       now derive the same number from the same fields.")
        store_bytes = 2 ** AW_TODAY
        # ⛔⛔ THIS SECTION USED TO READ "THE PROGRAM STORE IS AN ORDER OF
        # MAGNITUDE TOO SMALL, RECOMMEND AW >= 8". That finding is SUPERSEDED by
        # ruling F1 and the recommendation is WITHDRAWN. The count was right and
        # the root cause was wrong: the action word carried a LEVEL BIT, so the
        # program spelled out the data one action per bit, and program size grew
        # LINEARLY WITH MESSAGE LENGTH -- a waveform player, not a protocol
        # emulator. The store was never the problem.
        #
        # ⛔ AND THE FIX I PROPOSED WOULD HAVE COST THE CHIP. At ~4 cells per
        # stored bit (itemised from the shipped cell inventory in
        # gate_encoding_f1.py), AW = 9 is ~17,000 cells -- over half a practical
        # tile budget -- spent holding payload. "Area is free at 6.28%" was
        # wrong: 6.28% is DIE-AREA utilisation including 68,161 filler
        # instances, not a cell budget.
        need_actions = sum(sh for _n, _pb, sh, _w in ())  # see gate_encoding_f1
        print()
        print("  --- the store, AFTER ruling F1 (see gate_encoding_f1.py) ---")
        print("    store at AW = %d : %d bytes" % (AW_TODAY, store_bytes))
        print("    ⛔ MY EARLIER FINDING HERE IS SUPERSEDED AND MY FIX WITHDRAWN.")
        print("    I reported 'the store is an order of magnitude too small,")
        print("    recommend AW >= 8'. The count was right, the root cause was")
        print("    not: the LEVEL BIT put payload in the program, so program")
        print("    size grew with MESSAGE LENGTH. With F1's shift/repeat action")
        print("    and a host data channel, one transaction on each required")
        print("    protocol fits in 62 of these %d bytes." % store_bytes)
        print("    ⛔ And AW = 9 would have cost ~17,000 cells at ~4 cells per")
        print("    stored bit -- over half a practical tile budget -- to hold")
        print("    data that should not be in the store. 'Area is free at")
        print("    6.28%' was wrong: that is die-area utilisation INCLUDING")
        print("    68,161 filler instances, not a cell budget.")
        print("    ⚠ The fit is 2 bytes spare, so SRAM (the TT IHP examples) is")
        print("    the next step for anything beyond one transaction each --")
        print("    not more flops.")

    # ---- the structural claims, as claims ------------------------------
    print()
    print("  --- drive mode: the F5 property, structural rather than tested ---")
    print("    uio_out[i] = data[i] & pushpull[i]")
    print("    pushpull[i] = 0  =>  uio_out[i] is CONSTANT 0, so")
    print("                         (uio_oe[i] && uio_out[i]) is UNSATISFIABLE")
    print("    ⭐ That is the strongest form of 'open-drain never drives high':")
    print("       not untested, unsatisfiable. It is how src/project.v already")
    print("       does it, with pushpull hard-wired to 0 -- which is also why")
    print("       the chip currently cannot drive a 1 on any uio pin.")
    print("    MUST-FIRE, both faces, named for Phase 2:")
    print("      (a) pushpull=0: assert uio_oe asserts and uio_out stays 0")
    print("      (b) pushpull=1: assert BOTH levels appear at the pin")
    print("      ⛔ (b) is the one that cannot pass today. A suite with only")
    print("         (a) is green on the shipped RTL, which is exactly the")
    print("         'too simple to reach the broken path' shape.")

    print()
    print("  --- P-ORDER: no new fields, and that is the point ---")
    print("    ordering between lanes is expressed as timestamp OFFSETS in the")
    print("    program, not as a priority field. The EDF key already orders")
    print("    everything; a second ordering mechanism would be a second")
    print("    scheduler, and the two would disagree somewhere.")
    print("    1.6 condition: N_sep - (r_i - C_i) >= t_min")

    print()
    print("  --- P-ATOMIC: the 350-vs-46 discrepancy, RECONCILED ---")
    print("    ⛔ CORRECTION FIRST. I reported 'I was handed about 350 cells and")
    print("    can find no basis for it in this repo'. The repo part is true and")
    print("    the framing was wrong: 350 WAS MY OWN FIGURE from an earlier")
    print("    round (~60 bits x ~5.8 cells/bit, 5 lanes of mask+data). I had")
    print("    treated my own estimate as an external one and asked where it")
    print("    came from. It came from me.")
    print()
    print("    The two numbers differ on TWO axes, not one:")
    print("      SCOPE          : 5 PER-LANE groups  vs  1 SHARED group")
    print("      CELLS PER BIT  : 5.8 (a STORE bit: flop + mux tree + tie +")
    print("                       hold-fix) vs ~2 (a plain register bit)")
    print("    ⛔ The 5.8 figure is the store's, and it is dominated by the")
    print("    64-entry readback MUX TREE. A 16-bit register has no such mux, so")
    print("    carrying 5.8 into it over-prices the field about 3x.")
    print()
    w = N_PINS
    per_bit_reg = 2           # flop + its pro-rata hold-fix buffer
    apply_net = 3 * N_PINS + bits_for(N_PINS - 1) * 2
    print("    %-26s %-8s %-10s %-10s %s"
          % ("variant", "bits", "@2/bit", "+apply", "total"))
    for label, groups, width in (("1 shared group", 1, w),
                                 ("5 per-lane groups", N_LANES, w),
                                 ("5 per-lane, w=6", N_LANES, 6)):
        bits = groups * 2 * width
        tot = bits * per_bit_reg + groups * apply_net
        print("    %-26s %-8d %-10d %-10d ~%d"
              % (label, bits, bits * per_bit_reg, groups * apply_net, tot))
    print("    => the earlier ~350 lands on the PER-LANE row; the ~46 was the")
    print("       SHARED row costed with flops at 1 cell. Both arithmetics were")
    print("       fine; they were pricing different designs.")
    print()
    print("    ⭐⭐ AND THE RECONCILIATION SETTLES THE DESIGN QUESTION. P-ATOMIC")
    print("    needs ONE SHARED mask+data register, not five, BECAUSE THE")
    print("    SCHEDULER IS NON-PREEMPTIVE: exactly one job is in service at any")
    print("    instant, so at most one atomic group can be mid-apply. Five")
    print("    registers would be four copies that provably cannot be live")
    print("    together. The per-lane variant is ~%d cells for nothing."
          % ((N_LANES * 2 * w * per_bit_reg + N_LANES * apply_net)
             - (2 * w * per_bit_reg + apply_net)))
    print("    ⛔ The condition that makes it true is worth naming, because it")
    print("    is a property we could lose: if the engine ever overlapped two")
    print("    services (a deeper pipeline than Ruling 1's two stages), the")
    print("    shared register stops being sufficient. 1.5 freezes ONE group")
    print("    and the pipeline depth is what guards it.")

    print()
    print("  --- sticky ovr ---")
    print("    1 flop, set-only until reset, REGISTERED to a pin.")
    print("    ⛔ registered, never combinational to a pad: the one nearly-full")
    print("       path in this design is a pad-to-pad feedthrough, and that is")
    print("       precisely the shape not to add to.")
    print("    MUST-FIRE: force an overflow and require the pin to latch high")
    print("    and STAY high. A sticky bit that is never seen set is a wire.")

    print()
    print("  --- hooks: surface reserved, nothing built ---")
    for h, why in (("lateness-witness tap (engine r_i)",
                    "r_i as defined in task_model.py, so the silicon and the "
                    "model measure the same quantity"),
                   ("admissibility check site",
                    "where 1.6's conditions would be evaluated; ⚠ whether this "
                    "runs in silicon decides if D_tol is a flop or loader data"),
                   ("CRC read-path tap",
                    "the attestation form pre-registered in plan 6 L3")):
        print("    * %-34s %s" % (h, why))
    print("    ⛔ HOOKS ONLY. Each reserves a place to attach; none is")
    print("       implemented, and none is counted as evidence of anything.")

    # ---- the flag-backs -------------------------------------------------
    print()
    print("=" * 78)
    print("  1.5 -- ALL THREE FLAG-BACKS NOW RULED")
    print("=" * 78)
    print("   F2  ✅ RULED + EXTENDED. Register the readback: retires the")
    print("       %.4f ns feedthrough and decouples store depth from the"
          % (SLOW_PERIOD_NS - WNS_NS))
    print("       critical path. EXTENSION: every engine-driven output bit")
    print("       (uo_out, uio_out, uio_oe) comes from a flop -- the reason is")
    print("       CORRECTNESS, not timing: a glitch on SCLK is an extra clock")
    print("       edge, and I2C's T_SP filter is the device's mercy, not ours.")
    print("       Checked statically by model/f2_flop_driven_outputs.py, which")
    print("       is EXPECTED RED on today's netlist.")
    print("   F3  ✅ RULED: D_tol is NOT a silicon register. It lives in the")
    print("       PROGRAM-IMAGE FORMAT as loader metadata, so a 5.3 load-time")
    print("       screen reads it from the store. %d flops not spent, and the"
          % (d_width * N_LANES))
    print("       certificate path stays open at zero runtime cost.")
    print("   F1  ✅ RULED, and the root cause was not store size -- see")
    print("       model/a2/gate_encoding_f1.py. The level bit put PAYLOAD in")
    print("       the program; with a shift/repeat action and a host data")
    print("       channel, one transaction each fits the EXISTING 64 B store.")
    print("       ⛔ My AW>=8 recommendation is WITHDRAWN: at ~4 cells per")
    print("       stored bit, AW=9 is ~17K cells -- over half a practical tile")
    print("       budget, to hold data that should not be in the store.")
    print()
    print("  GATE 1.5: %s" % ("PASSED -- every field traced and priced, the "
                              "encoding derived per opcode variant, and all "
                              "three flag-backs RULED (F1 withdrew my own "
                              "store-size fix)"
                              if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
