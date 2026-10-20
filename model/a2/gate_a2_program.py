"""RULING S -- A2's post-HIGH gap bound belongs to (PROGRAM, LANE), adjudicated.

⛔⛔ THE DEFECT. `test/clocked_conform.vh` held ONE number, `CK_GAP_SLACK = 8`,
derived from the A2 MODEL's shipped lane set and enforced on `ckod` -- a
different lane set. Derived over `ckod`'s own four lanes the bounds are 8 / 11 /
17 / 18, so the shared 8 was tighter than the worst case of three of them and
held only because the measured schedule was gentler. Every other clocked arm ran
unbounded. This is the narrow-lane-set error this session has now made four
times, in its original form.

WHAT THIS GATE HOLDS:

  1. `test/clocked_a2_bounds.json` is CURRENT. It is regenerated in memory from
     the images on disk and compared; a stale file means some arm is being held
     to a bound for a program that no longer exists.
  2. NO BOUND IS TYPED. The bench carries no slack constant, and every arm
     `test/benchset.py` plans gets `+A2SLACK` equal to the generated row.
  3. THE MUST-FIRE (`test/a2_run.sh`): `ckheavy`, an ADMISSIBLE program
     heavier than `corpus_i2c` (ruling DT-C; it was `ckdense` until that
     failed 1.6a under W1), PASSES under its own budgets and FAILS under
     `corpus_i2c`'s. Without both halves the per-program derivation would be
     indistinguishable on the bench from one shared number.
  4. OVERLOADED PROGRAMS ARE NAMED, with the utilisation that leaves them
     unbounded, rather than given a number.

⚠ `J` IS CONSERVATIVE BY CONSTRUCTION, and declared: `program_a2` takes `J` from
the program's MINIMUM ACTION DELAY, which is a lower bound on the refill-bearing
`d_min` §1 computes. So `J` -- and with it `r_i` and the budget -- can only come
out LARGER than exact, never smaller: the bound stays sound and may be loose.
It changes nothing for any program with `d >= D*` (all of them `J = 1` either
way); it loosens the `ckhold_*` images, whose delays sit just above
`SDA_HOLD`.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
sys.path.insert(0, os.path.join(ROOT, "model"))

import gate_degenerate_fields as dgf                              # noqa: E402
import program_a2                                                 # noqa: E402
import image_universe                                             # noqa: E402
from pyrta_src import pinned_pyrta                                # noqa: E402

#: Ruling S's must-fire subject (DT-C). `test/a2_run.sh` measures the same one.
SUBJECT = "ckheavy_image.hex"


def load_measurement():
    p = os.environ.get("PE_A2_JSON", "")
    if not p:
        cand = os.path.join(ROOT, "probe_a2", "a2.json")
        if os.path.isfile(cand):
            p = cand
    if not p or not os.path.isfile(p):
        return None, p
    with io.open(p, encoding="utf-8") as fh:
        return json.load(fh), p


#: the fields only a pyRTA run can fill. Skipped when comparing without it,
#: so CI never reports a stale row merely because it could not run pyRTA.
# `budget` (HC1-B) labels a slack as pyRTA's or EMPIRICAL; it exists only where
# the slack does, so it is pyRTA-side like the slack itself.
PYRTA_ONLY = {"r_pyrta", "slack", "r_floor", "why", "budget"}


def stale_rows(on_disk, fresh, with_pyrta):
    """Image names whose committed row no longer matches a re-derivation."""
    stale = sorted(set(on_disk) ^ set(fresh))
    for n in sorted(set(on_disk) & set(fresh)):
        a, b = on_disk[n], fresh[n]
        # ⭐ `w1_pyrta` (ruling A8) is pyRTA's own W1 term: compared only when
        # pyRTA is present, like the per-lane pyRTA column.
        tskip = {"lanes"} | (set() if with_pyrta else {"w1_pyrta"})
        top = ({k: a.get(k) for k in a if k not in tskip}
               != {k: b.get(k) for k in b if k not in tskip})
        if top or set(a["lanes"]) != set(b["lanes"]):
            stale.append(n)
            continue
        skip = set() if with_pyrta else PYRTA_ONLY
        for ln in a["lanes"]:
            ea, eb = a["lanes"][ln], b["lanes"][ln]
            if any(ea.get(k) != eb.get(k) for k in ea if k not in skip):
                stale.append(n)
                break
    return sorted(set(stale))


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("  RULING S -- A2's POST-HIGH BOUND, PER (PROGRAM, LANE)")
    print("=" * 78)

    # ---- 1. the generated bounds are current --------------------------
    print()
    print("  --- 1. test/clocked_a2_bounds.json matches the images on disk ---")
    # ⛔⛔ pyRTA IS NOT REQUIRED HERE, AND THE FIRST VERSION REQUIRED IT. This
    # gate is in `ci/run_gates.sh`, and pyRTA is deliberately absent from CI
    # (not vendored; every pyRTA-primary gate runs under `run_a2.py` by hand).
    # It went red at 20 of 22 in CI while passing here, because a pyRTA clone
    # happens to sit in a scratch directory on this box.
    # ⇒ CI re-derives EVERYTHING EXCEPT THE pyRTA COLUMN -- lane set, U, J and
    #   our own recurrence -- which is what catches an image that changed
    #   without the JSON being regenerated. The pyRTA column, and so the bench
    #   budgets, is re-derived by `gate_a2_bounds_pyrta.py` under `run_a2.py`,
    #   RED without pyRTA. When pyRTA IS present here, it is compared too.
    # ⛔ P6: an UNPINNED pyRTA counts as absent here, so the pyRTA column
    # is compared only against the pinned witness that produced it.
    src = pinned_pyrta()
    if not os.path.isfile(program_a2.OUT_JSON):
        print("    *** FAIL test/clocked_a2_bounds.json is absent -- every")
        print("        clocked arm would run with A2's upper bound OFF.")
        return 1
    with io.open(program_a2.OUT_JSON, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    # ⛔ HC1-B: re-derived through `budgets()`, the SAME path that writes the
    # json (refuse-to-emit, NO_RTA_BUDGET's empirical rows, the `budget`
    # label). Re-deriving through `derive()` alone compared the file against
    # a different producer and called every row stale.
    try:
        fresh = program_a2.budgets(src)
    except RuntimeError as exc:
        print("    *** FAIL program_a2 refused to emit: %s" % exc)
        return 1
    stale = stale_rows(on_disk, fresh, with_pyrta=bool(src))
    if stale:
        print("    *** FAIL stale for: %s" % ", ".join(sorted(set(stale))))
        print("        Run `python model/a2/program_a2.py`. A stale row holds an")
        print("        arm to the bound of a program that no longer exists.")
        rc = 1
    else:
        print("    current -- %d image(s) re-derived and identical" % len(fresh))
        print("    %s" % ("pyRTA column compared too (pyRTA present)" if src
                         else "pyRTA column NOT re-derived here -- pyRTA is "
                              "not in CI by design; `gate_a2_bounds_pyrta.py` "
                              "under `run_a2.py` owns it"))

    # ---- 1c. WF2 / V3-T: the per-lane response bounds are current ----------
    # Same rule as 1: CI re-derives everything but the pyRTA column (images,
    # lanes, our recurrence, T, D_tol); with pyRTA present it is compared too.
    print()
    print("  --- 1c. test/lane_response_bounds.json matches the images ---")
    if not os.path.isfile(program_a2.RESP_JSON):
        print("    *** FAIL test/lane_response_bounds.json is absent -- every")
        print("        unclocked arm's V3-T would run with no bound.")
        return 1
    with io.open(program_a2.RESP_JSON, encoding="utf-8") as fh:
        rb_disk = json.load(fh)
    rb_fresh = program_a2.response_bounds(src)
    rb_stale = sorted(set(rb_disk) ^ set(rb_fresh))
    for n in sorted(set(rb_disk) & set(rb_fresh)):
        a, b = rb_disk[n]["lanes"], rb_fresh[n]["lanes"]
        if set(a) != set(b):
            rb_stale.append(n)
            continue
        for ln in a:
            keys = {"r_ours", "T", "dtol"} | ({"r_pyrta"} if src else set())
            if any(a[ln].get(k) != b[ln].get(k) for k in keys):
                rb_stale.append(n)
                break
    if rb_stale:
        print("    *** FAIL stale for: %s" % ", ".join(sorted(set(rb_stale))))
        print("        Run `python model/a2/program_a2.py`.")
        rc = 1
    else:
        print("    current -- %d image(s) re-derived and identical%s"
              % (len(rb_fresh), " (pyRTA column too)" if src else
                 " (pyRTA column not re-derived: not in CI by design)"))

    # ---- 1b. Z5 / DT-F: the CI floor is never looser than pyRTA -----------
    # ⛔⛔ CI has no pyRTA, so every CI-side refusal (pe_asm's mode floor and
    # 1.6a, gate_admissible_images' QUEUE) rests on OUR recurrence alone. After
    # ruling Z1 it is >= pyRTA on every lane we have; that is checked here on
    # the COMMITTED pyRTA column, for every ADMISSIBLE program, rather than
    # assumed -- a lane where ours < pyRTA is one where CI would accept what
    # the published bound refuses.
    print()
    print("  --- 1b. CI floor (ours) >= pyRTA, every lane of every admissible "
          "program ---")
    import gate_admissible_images as ga
    n_ok, below = 0, []
    for name, row in sorted(on_disk.items()):
        # ⛔ by NAME through program_a2's resolver: the bounds file holds
        # fpga/images/ entries too (10-18), and a test/-only path crashed here
        img = dgf.load(image_universe.resolve(name))
        if ga.conditions(name, img)[0]:
            continue                      # non-admissible: declared in N1
        for ln, e in sorted(row["lanes"].items()):
            # ⛔ RULING E: an admissible lane where pyRTA gave a bound but
            # OUR recurrence gave none is a FAILURE, not a skip.
            # `program_a2` records `r_ours = None` when the recurrence RAISES,
            # and skipping it here would drop exactly that lane from the
            # ours >= pyRTA check -- a guard passing because of the defect.
            if e.get("r_pyrta") is not None and e.get("r_ours") is None:
                below.append((name, ln, None, e["r_pyrta"]))
                continue
            if e.get("r_pyrta") is None or e.get("r_ours") is None:
                continue
            if e["r_ours"] >= e["r_pyrta"]:
                n_ok += 1
            else:
                below.append((name, ln, e["r_ours"], e["r_pyrta"]))
    for name, ln, o, p in below:
        if o is None:
            print("    *** %s lane %s: OUR recurrence gave no bound (pyRTA %d) "
                  "-- see the lane's `why`" % (name, ln, p))
        else:
            print("    *** %s lane %s: ours %d < pyRTA %d -- CI's floor is "
                  "looser than the published bound" % (name, ln, o, p))
        rc = 1
    print("    %d admissible lane(s): ours >= pyRTA on every one%s"
          % (n_ok, "" if not below else " EXCEPT the above"))

    # ---- 2. no bound is typed --------------------------------------------
    print()
    print("  --- 2. no bound is typed anywhere ---")
    vh = io.open(os.path.join(ROOT, "test", "clocked_conform.vh"),
                 encoding="utf-8").read()
    if re.search(r"localparam\s+integer\s+CK_GAP_SLACK", vh):
        print("    *** FAIL `CK_GAP_SLACK` is back in clocked_conform.vh -- a")
        print("        shared constant is the defect this ruling removed")
        rc = 1
    else:
        print("    the bench carries no slack constant")
    import benchset                                               # noqa: E402
    recs, probs = benchset.plan()
    checked, mism = 0, []
    for r in recs:
        img = next((a.split("=", 1)[1] for a in r["args"]
                    if a.startswith("+IMG=")), None)
        if img is None:
            continue
        want = benchset.a2_slack_arg(img)
        have = next((a for a in r["args"] if a.startswith("+A2SLACK=")), None)
        if want is None and have is None:
            continue
        checked += 1
        if want != have:
            mism.append((r["top"], r["label"], want, have))
    for top, lab, want, have in mism:
        print("    *** FAIL %s/%s carries %s, the generated row says %s"
              % (top, lab, have, want))
        rc = 1
    if not mism:
        print("    %d clocked arm(s), every one carrying its generated budget"
              % checked)

    # ---- 3. the must-fire ------------------------------------------------
    print()
    print("  --- 3. must-fire: a LIGHTER set's bound on a HEAVIER program ---")
    meas, mpath = load_measurement()
    if meas is None:
        print("    *** FAIL no measurement at PE_A2_JSON='%s'" % mpath)
        print("        `bash test/a2_run.sh <outdir>` produces it. RED rather")
        print("        than skipped: without it the per-program bound has never")
        print("        been seen to do anything a shared number would not.")
        rc = 1
    else:
        own, light = meas.get("own") or {}, meas.get("light") or {}
        # ⛔ U and J READ from the committed bounds, never typed: the subject
        # was re-spanned by ruling W and a typed "0.518" outlived it
        with io.open(program_a2.OUT_JSON, encoding="utf-8") as fh:
            row = json.load(fh).get(SUBJECT, {})
        print("    %s (U = %s, J = %s) under two budgets:"
              % (SUBJECT, row.get("U"), row.get("J")))
        # ⛔ RULING DT-C: THE SUBJECT MUST BE ADMISSIBLE. A must-fire on a
        # program outside the model (ckdense fails 1.6a under W1) proves
        # nothing about the bound the model gives -- so admissibility is
        # derived here, not assumed from the subject's name.
        import gate_admissible_images as ga
        sub_img = dgf.load(os.path.join(ROOT, "test", SUBJECT))
        conds = ga.conditions(SUBJECT, sub_img)[0]
        print("    subject admissibility: %s"
              % ("ADMISSIBLE (no OVERLOAD/PORT/PINMAP/QUEUE)" if not conds
                 else "*** violates %s" % sorted(conds)))
        if conds:
            rc = 1
        print("      %-7s %-18s %-8s %-6s %s"
              % ("arm", "budget", "verdict", "late", "widest per lane"))
        for nm, r in (("own", own), ("light", light)):
            print("      %-7s %-18s %-8s %-6s %s"
                  % (nm, r.get("budget"), r.get("verdict"), r.get("late"),
                     r.get("lane_widest")))
        if own.get("verdict") != "ok":
            print("    *** FAIL the subject's OWN budget did not hold -- the")
            print("        per-program derivation is unsound for it")
            rc = 1
        if light.get("verdict") != "red":
            print("    *** FAIL the lighter budget did NOT fail on the heavier")
            print("        program -- on the bench the per-program bound is")
            print("        indistinguishable from one shared number")
            rc = 1
        if own.get("verdict") == "ok" and light.get("verdict") == "red":
            print("    => holds under its own bound, fails under the lighter one.")
            print("    it fires on %s release(s), widest per lane %s against"
                  % (light.get("late"), light.get("lane_widest")))
            print("    the light budget -- the gate requires the verdict, not a")
            print("    count.")

    # ---- 4. programs with no bound ----------------------------------------
    print()
    print("  --- 4. programs whose lane set has NO finite bound ---")
    none = [(n, r) for n, r in sorted(fresh.items())
            if any(e["slack"] is None for e in r["lanes"].values())]
    for n, r in none:
        print("    %-24s U = %.3f -- overloaded, so unbounded; the bench"
              % (n, r["U"]))
        print("    %-24s reports its lateness WITHOUT a verdict" % "")
    if not none:
        print("    none")

    # ---- must-fire: the currency check can see a stale row --------------
    # ⛔ PRICED WITHOUT pyRTA, because that is how it runs in CI. A copy of the
    # committed rows has ONE non-pyRTA field moved (a lane's `T`) and must be
    # reported; the untouched copy must not. A comparison that skipped too
    # much -- the risk of a skip-list -- would pass both.
    print()
    print("  --- must-fire: the currency check sees a stale row ---")
    import copy as _copy
    bent = _copy.deepcopy(on_disk)
    victim = next(n for n in sorted(bent) if bent[n]["lanes"])
    ln0 = sorted(bent[victim]["lanes"])[0]
    bent[victim]["lanes"][ln0]["T"] += 1
    hit = victim in stale_rows(bent, fresh, with_pyrta=False)
    clean = not stale_rows(on_disk, fresh, with_pyrta=False)
    print("    a lane's T moved by one is reported stale    %s"
          % ("ok" if hit else "*** MISSED"))
    print("    the committed rows read as current           %s"
          % ("ok" if clean else "*** FALSE STALE"))
    if not (hit and clean):
        rc = 1

    # ---- must-fire: an EDGE-PACED lane takes its period from T_ext ---------
    # ⛔ Wilson 10-18 ruling 3. The SPI target's SHIFT delay (20) is the gap
    # AFTER a bit; taking it as T judged the lane at the wrong rate. Built in
    # memory from pe_proto.SPITarget (no image file needed).
    print()
    print("  --- must-fire: an edge-paced lane's period is T_ext ---")
    sys.path.insert(0, os.path.join(ROOT, "model"))
    import pe_asm
    import pe_proto
    tg = pe_proto.SPITarget(mode=0, sck=4, mosi_pin=5)
    lanes_t, hdr_t = {0: tg.program()}, {0: tg.header()}
    try:
        pe_proto.image(lanes_t, hdr_t)
        print("    pe_asm, no T_ext: *** ACCEPTED (an edge-paced lane certified)")
        rc = 1
    except pe_asm.Reject as e:
        ok0 = "EDGE-PACED" in str(e)
        print("    pe_asm, no T_ext: REFUSED (%s...)  %s"
              % (str(e)[:44], "red ok" if ok0 else "*** wrong reason"))
        rc |= 0 if ok0 else 1
    # the build declares its T_ext (the master's claimed 1 MHz): accepted
    timg = pe_proto.image(lanes_t, hdr_t, t_ext=tg.t_ext())
    print("    pe_asm, T_ext 50 declared at build: ACCEPTED  ok")
    try:
        program_a2.lane_set(timg, t_ext={})
        print("    lane_set, no T_ext: *** ACCEPTED")
        rc = 1
    except program_a2.EdgePacedNoTExt:
        print("    lane_set, no T_ext: REFUSED  red ok")
    l1 = program_a2.lane_set(timg, t_ext={0: 50})[0][0]["blane"]
    ok1 = l1.T == 50 and l1.D_tol == 17
    print("    T_ext 50 (1 MHz): T %d, D_tol %d   %s"
          % (l1.T, l1.D_tol, "ok" if ok1 else "*** WRONG (want 50, 17)"))
    l2 = program_a2.lane_set(timg, t_ext={0: 25})[0][0]["blane"]
    ok2 = l2.T == 25 and l2.D_tol == 4
    print("    T_ext 25 (2 MHz): T %d, D_tol %d   %s -- the budget the 9-cycle"
          % (l2.T, l2.D_tol, "ok" if ok2 else "*** WRONG (want 25, 4)"))
    print("      shipped r cannot meet (gate_reactive_2mhz: 2 MHz FAILS)")
    if not (ok1 and ok2):
        rc = 1

    print()
    print("  --- 5. what this gate does NOT check ---")
    print("    ⚠ J IS CONSERVATIVE: taken from the minimum ACTION delay, a")
    print("      lower bound on §1's refill-bearing d_min, so budgets can only")
    print("      be looser than exact. No change for any program at d >= D*.")
    print("    ⚠ THE BOUND IS A2's MODEL OF THE ENGINE, not the engine. It is")
    print("      checked against the bench on every swept clocked arm, which")
    print("      is what makes it more than arithmetic.")

    print()
    print("=" * 78)
    print("  GATE a2-program: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
