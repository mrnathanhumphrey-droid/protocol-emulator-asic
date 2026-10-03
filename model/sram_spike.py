"""SRAM SPIKE -- decide the program memory technology BEFORE Part 1 RTL.

THE ONE CLAIM: an IHP SRAM macro holds the program in about 6% of the 6x4 tile
area where flops would need about 73%, with a one-cycle synchronous read that
SUITS Ruling 1's pipelined fetch -- so the decision is not close, and it has to
be taken before the RTL because the fetch stage differs.

⛔⛔ WHY THIS IS A PART-1 DECISION AND NOT AN OPTIMISATION. A flop array reads
combinationally; an SRAM macro reads SYNCHRONOUSLY, one cycle after the address
is presented. Ruling 1's pipeline prefetches the descriptor a stage early, so a
synchronous read drops straight into the stage that already exists -- but the
RTL has to be WRITTEN for one or the other. Deciding after the RTL means
rewriting the fetch stage.

⛔ AND THE TRIGGER WAS ALREADY PAST. F1 fitted one transaction per protocol into
62 of 64 bytes, which I reported as "2 bytes spare, so SRAM is the next step for
anything beyond that". It is already beyond that: the rung-5 FRAM readback oracle
needs TWO TRANSACTION SHAPES, not one shape looped --
    a write   (address + data), and
    a read    (address + repeated START + read)
-- so the demo the plan depends on does not fit. "If it doesn't fit" was the
wrong framing; it already doesn't.

⭐ ORIGIN OF EVERY NUMBER BELOW (standing rule: an unsourced estimate is
unverified, including our own):
  * macro names        -- read from the PDK tree, IHP-Open-PDK
                          ihp-sg13g2/libs.ref/sg13g2_sram/gds (30 macros)
  * macro geometry     -- the `SIZE` line of each macro's LEF in
                          ihp-sg13g2/libs.ref/sg13g2_sram/lef, fetched directly
  * cells/bit for flops-- ITEMISED from this project's own shipped cell
                          inventory in docs/SILICON_EVIDENCE.md
                          (gate_encoding_f1.store_cost), not a rule of thumb
  * um^2/cell          -- derived from the shipped run: 2,946 cells at 6.28% of
                          a 902,417 um^2 core
  * tile geometry      -- ARCH_PREREG_01 s110: 167 x 108 um per tile
⚠ NOT MEASURED HERE: read latency in ns, setup/hold at the macro pins, and
whether it routes alongside the engine. The first is a one-cycle ARCHITECTURAL
latency from the macro's timing model; the other two need a trial harden and are
named as the spike's remaining work rather than guessed.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "a2"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- ORIGIN: LEF `SIZE` lines, fetched from the IHP PDK ------------------
# RM_IHPSG13_1P_256x8_c3_bm_bist   SIZE 236.8 BY 74.1 ;
# RM_IHPSG13_1P_512x8_c3_bm_bist   SIZE 236.8 BY 110.38 ;
MACROS = [
    ("RM_IHPSG13_1P_256x8_c3_bm_bist", 256, 8, 236.8, 74.1, "LEF SIZE"),
    ("RM_IHPSG13_1P_512x8_c3_bm_bist", 512, 8, 236.8, 110.38, "LEF SIZE"),
]
# others present in the tree, geometry NOT fetched -- listed so the choice is
# visible, not so it can be costed from thin air.
OTHERS_PRESENT = ["RM_IHPSG13_1P_64x16_c2", "RM_IHPSG13_1P_256x16_c2_bm_bist",
                  "RM_IHPSG13_1P_1024x8_c2_bm_bist",
                  "RM_IHPSG13_1P_512x16_c2_bm_bist"]

# ---- ORIGIN: this project's own shipped run -----------------------------
CELLS_TOTAL = 2946
CORE_UM2 = 902_417
UTIL_PCT = 6.28
TILE_UM2 = 167 * 108
TILES = 24
STORE_BITS_TODAY = 512
AW_TODAY = 6


def main() -> int:
    print()
    print("=" * 78)
    print("SRAM SPIKE -- program memory technology, decided before Part 1 RTL")
    print("=" * 78)
    from gate_encoding_f1 import store_cost                         # noqa
    sc = store_cost()
    cell_um2 = (CORE_UM2 * UTIL_PCT / 100.0) / CELLS_TOTAL
    um2_per_bit_flops = sc["per_bit_itemised"] * cell_um2
    budget_um2 = TILE_UM2 * TILES

    print()
    print("  --- the flop baseline, from OUR OWN shipped silicon ---")
    print("    itemised store cost      %.2f cells per stored bit"
          % sc["per_bit_itemised"])
    print("    cell area                %.2f um^2  (2,946 cells at %.2f%% of"
          % (cell_um2, UTIL_PCT))
    print("                             a %s um^2 core)" % f"{CORE_UM2:,}")
    print("    => flops cost            %.1f um^2 per stored bit"
          % um2_per_bit_flops)
    print("    6x4 budget               %d tiles x %d um^2 = %s um^2"
          % (TILES, TILE_UM2, f"{budget_um2:,.0f}"))
    print("    today's 64 B store       %d bits = %s um^2 = %.1f%% of 6x4"
          % (STORE_BITS_TODAY, f"{STORE_BITS_TODAY * um2_per_bit_flops:,.0f}",
             100 * STORE_BITS_TODAY * um2_per_bit_flops / budget_um2))

    print()
    print("  --- the macros, geometry from their LEF SIZE lines ---")
    print("    %-34s %-7s %-16s %-11s %s"
          % ("macro", "bytes", "size um", "area um^2", "% of 6x4"))
    best = None
    for name, words, width, x, y, origin in MACROS:
        area = x * y
        byts = words * width // 8
        pct = 100 * area / budget_um2
        print("    %-34s %-7d %-16s %-11s %.1f%%"
              % (name, byts, "%.1f x %.2f" % (x, y), f"{area:,.0f}", pct))
        if best is None or byts > best[1]:
            best = (name, byts, area, pct, words, width)
    print("    also in the tree, geometry not fetched: %s"
          % ", ".join(OTHERS_PRESENT))

    print()
    print("  --- SRAM against flops, same capacity ---")
    print("    %-34s %-13s %-13s %s"
          % ("capacity", "SRAM um^2", "flops um^2", "SRAM is"))
    for name, words, width, x, y, origin in MACROS:
        bits = words * width
        area = x * y
        fl = bits * um2_per_bit_flops
        print("    %-34s %-13s %-13s %.1fx smaller"
              % ("%d bits (%d B)" % (bits, bits // 8), f"{area:,.0f}",
                 f"{fl:,.0f}", fl / area))
    print()
    print("    ⭐ THE DECISION IS NOT CLOSE. %d bytes of program memory costs"
          % best[1])
    print("    %.1f%% of the 6x4 area as a macro and %.0f%% as flops. The same"
          % (best[3], 100 * best[4] * best[5] * um2_per_bit_flops / budget_um2))
    print("    comparison also cross-checks the F1 area finding by a DIFFERENT")
    print("    route -- that one was in cells, this one in um^2, and they agree")
    print("    that a flop store at this size is most of the chip.")

    print()
    print("  --- what it does to Ruling 1's pipeline ---")
    print("    flop array : combinational read. The fetch stage reads the array")
    print("                 and the EDF compare / timestamp add would stack on")
    print("                 top of it inside one cycle -- the F2 feedthrough")
    print("                 problem, structurally.")
    print("    SRAM macro : SYNCHRONOUS one-cycle read. Address out in cycle k,")
    print("                 data in k+1, landing in the pipeline register that")
    print("                 Ruling 1 already requires.")
    print("    ⭐ So the macro does not cost a pipeline stage -- it USES the one")
    print("    the ruling already bought. Nothing in the (C, J) frontier moves:")
    print("    C = 2 with the prefetch is exactly the shape a synchronous read")
    print("    wants, and the descriptor is in per-lane registers (Ruling 1 (i))")
    print("    so the SRAM is on the PROGRAM path only, never the EDF path.")

    print()
    print("  --- integration risks, named rather than discovered later ---")
    print("    1. METAL4 TOP, AND POWER PINS ON METAL4. The LEF's top routing")
    print("       layer is Metal4 and its VDD/VSS pins are Metal4-only, while a")
    print("       TT PDN typically lands on Metal5/TopMetal1. Bridging that is a")
    print("       known integration step, not a surprise -- ⚠ I have seen it")
    print("       referenced in public OpenROAD/TT issue titles for this exact")
    print("       macro family but have NOT reproduced it here, so it is a RISK")
    print("       to check in the spike, not a measured fact.")
    print("    2. BIST PINS. The macro carries A_BIST_* inputs (EN, CLK, REN,")
    print("       WEN, MEN, ADDR, DIN, BM). They must be tied off deliberately;")
    print("       a floating BIST enable is a write port nobody declared.")
    print("    3. GEOMETRY vs TILES. The macro is %.1f um wide against a %d um"
          % (MACROS[0][3], 167))
    print("       tile, so it spans ~1.4 tiles horizontally and (at %.2f um)"
          % MACROS[1][4])
    print("       more than one tile row. It fits a 6x4 (%d x %d um) with room,"
          % (6 * 167, 4 * 108))
    print("       but it is NOT a drop-in inside one tile.")
    print("    4. PRECHECK. ⚠ Whether the macro's GDS layers pass the CMOS5L")
    print("       precheck allowlist is NOT verified here. It is the first thing")
    print("       the spike should run, because a precheck failure kills the")
    print("       approach regardless of the area argument.")

    print()
    print("  --- the cheap reclaim, which applies either way ---")
    from lane_digest import shipped                                 # noqa
    lanes = shipped()
    d_bits = 8
    dtol_bytes = -(-d_bits * len(lanes) // 8)
    print("    D_tol in the image header costs %d bytes for %d lanes."
          % (dtol_bytes, len(lanes)))
    print("    It exists ONLY for a 5.3 load-time admissibility screen. If that")
    print("    screen does not ship, drop it: %d of 64 bytes back, and the"
          % dtol_bytes)
    print("    engine never read it anyway (ruling F3).")
    print("    ⛔ Do NOT drop it silently if 5.3 is still planned -- that would")
    print("       remove the input the certificate path reads, which is the one")
    print("       thing F3 kept it for.")

    print()
    print("=" * 78)
    print("  SRAM SPIKE: RECOMMEND the macro path")
    print("    * %s -- %d bytes, %s um^2, %.1f%% of 6x4"
          % (best[0], best[1], f"{best[2]:,.0f}", best[3]))
    print("    * %.0fx smaller than the equivalent flop array, on numbers taken"
          % (best[4] * best[5] * um2_per_bit_flops / best[2]))
    print("      from this project's own silicon and the PDK's own LEF")
    print("    * one-cycle synchronous read FITS Ruling 1's prefetch stage")
    print("    * (C, J) frontier unaffected: the SRAM is on the program path,")
    print("      not the EDF path")
    print("  ⛔ BEFORE RTL, the spike still owes: CMOS5L precheck on the macro")
    print("     GDS, a trial harden for routability beside the engine, and the")
    print("     Metal4 PDN bridge. Those are build steps, not estimates, and")
    print("     none of them is assumed above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
