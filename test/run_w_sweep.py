"""RULING W -- THEOREM 3 ON THE BENCH, AND THE D* SWEEP THAT FEEDS THE GATE.

`test/tb_w.v` measures, per lane: the conclusion's violations (a decision that
found its head slot invalid), the slack the refills left, the most slots owed
at one instant, refills served ahead of an owed one by branch, worst R_i and
the smallest same-lane dispatch gap. This script owns the arms and the
verdicts.

TWO MODES:
  (default)  THE LIVE SUBSET, in CI, 200k cycles each:
               u20       20 20 20 20 20     must be clean (0 violations)
               m20       20 21 22 23 24     must be clean
               u18       18 18 18 18 18     MUST-FIRE: below D*, must violate
               slow_u20  u20 on the SLOW-REFILL MUTANT -- must violate
  --full     THE SWEEP (ruling W1), ~35 min with 3 jobs: five-lane families
             at d = 19, 20, 21, 22, 25, 30, 40, 60, the must-fires, and the 12
             shipped admissible images; 1M cycles synthetic, 200k images.
             Writes `model/a2/sweep_w.json`, which `gate_j_program` checks.
             The record carries the sha256 of the RTL it ran on, so an RTL
             change makes it STALE and the gate red until this is re-run.

⭐ THE SLOW-REFILL MUTANT IS BUILT, NOT SHIPPED. Three landmark substitutions
make the fetch port idle `L_REFILL` = 4 cycles after every capture, so each
refill costs 8 cycles: at d = 20 five lanes then ask for 40 cycles of port per
20. It is written to the scratch directory from `src/pe_engine.v`'s own text --
`src/` is never touched, so lock hygiene does not charge a harden for it -- and
a landmark that does not match exactly once is a failure, not a skip.

⛔ A CLEAN VERDICT NEEDS DISPATCHES. Zero violations from a run in which a
lane never consumed a refill is the bench not running, not the theorem
holding, so every clean arm must show every lane consuming.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool, scratch_sub  # noqa: E402  ruling V
import sim_run                                   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_w"))
RECORD = os.path.join(ROOT, "model", "a2", "sweep_w.json")
SRCS = ["pe_engine.v", "pe_store.v", "project.v"]

#: scratch-built mutants this file kills (gate_mutant_kills' SCRATCH table)
SCRATCH_MUTANTS = {
    "S_W4_SLOW_REFILL": "the fetch port idles L_REFILL cycles after every "
                        "capture, so each refill costs 8 cycles; u20 must "
                        "violate Theorem 3's conclusion",
    "S_PR_CKSTALE": "ruling PR2: the dispatch no longer loads `cur_ck`, so "
                    "the registered clock pin goes stale on the first "
                    "dispatch to a lane with a different clock pin; "
                    "`test/inv_curck.vh` must fire on m20",
}


def ckstale_subs():
    """(landmark, replacement) for S_PR_CKSTALE: drop the dispatch-time load
    of the registered clock pin. A Verilog spec, not stored numbers."""
    return [("                     cur_ck  <= w_ck;          "
             "// PR2: == l_clkpin[winner]\n", "")]


def slow_subs():
    """(landmark, replacement) for the slow-refill mutant; each landmark must
    occur exactly once. A Verilog spec, not stored numbers."""
    return [
        ("  reg                   pbr1;",
         "  reg                   pbr1;\n  reg [2:0] pslow = 3'd0;  // W4 SLOW-REFILL MUTANT"),
        ("          P_SCAN: begin\n",
         "          P_SCAN: if (pslow != 3'd0) pslow <= pslow - 3'd1; else begin\n"),
        ("            pst       <= P_SCAN;\n            // ⛔ TF3",
         "            pst       <= P_SCAN;\n            pslow     <= 3'd4;  // W4: +L_REFILL\n"
         "            // ⛔ TF3"),
    ]


def src_sha256():
    """sha256 per RTL source, line endings normalised so a Windows checkout
    and CI agree on the same commit."""
    out = {}
    for s in SRCS:
        with open(os.path.join(ROOT, "src", s), "rb") as fh:
            out[s] = hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()
    return out


def slow_engine(tag="slow", subs=slow_subs, what="slow-refill mutant"):
    with open(os.path.join(ROOT, "src", "pe_engine.v"), encoding="utf-8",
              newline="") as fh:
        txt = fh.read().replace("\r\n", "\n")
    for a, b in subs():
        txt = scratch_sub(txt, a, b, "%s (%r)" % (what, a[:50]))
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "pe_engine_%s.v" % tag)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt)
    return out


def build(rtl):
    os.makedirs(SCRATCH, exist_ok=True)
    eng = (slow_engine() if rtl == "slow"
           else slow_engine("ckstale", ckstale_subs, "S_PR_CKSTALE")
           if rtl == "ckstale"
           else os.path.join(ROOT, "src", "pe_engine.v"))
    out = os.path.join(SCRATCH, "w_%s.vvp" % rtl)
    cmd = [tool("iverilog"), "-g2012", "-o", out, "-s", "tb_w", "test/tb_w.v",
           eng] + [os.path.join(ROOT, "src", s) for s in SRCS[1:]]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("*** build failed (%s)\n%s"
                         % (rtl, (r.stdout + r.stderr)[-700:]))
    return out


def five_image(name, delays):
    import make_smoke_image as m
    from pe_isa import write_image
    os.makedirs(SCRATCH, exist_ok=True)
    path = os.path.join(SCRATCH, "w_%s.hex" % name)
    write_image(path, m.build_five(list(delays)))
    return path


def run(vvp, hexpath, ncyc, warmup):
    with open(hexpath, encoding="ascii") as fh:
        nb = len(fh.read().split())
    # an absolute path for anything outside the repo (the scratch dir can be
    # on another drive, where relpath raises)
    ap, rp = os.path.abspath(hexpath), os.path.abspath(ROOT)
    img = (os.path.relpath(ap, rp) if ap.startswith(rp + os.sep) else ap
           ).replace(os.sep, "/")
    r = subprocess.run(sim_run.vvp([vvp, "+IMG=" + img, "+NBYTES=%d" % nb,
                                    "+NCYC=%d" % ncyc, "+WARMUP=%d" % warmup],
                                   images=[img]), cwd=ROOT,
                       capture_output=True, encoding="utf-8", errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    lanes = [{k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", l)}
             for l in txt.splitlines() if l.startswith("W lane=")]
    iss = next((l for l in txt.splitlines() if l.startswith("ISSUE ")), "")
    if len(lanes) != 5 or "END tb_w" not in txt:
        raise SystemExit("*** tb_w did not finish on %s:\n%s" % (img, txt[-500:]))
    return {"lanes": lanes,
            "issue": {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", iss)}}


def viol(res):
    return sum(l["viol_ev"] for l in res["lanes"])


def all_consume(res):
    return all(l["consumed"] > 0 for l in res["lanes"])


def subset():
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("W -- THEOREM 3 ON THE BENCH: the live subset (200k cycles)")
    print("=" * 78)
    good, slow = build("good"), build("slow")
    arms = [("u20", good, (20, 20, 20, 20, 20), False),
            ("m20", good, (20, 21, 22, 23, 24), False),
            ("u18", good, (18, 18, 18, 18, 18), True),
            ("slow_u20", slow, (20, 20, 20, 20, 20), True)]
    rc = 0
    for name, vvp, delays, want_red in arms:
        res = run(vvp, five_image(name, delays), 200000, 20000)
        v = viol(res)
        slk = [l["slack_min"] for l in res["lanes"]]
        own = max(l["owed_max"] for l in res["lanes"])
        if want_red:
            ok = v > 0
            verdict = "red  ok (must-fire)" if ok else "*** MUST-FIRE FAILED"
        else:
            ok = v == 0 and all_consume(res)
            verdict = ("clean ok" if ok else
                       "*** NOT CLEAN" if v else "*** A LANE NEVER CONSUMED")
        print("  %-9s %-16s violations %6d  slack_min %-16s owed_max %d  %s"
              % (name, " ".join(map(str, delays)), v,
                 ",".join(map(str, slk)), own, verdict))
        if not ok:
            rc = 1
    # ⭐ RULING PR2's invariant, PRICED: with the dispatch-time `cur_ck` load
    # removed, tb_w's `inv_curck.vh` must stop the run. The clean arms above
    # already carry the same check (a failure there never prints `END tb_w`,
    # which `run` refuses).
    stale = build("ckstale")
    img = five_image("m20", (20, 21, 22, 23, 24))
    with open(img, encoding="ascii") as fh:
        nb = len(fh.read().split())
    r = subprocess.run(sim_run.vvp([stale, "+IMG=" + os.path.abspath(img)
                                    .replace(os.sep, "/"), "+NBYTES=%d" % nb,
                                    "+NCYC=20000", "+WARMUP=0"],
                                   images=[os.path.abspath(img)]), cwd=ROOT,
                       capture_output=True, encoding="utf-8", errors="replace")
    fired = "*** FAIL inv_curck" in (r.stdout or "") + (r.stderr or "")
    print("  %-9s %-16s %s" % ("ckstale", "20 21 22 23 24",
                               "red  ok (must-fire: inv_curck)" if fired
                               else "*** MUST-FIRE FAILED (inv_curck silent)"))
    if not fired:
        rc = 1
    print()
    print("  GATE w_subset: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


def image_sha256():
    """sha256 of every image row's .hex, line endings normalised (RC6): a
    program can change while the RTL does not, and the record must notice."""
    from run_lockstep import IMAGES
    out = {}
    for i in IMAGES:
        with open(os.path.join(HERE, i), "rb") as fh:
            out[i] = hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()
    return out


def images_only():
    """RC6: re-run ONLY the image rows and refresh their hashes. Refused if
    the RTL hash is stale -- a partial re-run must not paper over an RTL
    change, which needs `--full`."""
    from run_lockstep import IMAGES
    with open(RECORD, encoding="utf-8") as fh:
        rec = json.load(fh)
    if rec.get("_src_sha256") != src_sha256():
        raise SystemExit("*** the record's RTL hash is STALE: an RTL change "
                         "needs `--full`, not `--images`")
    banner("iverilog", "vvp")
    good = build("good")
    for i in IMAGES:
        res = run(good, os.path.join(HERE, i), 200000, 20000)
        res.update(kind="image", rtl="good", image=i)
        rec["arms"]["img_" + i.replace(".hex", "")] = res
        print("  done img_%-14s violations %d" % (i.replace(".hex", ""),
                                                  viol(res)), flush=True)
    rec["_image_sha256"] = image_sha256()
    with open(RECORD, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("  rewrote the %d image rows of %s" % (len(IMAGES),
                                                os.path.relpath(RECORD, ROOT)))
    return 0


def full():
    from run_lockstep import IMAGES
    banner("iverilog", "vvp")
    good, slow = build("good"), build("slow")
    jobs = []
    for d in (19, 20, 21, 22, 25, 30, 40, 60):
        fam = {"u": (d, d, d, d, d),
               "m": (d, d + 1, d + 2, d + 3, d + 4),
               "mb": (d, d, d, d, d + 4),
               "mc": (d, d + 4, d, d + 4, d),
               "adv": (d, d, d, d, 100),
               "advk": (d, d, d, d, 1000),
               "drift": (d, d + 1, d + 2, d + 3, 100),
               "driftk": (d, d + 1, d + 2, d + 3, 1000)}
        for f, dl in fam.items():
            jobs.append(("%s%d" % (f, d), "synthetic", "good", dl))
    jobs += [("MF_u18", "mustfire", "good", (18, 18, 18, 18, 18)),
             ("MF_m18", "mustfire", "good", (18, 19, 20, 21, 22)),
             ("MF_slow_u20", "mustfire", "slow", (20, 20, 20, 20, 20)),
             ("MF_slow_m20", "mustfire", "slow", (20, 21, 22, 23, 24))]
    jobs += [("img_" + i.replace(".hex", ""), "image", "good", i)
             for i in IMAGES]

    def one(j):
        name, kind, rtl, arg = j
        vvp = good if rtl == "good" else slow
        if kind == "image":
            res = run(vvp, os.path.join(HERE, arg), 200000, 20000)
            res.update(kind=kind, rtl=rtl, image=arg)
        else:
            res = run(vvp, five_image(name, arg), 1000000, 200000)
            res.update(kind=kind, rtl=rtl, delays=list(arg))
        print("  done %-16s violations %d" % (name, viol(res)), flush=True)
        return name, res

    with ThreadPoolExecutor(3) as ex:
        arms = dict(ex.map(one, jobs))
    rec = {"_recipe": "python test/run_w_sweep.py --full",
           "_src_sha256": src_sha256(),
           "_image_sha256": image_sha256(),
           "_ncyc_synthetic": 1000000, "_warmup_synthetic": 200000,
           "_ncyc_image": 200000, "_warmup_image": 20000,
           "arms": arms}
    with open(RECORD, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("  wrote %s (%d arms)" % (os.path.relpath(RECORD, ROOT), len(arms)))
    return 0


if __name__ == "__main__":
    sys.exit(full() if "--full" in sys.argv
             else images_only() if "--images" in sys.argv else subset())
