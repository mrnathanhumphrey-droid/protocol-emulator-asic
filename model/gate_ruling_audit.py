"""RULING IMPLEMENTATION AUDIT -- rulings -> implementation, in one sweep.

THE ONE CLAIM: every ruled item either has a RESOLVABLE implementation site, or
is recorded as unbuilt/partial/superseded with a reason. Nothing is assumed
built because it was ruled.

⛔⛔⛔ WHY THIS EXISTS. Five day-one commitments have now been found unbuilt, ONE
AT A TIME, each by accident while working on something else:

  1. EDGE CAPTURE          -- the reactive release had no hardware at all
  2. THE NO-OP HALF-BIT    -- no primitive to express it
  3. RULING 1.5            -- the per-pin drive-mode mask did not exist, so the
                              only open-drain discipline was a hand-written
                              branch per opcode path, and a later third branch
                              duly drove a hard 1 on SCL
  4. F1's HOST CHANNEL     -- the nibble pins sat in `_unused` and the payload
                              came off the protocol bus, so NO PROGRAM COULD
                              EVER ADDRESS A PEER
  5. F1's ONE FIFO         -- absent, so a byte had to arrive in the exact cycle
                              a lane wanted it or that lane logged an underrun

Four of those were found in the last three sessions. ⇒ The rate of discovery is
a property of how we look, not of how many are left.

⛔ AND REVERSE TRACEABILITY DOES NOT COVER THIS. `gate_reverse_trace.py` checks
BEHAVIOURS -> FIELDS: every ruled behaviour has an encoding field to carry it.
That is a different question from RULINGS -> IMPLEMENTATION, and a ruling can
have a perfectly good field and no logic reading it. 1.5 had a `mode` bit in
every header and nothing at the output stage.

## What gives this teeth

A table of rulings alone is prose. Each `rtl`/`model`/`toolchain` item carries an
ANCHOR -- a file and a substring that must be PRESENT -- so:

  * a ruling marked `built` whose anchor no longer resolves FAILS the gate. If
    someone deletes `pin_pp`, this goes red rather than the next reader
    rediscovering 1.5 in a year.
  * a ruling marked `unbuilt` is a recorded finding, not a failure -- it fails
    only if it claims an anchor that does resolve, because then the status is
    stale in the other direction.

⚠ AND ITS OWN COVERAGE IS MEASURED, NOT ASSERTED. An audit that quietly covers
60% while looking complete is the exact failure it exists to prevent. So the
ruling identifiers are SCRAPED from `docs/` and compared against this table; any
identifier with no entry is reported as UNREVIEWED and the count is printed.
Coverage is a number here, not a feeling.
"""

from __future__ import annotations

import collections
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")

BUILT, PARTIAL, UNBUILT, SUPERSEDED, ANALYSIS = (
    "built", "partial", "unbuilt", "superseded", "analysis")

