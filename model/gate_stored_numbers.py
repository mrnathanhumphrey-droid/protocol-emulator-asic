"""THE STORED-NUMBER AUDIT -- every gate that compares a number it was TOLD
rather than a number it MEASURED.

⛔⛔ WHY, FROM THE WORST DEFECT THIS PROJECT HAS HAD. `gate_j_program.py`
compared its derivation against `SWEEP`, a dict of stall measurements recorded
once. `sim <= derived` held against those values and FAILS against live
measurement at ten admissible points -- so the universal `J = 8` survived in a
PASSING gate for as long as nobody re-measured. The script that would have
re-measured it did not exist.

And the same shape, worse, next to it: `SWEEP_SINGLE` describes a
single-buffer configuration with **no build option at all**, so its arm cannot
be re-run even in principle -- while the gate computed the double buffer's
advertised benefit from it.

⇒ A stored number is not forbidden. Foreign-tool results (TChecker, pyRTA) and
  pre-registrations SHOULD be stored, and a typed expected value that a gate
  recomputes live is a regression pin, not a liability. What is forbidden is a
  stored number with **no way back to its source**.

So every site is classified, and each one must be exactly one of:

  LIVE    the gate recomputes the quantity in the same run and compares. The
          stored value is a regression pin; drift goes red by itself.
  RECORD  stored from a run that is not repeated in-gate. Must carry a RECIPE
          THAT CAN RUN -- a file that exists -- so the number can be remade.
  LEDGER  a historical entry whose whole purpose is to be immutable (a
          pre-registration, a digest ledger). Not re-measurable BY DESIGN, and
          it must say so.

⭐ THE TEETH: a RECORD whose recipe file does not exist is a FINDING, which is
exactly the `SWEEP_SINGLE` class. And coverage is measured, not asserted --
every module-level constant collection carrying three or more numbers is
scraped out of `model/` and `test/` and compared against the table, so a new
stored sweep cannot be added without appearing here as UNREVIEWED.
"""

from __future__ import annotations

import ast
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE, RECORD, LEDGER = "LIVE", "RECORD", "LEDGER"


class Site:
    def __init__(self, path, symbol, kind, what, recipe, dated, note=""):
        self.path = path            # repo-relative
        self.symbol = symbol        # module-level name that must exist
        self.kind = kind
        self.what = what
        self.recipe = recipe        # a FILE that can be run, or "" for LEDGER
        self.dated = dated          # commit / date / tool the number came from
        self.note = note


