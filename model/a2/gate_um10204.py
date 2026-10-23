"""Measured clocked-bus timings against the UM10204 minima (C1, C2, F1, F4).

THE ONE CLAIM: on an open-drain clocked lane the SCL high period is at least
the programmed delay `d`, at any stretch, and the measured phase timings are
reported against UM10204's minima with the mode each `d` can actually claim.

⛔⛔ NAMED HONESTLY, AND THE NAME IS THE POINT. This is OUR code checking OUR
traces against a table TRANSCRIBED from a foreign standard. That is NOT foreign
certification: `sigrok` certifies that a foreign DECODER reads our frame, which
is a statement about decode and says nothing about timing. A decoder will
happily decode a frame whose high phase is a tenth of the legal minimum. So
this gate reports "measured vs UM10204 minima" and never "compliant".
⚠ THE TABLE IS TRANSCRIBED, NOT VENDORED, and that is a real weakness rather
than a formality: UM10204 is third-party copyright and `refs/` is gitignored
with the guard committed, because the submission is open source. Nothing in
this repo can re-derive these numbers, so they are a hand-carried constant and
are labelled as one.
⭐ ONE INDEPENDENT CROSS-CHECK EXISTS AND IT AGREED: the t_LOW minima here give
`d >= 25` (Fm+), `65` (Fm) and `235` (Sm) at 50 MHz, which were derived
separately in the ruling that ordered this gate. Two routes to the same three
numbers is not proof of the table, but a transcription error would have had to
survive both.

⛔ WHAT IT IS ADJUDICATING -- A MEASURED FAILURE, NOT A HYPOTHETICAL. The
post-HIGH park arms on `ck_act & ck_is_high & ck_park_en & ~l_mode`, and
`ck_act` covers SHIFT as well as SHIFTIN, so every open-drain clocked high
phase parks. While the park released the next dispatch AT the observed rise,
the high phase was the synchroniser latency and nothing else -- MEASURED FLAT
AT 5-6 CYCLES while `d` spanned 13x (9/25/60/120) and t_LOW tracked `d`. Against
minima of 13 / 30 / 200 cycles, the clocked scheme met NO I2C mode, and no
choice of `d` could fix it because the high phase was not programmable.
⇒ F1: the release is `observed rise + d`, which is UM10204's own clock-
  synchronisation rule (a master counts its HIGH period from SCL SEEN high).

⚠ WHAT THIS GATE DOES NOT CHECK, NAMED SO ITS SILENCE IS NOT READ AS A PASS:
t_SU;STA, t_HD;STA and t_SU;STO need START and STOP conditions, which the
clocked images do not contain -- `OP_START`/`OP_STOP` are separate opcodes and
the clocked scheme does not emit them. Those remain owed, against the certified
two-action frame where they do occur.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

#: ns per cycle at the shipped 50 MHz.
NS_PER_CYCLE = 20

#: UM10204 Table 10's own note: a device must INTERNALLY provide at least this
#: much data hold to bridge the undefined region of SCL's falling edge. The
#: tabulated t_HD;DAT minimum is 0 ns, so this note is the STRONGER requirement
#: and the one a transmitter actually has to meet.
HD_BRIDGE_NS = 300

#: UM10204 Rev 7, Table 10, minima in ns. TRANSCRIBED -- see the header.
#: `None` means the standard sets no minimum for that mode.
UM10204 = {
    "Sm  100 kHz": {"t_LOW": 4700, "t_HIGH": 4000, "t_SU_DAT": 250,
                    "t_HD_DAT": 0},
    "Fm  400 kHz": {"t_LOW": 1300, "t_HIGH": 600, "t_SU_DAT": 100,
                    "t_HD_DAT": 0},
    "Fm+ 1 MHz":   {"t_LOW": 500, "t_HIGH": 260, "t_SU_DAT": 50,
                    "t_HD_DAT": 0},
}

#: THE MAXIMA THAT BOUND THE HOLD FROM ABOVE, in ns. ⛔ A REQUIREMENT WITH A
#: FLOOR AND NO CEILING IS HALF A REQUIREMENT: without these the gate would
#: accept any hold at all above 15 cycles, and a hold long enough to outlast the
#: low phase is a WORSE defect than the one the hold fixes -- it moves data
#: across the clock rise.
#: ⚠ `t_r` is the SDA RISE TIME, which a cycle-resolution trace cannot measure,
#: so the mode's MAXIMUM is charged as a budget rather than observed. That is
#: the conservative direction.
UM10204_MAX = {
    "Sm  100 kHz": {"t_VD_DAT": 3450, "t_r": 1000},
    "Fm  400 kHz": {"t_VD_DAT": 900, "t_r": 300},
    "Fm+ 1 MHz":   {"t_VD_DAT": 450, "t_r": 120},
}
MODES = list(UM10204)


def cycles(ns):
    """ns -> whole cycles, rounding UP: a minimum is not met by rounding down."""
    return -(-ns // NS_PER_CYCLE)


def rate_hz(mode):
    """A mode's maximum SCL rate, read from its own table key ("Fm  400 kHz",
    "Fm+ 1 MHz") so the rate and the minima cannot come from two places."""
    num, unit = mode.split()[-2:]
    return int(num) * {"kHz": 1000, "MHz": 1000000}[unit]


def table_cycles():
    return {m: {k: cycles(v) for k, v in d.items()} for m, d in UM10204.items()}


def claimable(lo, hi, tc):
    """The fastest mode whose t_LOW/t_HIGH minima this clock actually meets.

    ⛔⛔ A LANE CANNOT BE HELD TO A MODE ITS CLOCK CANNOT ACHIEVE, and
    the first version of the hold checks did exactly that: it compared the
    WORST setup seen on any lane against EVERY mode's minimum, so a d = 25
    lane (an Fm+ clock) was failed for not meeting Sm's 250 ns setup -- a
    requirement that only applies at 100 kHz. A category error reads as a
    design violation, which is worse than no check.
    """
    for m in reversed(list(tc)):            # loosest minima first
        if lo >= tc[m]["t_LOW"] and hi >= tc[m]["t_HIGH"]:
            return m
    return None


def load():
    p = os.environ.get("PE_PHASES_JSON", "")
    if not p or not os.path.isfile(p):
        return None, p
    with open(p, encoding="utf-8") as fh:
        return json.load(fh), p


OD_ARMS = ("clean", "stretch_mid", "stretch_long", "half")


def empty_arms(counts, arms, what):
    """⛔ S1g (10-22): an arm that contributed ZERO measured items to a section
    is red, per arm -- never pooled. §1 and §4b(a) counted lanes across every
    arm together, so the `half` arm measured nothing for nine days while the
    other arms kept the pooled count above 0. Returns 1 if any arm is empty."""
    bad = [arm for arm in arms if counts.get(arm, 0) == 0]
    for arm in bad:
        print("    *** FAIL %s: the `%s` arm measured nothing here -- a section "
              "with zero measured items is not a pass" % (what, arm))
    return 1 if bad else 0


def high_len(lane):
    """The lane's programmed HIGH length: `d`, or `d // 2` on a HALF_HIGH lane
    (ruling CE1) -- the golden model's own rule, imported, not restated."""
    sys.path.insert(0, os.path.dirname(HERE))
    from clocked_phase import high_gap
    return high_gap(lane["d"], lane.get("half", False))


