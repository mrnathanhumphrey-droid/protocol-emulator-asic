"""EVERY IMAGE IN THE ONE UNIVERSE HAS THE BOUNDS ITS LANES NEED.

⛔⛔ WHY (Wilson 10-18, the image-universe audit). Eight tools each listed
images their own way, so the bound writers and the bench disagreed about which
images exist: the tb_cktx arms probe_cov_pindiv (clocked open-drain lane 3) and
probe_cov_cemodes (lane 0) had no clocked A2 bound, and the bench ran them with
A2 switched off, printing "NO BOUND SUPPLIED". Nothing was red.
⇒ Over `model/image_universe.py` (the ONE list every writer and gate now uses):
  G1  every image with a clocked open-drain lane has a clocked A2 record, and
      the record covers every such lane       (test/clocked_a2_bounds.json)
  G2  every image with an unclocked SHIFT has a response-bound record
                                              (test/lane_response_bounds.json)
  G3  the bench runner fails CLOSED: a clocked image with no record is a
      refused arm (`benchset.a2_slack_arg` raises, naming it), and the only
      escape, `benchset.A2_UNBOUNDED_EXEMPT`, carries a reason per entry
  G4  names are unique: a byte-identical copy is de-duplicated and LISTED, a
      different image under a known name is a hard error
  G5  every clocked image is in a run_recert class -- at least one; corpus_all5
      is in both I2C and SPI, one lane each (Wilson 10-19:
      corpus_spim25 sat unclassed from 6c919bc because run_recert is local
      and nothing in CI asked); a stale class is red too
"Clocked open-drain" and "unclocked SHIFT" are decided by the WRITER's own
functions (`program_a2.lane_set`, `program_a2.is_clocked`), not a second copy.

MUST-FIRES (each must turn the gate red):
  M1 the i2c_fram_fpga.hex record removed from the clocked file
  M2 a response record removed from the response file
  M3 probe_cov_pindiv's bound removed -> its bench arm's lookup raises, naming it
  M4 a DIFFERENT tx_image.hex in a scanned directory -> NameCollision
     (a temporary directory added to the scan; nothing in the tree is touched)
  M5 corpus_spim25's run_recert class deleted -> red naming it
and the controls that must stay GREEN: a byte-identical tx_image.hex copy is
de-duplicated and listed; a non-clocked image with no record (tx_image) gets
no bound and no refusal.
POSITIVE TOKEN: `GATE image-bounds: PASSED`.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                     # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import benchset                                                   # noqa: E402
import gate_degenerate_fields as dgf                              # noqa: E402
import image_universe as U                                        # noqa: E402
import pe_isa as I                                                # noqa: E402
import program_a2 as P                                            # noqa: E402

CLOCKED_JSON = os.path.join(ROOT, "test", "clocked_a2_bounds.json")
RESP_JSON = os.path.join(ROOT, "test", "lane_response_bounds.json")


def needs(img):
    """(clocked open-drain lanes, has an unclocked SHIFT) by the writer's own
    functions."""
    ck = sorted(str(r["lane"]) for r in P.lane_set(img)[0] if r["clocked_od"])
    tx = any(a["op"] == I.OP_SHIFT and not P.is_clocked(h, a)
             for _ln, h, acts in P.lanes_of(img) for a in acts)
    return ck, tx


def audit(imgs, clocked, resp):
    """Problems for G1 + G2 over `imgs` = [(name, image)]."""
    probs = []
    for name, img in imgs:
        ck, tx = needs(img)
        if ck:
            rec = clocked.get(name)
            if rec is None:
                probs.append("%s: clocked open-drain lane(s) %s and NO clocked "
                             "A2 record" % (name, ",".join(ck)))
            else:
                miss = [ln for ln in ck if ln not in rec.get("lanes", {})]
                if miss:
                    probs.append("%s: clocked lane(s) %s missing from its A2 "
                                 "record" % (name, ",".join(miss)))
        if tx and name not in resp:
            probs.append("%s: an unclocked SHIFT and NO response-bound record"
                         % name)
    return probs


def class_problems(clocked, classes):
    """(unclassed, stale) problems for G5: run_recert's clocked images vs its
    classes. Pure, so M5 can price it."""
    unc = ["%s: a clocked image in NO run_recert class (I2C / SPI / "
           "NOT_CERTIFIABLE)" % n for n in sorted(set(clocked) - set(classes))]
    stale = ["%s: a run_recert class names an image that is not clocked (or "
             "not in the universe) -- stale" % n
             for n in sorted(set(classes) - set(clocked))]
    return unc, stale


def main() -> int:
    print()
    print("=" * 78)
    print("  EVERY IMAGE IN THE ONE UNIVERSE HAS THE BOUNDS ITS LANES NEED")
    print("=" * 78)
    rc = 0

    def say(ok, what):
        nonlocal rc
        print("    %-64s %s" % (what, "ok" if ok else "*** FAIL"))
        if not ok:
            rc = 1

    u = U.default()
    U.report(u)
    say(not u.probs, "the universe builds (no generator failure / absent "
        "arm image)%s" % ("" if not u.probs else ": " + "; ".join(u.probs)))
    # v2: board images, translated (image_universe.board_as_v2)
    imgs, board = U.board_as_v2([(n, dgf.load(p)) for n, p in u.items()])
    with open(CLOCKED_JSON, encoding="utf-8") as fh:
        clocked = json.load(fh)
    with open(RESP_JSON, encoding="utf-8") as fh:
        resp = json.load(fh)

    nck = sum(1 for _n, img in imgs if needs(img)[0])
    ntx = sum(1 for _n, img in imgs if needs(img)[1])
    print("  %d images: %d with a clocked open-drain lane, %d with an "
          "unclocked SHIFT" % (len(imgs), nck, ntx))
    probs = audit(imgs, clocked, resp)
    for p in probs:
        print("    *** %s" % p)
    say(not probs, "G1/G2: every image has the bounds its lanes need")

    # G3: the bench runner, fail-closed
    ex = benchset.A2_UNBOUNDED_EXEMPT
    say(all(isinstance(v, str) and v.strip() for v in ex.values()),
        "G3: every A2_UNBOUNDED_EXEMPT entry carries a reason (%d entr%s)"
        % (len(ex), "y" if len(ex) == 1 else "ies"))
    bad = []
    byname = dict(imgs)
    for name, path in u.items():
        if needs(byname[name])[0] and name not in ex:
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            try:
                arg = benchset.a2_slack_arg(rel)
            except RuntimeError as exc:
                arg = None
                print("    *** %s" % exc)
            if not arg:
                bad.append(name)
    say(not bad, "G3: every clocked image's bench lookup returns its bound"
        "%s" % ("" if not bad else " (not: %s)" % ", ".join(bad)))

    # G5: every clocked image is classed in run_recert (Wilson 10-19)
    import run_recert as RC
    ck5 = RC.clocked_images()
    cl5 = RC.classes()
    unc, stale = class_problems(ck5, cl5)
    for q in unc + stale:
        print("    *** %s" % q)
    say(not unc and not stale,
        "G5: every clocked image (%d) is in a run_recert class "
        "(I2C %d, SPI %d, NOT_CERTIFIABLE %d of which %d derived)"
        % (len(ck5), len(RC.I2C), len(RC.SPI), len(RC.NOT_CERTIFIABLE),
           len(RC.derived_not_certifiable())))

    print()
    print("  --- must-fires (each must be RED) and controls (GREEN) ---")
    # M5: a class entry deleted -> red naming that image
    cl_m = {k: v for k, v in cl5.items() if k != "corpus_spim25.hex"}
    m5 = class_problems(ck5, cl_m)[0]
    say(any("corpus_spim25.hex" in q for q in m5),
        "M5 corpus_spim25's class deleted -> red, naming it")
    # M1
    c2 = copy.deepcopy(clocked)
    c2.pop("i2c_fram_fpga.hex", None)
    m1 = audit(imgs, c2, resp)
    say(any("i2c_fram_fpga.hex" in p for p in m1),
        "M1 i2c_fram_fpga record removed -> red")
    # M2
    victim = sorted(resp)[0]
    r2 = {k: v for k, v in resp.items() if k != victim}
    m2 = audit(imgs, clocked, r2)
    say(any(victim in p for p in m2),
        "M2 response record %s removed -> red" % victim)
    # M3
    c3 = copy.deepcopy(clocked)
    c3.pop("probe_cov_pindiv.hex", None)
    try:
        benchset.a2_slack_arg("test/probe_cov_pindiv.hex", blob=c3)
        m3 = False
    except RuntimeError as exc:
        m3 = "probe_cov_pindiv.hex" in str(exc)
    say(m3, "M3 pindiv bound removed -> its bench arm's lookup refuses, "
        "naming it")
    # control: a non-clocked image with no record is not refused
    try:
        none = benchset.a2_slack_arg("test/tx_image.hex", blob={})
        ctl = none is None
    except RuntimeError:
        ctl = False
    say(ctl, "control: tx_image (no clocked lane, no record) -> no bound, "
        "no refusal")
    # M4 + control, in a temporary directory added to the scan
    tmp = tempfile.mkdtemp(prefix="probe_imgu_")
    try:
        src = os.path.join(ROOT, "test", "tx_image.hex")
        shutil.copyfile(src, os.path.join(tmp, "tx_image.hex"))
        same = U.scan(dirs=U.DIRS + (tmp,), arms=False)
        say(any(n == "tx_image.hex" and o.startswith(tmp)
                for n, _k, o in same.dups),
            "control: byte-identical tx_image copy -> de-duplicated + listed")
        with open(os.path.join(tmp, "tx_image.hex"), "a",
                  encoding="ascii") as fh:
            fh.write("\n00\n")
        try:
            U.scan(dirs=U.DIRS + (tmp,), arms=False)
            m4 = False
        except U.NameCollision as exc:
            m4 = "tx_image.hex" in str(exc)
        say(m4, "M4 a DIFFERENT tx_image.hex in a scanned dir -> hard error")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if rc == 0 and board:
        v, why = U.board_stale_verdict("model/gate_image_bounds.py", board)
        print("  stale_records: %s -- %s" % (v, why))
        if v == "STALE":
            import stale_records as SR
            print(SR.token("image-bounds", why))
            return 0
        if v == "FAIL":
            rc = 1
    if rc == 0:
        print("GATE image-bounds: PASSED")
    else:
        print("GATE image-bounds: FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(main())
