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

⛔⛔⛔ PROVENANCE CORRECTION -- READ THIS BEFORE THE AREA NUMBERS.

THE GEOMETRY BELOW COMES FROM THE **SG13G2** PDK TREE, NOT FROM SG13CMOS5L.
I fetched it from `IHP-Open-PDK/ihp-sg13g2/libs.ref/sg13g2_sram/lef/`. I wrote
that path down honestly and then reasoned as if it were ours -- and this
competition targets **sg13cmos5l**, a different library (our own netlist's cells
are `sg13cmos5l_*`, not `sg13g2_*`). A macro that exists for SG13G2 does not
automatically exist for, or route in, CMOS5L.

⭐ THE ORIGIN RULE IS WHAT CAUGHT THIS. The path was recorded, so the question
"which PDK tree?" was askable. Had the number been quoted as "26,138 um^2" with
no provenance, nothing would have exposed it.

WHAT IS NOW ESTABLISHED, AND FROM WHERE:

  (1) `IHP-Open-PDK` has exactly ONE PDK directory, `ihp-sg13g2`. There is no
      sg13cmos5l tree in it. So the LEF is definitively SG13G2's.
      SOURCE: the repository's own top-level listing.

  (2) SG13CMOS5L is documented as the same process MINUS the HBTs and MINUS
      Metal5 and TopMetal2 -- i.e. a 5-metal CMOS-only variant, Metal1..Metal4
      plus TopMetal1.
      SOURCE: secondary (project/tooling documentation summaries), NOT a
      primary IHP datasheet. Labelled accordingly.

  (3) ⭐ THE MACRO'S TOP ROUTING LAYER IS METAL4, which is BELOW both removed
      layers. So the macro does not use what CMOS5L lacks, and its GDS/geometry
      has no reason to differ.
      SOURCE: the LEF's own OBS section, read directly.

  (4) ⭐⭐ AND TINY TAPEOUT'S OWN TOOLING SUPPORTS SRAM MACROS IN CMOS5L.
      `TinyTapeout/tt-support-tools` PR #187, MERGED into the branch
      `TinyTapeout:ihp-sg13cmos5l`, adds the `SRAM.drawing` and `DigiBnd.drawing`
      marker layers to the **SG13CMOS5L** valid-layer list, because "the
      SG13CMOS5L DRC deck" uses them and "without these layers, the macro is
      either rejected by the layer check or incorrectly checked under non-SRAM
      DRC rules". It states: "Tested with RM_IHPSG13_1P_1024x8_c2_bm_bist; full
      Tiny Tapeout precheck passes."
      SOURCE: TinyTapeout's repository -- first-party to the competition's own
      flow, not a competitor's claim. ⭐ And the change is LAYER-based, not
      macro-based, so it admits the whole RM_IHPSG13_1P_* family rather than one
      part number.

  => PRECHECK, which I had named as the risk that "kills the approach regardless
     of the area argument", IS ANSWERED. The remaining risks are PLACEMENT and
     POWER, not admissibility.