# (id, kind, status, anchor_file, anchor_substring, exercised_by, note)
#   kind: rtl | toolchain | model | host | process
#   anchor: None for host/process/superseded items, which have no code site
RULINGS = [
    # ---- the F series: the pin abstraction -----------------------------
    ("F1", "rtl", BUILT, "src/project.v", "tx_fifo",
     "cocotb + HOST_INTERFACE.md",
     "the host data channel: nibble on ui_in[4:1], push on ui_in[6], ONE FIFO. "
     "WAS UNBUILT until R0 -- the payload came from uio_q1, i.e. eight bits of "
     "the protocol bus, and no FIFO existed. That is why no program could "
     "address a peer."),
    ("F2", "rtl", BUILT, "src/project.v", "uo_q",
     "model/f2_flop_driven_outputs.py (24/24 flop-or-const)",
     "every output bit is a registered value or a constant tie; no "
     "combinational function of the store reaches a pin."),
    ("F3", "model", BUILT, "model/a2/gate_admissibility_1_6.py", "1.6",
     "run_a2", "the admissibility conditions are a checked set, not prose."),
    ("F4", "model", BUILT, "model/a2/run_a2.py", "GATES",
     "run_a2", "one suite, one lane table, digest-checked across gates."),
    ("F5", "rtl", BUILT, "src/pe_engine.v", "open-drain: NEVER drives 1",
     "test.py::test_open_drain_data_pin + the corpus invariant",
     "open-drain is expressible through uio_oe: pull low with oe=1/out=0, "
     "release with oe=0."),

    # ---- 1.5: the drive-mode construction ------------------------------
    ("1.5", "rtl", BUILT, "src/pe_engine.v", "pin_pp",
     "gate_corpus_trace open-drain invariant + M_OD_CLK_PUSHPULL",
     "out[i] = data[i] & pushpull[i], per PIN, at the output flop's D input. "
     "WAS UNBUILT: no per-pin mask existed anywhere in src/ and l_mode was "
     "per-LANE. ⚠ Holds BY DECLARATION -- a program that declares its I2C lane "
     "push-pull still drives SCL high, which is a program error the loader "
     "cannot detect (uio pins are physically PP- or OD-capable)."),

    # ---- the microarchitecture rulings ---------------------------------
    ("R2", "rtl", BUILT, "src/pe_engine.v", "l_timestamp[cur] + ",
     "tb_smoke + run_mutants",
     "REARM adds to the STORED timestamp, never to `now`; the relative form "
     "drifts k*(r-C) and is invisible at k=1."),
    ("N1a", "rtl", BUILT, "src/pe_engine.v", "arm_hit",
     "tb_edge (5/5 must-fires)",
     "the reactive release: ARM fires on an observed peer edge, with the "
     "existing deadline comparator as the timeout. WAS UNBUILT -- commitment 1."),
    ("half-bit", "rtl", BUILT, "src/pe_engine.v", "PIN_NONE",
     "tb_edge must-fire 5 + noop_image_bad",
     "the non-driving no-op: a reserved pin index so a half-bit delay costs no "
     "pin. WAS UNBUILT -- commitment 2, no primitive existed to express it."),
    ("prime", "rtl", BUILT, "src/pe_engine.v", "primed_q",
     "run_mutants M_NO_PRIME",
     "prime-before-release: `now` is frozen until the first fetch has landed, "
     "so a lane's first release is not measured from a stale timestamp."),
    ("double-buffer", "rtl", BUILT, "src/pe_engine.v", "l_sel",
     "run_mutants (4/4: M_BUF_SWAP/NOINVAL/CHAINFLIP + M_TIMEOUT_PROCEED)",
     "two action slots per lane, head + spare, which is what reduces J to 1."),
    ("1.6r", "rtl", BUILT, "src/project.v", "cs_deasserted",
     "gate_corpus_trace async-clear arm (cycle-exact with CS off-edge)",
     "shared MISO: the output enable is async-cleared by CS rising, so release "
     "is hardware rather than an obligation on the master."),
    ("D1", "rtl", BUILT, "src/project.v", "rb_prime",
     "test.py::test_readback_reaches_byte_zero + the readback seed sweep",
     "program byte 0 is readable: rb_addr latches the pre-increment address AND "
     "the readback primes before it frames."),
    ("D2", "rtl", BUILT, "src/pe_engine.v", "pin_oe[l_clkpin[cur]]  <= ~a_lvl",
     "test.py::test_open_drain_clock_pin_is_released + the invariant/stretch "
     "must-fires", "an open-drain lane's CLOCK pin is released, not driven."),
    ("serial-RX", "rtl", BUILT, "src/project.v", "ser_sh",
     "test.py::test_serial_readback_walks_the_image",
     "the 3-pin serial host view: 9-bit frames, payload LSB-first + marker, "
     "payload alternating with a sticky status frame."),

    # ---- ruled as LOADER behaviour, and absent from the chip ------------
    ("1.6s", "rtl", UNBUILT, None, None,
     "model/a2/gate_admissibility_1_6.py (on programs WE author)",
     "⛔ ruled as 'the loader REJECTS an open-drain lane assigned a uo_out "
     "pin'. There is NO load-time rejection in the RTL and the image "
     "toolchain only states the rule in a docstring -- make_smoke_image's "
     "hdr() says open-drain 'is only MEANINGFUL on a uio pin' and asserts "
     "nothing. Two RTL comments defer to '1.6's load-time screen', which does "
     "not exist. The condition is checked only against our own programs."),
    ("1.6t", "rtl", UNBUILT, None, None,
     "model/a2/gate_j_program.py (derives J offline)",
     "⛔ ruled as 'the loader COMPUTES the program's J from d_min'. No RTL "
     "site; the derivation lives in the model. A host loading an arbitrary "
     "program gets no J and no admissibility verdict from the chip."),

    # ---- known-open, already recorded ----------------------------------
    ("TX-routing", "rtl", PARTIAL, "src/project.v", "TXD",
     "none yet -- must-fires owed",
     "⚠ ONE SHARED FIFO WITH NO LANE TAG is only correct with ONE "
     "TX-consuming lane. With more than one, consumption order is the EDF "
     "interleave, which is timing-dependent, so a host cannot order its "
     "pushes and the wrong lane transmits the wrong byte SILENTLY. Awaiting a "
     "decision between a 2-bit lane tag and an admissibility limit."),
    ("RX-attribution", "rtl", UNBUILT, None, None,
     "none yet -- must-fires owed",
     "⚠ the mirror: serial frames carry payload or status but NO LANE "
     "IDENTITY, so with UART-rx and SPI-target both receiving the host cannot "
     "tell which lane a byte came from."),

    # ---- superseded, cited ---------------------------------------------
    ("1.6q", "rtl", SUPERSEDED, None, None, "n/a",
     "the pointer echo on uo_out. Superseded by the two-bank ruling: uo_out[3:0] "
     "became protocol outputs and [6:4] the serial view, so there are no pins "
     "left to echo a pointer on. Retired the old cocotb pointer tests."),
    ("F1-RX-parallel", "rtl", SUPERSEDED, None, None, "n/a",
     "a parallel RX byte on uo_out. Superseded in PHASE1_CLOSEOUT_PART4: with "
     "5 of 8 uo_out pins on protocol outputs, 3 remain and cannot carry a "
     "nibble plus a valid, so RX went bit-serial."),
    ("F1-view-select", "rtl", SUPERSEDED, None, None, "n/a",
     "ui_in[0] selecting payload vs status on uo_out, and ui_in[5] as RX pop. "
     "Superseded in PART5: the status byte is framed INTO the stream, because a "
     "host that has stopped reading cannot be told by a pin it is not reading. "
     "⇒ both pins are free, which is what a lane tag could use."),

    # ---- analysis-only: no RTL site is owed ----------------------------
    ("A2", "model", ANALYSIS, "model/a2/run_a2.py", "GATES",
     "run_a2 (30/30)",
     "the non-preemptive EDF response-time analysis. Analysis, not hardware: "
     "its product is the published r_i and the bar verdict."),
    ("N1", "model", BUILT, "model/a2/gate_lane_class.py", "D_tol",
     "run_a2 + the digest meta-check",
     "the I2C deadline derivation, 30 -> 15, from UM10204 Table 11's "
     "asymmetric 80/45 split. Reflected in the shipped lane table as "
     "I2C D_tol = 15, which the digest pins."),
    ("pyRTA-primary", "model", BUILT, "model/a2/pyrta_bound.py", "check_direction",
     "run_a2 + price_gates (13/13 red without the tool)",
     "pyRTA is the PRIMARY bound; ours is a cross-check allowed only to be more "
     "conservative, and a gate fails if ours is ever smaller."),
]

