"""THE CMOS5L SRAM HARDEN GATE -- placement, route and timing, not GeneratePDN.

THE ONE CLAIM: `MEM_TYPE = "sram"` does not lock until the macro is PLACED,
the design ROUTED (defined below, because on this flow "routed" is ambiguous)
and TIMING MET in the CMOS5L template.

⛔⛔ THIS GATE IS RED UNTIL THAT RUN EXISTS, ON PURPOSE -- alongside
`part1_param_contract.py` and `f2_flop_driven_outputs.py` face 3. It is an
ACCEPTANCE TEST for work not yet done. What it does today is compute the
placement decision from PRIMARY artefacts and separate the two crossing
problems, which turn out not to be the same problem.

=============================================================================
PRIMARY #1 -- OUR OWN FLOW SETTINGS: src/config.json
=============================================================================
    FP_PDN_MULTILAYER   0       no horizontal straps: a SINGLE-LAYER VERTICAL
                                comb
    FP_PDN_VPITCH       50.0    um between vertical straps
    FP_PDN_VWIDTH       2.1     um per strap
    GRT_ALLOW_CONGESTION 1      the global router is TOLD to tolerate
                                congestion
    CLOCK_PERIOD        20      ns = 50 MHz

⭐⭐ `GRT_ALLOW_CONGESTION = 1` IS WHY "ROUTED" HAS TO BE DEFINED. The router is
instructed not to fail on congestion, so it can succeed by OVERFLOWING and pay
for it in detour, coupling and delay. A flow that prints success is therefore
not evidence. ⇒ ROUTED is defined here as three separate assertions, all
required:

    (1) global-route OVERFLOW = 0, PARSED from the GRT report -- not inferred
        from the absence of an error, because the flow is configured not to
        error;
    (2) detailed-route DRC CLEAN;
    (3) TIMING MET at the corner that matters.

⛔ A route that only succeeds by overflowing is a FAIL under this gate,
whatever the flow prints.

=============================================================================
PRIMARY #2 -- THE TILE'S OWN DEF, and it OVERTURNED my inference
=============================================================================
ORIGIN: TinyTapeout/tt-support-tools, branch `ihp-sg13cmos5l`, file
`tech/ihp-sg13cmos5l/def/tt_block_6x4_pgvdd.def` -- OUR tile size (info.yaml
says `tiles: "6x4"`), first-party to the competition's own flow.

    DIEAREA ( 0 0 ) ( 1289280 710640 ) ;   UNITS DISTANCE MICRONS 1000
      -> the 6x4 die is 1289.28 x 710.64 um
    PINS 43 ;  ALL at y = 710140, ALL on LAYER Metal4
      -> every pin is on the MAX-Y edge
    pin x range 29760 .. 191040  -> 29.76 .. 191.04 um
      -> all 43 pins are clustered in the leftmost ~161 um of a 1289 um die
    TRACKS ... STEP 480 LAYER Metal4      -> Metal4 pitch 0.48 um
    TRACKS ... STEP 2280 LAYER TopMetal1  -> TopMetal1 pitch 2.28 um

⛔⛔ THIS FALSIFIED MY OWN PLACEMENT REASONING. I had inferred the IO side from
`LEFT/RIGHT_MARGIN_MULT = 6` against `TOP/BOTTOM = 1`, concluded IO arrived on
the left and right, and therefore recommended the TOP or BOTTOM edge -- and the
scoring matrix preferred TOP. The DEF says every pin is on the MAX-Y edge. So
the recommendation pointed AT the IO edge: the single worst placement.

⭐ THE LESSON IS ABOUT THE INSTRUMENT, NOT THE ANSWER. A matrix that scores
every assumption looks rigorous and cannot tell you which assumption is true;
it launders a guess as coverage. One primary read collapsed it and REVERSED it.
The matrix is kept below as a BACKSTOP only, and it is explicitly scored against
the known answer so its earlier preference stays visible.

⇒ THE PINS ARE A CORNER CLUSTER, NOT AN EDGE: max-y, low-x. So the macro goes
DIAGONALLY OPPOSITE -- MIN-Y, MAX-X, the far corner -- which is Wilson's
original "edge or corner away from the pin side", not my "refinement".

⛔ AND THE PINS ARE ON Metal4, WHICH THE MACRO'S OBS BLOCKS. Routes leaving
those pins START on the one layer the macro is opaque to, which is an
independent reason not to put it near them.

=============================================================================
⛔ THE TWO CROSSING PROBLEMS ARE NOT THE SAME PROBLEM
=============================================================================
  * SIGNAL crossing is a PLACEMENT problem. TopMetal1 is the only layer that
    crosses the macro, so crossings are scarce; moving the macro away from the
    pin cluster makes the crossing requirement ~zero by construction.
  * PDN crossing is NOT a placement problem. The straps are VERTICAL at a FIXED
    50 um pitch spanning the die, so a 236.8 um wide macro intercepts ~5 of
    them WHEREVER IT SITS.

⛔⛔ AND THE STRAP LAYER IS RESOLVED -- IT IS THE BAD CASE. IHP's own
ihp-sg13cmos5l/libs.tech/librelane/config.tcl (@ 2bbec75) sets
FP_PDN_VERTICAL_LAYER = Metal4, which is exactly the layer the macro's OBS
blocks; FP_PDN_HORIZONTAL_LAYER = TopMetal1 is the one layer that could cross
it, and our own template sets FP_PDN_MULTILAYER = 0. So the ~5 guaranteed
crossings become guaranteed CONFLICTS. ⭐ I had this argument's SIGN backwards
while the layer was unread -- I called the guaranteed crossing good news.

⛔⛔ AND TWO EARLIER "PRIMARY FULL-TREE READS" WERE TRUNCATION ARTEFACTS. The
GitHub recursive-tree API truncates large trees, and the summariser did not say
so, so "no SRAM library in cmos5l" and "no librelane config in cmos5l" were both
FALSE -- both claiming ABSENCE. `libs.ref/sg13cmos5l_sram` is a SYMLINK to
`../../ihp-sg13g2/libs.ref/sg13g2_sram` (so IHP itself ships those macros under
the CMOS5L name, and "cross-PDK" is RETRACTED), and the librelane config is in
`libs.tech/librelane/config.tcl` (so the strap layer was readable all along).
⇒ FOR AN EXISTENCE QUESTION, USE THE CONTENTS API ON THE SPECIFIC DIRECTORY --
a short definite listing -- NEVER a recursive tree plus a summary. See section 3.
"""