# ===========================================================================
# THE TABLE. Known members from Wilson's T4 plus whatever the scraper finds.
# ===========================================================================
SITES = [
    # ---- the headline pair ------------------------------------------------
    Site("model/a2/gate_j_program.py", "SWEEP", RECORD,
         "steady-state stall per action delay d, double buffer",
         "model/a2/price_j_sweep.sh",
         "live counterpart added after the J retraction",
         "the gate's `sim <= derived` check runs against THESE values; the "
         "live sweep is the authority and must be run to make the claim"),
    Site("model/a2/gate_j_program.py", "SWEEP_SINGLE", RECORD,
         "the same sweep on a SINGLE-BUFFER engine",
         "test/run_spl_compare.py",
         "WITHDRAWN -- contradicted by live measurement at 5 of 6 shared "
         "points once the configuration became buildable",
         "⛔ IT HAD NO RECIPE AT ALL: `NSLOT = 2*N_LANES` was fixed in "
         "pe_engine.v, so this arm described a configuration no command could "
         "produce -- while the double buffer's advertised benefit was computed "
         "from it. `SPL` is now a parameter, the arm is buildable, and the "
         "live numbers disagree with these (d=16: stored 0, measured 9). The "
         "stored values are retained as a labelled record and the benefit "
         "claim is withdrawn, not re-fitted"),

    # ---- foreign-tool records: stored ON PURPOSE -------------------------
    Site("model/a2/jitter_instances.py", "TCHECKER_RECORDED", RECORD,
         "TChecker reachability answers on the 11 jitter lane-instances",
         "model/a2/jitter_instances.py",
         "TChecker, tck-reach -a reach, /opt/ta/tchecker/bin (WSL Ubuntu)",
         "⚠ the recipe is the tool invocation described in the module header, "
         "not a committed script -- a foreign authority is re-run by hand. "
         "That is acceptable for a FOREIGN witness and would not be for ours"),
    Site("model/a2/jitter_instances.py", "PYRTA_SHIPPED", RECORD,
         "pyRTA response times on the shipped five lanes, per J_pipe",
         "model/a2/gate_pyrta_jitter.py",
         "PYRTA_SRC=<clone>/src, arm 3",
         "stored so `gate_j_sound.py` carries the margin verdict WITHOUT "
         "needing a third-party clone -- price_gates.sh removes pyRTA to "
         "prove the pyRTA gates are real, and the verdict must survive that"),

    # ---- synthesis measurements -----------------------------------------
    Site("model/a2/gate_cj_bounds.py", "DOUBLE_BUFFER_COST", RECORD,
         "flop and cell counts before/after double buffering",
         "test/yosys_check.sh",
         "Yosys 0.52, synth -flatten, both trees",
         "⚠ `flops_before` was measured on the PRE-DOUBLE-BUFFER TREE, which "
         "HEAD no longer is, and no commit ref is recorded -- so the recipe "
         "reproduces `flops_after` only. The delta is not re-derivable from "
         "HEAD alone"),

    # ---- immutable by design --------------------------------------------
    Site("model/a2/bursty.py", "DOUBLE_BUFFER_PREREG", LEDGER,
         "the pre-registered double-buffer prediction",
         "", "written before the measurement",
         "a pre-registration is worthless if it can be re-run; being frozen "
         "is the point"),
    Site("model/a2/lane_digest.py", "DIGEST_LEDGER", LEDGER,
         "historical lane-table digests",
         "", "appended at each table change",
         "the ledger is the record OF changes, so entries are immutable"),

    # ---- regression pins: recomputed live in the same run ----------------
    Site("model/a2/gate_pyrta.py", "EXPECTED_R", LIVE,
         "per-lane response times, typed",
         "model/a2/gate_pyrta.py", "n/a -- recomputed every run",
         "the answers are TYPED while the parameters are IMPORTED, so a "
         "recurrence change disagrees instead of re-blessing itself"),
    Site("model/a2/gate_j_sound.py", "EXPECTED", LIVE,
         "min margin per J_pipe over the shipped lane set",
         "model/a2/gate_j_sound.py", "n/a -- recomputed every run",
         "written down so a change in the recurrence, the lane table or the "
         "deadlines shows up as a disagreement instead of as a new table"),
    Site("model/gate_reset_audit.py", "ALLOWED", LIVE,
         "per-group expected widths of the unreset flop groups",
         "model/gate_reset_audit.py", "n/a -- read off the netlist every run",
         "⭐ this pin has fired for real: `s_wrdata` went 22 -> 24 when ACT_W "
         "absorbed the TX queue field, and the gate refused the new total"),
    Site("model/gate_mutant_arms.py", "EXPECT", LIVE,
         "declared line budget for each mutant `ifdef` arm",
         "model/gate_mutant_arms.py",
         "n/a -- the arms are preprocessed every run",
         "a budget with a declared reason per arm; drift in an arm goes red"),
]