# ---------------------------------------------------------------------------
# THE 1.6 ADMISSIBILITY FAMILY, covered BY REFERENCE
# ---------------------------------------------------------------------------
# `model/a2/gate_admissibility_1_6.py` carries 23 conditions (1.6a..1.6w), each
# with a satisfied-on-the-shipped-set check AND a firing witness. That is the
# right home for them: they are conditions on PROGRAMS, so they are checked
# where programs are analysed.
#
# ⚠ BUT THAT GATE CHECKS PROGRAMS WE AUTHOR, NOT A CHIP-SIDE REJECTION, and for
# most of the family that is exactly the intent -- 1.6a's queue-slot bound or
# 1.6i's minimum pulse width are obligations on whoever writes the program.
# ⛔ TWO ARE DIFFERENT, AND THEY ARE BROKEN OUT ABOVE AS UNBUILT: 1.6s says "the
# loader REJECTS" and 1.6t says "the loader COMPUTES". Those state HARDWARE
# behaviour, and there is none -- no load-time screen exists in the RTL, and two
# RTL comments defer to one. Being inside a passing model gate is precisely what
# let them read as built.
_F16_BY_REFERENCE = [
    "1.6a", "1.6b", "1.6c", "1.6d", "1.6e", "1.6f", "1.6g", "1.6h",
    "1.6i", "1.6j", "1.6k", "1.6l", "1.6m", "1.6n", "1.6o", "1.6p",
    "1.6u", "1.6v", "1.6w",
]
for _rid in _F16_BY_REFERENCE:
    RULINGS.append((
        _rid, "model", ANALYSIS,
        "model/a2/gate_admissibility_1_6.py", '("%s"' % _rid,
        "gate_admissibility_1_6 (condition + firing witness)",
        "a program-admissibility condition, checked where programs are "
        "analysed. ⚠ Checked against programs WE author -- the chip does "
        "not reject a non-conforming program."))