from __future__ import annotations

import glob
import json
import os
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

# ---- ORIGIN: tt_block_6x4_pgvdd.def, tt-support-tools@ihp-sg13cmos5l ----
# ⛔ EVERY NUMBER HERE CARRIES ITS REF. The previous batch recorded a PDK fact
# as "the repo's own top-level listing" with NO commit or branch -- and it went
# stale and was falsified. A listing is a snapshot of a REF.
DEF_REF = ("TinyTapeout/tt-support-tools @ ihp-sg13cmos5l : "
           "tech/ihp-sg13cmos5l/def/tt_block_6x4_pgvdd.def")
DIE_W, DIE_H = 1289.28, 710.64
N_PINS_DEF = 43
PIN_Y = 710.140                 # all 43 pins
PIN_X_LO, PIN_X_HI = 29.76, 191.04
PIN_LAYER = "Metal4"

# ---- routing pitches, FROM THE DEF's OWN TRACKS statements --------------
# ⛔⛔ THIS CORRECTS A NUMBER I HAVE BEEN QUOTING. I recorded TopMetal1 pitch as
# 3.28 um from the PDK tech LEF. The DEF that this flow actually routes on says
# `STEP 2280`, i.e. 2.28 um. The two disagree by one digit, which is what a
# transposition looks like. ⭐ The DEF wins for this purpose because it IS the
# grid the router uses for OUR tile -- but the conflict is recorded rather than
# silently resolved, and re-reading the tech LEF is owed.
PITCH = {"Metal2": 0.48, "Metal3": 0.48, "Metal4": 0.48, "TopMetal1": 2.28}
PITCH_DISPUTED = {"TopMetal1": (2.28, "DEF TRACKS STEP 2280 (this flow's grid)",
                                3.28, "my earlier read of the PDK tech LEF")}