⛔ WHAT IS STILL NOT VERIFIED, AND IS THE GATE BEFORE `MEM_TYPE=SRAM` LOCKS:
  a hardening run with the macro actually INSTANTIATED in the CMOS5L template --
  DRC and LVS with macro placement, and the PDN reaching its Metal4-only power
  pins. ⚠ That last one is a NAMED, OBSERVED failure mode in public issue titles
  for this macro family ("PDN cannot reach the SRAM macro's Metal4-only power
  pins -- gds blocked at GeneratePDN"), which I have NOT reproduced. It is the
  single most likely way this falls over.
  ⭐ One hypothesis worth testing first, because it would be good news: in
  CMOS5L there IS no Metal5, so the PDN must already live on Metal4/TopMetal1 --
  adjacent to the macro's pins rather than two layers above them. The bridging
  problem may be SG13G2-specific. Hypothesis, not a finding.

⛔ IF THE HARDEN FAILS, THE FALLBACK IS NOT A DEGRADATION: the flop store becomes
the SHIPPED design, and F1's encoding work is exactly what makes 64 bytes enough
(one transaction per protocol in 62 of 64). SRAM then survives only as a
scaling-tier option.

⭐ ORIGIN OF EVERY NUMBER BELOW (standing rule: an unsourced estimate is
unverified, including our own):
  * macro names        -- read from the PDK tree, IHP-Open-PDK
                          ihp-sg13g2/libs.ref/sg13g2_sram/gds (30 macros)
                          ⛔ SG13G2's tree -- see the correction above
  * macro geometry     -- the `SIZE` line of each macro's LEF in
                          ihp-sg13g2/libs.ref/sg13g2_sram/lef, fetched directly
                          ⛔ SG13G2's tree -- see the correction above
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
    print("    1. ⛔ THE LIKELIEST WAY THIS FALLS OVER: Metal4-only POWER PINS.")
    print("       The LEF's top routing layer is Metal4 and its VDD/VSS pins are")
    print("       Metal4-only. ⚠ 'PDN cannot reach the SRAM macro's Metal4-only")
    print("       power pins -- blocked at GeneratePDN' is a NAMED, OBSERVED")
    print("       failure for this macro family in public issue titles, which I")
    print("       have NOT reproduced. Treated as the primary risk, not a fact.")
    print("       ⭐ AND ONE HYPOTHESIS WORTH TESTING FIRST, because it would be")
    print("       good news: CMOS5L HAS NO METAL5. So its PDN must already live")
    print("       on Metal4/TopMetal1 -- ADJACENT to the macro's pins rather than")
    print("       two layers above them. The reports are against SG13G2, where")
    print("       Metal5 sits in between. The problem may not transfer.")
    print("       ⛔ Hypothesis, not a finding. It is the first thing the harden")
    print("       should answer because it is cheap to check and decides the")
    print("       whole approach.")
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
    print("    4. PRECHECK -- ✅ RESOLVED, and not by us. TinyTapeout's own")
    print("       tt-support-tools PR #187 is MERGED into the ihp-sg13cmos5l")
    print("       branch, adding SRAM.drawing + DigiBnd.drawing to the")
    print("       SG13CMOS5L valid-layer list, 'Tested with")
    print("       RM_IHPSG13_1P_1024x8_c2_bm_bist; full Tiny Tapeout precheck")
    print("       passes.' ⭐ It is LAYER-based, not macro-based, so it admits")
    print("       the whole RM_IHPSG13_1P_* family. First-party to the")
    print("       competition's flow -- not a competitor's claim.")
    print("    ⛔ 5. PROVENANCE OF THE GEOMETRY. The LEF above is from the")
    print("       **SG13G2** tree; IHP-Open-PDK has no sg13cmos5l directory at")
    print("       all. CMOS5L is documented as the same process minus the HBTs")
    print("       and minus Metal5/TopMetal2, and this macro tops out at Metal4")
    print("       -- BELOW both removed layers -- so its geometry has no reason")
    print("       to differ. ⚠ Strong inference, NOT verification. The harden is")
    print("       what settles it.")

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
    print("  ⛔ BEFORE Part 1 LOCKS MEM_TYPE=SRAM, the gate is a HARDENING RUN")
    print("     with the macro INSTANTIATED in the CMOS5L template: DRC + LVS")
    print("     with macro placement, and a PDN that reaches its Metal4-only")
    print("     power pins. Precheck is already answered (risk 4); placement and")
    print("     power are not. Those are build steps, not estimates.")
    print("  ⭐ AND IF IT FAILS THAT IS NOT A DEGRADATION: the flop store becomes")
    print("     the SHIPPED design, because F1's encoding already fits one")
    print("     transaction per protocol into 62 of 64 bytes. SRAM would survive")
    print("     only as a scaling-tier option. The decision is therefore")
    print("     reversible in one direction and we are not betting Part 1 on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