# ruling identifiers that are prose structure rather than ruled items
NOT_RULINGS = {
    "A2",       # the analysis programme, entered above explicitly
    "S0", "S1", "S2", "S3", "S4",   # spec-freeze stages, not rulings
    "Q1", "Q2", "Q3",               # Wilson's questions, answered in records
    "R0", "R1", "R2", "R3", "R4",   # ruling-block indices, reused per round
    "A1", "A3", "A4", "A5",         # amendment indices, reused per round
    "1.0", "1.1", "1.2", "1.3", "1.4",   # rung numbers
    "F6",
    "1.6",      # bare prose reference to the family
    # ⚠ A KNOWN FALSE POSITIVE, listed rather than silently filtered:
    # `F7` is a CRC byte in TA02_RESULTS.md ("7B B5 7D F7"), not a ruling.
    # The scraper is deliberately loose -- over-reporting is the safe
    # direction for a coverage measure -- so the exclusions are named.
    "F7",
}

ID_RE = re.compile(r"\b(1\.6[a-z]|1\.[0-9]|F[1-9]|N[0-9][a-z]?|D[12])\b")


def scrape_ids():
    """The ruling-identifier universe, from docs/ -- so coverage is measured."""
    seen = collections.Counter()
    for fn in sorted(os.listdir(DOCS)):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(DOCS, fn), encoding="utf-8") as fh:
            for m in ID_RE.finditer(fh.read()):
                seen[m.group(1)] += 1
    return seen


def anchor_resolves(path, needle):
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        return False
    with open(full, encoding="utf-8") as fh:
        return needle in fh.read()