# ⛔ Collections that carry numbers but are SPECIFICATIONS, not measurements:
# a pin map, a lane table, a condition list. They are excluded BY NAME rather
# than by a pattern, because a silent filter is how a coverage measure starts
# over-reporting itself as complete. Each name here is a claim that the thing
# is an input to the design, not an observation of it.
# ⚠ BUILT FROM THE SCRAPER'S OUTPUT, NOT FROM A GREP. The first version of
# this list was assembled from a text search and 10 of its 32 names were never
# scraped at all -- the exclusion list had drifted out of contact with the tree
# before it was ever committed, which is why the stale-exclusion check below
# exists and why it fired immediately.
SPEC_SYMBOLS = {
    # instance / lane / pin definitions -- inputs to the design
    ("model/a2/a2_close.py", "REQUIRED"),
    ("model/a2/frontier.py", "LANE_SPEC"),
    ("model/a2/task_model.py", "LANES"),
    ("model/a2/gate_differential.py", "LANES"),
    ("model/a2/gate_twin_pair.py", "TWINS"),
    ("model/a2/jitter_instances.py", "JINSTANCES"),
    ("model/a2/gate_pin_subsets.py", "PINS"),
    ("model/a2/gate_pin_subsets.py", "PINS_DIR"),
    ("model/a2/gate_load_pin_safety.py", "PINMAP"),
    ("model/a2/gate_load_pin_safety.py", "SERIAL_BITS"),
    ("model/a2/gate_encoding_f1.py", "PIN_MAP"),
    ("model/a2/gate_encoding_f1.py", "TRANSACTIONS"),
    ("model/a2/gate_cj_bounds.py", "OPNAMES"),
    ("model/a2/gate_cj_bounds.py", "J_SOURCES"),
    ("model/a2/gate_admissibility_1_6.py", "CONDITIONS"),
    ("model/a2/gate_spec_freeze_s2.py", "CUT_FIELDS"),
    ("model/a2/grid_quantization.py", "EDGES"),
    ("model/a2/gate_microarch_1_3.py", "UNPIPELINED"),
    ("model/a2/gate_microarch_1_3.py", "PIPELINED"),
    ("model/a2/gate_microarch_1_3.py", "CANDIDATES"),
    ("model/part1_param_contract.py", "FORBIDDEN_LITERALS"),
    ("model/part1_param_contract.py", "REQUIRED_PARAMS"),
    ("model/sram_spike.py", "MACROS"),
    ("model/ta01b/uart_stream.py", "STREAM_DEFAULT"),
    ("model/gate_reverse_trace.py", "LANE_CFG"),
    ("test/make_smoke_image.py", "FIVE_STRESS"),
    ("test/gate_corpus_trace.py", "COLS"),
    # ⭐ FORCED ANSWERS, NOT OBSERVATIONS. The `zone/` validation tables are
    # schedules whose answers are DERIVED BY HAND, used to validate the model
    # generator before TChecker is trusted on anything else. They are a
    # specification of what the tool must reproduce, and the tool computes
    # live against them -- so a drift shows up as a disagreement.
    ("model/a2/zone/run_edf.py", "VALIDATION"),
    ("model/a2/zone/run_edf.py", "INSTANCES"),
    ("model/a2/zone/run_bursty.py", "INSTANCES"),
    ("model/a2/zone/run_jitter.py", "JVALIDATION"),
    # gate / mutant inventories and fixtures
    ("model/a2/run_a2.py", "GATES"),
    ("model/ta02/run_ta02.py", "GATES"),
    ("model/ta02/audit_branches.py", "MUTANTS"),
    ("model/gate_ruling_audit.py", "RULINGS"),
    ("test/run_mutants.py", "EDGE_MUTANTS"),
    ("test/run_jlane.py", "ARMS"),
    # ⭐ CAUGHT BY THIS GATE'S OWN COVERAGE CHECK, on the commit that added it:
    # the T3 sweep's d points. They are which programs to BUILD, not readings.
    ("test/run_spl_compare.py", "D_LIST"),
    # ⭐ CAUGHT THE SAME WAY ON THE NEXT COMMIT: the parameter-point sweep's
    # bench inventory. Its numbers are run lengths and plusargs -- how to
    # invoke a bench, not an observation of one.
    # ⚠ Twice in two commits, both times on my own new file. That is the
    # coverage check doing the job it exists for, and it is worth recording
    # that it catches the AUTHOR rather than only a future editor.
    ("test/run_param_points.py", "BENCHES"),
    # ⭐ AND A THIRD TIME, ON A THIRD NEW FILE: the J=9 proof's premise list.
    # Its numbers are Verilog literals inside the RTL anchors (`3'd0`, `1'b0`),
    # so it is a specification of what the proof rests on, not an observation.
    # ⚠ Three commits, three catches, all of them on my own new work. Worth
    # recording: the coverage check's value is that it does not care whose file
    # it is, and it has now never once been triggered by someone else.
    ("model/gate_j_proof_anchors.py", "PREMISES"),
    # the D* theorem's check: which programs to BUILD, not readings from them
    ("test/run_dstar_check.py", "D_POINTS"),
    ("test/run_dstar_check.py", "CONTROL"),
    # ⚠ A DELIBERATELY WRONG FIXTURE: a stale lane table kept to price a gate.
    ("model/a2/_price_stale_lane_table.py", "STALE"),
    # this audit's own table
    ("model/gate_stored_numbers.py", "SITES"),
}