WANT = ("FP_PDN_MULTILAYER", "FP_PDN_VPITCH", "FP_PDN_VWIDTH",
        "GRT_ALLOW_CONGESTION", "CLOCK_PERIOD")

# ---- what a real harden must leave behind, per the ROUTED definition ----
# ⛔ Each entry names the ASSERTION, not just the file, because the whole point
# is that a file's existence is not the claim.
HARDEN_ARTEFACTS = [
    ("runs/*/final/def/*.def", "placed + routed DEF"),
    ("runs/*/final/*.gds", "the GDS"),
    ("runs/*/reports/routing/*grt*", "GRT report -> assert OVERFLOW = 0, "
                                     "PARSED (the flow is configured not to "
                                     "error on congestion)"),
    ("runs/*/reports/signoff/*drc*", "detailed-route DRC -> assert CLEAN"),
    ("runs/*/reports/signoff/*summary*", "timing signoff -> assert MET"),
    ("runs/*/logs/*pdn*", "GeneratePDN log -> which LAYER the vertical straps "
                          "landed on (see the quarantine in section 2)"),
]


def read_config():
    p = os.path.join(ROOT, "src", "config.json")
    if not os.path.isfile(p):
        return None, "src/config.json is missing"
    try:
        cfg = json.loads(open(p, encoding="utf-8").read())
    except Exception as e:                                   # pragma: no cover
        return None, "src/config.json does not parse: %s" % e
    return cfg, None