def main() -> int:
    rc = 0
    blob, path = load()
    print()
    print("=" * 78)
    print("  MEASURED CLOCKED-BUS TIMINGS vs UM10204 MINIMA  (C1/C2/F1/F4)")
    print("=" * 78)
    if blob is None:
        print("  *** FAIL no measurement at PE_PHASES_JSON=%r" % path)
        print("      `bash test/phases_run.sh <outdir>` produces it. This gate")
        print("      is RED without it rather than skipping: a timing gate that")
        print("      passes when the measurement is missing is a guard that")
        print("      passes because of what it guards.")
        return 1
    print("  measurement : %s" % path)
    print("  arms        : %s" % ", ".join(sorted(blob)))
    tc = table_cycles()
    print()
    print("  --- the transcribed table, in cycles at 50 MHz (%d ns/cycle) ---"
          % NS_PER_CYCLE)
    print("    %-13s %-9s %-9s %-10s %s"
          % ("mode", "t_LOW", "t_HIGH", "t_SU;DAT", "t_HD;DAT"))
    for m in MODES:
        print("    %-13s %-9d %-9d %-10d %d"
              % (m, tc[m]["t_LOW"], tc[m]["t_HIGH"], tc[m]["t_SU_DAT"],
                 tc[m]["t_HD_DAT"]))

    # -----------------------------------------------------------------
    # 1. F1 IN SILICON: t_HIGH >= d on every open-drain clocked lane
    # -----------------------------------------------------------------
    print()
    print("  --- 1. F1 in silicon: t_HIGH >= d, at every stretch ---")
    print("    %-14s %-6s %-6s %-8s %-8s %-9s %s"
          % ("arm", "lane", "d", "t_HIGH", "t_LOW", "high-d", "verdict"))
    seen_od = 0
    per1 = {}
    for arm in OD_ARMS:
        a = blob.get(arm)
        if a is None:
            print("    %-14s *** FAIL arm absent from the measurement" % arm)
            rc = 1
            continue
        for l in a["lanes"]:
            if l["mode"] != 0 or not l.get("t_HIGH"):
                continue
            seen_od += 1
            per1[arm] = per1.get(arm, 0) + 1
            # ⭐ CE1: held to the lane's OWN HIGH length (d, or d/2 when
            # HALF_HIGH) -- `d` in the table is still the programmed delay
            d, hi = high_len(l), l["t_HIGH"]["min"]
            lo = l["t_LOW"]["min"] if l.get("t_LOW") else -1
            ok = hi >= d
            if not ok:
                rc = 1
            print("    %-14s %-6d %-6s %-8d %-8d %-9s %s"
                  % (arm, l["lane"], "%d%s" % (l["d"], "/2" if l.get("half")
                                               else ""),
                     hi, lo, "%+d" % (hi - d),
                     "ok" if ok else "*** FAIL t_HIGH < its HIGH length"))
    rc |= empty_arms(per1, [x for x in OD_ARMS if x in blob], "§1")
    if seen_od == 0:
        print("    *** FAIL no open-drain clocked lane in any arm, so the")
        print("        claim was not measured at all")
        rc = 1
    else:
        print("    ⇒ %d open-drain lane-arms, every t_HIGH at or above its own"
              % seen_od)
        print("      programmed d, and UNMOVED by a 200- or 4000-cycle stretch.")

    # -----------------------------------------------------------------
    # 1b. RULING CE1 -- HALF_HIGH: the d/2 phase lands, and the lane still
    #     meets its mode's t_HIGH with it
    # -----------------------------------------------------------------
    print()
    print("  --- 1b. CE1: HALF_HIGH -- t_HIGH is the d/2 phase, and it meets "
          "the mode ---")
    for arm, want_half in (("half", True), ("half_mutant", False)):
        a = blob.get(arm)
        if a is None:
            print("    %-12s *** FAIL arm absent from the measurement" % arm)
            rc = 1
            continue
        # ⛔ AN ARM WITH NO CHECKED LANE IS RED, NOT A PASS (10-22 must-fire
        # audit): the filter below can drop every lane, and the loop then
        # printed nothing and left rc alone -- for `half_mutant`, a must-fire
        # that "did not fail" because it examined nothing.
        checked = 0
        for l in a["lanes"]:
            if l["mode"] != 0 or not l.get("t_HIGH") or not l.get("t_LOW"):
                continue
            checked += 1
            hi, lo = l["t_HIGH"]["min"], l["t_LOW"]["min"]
            landed = hi < l["d"]           # the d/2 phase, not d
            # ⛔ THE LANE'S OWN MODE, NOT THE LOOSEST ONE ITS PHASES MEET: the
            # mode whose RATE band its measured bit period sits in (the
            # slowest mode whose ceiling the period respects) -- an 82-cycle
            # HALF_HIGH lane is an Fm clock and is held to Fm's t_HIGH, not
            # to Fm+'s 13 cycles, which any clock this slow clears.
            period = hi + lo
            target = None
            for m in MODES:                  # Sm first: the slowest ceiling
                if period >= cycles(10 ** 9 // rate_hz(m)):
                    target = m
                    break
            if want_half:
                ok = landed and target is not None and \
                    hi >= tc[target]["t_HIGH"] and lo >= tc[target]["t_LOW"]
                verdict = ("ok -- an %s clock (period %d): t_HIGH %d >= %d, "
                           "t_LOW %d >= %d" % (target, period, hi,
                                               tc[target]["t_HIGH"], lo,
                                               tc[target]["t_LOW"])
                           if ok else "*** FAIL (d/2 landed: %s, mode %s)"
                           % (landed, target))
            else:
                # ⛔ MUST-FIRE: `M_HALF_IGNORED` (phases_run.sh builds the
                # `half_mutant` arm with it) -- the HIGH phase is d
                ok = not landed
                verdict = ("ok -- the mutant's HIGH is the full d (red)"
                           if ok else "*** the mutant still ran d/2")
            if not ok:
                rc = 1
            print("    %-12s lane %d d=%-4d t_HIGH %-4d t_LOW %-4d %s"
                  % (arm, l["lane"], l["d"], hi, lo, verdict))
        if checked == 0:
            print("    %-12s *** FAIL no open-drain lane with both phases "
                  "measured -- nothing was checked" % arm)
            rc = 1

    # -----------------------------------------------------------------
    # 2. MUST-FIRE: the pre-fix design must MISS it
    # -----------------------------------------------------------------
    print()
    print("  --- 2. must-fire: M_CK_RISE_ELIGIBLE must FAIL t_HIGH >= d ---")
    mut = blob.get("mutant")
    if mut is None:
        print("    *** MUST-FIRE FAILED: no `mutant` arm. The clean result")
        print("        alone cannot show this gate is capable of failing.")
        rc = 1
    else:
        rows = [l for l in mut["lanes"] if l["mode"] == 0 and l.get("t_HIGH")]
        bad = [l for l in rows if l["t_HIGH"]["min"] < l["d"]]
        flat = sorted({l["t_HIGH"]["min"] for l in rows})
        print("    %-6s %-6s %-8s %s" % ("lane", "d", "t_HIGH", "fails?"))
        for l in rows:
            print("    %-6d %-6d %-8d %s"
                  % (l["lane"], l["d"], l["t_HIGH"]["min"],
                     "fires" if l["t_HIGH"]["min"] < l["d"] else "*** NO"))
        if len(bad) != len(rows) or not rows:
            print("    *** MUST-FIRE FAILED: %d of %d lanes missed the bound;"
                  % (len(bad), len(rows)))
            print("        the pre-fix design must fail at EVERY delay")
            rc = 1
        else:
            print("    ⇒ fires on all %d lanes, and t_HIGH is FLAT at %s while"
                  % (len(rows), flat))
            print("      d spans %d..%d -- the defect is that the high phase"
                  % (min(l["d"] for l in rows), max(l["d"] for l in rows)))
            print("      did not depend on d at all, which is why one delay")
            print("      could not have revealed it.")

    # -----------------------------------------------------------------
    # 3. THE CONTROL ARM
    # -----------------------------------------------------------------
    print()
    print("  --- 3. control arm: push-pull never parks ---")
    ctl = blob.get("control")
    if ctl is None:
        print("    *** FAIL no `control` arm. Without it a bench artefact and")
        print("        a design property are indistinguishable.")
        rc = 1
    else:
        # ⛔ A PAD-OVERRIDDEN LANE IS NOT MEASURABLE HERE, and skipping it is
        # stated rather than silent. `project.v` overrides `uio_oe[MISO_PIN]`
        # with the SPI target's `miso_oe_q`, so a "clock" read on that pin is
        # the target's output, not the lane's. `build_ckfive` lane 3 sits on
        # pin 6 / clkpin 7 -- CS_PIN and MISO_PIN -- and this arm reported a
        # symmetric clock there for several runs before the override was found.
        skipped = [l for l in ctl["lanes"] if l.get("pad_overridden")]
        rows = [l for l in ctl["lanes"]
                if l.get("t_HIGH") and l.get("t_LOW")
                and not l.get("pad_overridden")]
        for l in skipped:
            print("    lane %d pin=%d clk=%d  SKIPPED -- pad-overridden "
                  "(MISO_PIN/CS_PIN); the pad value is the SPI target's, "
                  "not this lane's" % (l["lane"], l["pin"], l["clkpin"]))
        print("    %-6s %-6s %-8s %-8s %s"
              % ("lane", "d", "t_HIGH", "t_LOW", "symmetric?"))
        asym = 0
        for l in rows:
            hi, lo = l["t_HIGH"]["min"], l["t_LOW"]["min"]
            sym = abs(hi - lo) <= 8
            if not sym:
                asym += 1
            print("    %-6s %-6d %-8d %-8d %s"
                  % (l["lane"], l["d"], hi, lo,
                     "yes" if sym else "*** no (%+d)" % (hi - lo)))
        rc |= empty_arms({"control": len(rows)}, ["control"], "§3")
        if asym:
            # ⛔ THE ARGUMENT WAS MISSING HERE and the line printed a literal
            # `%d`. That is the "a check that cannot speak" shape
            # `gate_bench_lint` exists to catch in Verilog, in Python -- the
            # failure fired correctly and then described itself uselessly.
            print("    *** FAIL %d push-pull lane(s) asymmetric: the park is"
                  % asym)
            print("        open-drain only, so a push-pull clock must be")
            print("        symmetric in d")
            rc = 1
        else:
            print("    ⇒ symmetric, as a non-parking lane must be. The SAME")
            print("      bench reads both, so the open-drain result above is a")
            print("      comparison and not a reading.")

    # -----------------------------------------------------------------
    # 4. UM10204 ADJUDICATION, per lane, at the mode its d can claim
    # -----------------------------------------------------------------
    print()
    print("  --- 4. measured vs UM10204 minima (NOT a compliance claim) ---")
    a = blob.get("clean")
    if a is None:
        print("    *** FAIL no `clean` arm")
        rc = 1
    else:
        print("    %-6s %-6s %-13s %-9s %-9s %-10s %s"
              % ("lane", "d", "fastest mode", "t_LOW", "t_HIGH", "t_SU;DAT",
                 "t_HD;DAT"))
        for l in a["lanes"]:
            if l["mode"] != 0 or not l.get("t_LOW"):
                continue
            lo, hi = l["t_LOW"]["min"], l["t_HIGH"]["min"]
            su = (l.get("t_SU_DAT") or {}).get("min")
            hd = (l.get("t_HD_DAT") or {}).get("min")
            # the fastest mode whose minima the MEASURED timings all meet
            claim = None
            for m in reversed(MODES):            # Fm+ first (loosest minima)
                t = tc[m]
                if lo >= t["t_LOW"] and hi >= t["t_HIGH"] and \
                   (su is None or su >= t["t_SU_DAT"]) and \
                   (hd is None or hd >= t["t_HD_DAT"]):
                    claim = m
                    break
            print("    %-6d %-6d %-13s %-9d %-9d %-10s %s"
                  % (l["lane"], l["d"], claim or "NONE", lo, hi,
                     su if su is not None else "-",
                     hd if hd is not None else "-"))
        print("    ⚠ `NONE` is not a failure of this gate -- a 9-cycle delay is")
        print("      a 2.7 MHz clock and no I2C mode reaches it. It is a")
        print("      statement about that PROGRAM, and §5 is the rule that")
        print("      picks a legal d.")

    # -----------------------------------------------------------------
    # 4b. RULING H -- t_HD;DAT, AND THE GATE FAILS ON IT
    # -----------------------------------------------------------------
    print()
    print("  --- 4b. RULING H: the SDA data hold across the SCL fall ---")
    print("    ⛔⛔ IN SCOPE, AND THIS GATE FAILS ON IT. UM10204 Table 10")
    print("    tabulates t_HD;DAT min = 0 ns, but the table's own note requires")
    print("    a DEVICE to internally provide >= %d ns (%d cycles at 50 MHz),"
          % (HD_BRIDGE_NS, cycles(HD_BRIDGE_NS)))
    print("    and this chip is the device driving SDA. The hazard is concrete:")
    print("    SCL takes up to 300 ns (Fm) to fall through a receiver's")
    print("    undefined region, so SDA moving in the same cycle we pull SCL")
    print("    low can be read as a START or a STOP. On a FRAM that aborts the")
    print("    transfer at best and corrupts the write at worst.")
    print("    ⚠ The tabulated 0 ns minimum is the WEAKER test and is not")
    print("    the one adjudicated here.")
    need = cycles(HD_BRIDGE_NS)
    a_clean = blob.get("clean")
    print()
    print("    (a) hold floor: t_HD;DAT >= %d cycles" % need)
    print("      %-13s %-6s %-11s %-9s %s"
          % ("arm", "d", "t_HD;DAT", "periods", "verdict"))
    nmeas = 0
    per4a = {}
    # ⛔ RULING K4: `corpus_i2c` is REQUIRED, not optional -- it is the arm that
    # contains the clocked SHIFTIN release, and skipping it when absent would
    # restore the blindness that hid the defect.
    for arm in ("clean", "certified", "stretch_mid", "stretch_long",
                "corpus_i2c"):
        a = blob.get(arm)
        if a is None:
            if arm == "corpus_i2c":
                print("      *** FAIL the corpus_i2c arm is absent -- K4 is "
                      "not measured")
                rc = 1
            continue
        for l in a["lanes"]:
            hd = l.get("t_HD_DAT")
            if not hd:
                # ⛔ NO IN-PERIOD SDA TRANSITION IS NEITHER A PASS NOR A
                # FAIL: the lane's consecutive bits did not differ, so there was
                # no hold to observe. Recording it as a pass is how a
                # measurement starts reporting absence of evidence as evidence.
                print("      %-13s %-6d %-11s %-9s %s"
                      % (arm, l["d"], "none", l.get("periods"),
                         "not measured -- SDA moved in no period"))
                continue
            nmeas += 1
            per4a[arm] = per4a.get(arm, 0) + 1
            ok = hd["min"] >= need
            if not ok:
                rc = 1
            print("      %-13s %-6d %-11d %-9s %s"
                  % (arm, l["d"], hd["min"], l.get("periods"),
                     "ok" if ok else "*** FAIL below %d" % need))
    rc |= empty_arms(per4a, [x for x in ("clean", "certified", "stretch_mid",
                                         "stretch_long", "corpus_i2c")
                             if x in blob], "§4b(a)")
    if nmeas == 0:
        print("      *** FAIL no lane in any arm produced a t_HD;DAT")
        print("          measurement, so the requirement was not checked")
        rc = 1

    print()
    print("    (b) hold ceiling: hold + t_r(max) <= t_VD;DAT(max)")
    print("      \u26d4 THE DESIGN'S HOLD IS THE **MODAL** MEASURED VALUE, not")
    print("      the maximum, and the first version used the maximum. A later")
    print("      unrelated SDA move inside the same long low phase pushed that")
    print("      to 77 cycles and failed two modes for a hold the design never")
    print("      applies -- the clean build measures min = modal = max = 15 on")
    print("      every lane that has a transition to measure.")
    print("      %-13s %-6s %-7s %-9s %-9s %-9s %s"
          % ("arm", "d", "hold", "mode", "t_r(max)", "budget", "verdict"))
    per4b = {}
    for arm in ("clean", "certified", "stretch_mid", "stretch_long"):
        a = blob.get(arm)
        if a is None:
            continue
        for l in a["lanes"]:
            hd = l.get("t_HD_DAT")
            lo = (l.get("t_LOW") or {}).get("min")
            hi = (l.get("t_HIGH") or {}).get("min")
            if not hd or lo is None or hi is None:
                continue
            m = claimable(lo, hi, tc)
            if m is None:
                print("      %-13s %-6d %-7d %-9s %-9s %-9s %s"
                      % (arm, l["d"], hd["modal"], "NONE", "-", "-",
                         "not checked -- this clock claims no mode"))
                continue
            tr = cycles(UM10204_MAX[m]["t_r"])
            budget = cycles(UM10204_MAX[m]["t_VD_DAT"]) - tr
            per4b[arm] = per4b.get(arm, 0) + 1
            ok = hd["modal"] <= budget
            if not ok:
                rc = 1
            print("      %-13s %-6d %-7d %-9s %-9d %-9d %s"
                  % (arm, l["d"], hd["modal"], m.split()[0], tr, budget,
                     "ok" if ok else "*** FAIL hold over the budget"))

    rc |= empty_arms(per4b, [x for x in ("clean", "certified", "stretch_mid",
                                         "stretch_long") if x in blob],
                     "§4b(b)")
    print()
    print("    (c) setup: t_SU;DAT before the next rise, PER LANE")
    print("      %-13s %-6s %-9s %-9s %-11s %s"
          % ("arm", "d", "mode", "need", "worst seen", "verdict"))
    per4c = {}
    for arm in ("clean", "certified", "stretch_mid", "stretch_long"):
        a = blob.get(arm)
        if a is None:
            continue
        for l in a["lanes"]:
            su = l.get("t_SU_DAT")
            lo = (l.get("t_LOW") or {}).get("min")
            hi = (l.get("t_HIGH") or {}).get("min")
            if not su or lo is None or hi is None:
                continue
            m = claimable(lo, hi, tc)
            if m is None:
                print("      %-13s %-6d %-9s %-9s %-11d %s"
                      % (arm, l["d"], "NONE", "-", su["min"],
                         "not checked -- this clock claims no mode"))
                continue
            need_su = tc[m]["t_SU_DAT"]
            per4c[arm] = per4c.get(arm, 0) + 1
            ok = su["min"] >= need_su
            if not ok:
                rc = 1
            print("      %-13s %-6d %-9s %-9d %-11d %s"
                  % (arm, l["d"], m.split()[0], need_su, su["min"],
                     "ok" if ok else "*** FAIL setup below the minimum"))

    rc |= empty_arms(per4c, [x for x in ("clean", "certified", "stretch_mid",
                                         "stretch_long") if x in blob],
                     "§4b(c)")
    print()
    print("    (d) SDA must NOT move while SCL is high")
    print("      ⛔⛔ THE FIX FOR (a) CAN CREATE THIS, which is why it")
    print("      is measured and not reasoned about. If the hold outlasts the")
    print("      low phase the held value lands AFTER the next rise -- data")
    print("      changing while SCL is high, which to any receiver is a START")
    print("      or a STOP. MEASURED at a delay below the hold: 613 of 1718")
    print("      clock periods.")
    print("      ⚠ THE CERTIFIED FRAME IS EXEMPT BY CONTENT, NOT BY CHOICE:")
    print("      it contains OP_START and OP_STOP, which move SDA while SCL is")
    print("      high ON PURPOSE. A pin trace cannot tell those from a")
    print("      violation -- that needs opcode visibility -- so its count is")
    print("      checked for CONSISTENCY against two per transaction instead,")
    print("      and a trace-level separation is OWED.")
    print("      %-13s %-6s %-9s %-9s %s"
          % ("arm", "d", "moves", "periods", "verdict"))
    for arm in ("clean", "stretch_mid", "stretch_long"):
        a = blob.get(arm)
        if a is None:
            continue
        for l in a["lanes"]:
            mv = l.get("sda_moves_in_high")
            ok = (mv == 0)
            if not ok:
                rc = 1
            print("      %-13s %-6d %-9s %-9s %s"
                  % (arm, l["d"], mv, l.get("periods"),
                     "ok" if ok else "*** FAIL SDA moved while SCL was high"))
    cert = blob.get("certified")
    if cert:
        for l in cert["lanes"]:
            # ⛔ a MISSING field is not "0 moves" (10-22 sweep)
            mv = l.get("sda_moves_in_high")
            even = mv is not None and mv % 2 == 0
            if not even:
                rc = 1
            print("      %-13s %-6d %-9s %-9s %s"
                  % ("certified", l["d"], mv, l.get("periods"),
                     "ok -- %d transaction(s) x (START + STOP)" % (mv // 2)
                     if even else "*** FAIL not two per transaction (or not "
                     "measured)"))

    print()
    print("    (e) the MINIMUM LEGAL d the hold implies")
    print("      ⛔ DERIVED, and a NEW constraint the hold introduces: the")
    print("      hold must fit inside the low phase AND leave setup before the")
    print("      rise, so `d > SDA_HOLD + t_SU;DAT(min)`.")
    print("      %-13s %-9s %-13s %-13s %s"
          % ("mode", "hold", "+ t_SU;DAT", "min legal d", "t_LOW floor clears?"))
    for m in MODES:
        mind = need + tc[m]["t_SU_DAT"]
        print("      %-13s %-9d %-13d %-13d %s"
              % (m, need, tc[m]["t_SU_DAT"], mind,
                 "yes (%d)" % tc[m]["t_LOW"] if tc[m]["t_LOW"] >= mind
                 else "*** NO"))
    print("      ⚠ EVERY MODE-LEGAL PROGRAM CLEARS IT, and a program that")
    print("      asks for less NO LONGER RUNS. ⭐ RULED AND IN SILICON (D1):")
    print("      a clocked open-drain action with `d <= SDA_HOLD` sets")
    print("      CONFIG_ERR and halts the engine, so the silent-corruption")
    print("      case this gate used to report as OWED cannot reach a wire.")
    print("      `pe_asm.check_clocked_hold_delay` refuses it statically too,")
    print("      and the boundary is read from the RTL, never typed twice.")
    print("      ⚠ THE **MODE** FLOOR IS STILL OWED (D2 with S): `SDA_HOLD` is")
    print("      a hard floor for every mode, but the column above shows each")
    print("      mode wants MORE, per program and with its own jitter.")

    # -----------------------------------------------------------------
    # 4c. THE TWO MUST-FIRES FOR RULING H (H3)
    # -----------------------------------------------------------------
    print()
    print("  --- 4c. must-fire: the hold is priced at BOTH ends (H3) ---")
    fired = []
    h0 = blob.get("hold0")
    if h0 is None:
        print("    *** MUST-FIRE FAILED: no `hold0` arm, so the floor in (a)")
        print("        has never been seen to fail.")
        rc = 1
    else:
        meas = [l for l in h0["lanes"] if l.get("t_HD_DAT")]
        bad = [l for l in meas if l["t_HD_DAT"]["min"] < need]
        good = bool(meas) and len(bad) == len(meas)
        print("    SDA_HOLD=0  : %d of %d measured lane(s) below %d   %s"
              % (len(bad), len(meas), need,
                 "fires" if good else "*** DID NOT FIRE"))
        if good:
            fired.append("hold0")
        else:
            rc = 1
    hb = blob.get("holdbig")
    if hb is None:
        print("    *** MUST-FIRE FAILED: no `holdbig` arm, so the ceiling in")
        print("        (b)/(d) has never been seen to fail.")
        rc = 1
    else:
        fmp = UM10204_MAX["Fm+ 1 MHz"]
        budget = cycles(fmp["t_VD_DAT"]) - cycles(fmp["t_r"])
        # ⛔⛔ THE ARM'S OWN BOUNDARY, OUT OF ITS OWN DATA. This line used to
        # print a LITERAL `SDA_HOLD=40` while `test/phases_run.sh` decided the
        # actual value, and the two could disagree without a word -- which is
        # what happened: ruling D1 forced the arm from 800 ns to 500 ns, and
        # the label would have gone on claiming 40.
        hb_hold = hb.get("sda_hold")
        lab = ("SDA_HOLD=%d" % hb_hold) if hb_hold is not None \
            else "SDA_HOLD=UNRECORDED"
        moved = [l for l in hb["lanes"] if (l.get("sda_moves_in_high") or 0) > 0]
        over = [l for l in hb["lanes"]
                if l.get("t_HD_DAT") and l["t_HD_DAT"]["min"] > budget]
        # ⛔⛔ AND THE ARM MUST HAVE PRODUCED TRAFFIC AT ALL. Ruling D1 refuses
        # a clocked open-drain action with `d <= SDA_HOLD`, so a `holdbig` hold
        # at or above the image's smallest delay REFUSES THE PROGRAM: the
        # engine halts, no lane measures anything, and `moved`/`over` are both
        # empty -- a must-fire reading as "did not fire" for the one reason
        # that is not a design regression. ⇒ The vacuity is named separately
        # from the failure, because the fix is different: choose a hold between
        # the Fm+ budget and the image's smallest delay.
        measured = [l for l in hb["lanes"] if l.get("t_HD_DAT")]
        good = bool(moved) or bool(over)
        print("    %-12s: %d lane(s) moved SDA while SCL high, %d over "
              "the Fm+ budget of %d   %s"
              % (lab, len(moved), len(over), budget,
                 "fires" if good else "*** DID NOT FIRE"))
        if not measured:
            print("        ⛔ AND NO LANE MEASURED ANYTHING: the arm produced no")
            print("        traffic, so this is VACUOUS rather than a regression.")
            print("        Under D1 a hold at or above the image's smallest")
            print("        delay REFUSES the program (config_err, engine-wide")
            print("        halt). Pick a hold strictly between the Fm+ budget")
            print("        (%d) and the smallest delay in the image." % budget)
        if hb_hold is None:
            print("        ⛔ the arm did not record its own SDA_HOLD, so this")
            print("        verdict cannot be tied to the boundary it ran at")
            print("        -- pass --hold-ns from test/phases_run.sh.")
            rc = 1
        if good:
            fired.append("holdbig")
        else:
            rc = 1
    if len(fired) == 2:
        print("    => both ends priced. Too short fails (a); too long fails")
        print("      (b) or (d). Neither end is a check nobody has seen fail.")

    # -----------------------------------------------------------------
    # 5. C2: the d a mode needs, WITH the measured jitter
    # -----------------------------------------------------------------
    print()
    print("  --- 5. C2: the d each mode needs, and whether d can carry it ---")
    print("    ⛔⛔ `d >= t_LOW(min)` IS NOT THE RULE, AND THE MEASUREMENT IS")
    print("    WHY. t_LOW came out BELOW the programmed d on every lane --")
    # ⛔ THE CLEAN ARM, by name (10-22 sweep): `a` here was whatever arm the
    # §4b(d) loop ended on (stretch_long). Same numbers today, wrong source.
    a = blob.get("clean")
    if a is not None:
        jit = [(l["d"], l["d"] - l["t_LOW"]["min"])
               for l in a["lanes"] if l["mode"] == 0 and l.get("t_LOW")]
        print("    measured shortfall %s at d = %s -- because the LOW"
              % ([j for _d, j in jit], [d for d, _j in jit]))
        print("    dispatch competes under EDF and can be serviced late. The")
        print("    high phase is immune (it is counted from the rise), so only")
        print("    t_LOW needs the margin.")
        worst = max(j for _d, j in jit) if jit else 0
        print()
        print("    %-13s %-11s %-10s %-12s %s"
              % ("mode", "t_LOW min", "+jitter", "d needed", "DLY_W=10 reaches?"))
        for m in MODES:
            need = tc[m]["t_LOW"] + worst
            print("    %-13s %-11d %-10d %-12d %s"
                  % (m, tc[m]["t_LOW"], worst, need,
                     "yes" if need <= 1023 else "*** NO (max 1023)"))
        print("    ⚠ `+jitter` HERE IS AN OBSERVATION, NOT A BOUND. %d is the"
              % worst)
        print("      worst shortfall seen on a 4-lane image; the BOUND is")
        print("      A2's `r_i - C` for the lane, and quoting a measured")
        print("      maximum as a bound is the error this project retracted a")
        print("      universal J for. The d above is therefore a FLOOR to")
        print("      check against A2, not a shipped number.")

    # -----------------------------------------------------------------
    # 6. what was NOT measured
    # -----------------------------------------------------------------
    print()
    print("  --- 6. NOT checked here, so the silence is not a pass ---")
    print("    t_SU;STA, t_HD;STA, t_SU;STO -- need START/STOP conditions, and")
    print("      the clocked images contain none (`OP_START`/`OP_STOP` are")
    print("      separate opcodes the clocked scheme does not emit). Owed")
    print("      against the certified two-action frame, where they do occur.")
    print("    t_r / t_f -- edge RATES are a board and pull-up property; a")
    print("      cycle-resolution trace cannot see them at all.")
    print("    t_BUF, t_SU;STO -> bus-free time between transactions.")

    print()
    print("=" * 78)
    print("  GATE um10204: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * t_HIGH >= d on every open-drain clocked lane, every stretch")
    print("    * must-fire: the pre-fix design misses it at every delay")
    print("    * control arm: push-pull is symmetric, so the bench is not the")
    print("      explanation")
    print("    * measured against a TRANSCRIBED table; this is not foreign")
    print("      certification and does not claim compliance")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