def scrape():
    """Every module-level ALL-CAPS collection literal with >= 3 numbers.

    ⭐ DELIBERATELY LOOSE. Over-reporting is the safe direction for a coverage
    measure: a specification caught here is removed by NAME, in `SPEC_SYMBOLS`,
    where the exclusion is reviewable. A tightened pattern that quietly dropped
    a real stored sweep is the failure this is guarding.
    """
    found = []
    for base in ("model", "test"):
        for d, _subs, files in os.walk(os.path.join(ROOT, base)):
            if any(x in d for x in (".git", "__pycache__", "node_modules")):
                continue
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                p = os.path.join(d, f)
                rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                try:
                    with open(p, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                except Exception:
                    continue
                for node in tree.body:
                    if not isinstance(node, ast.Assign):
                        continue
                    if not isinstance(node.value, (ast.Dict, ast.List,
                                                   ast.Tuple, ast.Set)):
                        continue
                    for t in node.targets:
                        if not isinstance(t, ast.Name):
                            continue
                        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", t.id):
                            continue
                        try:
                            src = ast.unparse(node.value)
                        except Exception:
                            src = ""
                        nums = re.findall(r"(?<![\w.])\d+(?![\w.])", src)
                        if len(nums) >= 3:
                            found.append((rel, t.id, len(nums)))
    return sorted(set(found))


def check_sites():
    """Each tabled site's symbol must exist, and each RECORD needs a recipe
    file that is really there."""
    bad = []
    for s in SITES:
        p = os.path.join(ROOT, s.path.replace("/", os.sep))
        if not os.path.isfile(p):
            bad.append((s, "the file does not exist"))
            continue
        with open(p, encoding="utf-8") as fh:
            txt = fh.read()
        # ⛔ ANCHORED AT COLUMN 0: a module-level assignment, not a mention in
        # a comment. `gate_ruling_audit`'s lesson -- an anchor that resolves
        # against prose proves the prose, not the code.
        if not re.search(r"(?m)^%s\s*=" % re.escape(s.symbol), txt):
            bad.append((s, "no module-level `%s =` in %s"
                        % (s.symbol, s.path)))
            continue
        if s.kind == RECORD:
            if not s.recipe:
                bad.append((s, "RECORD with NO RECIPE -- the number cannot "
                               "be remade"))
            elif not os.path.isfile(os.path.join(
                    ROOT, s.recipe.replace("/", os.sep))):
                bad.append((s, "RECORD whose recipe file is missing: %s"
                            % s.recipe))
        if s.kind == LEDGER and s.recipe:
            bad.append((s, "LEDGER with a recipe -- if it can be re-run it is "
                           "not a ledger"))
    return bad


def selftest():
    """⛔ PRICE IT (standing rule 3): the gate must reject a bogus anchor, a
    missing file and a recipe-less RECORD."""
    global SITES
    keep = SITES
    rc = 0
    cases = (
        ("a bogus symbol",
         Site("model/a2/gate_j_program.py", "NO_SUCH_SYMBOL_XYZ", LIVE,
              "", "model/a2/gate_j_program.py", "")),
        ("a missing file",
         Site("model/no_such_file_xyz.py", "SWEEP", LIVE, "",
              "model/a2/gate_j_program.py", "")),
        ("a RECORD with no recipe",
         Site("model/a2/gate_j_program.py", "SWEEP", RECORD, "", "", "")),
        ("a RECORD with a missing recipe file",
         Site("model/a2/gate_j_program.py", "SWEEP", RECORD, "",
              "model/no_such_recipe_xyz.sh", "")),
        ("a LEDGER that can be re-run",
         Site("model/a2/bursty.py", "DOUBLE_BUFFER_PREREG", LEDGER, "",
              "test/yosys_check.sh", "")),
    )
    print("  --- must-fire: the checks reject what they claim to ---")
    try:
        for name, site in cases:
            SITES = [site]
            fired = bool(check_sites())
            print("    %-34s %s" % (name, "rejected" if fired
                                    else "*** NOT REJECTED"))
            if not fired:
                rc = 1
        # and a good one must be ACCEPTED, or the checks reject everything
        SITES = [Site("model/a2/gate_j_program.py", "SWEEP", RECORD, "",
                      "model/a2/price_j_sweep.sh", "")]
        ok = not check_sites()
        print("    %-34s %s" % ("a sound RECORD", "accepted" if ok
                                else "*** REJECTED, so the gate rejects all"))
        if not ok:
            rc = 1
    finally:
        SITES = keep
    return rc


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("STORED-NUMBER AUDIT -- which gates compare a number they were told?")
    print("=" * 78)

    by_kind = {LIVE: [], RECORD: [], LEDGER: []}
    for s in SITES:
        by_kind[s.kind].append(s)
    print("  tabled: %d sites -- %d LIVE, %d RECORD, %d LEDGER"
          % (len(SITES), len(by_kind[LIVE]), len(by_kind[RECORD]),
             len(by_kind[LEDGER])))
    print()
    for kind in (RECORD, LIVE, LEDGER):
        print("  === %s ===" % kind)
        for s in by_kind[kind]:
            print("    %s :: %s" % (s.path, s.symbol))
            print("      what   : %s" % s.what)
            print("      recipe : %s" % (s.recipe or "(none -- by design)"))
            print("      source : %s" % s.dated)
            if s.note:
                print("      note   : %s" % s.note)
        print()

    # ---- the anchors and the recipes ------------------------------------
    print("  --- anchors resolve, and every RECORD can be remade ---")
    bad = check_sites()
    if not bad:
        print("    all %d sites: symbol present, recipe runnable" % len(SITES))
    for s, why in bad:
        print("    *** %s :: %s -- %s" % (s.path, s.symbol, why))
        rc = 1

    # ---- coverage, measured ---------------------------------------------
    print()
    print("  --- coverage: scraped vs tabled ---")
    scraped = scrape()
    tabled = {(s.path, s.symbol) for s in SITES}
    unreviewed = [(p, sym, n) for p, sym, n in scraped
                  if (p, sym) not in tabled and (p, sym) not in SPEC_SYMBOLS]
    print("    constant collections carrying >= 3 numbers : %d" % len(scraped))
    print("    tabled as stored numbers                   : %d" % len(tabled))
    print("    excluded by name as specifications         : %d"
          % len(SPEC_SYMBOLS))
    print("    UNREVIEWED                                 : %d"
          % len(unreviewed))
    for p, sym, n in unreviewed:
        print("      *** %s :: %s (%d numbers) -- classify it" % (p, sym, n))
        rc = 1
    # ⛔ A STALE EXCLUSION IS ALSO A FINDING. A name in SPEC_SYMBOLS that the
    # scraper no longer sees means the list is drifting out of contact with
    # the tree, and the next real sweep could be excluded by a name that
    # happens to match.
    seen = {(p, sym) for p, sym, _n in scraped}
    stale = sorted(x for x in SPEC_SYMBOLS if x not in seen)
    if stale:
        print("    *** STALE EXCLUSIONS (named but not found): %d" % len(stale))
        for p, sym in stale:
            print("      *** %s :: %s" % (p, sym))
        rc = 1

    print()
    print("  --- the mechanism, priced ---")
    if selftest():
        rc = 1

    print()
    print("=" * 78)
    print("  STORED-NUMBER AUDIT: %s" % ("PASSED" if rc == 0 else "FAILED"))
    if rc:
        print("    ⛔ A RECORD with no runnable recipe is the SWEEP_SINGLE")
        print("       class: a number that cannot be remade, sitting inside a")
        print("       gate that passes because of it.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
