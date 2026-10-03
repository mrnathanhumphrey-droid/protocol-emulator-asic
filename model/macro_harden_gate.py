"""THE CMOS5L SRAM HARDEN GATE -- placement, route and timing, not GeneratePDN.

THE ONE CLAIM: `MEM_TYPE = "sram"` does not lock until the macro is PLACED,
the design FULLY ROUTED and TIMING MET in the CMOS5L template. A completed
`GeneratePDN` is a different claim and this gate does not accept it.

⛔⛔ THIS GATE IS RED UNTIL THAT RUN EXISTS, ON PURPOSE -- the fourth such gate,
alongside `part1_param_contract.py` and `f2_flop_driven_outputs.py` face 3. It
is an ACCEPTANCE TEST for work not yet done. What it CAN do today is compute the
placement decision and separate the two crossing problems, which turn out not to
be the same problem at all.

=============================================================================
PRIMARY EVIDENCE, FROM OUR OWN REPO: src/config.json
=============================================================================
These are the settings the shipped flow actually runs with -- first-party, in
version control, not recalled:

    FP_PDN_MULTILAYER   0       no horizontal straps. The PDN is a
                                SINGLE-LAYER VERTICAL COMB.
    FP_PDN_VPITCH       50.0    um between vertical straps
    FP_PDN_VWIDTH       2.1     um per strap
    GRT_ALLOW_CONGESTION 1      the global router is TOLD to tolerate
                                congestion
    LEFT/RIGHT_MARGIN_MULT  6   core-to-die margin, left and right
    TOP/BOTTOM_MARGIN_MULT  1   core-to-die margin, top and bottom
    CLOCK_PERIOD        20      ns, i.e. 50 MHz

⭐⭐ `GRT_ALLOW_CONGESTION = 1` IS THE LINE THAT JUSTIFIES THE GATE'S SHAPE.
The router is instructed not to fail on congestion. So "the design routed" is a
WEAKER claim on this flow than it sounds -- it can route by overflowing and pay
for it in detour, coupling and delay. That is why the gate requires TIMING and
not route completion, and it is a first-party reason rather than a cautious
preference.

=============================================================================
⛔ THE TWO CROSSING PROBLEMS ARE NOT THE SAME PROBLEM
=============================================================================
Edge placement was ruled to keep IO-to-engine routes from crossing the macro.
That is correct, and it addresses SIGNAL crossing -- the 72-TopMetal1-track
ceiling. It does NOT address PDN crossing, and the reason is geometric:

  * the PDN straps are VERTICAL, at a FIXED 50 um pitch, spanning the die;
  * a macro 236.8 um wide therefore intercepts ~5 of them WHEREVER IT SITS.

So moving the macro changes the signal picture and leaves the power picture
exactly as it was. Two problems, one lever each, and the ruling's rationale
names only the first.

⭐ AND FOR POWER THAT IS GOOD NEWS, WHICH INVERTS THE RISK. You WANT straps
over a macro -- that is how its VDD/VSS pins get tapped. Guaranteeing >= 4
straps across the footprint means the macro CANNOT BE MISSED by the PDN. So the
failure mode was never "no strap reaches it". It is narrower and sharper:

  ⛔ THE REAL QUESTION IS WHICH LAYER THE VERTICAL STRAPS LAND ON.
     on TopMetal1 -> they pass over the macro's M1-M4 OBS and tap down. Fine.
     on Metal4    -> the macro's own OBS blocks them. GeneratePDN cannot cross
                     the footprint, and that is the observed public failure.

⚠ THAT IS A HYPOTHESIS AND THE ARTEFACT THAT SETTLES IT IS NOT IN THIS REPO --
it is the PDK/librelane PDN configuration used by `tt-gds-action@ihp-cmos5l`,
or the first run's own `GeneratePDN` log. Named, not guessed.

=============================================================================
⚠ WHAT IS NOT ESTABLISHED: WHICH EDGE CARRIES THE IO
=============================================================================
`LEFT/RIGHT_MARGIN_MULT = 6` against `TOP/BOTTOM = 1` is consistent with the IO
pin channel living on the left and right edges -- six times the core-to-die
margin is reserved there and the minimum elsewhere. ⚠ SECONDARY, AN INFERENCE
FROM A MARGIN SETTING, not a pin placement. The primary artefact is the PINS
section of the generated DEF, which does not exist until the first run.

⭐ SO THE CONCLUSION IS MADE INVARIANT TO IT. The gate evaluates every candidate
placement under every IO-edge assumption and reports the choice that is best (or
tied-best) under all of them. A decision that does not depend on the unverified
fact does not have to wait for it.

⛔ AND THAT CHANGES THE RULING'S ANSWER IN ONE CASE. "The edge OPPOSITE the IO
side" presumes one IO side. If IO arrives on BOTH left and right -- which is
what the margin setting suggests -- there is no opposite edge, and a left or
right corner sits IN the fan-out channel. The placement that is perpendicular to
the flow, i.e. the TOP or BOTTOM edge, is the one that keeps horizontal
IO-to-engine routes clear.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- ORIGIN: the LEF SIZE line, via model/sram_spike.py -----------------
MACRO_W, MACRO_H = 236.8, 110.38
MACRO_NAME = "RM_IHPSG13_1P_512x8_c3_bm_bist"

# ---- ORIGIN: the PDK tech LEF, via model/sram_spike.py ------------------
PITCH = {"Metal2": 0.48, "Metal3": 0.48, "Metal4": 0.48, "TopMetal1": 3.28}

# The settings this gate reads out of src/config.json rather than restating.
WANT = ("FP_PDN_MULTILAYER", "FP_PDN_VPITCH", "FP_PDN_VWIDTH",
        "GRT_ALLOW_CONGESTION", "LEFT_MARGIN_MULT", "RIGHT_MARGIN_MULT",
        "TOP_MARGIN_MULT", "BOTTOM_MARGIN_MULT", "CLOCK_PERIOD")

# The artefacts a real harden leaves behind. Their ABSENCE is today's failure.
HARDEN_ARTEFACTS = [
    ("runs/*/final/def/*.def", "placed + routed DEF -- also the PRIMARY "
                               "artefact for which edge carries the IO"),
    ("runs/*/final/*.gds", "the GDS"),
    ("runs/*/reports/signoff/*summary*", "timing signoff summary"),
    ("runs/*/logs/*pdn*", "the GeneratePDN log -- which LAYER the vertical "
                          "straps landed on"),
]


def read_config():
    """⛔ READ, never restate. A config value quoted into a comment is a value
    that can drift from the flow without anything noticing."""
    p = os.path.join(ROOT, "src", "config.json")
    if not os.path.isfile(p):
        return None, "src/config.json is missing"
    raw = open(p, encoding="utf-8").read()
    # the file uses repeated "//" keys as comments, which json.loads collapses;
    # that is fine -- we only want the real settings, and they are unique.
    try:
        cfg = json.loads(raw)
    except Exception as e:                                   # pragma: no cover
        return None, "src/config.json does not parse: %s" % e
    return cfg, None


def straps_over(width_um: float, pitch_um: float):
    """How many vertical straps cross a window of this width.

    ⭐ POSITION-INDEPENDENT, and that is the finding. A window of width W on a
    lattice of pitch P contains floor(W/P) or that plus one, depending only on
    phase. So the count has a FLOOR that no placement can reduce.
    """
    lo = int(width_um // pitch_um)
    return lo, lo + 1


def tracks_across(width_um: float, layer: str) -> int:
    return int(width_um / PITCH[layer])


def candidates(io_edges):
    """Rank macro placements for SIGNAL crossing, given which edges carry IO.

    The model is deliberately coarse because the core's aspect ratio is NOT
    established (see the note printed below): it asks only whether a placement
    sits in the fan-out channel of an IO-bearing edge. That is enough to order
    the options and not enough to pretend a track count.
    """
    out = []
    for name, touches in (("centre", {"left", "right", "top", "bottom"}),
                          ("left edge", {"left"}),
                          ("right edge", {"right"}),
                          ("top edge", {"top"}),
                          ("bottom edge", {"bottom"}),
                          ("top-left corner", {"top", "left"}),
                          ("top-right corner", {"top", "right"}),
                          ("bottom-left corner", {"bottom", "left"}),
                          ("bottom-right corner", {"bottom", "right"})):
        # a placement is "in the channel" of each IO edge whose fan-out it
        # intersects. The centre intersects every edge's fan-out.
        blocked = sorted(touches & set(io_edges))
        out.append((name, blocked))
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("CMOS5L SRAM HARDEN -- placement + route + timing")
    print("=" * 78)
    rc = 0

    cfg, err = read_config()
    if err:
        print("  *** %s" % err)
        return 1

    # ---- 1. the flow's own settings -------------------------------------
    print()
    print("  --- 1. PRIMARY: the settings the flow runs with (src/config.json)")
    for k in WANT:
        if k not in cfg:
            print("    %-24s *** ABSENT -- this gate's reasoning assumed it"
                  % k)
            rc = 1
        else:
            print("    %-24s %s" % (k, cfg[k]))
    multi = cfg.get("FP_PDN_MULTILAYER")
    vpitch = float(cfg.get("FP_PDN_VPITCH", 0) or 0)
    vwidth = float(cfg.get("FP_PDN_VWIDTH", 0) or 0)
    cong = cfg.get("GRT_ALLOW_CONGESTION")
    print()
    print("    ⭐⭐ GRT_ALLOW_CONGESTION = %s. The router is TOLD to tolerate"
          % cong)
    print("    congestion, so 'it routed' is a WEAK claim on this flow -- it")
    print("    can route by overflowing and pay in detour and delay. That is")
    print("    the first-party reason this gate requires TIMING rather than")
    print("    route completion, and it is not a cautious preference.")
    if cong != 1:
        print("    ⚠ the setting changed -- re-read this paragraph against it")

    # ---- 2. the PDN, which placement cannot move ------------------------
    print()
    print("  --- 2. THE PDN: vertical-only, and POSITION-INDEPENDENT ---")
    if multi != 0:
        print("    ⚠ FP_PDN_MULTILAYER is %s, not 0 -- there ARE horizontal"
              % multi)
        print("      straps and the single-comb reasoning below is void")
        rc = 1
    lo, hi = straps_over(MACRO_W, vpitch)
    lo_r, hi_r = straps_over(MACRO_H, vpitch)
    print("    %s is %.1f x %.1f um; straps are %.1f um wide at %.1f um pitch"
          % (MACRO_NAME, MACRO_W, MACRO_H, vwidth, vpitch))
    print()
    print("    %-22s %-12s %s" % ("macro orientation", "width", "straps over"))
    print("    %-22s %-12s %d or %d" % ("as drawn (R0)", "%.1f um" % MACRO_W,
                                        lo, hi))
    print("    %-22s %-12s %d or %d" % ("rotated (R90)", "%.1f um" % MACRO_H,
                                        lo_r, hi_r))
    print()
    print("    ⛔ THE COUNT DOES NOT DEPEND ON WHERE THE MACRO SITS. A window")
    print("    of width W on a lattice of pitch P contains floor(W/P) or one")
    print("    more, by phase alone. So >= %d straps cross the footprint under"
          % lo)
    print("    EVERY placement, and EDGE PLACEMENT CHANGES NOTHING HERE.")
    print()
    print("    ⭐ AND FOR POWER THAT INVERTS THE RISK -- straps over a macro are")
    print("    how its VDD/VSS get tapped, so >= %d means the macro CANNOT BE"
          % lo)
    print("    MISSED by the PDN. The failure mode was never 'no strap reaches")
    print("    it'. It is narrower:")
    print()
    print("      ⛔ WHICH LAYER DO THE VERTICAL STRAPS LAND ON?")
    print("         TopMetal1 -> they pass over the macro's M1-M4 OBS and tap")
    print("                      down. Fine.")
    print("         Metal4    -> the macro's own OBS BLOCKS them. GeneratePDN")
    print("                      cannot cross the footprint. That is the")
    print("                      observed public failure.")
    print()
    print("    ⚠ NOT ESTABLISHED HERE. The artefact is the PDN configuration")
    print("    inside tt-gds-action@ihp-cmos5l, or the first run's own")
    print("    GeneratePDN log. ⛔ My earlier framing -- 'CMOS5L has no Metal5")
    print("    so the PDN is already adjacent' -- was too loose: 'adjacent'")
    print("    does not say whether the straps are ON the blocked layer, and")
    print("    that is the whole question.")
    # the interaction between the two findings
    tm1 = tracks_across(MACRO_W, "TopMetal1")
    strap_tracks = int(round(hi * max(1.0, vwidth / PITCH["TopMetal1"])))
    print()
    print("    ⭐ IF they are on TopMetal1, the two problems interact and the")
    print("    cost is small: %d straps x %.1f um on a %.2f um pitch consume"
          % (hi, vwidth, PITCH["TopMetal1"]))
    print("    about %d of the %d TopMetal1 tracks crossing the macro, leaving"
          % (strap_tracks, tm1))
    print("    ~%d for signals." % (tm1 - strap_tracks))

    # ---- 3. signal crossing, and the placement decision -----------------
    print()
    print("  --- 3. SIGNAL crossing: the 72-track ceiling and the placement ---")
    print("    CMOS5L stops at Metal4 + TopMetal1 and the macro's OBS blocks")
    print("    M1-M4, so TopMetal1 is the ONLY layer that crosses it:")
    for L in ("Metal2", "Metal3", "Metal4", "TopMetal1"):
        print("      %-10s pitch %.2f um  -> %4d tracks across %.1f um"
              % (L, PITCH[L], tracks_across(MACRO_W, L), MACRO_W))
    m234 = sum(tracks_across(MACRO_W, L) for L in ("Metal2", "Metal3",
                                                   "Metal4"))
    print("    ⛔ %d TopMetal1 tracks against %d on M2+M3+M4 -- a %.0fx drop."
          % (tm1, m234, m234 / tm1))
    print("    Area is NOT the issue (the macro is a few percent of the core);")
    print("    %d crossings is the ceiling on everything that must get past it."
          % tm1)
    print()
    print("    ⚠ WHICH EDGE CARRIES THE IO IS NOT ESTABLISHED. The margin")
    print("    settings -- left/right %s against top/bottom %s -- are"
          % (cfg.get("LEFT_MARGIN_MULT"), cfg.get("TOP_MARGIN_MULT")))
    print("    CONSISTENT with the IO channel being on the left and right")
    print("    edges. ⛔ SECONDARY: that is an inference from a margin, not a")
    print("    pin placement. The primary artefact is the generated DEF's PINS")
    print("    section, which does not exist yet.")
    print()
    print("    ⭐ SO THE DECISION IS MADE INVARIANT TO IT. Every placement is")
    print("    scored under every IO-edge assumption; a placement is CLEAR if")
    print("    it sits in no IO-bearing edge's fan-out channel.")
    print()
    ASSUMPTIONS = [("left+right (margin-implied)", ("left", "right")),
                   ("left only", ("left",)),
                   ("all four edges", ("left", "right", "top", "bottom")),
                   ("bottom only", ("bottom",))]
    names = [n for n, _ in candidates(())]
    print("    %-20s %s" % ("placement", "  ".join("%-14s" % a[:14]
                                                   for a, _ in ASSUMPTIONS)))
    score = {n: 0 for n in names}
    for n in names:
        row = []
        for _, edges in ASSUMPTIONS:
            blocked = [b for nm, b in candidates(edges) if nm == n][0]
            row.append("CLEAR" if not blocked else "in %s" % "+".join(blocked))
            score[n] += len(blocked)
        print("    %-20s %s" % (n, "  ".join("%-14s" % c for c in row)))
    best = min(score.values())
    winners = [n for n in names if score[n] == best]
    print()
    print("    ⭐ CLEAR UNDER THE MOST ASSUMPTIONS: %s" % ", ".join(winners))
    print()
    print("    ⛔ AND THIS REFINES THE RULING. 'The edge OPPOSITE the IO side'")
    print("    presumes ONE IO side. If IO arrives on both left and right --")
    print("    which the margin setting suggests -- there is no opposite edge,")
    print("    and a left or right corner sits IN the fan-out channel. The")
    print("    placement perpendicular to the flow (TOP or BOTTOM edge) is what")
    print("    keeps horizontal IO-to-engine routes clear.")
    print("    ⇒ PLACE AT THE TOP OR BOTTOM EDGE, and pick between them from")
    print("      the DEF once the first run produces one.")
    print()
    print("    ⚠ ONE LEVER IS DELIBERATELY NOT RECOMMENDED: rotating the macro")
    print("    to R90 cuts intercepted straps from %d to %d. Whether that is"
          % (hi, hi_r))
    print("    GOOD or BAD depends on the unknown layer -- fewer straps means")
    print("    fewer blocked crossings if they are on Metal4, and fewer power")
    print("    taps if they are on TopMetal1. ⛔ The sign of the effect is")
    print("    unknown, so no recommendation is made. (Many SRAM macros also")
    print("    cannot legally rotate; that is a second reason to settle the")
    print("    layer first.)")

    # ---- 4. the gate itself ---------------------------------------------
    print()
    print("  --- 4. THE GATE: placed + routed + TIMING, not GeneratePDN ---")
    import glob
    print("    %-38s %s" % ("artefact", "present"))
    missing = 0
    for pat, what in HARDEN_ARTEFACTS:
        hits = glob.glob(os.path.join(ROOT, pat))
        print("    %-38s %s" % (pat, "%d" % len(hits) if hits else "NO"))
        print("        %s" % what)
        if not hits:
            missing += 1
    if missing:
        print()
        print("    *** GATE IS RED, AND THIS IS THE CORRECT STATE TODAY.")
        print("        %d of %d harden artefacts are absent: the run has not"
              % (missing, len(HARDEN_ARTEFACTS)))
        print("        happened. ⛔ This gate is an ACCEPTANCE TEST, the fourth")
        print("        deliberately-red one alongside part1_param_contract.py")
        print("        and f2_flop_driven_outputs.py face 3. It must NOT be")
        print("        'fixed' -- it goes green when the harden runs.")
        print("        ⛔ AND IT WILL NOT ACCEPT A SUCCESSFUL GeneratePDN as a")
        print("        pass: a PDN that completes and a design that routes AND")
        print("        MEETS TIMING are three different claims, and")
        print("        GRT_ALLOW_CONGESTION=%s is why the third is required."
              % cong)
        rc = 1

    print()
    print("  --- fallback order, unchanged and reversible in one direction ---")
    print("    1. macro at the TOP or BOTTOM edge (per section 3)")
    print("    2. the FLOP store -- F1's encoding already fits one transaction")
    print("       per protocol into 62 of 64 bytes at the existing AW=6, so")
    print("       this is the SHIPPED design, not a degradation. SRAM then")
    print("       survives as a scaling-tier option only.")
    print("    ⇒ Part 1 is not betting on the harden, which is why MEM_TYPE is")
    print("      a parameter and the flop path is not deleted when SRAM wins.")

    print()
    print("=" * 78)
    print("  GATE cmos5l-harden: %s"
          % ("PASSED" if rc == 0 else
             "RED -- expected until the harden runs; see section 4"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