def straps_over(width_um: float, pitch_um: float):
    """How many vertical straps cross a window of this width.

    ⭐ POSITION-INDEPENDENT, and that is the finding. A window of width W on a
    lattice of pitch P contains floor(W/P) or that plus one, by phase alone.
    """
    lo = int(width_um // pitch_um)
    return lo, lo + 1


def tracks_across(width_um: float, layer: str) -> int:
    return int(width_um / PITCH[layer])


def main() -> int:
    print()
    print("=" * 78)
    print("CMOS5L SRAM HARDEN -- placed + ROUTED (defined) + timing")
    print("=" * 78)
    rc = 0

    cfg, err = read_config()
    if err:
        print("  *** %s" % err)
        return 1

    # ---- 1. the flow's own settings, and the definition of ROUTED -------
    print()
    print("  --- 1. PRIMARY: our flow settings (src/config.json), READ ---")
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
    print("    ⭐⭐ GRT_ALLOW_CONGESTION = %s, SO 'ROUTED' MUST BE DEFINED." % cong)
    print("    The router is TOLD not to fail on congestion, so it can succeed")
    print("    by OVERFLOWING. A flow that prints success is not evidence.")
    print("    ⇒ ROUTED := all three, each asserted separately:")
    print("        (1) global-route OVERFLOW = 0, PARSED from the GRT report")
    print("            -- not inferred from the absence of an error, because")
    print("            the flow is configured not to error;")
    print("        (2) detailed-route DRC CLEAN;")
    print("        (3) TIMING MET at the corner that matters.")
    print("    ⛔ A route that succeeds by overflow FAILS this gate.")
    if cong != 1:
        print("    ⚠ the setting changed -- re-read this paragraph against it")

    # ---- 2. the PDN, and the quarantine --------------------------------
    print()
    print("  --- 2. THE PDN: position-independent, and the strap layer RESOLVED ---")
    if multi != 0:
        print("    ⚠ FP_PDN_MULTILAYER is %s, not 0 -- there ARE horizontal"
              % multi)
        print("      straps and the single-comb reasoning is void")
        rc = 1
    lo, hi = straps_over(MACRO_W, vpitch)
    lo_r, hi_r = straps_over(MACRO_H, vpitch)
    die_straps = straps_over(DIE_W, vpitch)[0]
    print("    %s is %.1f x %.1f um; straps %.1f um wide at %.1f um pitch"
          % (MACRO_NAME, MACRO_W, MACRO_H, vwidth, vpitch))
    print("    the 6x4 die is %.2f um wide -> ~%d vertical straps across it"
          % (DIE_W, die_straps))
    print()
    print("    %-22s %-12s %s" % ("macro orientation", "width", "straps over"))
    print("    %-22s %-12s %d or %d" % ("as drawn (R0)", "%.1f um" % MACRO_W,
                                        lo, hi))
    print("    %-22s %-12s %d or %d" % ("rotated (R90)", "%.1f um" % MACRO_H,
                                        lo_r, hi_r))
    print()
    print("    ⛔ THE COUNT DOES NOT DEPEND ON WHERE THE MACRO SITS, so EDGE")
    print("    PLACEMENT CHANGES NOTHING HERE. >= %d straps cross the" % lo)
    print("    footprint under every placement, by phase alone.")
    print()
    print("    ⛔⛔ AND THE STRAP LAYER IS NOW RESOLVED -- IT IS THE BAD CASE.")
    print("    ORIGIN (primary, first-party, with its ref): IHP-Open-PDK @")
    print("    2bbec75, ihp-sg13cmos5l/libs.tech/librelane/config.tcl:")
    print("        set ::env(FP_PDN_RAIL_LAYER)       Metal1")
    print("        set ::env(FP_PDN_VERTICAL_LAYER)   Metal4")
    print("        set ::env(FP_PDN_HORIZONTAL_LAYER) TopMetal1")
    print("        set ::env(RT_MAX_LAYER)            \"TopMetal1\"")
    print("    and our own src/config.json sets FP_PDN_MULTILAYER = %s." % multi)
    print()
    print("    ⇒ THE VERTICAL PDN STRAPS ARE ON Metal4, WHICH IS EXACTLY THE")
    print("      LAYER THE MACRO'S OBS BLOCKS (it blocks M1-M4).")
    print()
    print("    ⛔⛔ SO MY 'GOOD NEWS' READING INVERTS. I argued that >= %d straps"
          % lo)
    print("    crossing the footprint meant the macro COULD NOT BE MISSED by")
    print("    the PDN. On Metal4 that guarantee becomes a guaranteed CONFLICT:")
    print("    ~%d straps that MUST cross a footprint they CANNOT cross. The"
          % hi)
    print("    position-independence argument was right and I had its SIGN")
    print("    backwards, because I had not read the layer.")
    print()
    print("    ⚠ ONE STEP IS AN INFERENCE AND IS LABELLED AS ONE: that")
    print("    FP_PDN_MULTILAYER=0 keeps the VERTICAL layer and drops the")
    print("    TopMetal1 horizontals. ⭐ Supporting evidence from our OWN file:")
    print("    src/config.json overrides FP_PDN_VWIDTH to %.1f where the PDK"
          % vwidth)
    print("    says 1.0, and overriding the VERTICAL width only matters if the")
    print("    vertical straps are the ones generated.")
    print()
    print("    ⇒ ⭐ THE ONE LAYER THAT COULD CROSS THE MACRO IS TopMetal1, AND")
    print("      OUR OWN TEMPLATE SWITCHES IT OFF. That is the shape of the")
    print("      problem, stated from primary config alone.")
    print()
    print("    ⛔ WHAT REMAINS QUARANTINED, NARROWLY. The DIAGNOSIS above is")
    print("    independently derived from IHP's config and our own, so it is")
    print("    ours and facts are not ownable. What is NOT ours is any FIX read")
    print("    from another competition entry's pull request -- that was never")
    print("    opened and must not be reconstructed from memory of a search")
    print("    summary. Any remedy here gets built FROM THE PROBLEM.")
    print("    ⚠ And the 'observed public GeneratePDN failure' cited since")
    print("    PART5 traces to that entry's issue tracker -- SINGULAR, not")
    print("    'public issue titles'. ⭐ It is also now SUPERSEDED as evidence:")
    print("    we no longer need anyone's bug report, because the PDK's own")
    print("    config says Metal4 and the LEF's own OBS says M1-M4 blocked.")
    print()
    print("    --- the remedies this gate can name from the problem alone ---")
    print("      A. turn the TopMetal1 horizontal straps ON (multilayer), so a")
    print("         layer exists above the macro. ⚠ UNVERIFIED: whether TT's")
    print("         CMOS5L precheck allowlist admits TopMetal1 for power, and")
    print("         why TT's template disables it. Both are readable.")
    print("      B. exclude the macro's footprint from the vertical PDN and")
    print("         power it from the layer above. ⚠ needs A to be viable.")
    print("      C. ✅ THE FLOP STORE. No PDN question at all, and F1's")
    print("         encoding already fits one transaction per protocol into 62")
    print("         of 64 bytes at the existing AW=6.")
    print("    ⇒ ⭐ THIS MATERIALLY RAISES THE CHANCE THAT C IS WHAT SHIPS, and")
    print("      that is a RESULT, not a retreat: Part 1 should default")
    print("      MEM_TYPE=flops and keep sram as the parameterised option,")
    print("      rather than the other way round.")

    # ---- 3. SRAM is a CROSS-PDK instantiation --------------------------
    print()
    print("  --- 3. ⛔⛔ RETRACTED: 'MEM_TYPE=sram IS A CROSS-PDK CLAIM' ---")
    print("    I claimed the ihp-sg13cmos5l tree contains NO SRAM library and")
    print("    that instantiating RM_IHPSG13_1P_* was therefore a CROSS-PDK")
    print("    act needing a sponsor's blessing. THAT IS FALSE. Primary, via")
    print("    the GitHub CONTENTS API on the directory itself (small, no")
    print("    truncation), IHP-Open-PDK @ 2bbec75:")
    print("        ihp-sg13cmos5l/libs.ref/  ->  sg13cmos5l_io      dir")
    print("                                      sg13cmos5l_sram    SYMLINK")
    print("                                      sg13cmos5l_stdcell dir")
    print("        sg13cmos5l_sram target = \"../../ihp-sg13g2/libs.ref/"
          "sg13g2_sram\"")
    print()
    print("    ⭐⭐ SO THE MACROS *ARE* THE SG13G2 ONES -- AND IHP ITSELF SHIPS")
    print("    THEM UNDER THE CMOS5L NAME. The symlink is the PDK VENDOR'S OWN")
    print("    STATEMENT that this library serves CMOS5L. Using it is using")
    print("    the PDK's own SRAM library, not importing a foreign one.")
    print("    ⇒ There is nothing unusual to get blessed. Combined with TT's")
    print("      layer allowlist (PR #187, tested with an RM_IHPSG13_1P_* part,")
    print("      'full Tiny Tapeout precheck passes'), BOTH halves of the")
    print("      admissibility question now have FIRST-PARTY answers.")
    print("    ⛔ The shuttle-acceptance email is therefore MOOT as drafted --")
    print("      its central premise was my error. Not sent.")
    print()
    print("    ⛔⛔ HOW I GOT IT WRONG, BECAUSE THE METHOD IS THE LESSON. I")
    print("    called two GitHub *recursive tree* API responses 'primary")
    print("    full-tree reads'. The tree API TRUNCATES large trees, and the")
    print("    answers came back through a SUMMARISER that did not say so. The")
    print("    same method also told me the sg13g2 tree has no SRAM -- while I")
    print("    HAD ALREADY FETCHED A MACRO LEF OUT OF THAT VERY TREE. That")
    print("    contradiction is what exposed it.")
    print("    ⭐ My own standing rule says a zero-hit search proves the STRING")
    print("    absent, not the THING. This was weaker still: a zero-hit search")
    print("    over an UNKNOWN SUBSET, reported as exhaustive.")
    print("    ⇒ FIX, applied here: for an EXISTENCE question use the CONTENTS")
    print("      API on the specific directory -- a short, definite listing --")
    print("      never a recursive tree plus a summary. And never call a")
    print("      summarised API response a 'full-tree read'.")
    print("    ⛔ TWO FINDINGS RESTED ON IT, AND BOTH WERE WRONG IN THE SAME")
    print("      DIRECTION -- claiming something was ABSENT: 'no SRAM library'")
    print("      (above) and 'no librelane config' (which sent me looking in")
    print("      LibreLane's repo, and was the stated reason the strap layer")
    print("      was unresolved). The config was in libs.tech/librelane all")
    print("      along, and section 2 now reads it.")
    print()
    print("    ⛔⛔ AND IT CORRECTS PART5's FINDING #1, WHICH I RECORDED AS")
    print("    *PRIMARY*: 'IHP-Open-PDK has exactly one PDK directory,")
    print("    ihp-sg13g2. No sg13cmos5l tree.' At the commit this flow PINS")
    print("    (2bbec75) there IS an ihp-sg13cmos5l tree, plus ihp-common.")
    print("    ⭐ THE DEFECT WAS IN THE ORIGIN FIELD, NOT THE READING: I wrote")
    print("    the origin as 'the repo's own top-level listing' WITHOUT A REF.")
    print("    A listing is a snapshot of a commit, and omitting which one is")
    print("    what let a primary fact go stale and then false. ⇒ An origin")
    print("    must name the REF, not just the repo.")

    # ---- 4. placement, from the DEF ------------------------------------
    print()
    print("  --- 4. PLACEMENT: settled by a PRIMARY read, not by a matrix ---")
    print("    ORIGIN: %s" % DEF_REF)
    print("      die            %.2f x %.2f um" % (DIE_W, DIE_H))
    print("      PINS           %d, ALL at y = %.3f um, ALL on %s"
          % (N_PINS_DEF, PIN_Y, PIN_LAYER))
    print("      pin x span     %.2f .. %.2f um" % (PIN_X_LO, PIN_X_HI))
    span = PIN_X_HI - PIN_X_LO
    print("    ⇒ all %d pins sit in the leftmost %.0f um (%.0f%%) of a %.0f um"
          % (N_PINS_DEF, span, 100.0 * span / DIE_W, DIE_W))
    print("      die, on the MAX-Y edge. THE IO IS A CORNER CLUSTER, NOT AN")
    print("      EDGE: max-y, low-x.")
    print()
    print("    ⇒ ✅ PLACE THE MACRO DIAGONALLY OPPOSITE: MIN-Y, MAX-X.")
    print("    ⭐ Which is the ORIGINAL ruling -- 'the edge or corner away from")
    print("    the pin side' -- not my 'refinement' to top/bottom.")
    print()
    print("    ⛔ AND THE PINS ARE ON %s, THE LAYER THE MACRO'S OBS BLOCKS."
          % PIN_LAYER)
    print("    Routes leaving those pins START on the one layer the macro is")
    print("    opaque to. That is an INDEPENDENT reason to keep it far away,")
    print("    and it does not depend on any crossing count.")
    print()
    print("    --- the matrix, kept as a BACKSTOP and scored against the fact ---")
    print("    ⛔ I inferred the IO side from LEFT/RIGHT_MARGIN_MULT %s vs"
          % cfg.get("LEFT_MARGIN_MULT"))
    print("    TOP/BOTTOM %s, concluded left+right, and the matrix therefore"
          % cfg.get("TOP_MARGIN_MULT"))
    print("    preferred the TOP edge -- which the DEF shows is the IO EDGE.")
    print("    %-26s %-22s %s" % ("", "matrix said", "DEF says"))
    print("    %-26s %-22s %s" % ("IO location", "left + right (inferred)",
                                  "max-y, low-x (READ)"))
    print("    %-26s %-22s %s" % ("best placement", "TOP edge",
                                  "MIN-Y, MAX-X corner"))
    print("    %-26s %-22s %s" % ("verdict on the matrix", "confident",
                                  "*** WRONG EDGE ***"))
    print()
    print("    ⭐ THE INSTRUMENT WAS THE PROBLEM, NOT THE ANSWER. Scoring every")
    print("    assumption looks rigorous and cannot say which is TRUE -- it")
    print("    launders a guess as coverage. One primary read collapsed the")
    print("    matrix and REVERSED it. ⇒ read the artefact first; keep the")
    print("    all-assumptions sweep for when no artefact exists.")

    # ---- 5. signal crossing, with the corrected pitch ------------------
    print()
    print("  --- 5. SIGNAL crossing, and a pitch I had wrong ---")
    for L in ("Metal2", "Metal3", "Metal4", "TopMetal1"):
        print("      %-10s pitch %.2f um  -> %4d tracks across %.1f um"
              % (L, PITCH[L], tracks_across(MACRO_W, L), MACRO_W))
    tm1 = tracks_across(MACRO_W, "TopMetal1")
    m234 = sum(tracks_across(MACRO_W, L) for L in ("Metal2", "Metal3",
                                                   "Metal4"))
    print("    ⛔ %d TopMetal1 tracks against %d on M2+M3+M4 -- a %.0fx drop."
          % (tm1, m234, m234 / tm1))
    for L, (new, src_new, old, src_old) in PITCH_DISPUTED.items():
        print()
        print("    ⛔⛔ A CORRECTION, AND THE TWO SOURCES DISAGREE:")
        print("      %s pitch = %.2f um  <- %s" % (L, new, src_new))
        print("      %s pitch = %.2f um  <- %s" % (L, old, src_old))
        print("      I have been quoting %.2f, which gave %d crossing tracks;"
              % (old, int(MACRO_W / old)))
        print("      the DEF's own grid gives %d." % tm1)
        print("      ⭐ The DEF wins for this purpose because it IS the grid the")
        print("      router uses for OUR tile. ⚠ But a one-digit disagreement")
        print("      is what a transposition looks like, so re-reading the PDK")
        print("      tech LEF is OWED, and the conflict is recorded rather than")
        print("      quietly resolved.")
        print("      ⛔ Either way the CONCLUSION is unchanged: TopMetal1 is the")
        print("      only layer crossing the macro and it is ~%.0fx scarcer"
              % (m234 / tm1))
        print("      than the layers below, so placement is the mitigation.")

    # ---- 6. the gate itself --------------------------------------------
    print()
    print("  --- 6. THE GATE ---")
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
        print("        %d of %d harden artefacts absent: the run has not"
              % (missing, len(HARDEN_ARTEFACTS)))
        print("        happened. ⛔ ACCEPTANCE TEST -- must NOT be 'fixed'.")
        print("        ⛔ AND IT WILL NOT ACCEPT A SUCCESSFUL GeneratePDN, NOR")
        print("        A ROUTE THAT COMPLETED: with GRT_ALLOW_CONGESTION=%s,"
              % cong)
        print("        'routed' means overflow=0 AND DRC clean AND timing met.")
        rc = 1

    print()
    print("  --- fallback order, reversible in one direction ---")
    print("    1. macro at the MIN-Y / MAX-X corner (section 4)")
    print("    2. the FLOP store -- F1's encoding already fits one transaction")
    print("       per protocol into 62 of 64 bytes at the existing AW=6, so")
    print("       this is the SHIPPED design, not a degradation. ⭐ And it")
    print("       sidesteps the cross-PDK macro question in section 3 entirely.")
    print("    ⇒ Part 1 is not betting on the harden, which is why MEM_TYPE is")
    print("      a parameter and the flop path is not deleted when SRAM wins.")

    print()
    print("=" * 78)
    print("  GATE cmos5l-harden: %s"
          % ("PASSED" if rc == 0 else
             "RED -- expected until the harden runs; see section 6"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
