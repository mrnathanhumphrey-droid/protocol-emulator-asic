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
        ("shift register", 8, "lane-reg", "ARCH_PREREG descriptor",
         "one byte, the largest frame payload in the required set"),
        ("bit counter", bits_for(8), "lane-reg", "ARCH_PREREG descriptor",
         "0..8 bits per frame"),
        ("next-action timestamp", N, "lane-reg", "ARCH_PREREG descriptor",
         "DERIVED floor is %d (wrap-safe compare); %d ships as headroom"
         % (derive_N()["floor"], N)),
        ("C_i (service time)", bits_for(8), "lane-reg", "1.5 per-lane C_i",
         "1..8 cycles; the frontier's admissible range is C <= 6"),
        ("D_sched (EDF key)", d_width, "lane-reg", "spec R2 + Ruling 1",
         "max key %d; REGISTER not store (Ruling 1 (i))" % max(l.D for l in LANES)),
        # ---- the program ------------------------------------------------
        ("action opcode", 3, "prog", "1.5 + Ruling 2",
         "drive / sample / wait / NO-OP RE-ARM / atomic-group / stop = 6 of 8"),
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
    if include_dtol:
        f.append(("D_tol (tolerance)", d_width, "lane-reg", "spec R2",
                  "⚠ NOT read by the engine datapath -- see the flag-back"))
    else:
        f.append(("D_tol (tolerance)", d_width, "load", "spec R2",
                  "loader metadata; the engine never reads it"))
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
        fl = fields(N, d_width, include_dtol)
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
        load_bits = sum(b for _n, b, w, _t, _y in fl if w == "load")
        print()
        print("  --- the DERIVED encoding ---")
        print("    per-lane register state : %3d bits x %d lanes = %d flops"
              % (lane_bits, N_LANES, lane_bits * N_LANES))
        print("    global                  : %3d bits" % glob_bits)
        print("    loader metadata (not silicon): %3d bits x %d lanes"
              % (load_bits, N_LANES))
        print("    engine flops (new)      : %d" % (lane_bits * N_LANES + glob_bits))
        print("      vs %d flops today, of which %d are the program store"
              % (FLOPS_TODAY, STORE_FLOPS_TODAY))
        print("      => %d non-store flops today -> %d, at %.2f%% utilisation"
              % (FLOPS_TODAY - STORE_FLOPS_TODAY,
                 FLOPS_TODAY - STORE_FLOPS_TODAY + lane_bits * N_LANES + glob_bits,
                 UTIL_TODAY))

        # a program action word: the non-atomic common case
        act_bits = sum(b for n, b, w, _t, _y in fl
                       if w == "prog" and not n.startswith("P-ATOMIC"))
        act_bytes = -(-act_bits // 8)
        atom_bits = act_bits + sum(b for n, b, w, _t, _y in fl
                                   if n.startswith("P-ATOMIC"))
        atom_bytes = -(-atom_bits // 8)
        print()
        print("    program action word     : %d bits -> %d bytes"
              % (act_bits, act_bytes))
        print("    P-ATOMIC action word    : %d bits -> %d bytes"
              % (atom_bits, atom_bytes))
        store_bytes = 2 ** AW_TODAY
        print()
        print("  ⛔⛔ --- AND HERE IS THE PROBLEM, DERIVED ---")
        print("    store at AW = %d            : %d bytes" % (AW_TODAY, store_bytes))
        print("    actions it holds            : %d" % (store_bytes // act_bytes))
        print("    one UART frame (10 edges)   : %d actions" % 10)
        print("    one SPI byte (16 edges)     : %d actions" % 16)
        print("    the required set, one frame each on 3 protocols:")
        need_actions = 10 + 16 + 2 * 9        # UART 10, SPI 16, I2C ~2 per bit
        print("      ~%d actions = %d bytes" % (need_actions, need_actions * act_bytes))
        fits = need_actions * act_bytes <= store_bytes
        print("    FITS at AW = %d? %s" % (AW_TODAY, "yes" if fits else "*** NO ***"))
        if not fits:
            aw_need = next(a for a in range(AW_TODAY, 16)
                           if need_actions * act_bytes <= 2 ** a)
            print("    => AW >= %d (%d bytes) for ONE frame on each protocol;"
                  % (aw_need, 2 ** aw_need))
            print("       AW >= %d (%d bytes) for a program with room to be"
                  % (aw_need + 1, 2 ** (aw_need + 1)))
            print("       interesting. Store flops go %d -> %d."
                  % (STORE_FLOPS_TODAY, 8 * 2 ** (aw_need + 1)))
            print()
            print("    ⛔ THIS IS A FLAG-BACK, NOT A FIX I SHOULD TAKE. Widening")
            print("    the store deepens the `mem[...]` mux, and that mux is on")
            print("    the %.4f-of-%.1f ns COMBINATIONAL PAD FEEDTHROUGH that is"
                  % (SLOW_PERIOD_NS - WNS_NS, SLOW_PERIOD_NS))
            print("    already the worst path in the design. Store depth and the")
            print("    critical path are ONE decision.")
            print("    ⭐ AND THEY HAVE ONE FIX: REGISTER THE READBACK. The")
            print("    feedthrough exists only because `uo_out` presents")
            print("    `mem[rd_ptr]` combinationally. A register there costs 8")
            print("    flops, retires the only nearly-full path on the chip, and")
            print("    makes the store depth a question about area alone.")
            print("    ⚠ It changes the readback TIMING, so the cocotb readback")
            print("    test moves by one cycle -- which is why it is a ruling and")
            print("    not a tidy-up.")

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
    print("  --- P-ATOMIC, priced from scratch ---")
    atom_flops = 2 * N_PINS
    atom_comb = 3 * N_PINS + bits_for(N_PINS - 1) * 2
    print("    mask + data registers      : %d flops" % atom_flops)
    print("    apply network (AND/OR/mux) : ~%d cells" % atom_comb)
    print("    total                      : ~%d cells" % (atom_flops + atom_comb))
    print("    ⚠ I was handed 'about 350 cells' for this field and can find NO")
    print("      basis for it in this repo. My derivation is ~%d, about %dx"
          % (atom_flops + atom_comb, round(350 / (atom_flops + atom_comb))))
    print("      smaller. Either 350 is scoping something bigger than the field")
    print("      (a whole atomic-group action path, perhaps) or it is stale.")
    print("      Recorded as a DISCREPANCY rather than reconciled by guesswork.")

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
    print("  1.5 FLAG-BACKS -- three, and the first two are design decisions")
    print("=" * 78)
    # ⛔ the recommendation is COMPUTED, not typed. A literal here said "AW >= 10"
    # while the derivation three lines up said 8 for one frame each and 9 for
    # headroom -- a number in prose disagreeing with the number in the run,
    # which is the whole class this project keeps tripping on.
    aw_one = next(a for a in range(AW_TODAY, 16)
                  if need_actions * act_bytes <= 2 ** a)
    print("   F1  PROGRAM STORE DEPTH. AW = %d holds %d actions; one frame on"
          % (AW_TODAY, store_bytes // act_bytes))
    print("       each required protocol needs ~%d (%d bytes). Recommend"
          % (need_actions, need_actions * act_bytes))
    print("       AW >= %d minimum, AW = %d for headroom (store flops %d -> %d)."
          % (aw_one, aw_one + 1, STORE_FLOPS_TODAY, 8 * 2 ** (aw_one + 1)))
    print("   F2  REGISTER THE READBACK. Retires the %.4f ns feedthrough and"
          % (SLOW_PERIOD_NS - WNS_NS))
    print("       decouples store depth from the critical path. Moves the")
    print("       existing cocotb readback test by one cycle.")
    print("   F3  IS D_tol A FLOP OR LOADER METADATA? The engine datapath never")
    print("       reads it -- only an admissibility checker would. In silicon it")
    print("       costs %d flops; as loader metadata it costs nothing and"
          % (d_width * N_LANES))
    print("       the check runs at load. The ruling said 'separate fields';")
    print("       this asks whether 'field' means silicon.")
    print()
    print("  GATE 1.5: %s" % ("PASSED -- every field traced and priced, encoding "
                              "derived, three flag-backs raised"
                              if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
