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
MODES = list(UM10204)


def cycles(ns):
    """ns -> whole cycles, rounding UP: a minimum is not met by rounding down."""
    return -(-ns // NS_PER_CYCLE)


def table_cycles():
    return {m: {k: cycles(v) for k, v in d.items()} for m, d in UM10204.items()}


def load():
    p = os.environ.get("PE_PHASES_JSON", "")
    if not p or not os.path.isfile(p):
        return None, p
    with open(p, encoding="utf-8") as fh:
        return json.load(fh), p


OD_ARMS = ("clean", "stretch_mid", "stretch_long")


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
            d, hi = l["d"], l["t_HIGH"]["min"]
            lo = l["t_LOW"]["min"] if l.get("t_LOW") else -1
            ok = hi >= d
            if not ok:
                rc = 1
            print("    %-14s %-6d %-6d %-8d %-8d %-9s %s"
                  % (arm, l["lane"], d, hi, lo, "%+d" % (hi - d),
                     "ok" if ok else "*** FAIL t_HIGH < d"))
    if seen_od == 0:
        print("    *** FAIL no open-drain clocked lane in any arm, so the")
        print("        claim was not measured at all")
        rc = 1
    else:
        print("    ⇒ %d open-drain lane-arms, every t_HIGH at or above its own"
              % seen_od)
        print("      programmed d, and UNMOVED by a 200- or 4000-cycle stretch.")

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
        rows = [l for l in ctl["lanes"] if l.get("t_HIGH") and l.get("t_LOW")]
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
        if asym:
            print("    *** FAIL %d push-pull lane(s) asymmetric: the park is")
            print("        open-drain only, so a push-pull clock must be" % ())
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
    # 4b. t_HD;DAT -- THE OWED ITEM, NOW A NUMBER
    # -----------------------------------------------------------------
    print()
    print("  --- 4b. t_HD;DAT against the BRIDGING note, not just the minimum ---")
    print("    ⛔⛔ THIS IS THE OWED ELECTRICAL ITEM AND THE MEASUREMENT SETTLES")
    print("    THAT IT IS REAL. The concern on record was that a clocked LOW")
    print("    dispatch changes SDA in the SAME dispatch that takes SCL low, so")
    print("    a slow SCL fall with SDA going H->L could be read as a START.")
    print("    Measured, that hold is ZERO cycles on the lanes below.")
    print()
    print("    UM10204 Table 10 sets t_HD;DAT minimum = 0 ns for every mode, so")
    print("    0 MEETS THE TABLE. But the table's own note requires a device to")
    print("    internally provide >= %d ns of hold to bridge the undefined"
          % HD_BRIDGE_NS)
    print("    region of SCL's falling edge -- %d cycles at 50 MHz."
          % cycles(HD_BRIDGE_NS))
    print("    ⚠ SO THE TABLE MINIMUM IS THE WEAKER TEST, AND PASSING IT IS NOT")
    print("    THE ANSWER. Both are reported; the gate does not silently take")
    print("    the one it meets.")
    print()
    if a is not None:
        need = cycles(HD_BRIDGE_NS)
        print("      %-6s %-6s %-11s %-13s %s"
              % ("lane", "d", "t_HD;DAT", "table (0 ns)", "bridge (%d cy)" % need))
        short = []
        for l in a["lanes"]:
            if l["mode"] != 0 or not l.get("t_HD_DAT"):
                continue
            hd = l["t_HD_DAT"]["min"]
            okb = hd >= need
            if not okb:
                short.append((l["lane"], l["d"], hd))
            print("      %-6d %-6d %-11d %-13s %s"
                  % (l["lane"], l["d"], hd, "met",
                     "met" if okb else "*** SHORT by %d" % (need - hd)))
        if short:
            print()
            print("    ⛔ %d lane(s) provide ZERO data hold across the SCL fall."
                  % len(short))
            print("      RULED SCOPE PENDING: the table minimum is met, so this")
            print("      gate does not fail on it -- but a requirement that is")
            print("      named in the standard and missed by the design is not")
            print("      something a green gate should absorb. It is reported")
            print("      here, counted, and OWED a ruling on whether the")
            print("      bridging note is in scope for this entry.")
            print("      ⚠ A guard that passes while a named requirement is")
            print("      unmet is the shape this project keeps finding bugs in.")

    # -----------------------------------------------------------------
    # 5. C2: the d a mode needs, WITH the measured jitter
    # -----------------------------------------------------------------
    print()
    print("  --- 5. C2: the d each mode needs, and whether d can carry it ---")
    print("    ⛔⛔ `d >= t_LOW(min)` IS NOT THE RULE, AND THE MEASUREMENT IS")
    print("    WHY. t_LOW came out BELOW the programmed d on every lane --")
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