def main() -> int:
    print()
    print("=" * 78)
    print("RULING IMPLEMENTATION AUDIT -- rulings -> implementation")
    print("=" * 78)

    rc = 0
    by_status = collections.Counter()
    findings, stale = [], []

    print("  %-16s %-11s %s" % ("ruling", "status", "site / note"))
    print("  " + "-" * 74)
    for rid, kind, status, afile, aneedle, exercised, note in RULINGS:
        by_status[status] += 1
        resolved = None
        if afile and aneedle:
            resolved = anchor_resolves(afile, aneedle)
        site = "%s :: %s" % (afile, aneedle) if afile else "(no code site)"
        flag = ""
        if status in (BUILT, PARTIAL, ANALYSIS):
            if resolved is None:
                flag = "*** claims built with NO ANCHOR"
                rc = 1
            elif not resolved:
                flag = "*** ANCHOR DOES NOT RESOLVE"
                rc = 1
        elif status in (UNBUILT,):
            if resolved:
                flag = "*** marked unbuilt but its anchor RESOLVES (stale)"
                stale.append(rid)
                rc = 1
        print("  %-16s %-11s %s %s" % (rid, status, site, flag))
        if status in (UNBUILT, PARTIAL):
            findings.append((rid, status, note))

    # ---- SELF-TEST: the anchor check must be able to FAIL ---------------
    # ⛔⛔ THE WHOLE VALUE OF THIS GATE IS THAT A DELETED RULING TURNS IT RED. A
    # check only ever seen to pass has unknown strength, and five rulings were
    # already found unbuilt by accident -- so the mechanism is priced here
    # rather than trusted. Two arms: a needle that cannot be present, and a file
    # that does not exist.
    st_ok = True
    if anchor_resolves("src/pe_engine.v", "THIS_STRING_IS_NOT_IN_THE_RTL_42"):
        print("  *** SELF-TEST: a bogus needle RESOLVED")
        st_ok = False
    if anchor_resolves("src/no_such_file.v", "pin_pp"):
        print("  *** SELF-TEST: a missing file RESOLVED")
        st_ok = False
    if not anchor_resolves("src/pe_engine.v", "pin_pp"):
        print("  *** SELF-TEST: a real anchor did NOT resolve")
        st_ok = False
    print()
    print("  --- self-test: can the anchor check fail? ---")
    if st_ok:
        print("    bogus needle rejected, missing file rejected, real anchor")
        print("    accepted ⇒ a deleted ruling WOULD turn this gate red.")
    else:
        rc = 1

    print()
    print("  --- status tally ---")
    for st, n in sorted(by_status.items()):
        print("    %-12s %d" % (st, n))

    # ---- COVERAGE, measured against the docs ---------------------------
    print()
    print("  --- coverage against the ruling identifiers in docs/ ---")
    seen = scrape_ids()
    covered = {r[0] for r in RULINGS}
    universe = {k for k in seen if k not in NOT_RULINGS}
    unreviewed = sorted(universe - covered)
    print("    identifiers found in docs/ : %d" % len(seen))
    print("    treated as ruled items     : %d" % len(universe))
    print("    with an entry here         : %d" % len(universe & covered))
    print("    UNREVIEWED                 : %d" % len(unreviewed))
    if unreviewed:
        for u in unreviewed:
            print("      %-10s (%d mentions)" % (u, seen[u]))
        print("    ⚠ UNREVIEWED IS NOT THE SAME AS BUILT. These have no entry,")
        print("      so this audit says NOTHING about them -- which is the")
        print("      honest state, and the number is printed so it cannot be")
        print("      mistaken for completeness.")

    print()
    if findings:
        print("  --- recorded findings (not failures) ---")
        for rid, status, note in findings:
            print("    %s [%s]" % (rid, status))
            for line in _wrap(note, 68):
                print("        %s" % line)

    print()
    print("=" * 78)
    print("  GATE ruling-audit: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * %d rulings tabled: %d built, %d partial, %d unbuilt, "
          "%d superseded, %d analysis"
          % (len(RULINGS), by_status[BUILT], by_status[PARTIAL],
             by_status[UNBUILT], by_status[SUPERSEDED], by_status[ANALYSIS]))
    print("    * every `built` claim is backed by a resolvable anchor, so")
    print("      deleting the logic turns this red instead of waiting for")
    print("      somebody to rediscover the ruling.")
    if stale:
        print("    * STALE statuses: %s" % ", ".join(stale))
    print("    ⚠ %d identifier(s) remain UNREVIEWED -- see above."
          % len(unreviewed))
    return rc


def _wrap(t, w):
    out, cur = [], ""
    for x in str(t).split():
        if cur and len(cur) + 1 + len(x) > w:
            out.append(cur)
            cur = x
        else:
            cur = (cur + " " + x) if cur else x
    if cur:
        out.append(cur)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
