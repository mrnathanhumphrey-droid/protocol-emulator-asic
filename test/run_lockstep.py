"""THE SCHEDULE FREEZE -- the dispatch and pin streams must not move.

⛔⛔ RULING TF4. The 50 MHz timing fix (TF1-TF3) is accepted only if it
changes nothing where a claim is made. On every image below -- the shipped
ADMISSIBLE images, the region every published timing number is about -- the
stream `test/tb_lock.v` prints (each dispatch's cycle, lane and action word;
each output-pin change) must be BYTE-IDENTICAL to the stream the pre-fix RTL
printed. The digests in `test/lockstep_golden.json` were recorded from that
RTL (`python test/run_lockstep.py --record <dir holding the pre-fix src>`).

⭐ THE MUST-FIRE IS TF1's NAIVE RETIMING. `M_TF1_LATE` registers readiness
from the CURRENT `now` and timestamp instead of the next-state ones. The
smoke bench PASSES on it -- its J / C / edge checks have slack a one-cycle
shift fits inside -- while its schedule is visibly different (a lane can
re-dispatch straight after its own writeback). This gate must go red on it,
or it is not checking the schedule at all.

⚠ WHAT IT DOES NOT COVER, said here so a green is not over-read:
  * sub-D* and non-admissible images: TF3 changes behaviour there ON PURPOSE
    (the starvation fix), so their streams are expected to move;
  * the priming time: TF3's registered winner may move it by a cycle at cold
    start, so it is REPORTED, not compared -- every stream is counted from
    the cycle priming completed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from toolchain import banner, tool          # noqa: E402  ruling V

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_lock"))
GOLDEN = os.path.join(HERE, "lockstep_golden.json")
NCYC = 60000
SRCS = ["pe_engine.v", "pe_store.v", "project.v"]
# ⭐ EACH must move at least one stream. TF2-R3's mutant keeps a lane that
# halted this cycle eligible for one more; on these images only
# `census_image` halts a lane in the window, and that one image is enough --
# MEASURED: its stream moves, the other eleven do not.
MUST_FIRE = [
    ("M_TF1_LATE", "registered readiness from CURRENT values"),
    ("M_TF2_LIVE_LATE", "a lane halted this cycle still eligible next cycle"),
]
IMAGES = ["smoke_image.hex", "stress_image.hex", "half_image.hex",
          "census_image.hex", "corpus_i2c.hex", "i2caddr_image.hex",
          "i2cframe_image.hex", "rxfast_image.hex", "ckheavy_image.hex",
          "ckfive_image.hex", "ckod_image.hex", "ckread_image.hex"]


def build(src_dir, defines=(), tag="clean"):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "lock_%s.vvp" % tag)
    cmd = [tool("iverilog"), "-g2012", "-o", out, "-s", "tb_lock"]
    cmd += ["-D%s" % d for d in defines]
    cmd += ["test/tb_lock.v"] + [os.path.join(src_dir, s) for s in SRCS]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("*** build failed (%s)" % tag)
        print((r.stdout + r.stderr)[-700:])
        return None
    return out


def stream(vvp, img):
    path = os.path.join(HERE, img)
    with open(path, encoding="ascii") as fh:
        nb = len([w for w in fh.read().split() if w])
    r = subprocess.run([tool("vvp"), vvp, "+IMG=test/%s" % img,
                        "+NBYTES=%d" % nb, "+NCYC=%d" % NCYC], cwd=ROOT,
                       capture_output=True, encoding="utf-8", errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    body = [l for l in txt.splitlines() if l[:2] in ("D ", "P ")]
    prim = [l for l in txt.splitlines() if l.startswith("C primed_at")]
    fails = [l for l in txt.splitlines() if "*** FAIL" in l]
    return {"sha256": hashlib.sha256("\n".join(body).encode()).hexdigest(),
            "lines": len(body),
            "dispatches": sum(1 for l in body if l.startswith("D ")),
            "primed_at": int(prim[0].split()[2]) if prim else None}, fails


def record(src_dir):
    vvp = build(src_dir, tag="record")
    if vvp is None:
        return 1
    out = {"_recorded_from": src_dir, "_ncyc_after_priming": NCYC}
    for img in IMAGES:
        s, fails = stream(vvp, img)
        if fails or s["primed_at"] is None or s["dispatches"] == 0:
            print("*** cannot record %s: %s" % (img, fails or s))
            return 1
        out[img] = s
        print("  recorded %-20s %6d dispatches  %s" % (img, s["dispatches"],
                                                      s["sha256"][:12]))
    with open(GOLDEN, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return 0


def compare(vvp, gold, label):
    """-> (n identical, list of mismatching images, priming moves)."""
    same, bad, moved = 0, [], []
    for img in IMAGES:
        s, fails = stream(vvp, img)
        g = gold[img]
        if fails:
            bad.append((img, "bench failed: %s" % fails[0][:60]))
            continue
        if s["sha256"] == g["sha256"]:
            same += 1
        else:
            bad.append((img, "%d dispatches vs %d recorded"
                        % (s["dispatches"], g["dispatches"])))
        if s["primed_at"] != g["primed_at"]:
            moved.append((img, g["primed_at"], s["primed_at"]))
    return same, bad, moved


def main() -> int:
    if "--record" in sys.argv:
        return record(sys.argv[sys.argv.index("--record") + 1])
    banner("iverilog", "vvp")   # ruling V2: the log names the binary that ran
    print()
    print("=" * 78)
    print("SCHEDULE FREEZE (TF4) -- dispatch + pin streams byte-identical to the")
    print("pre-fix RTL on %d shipped admissible images, %d cycles after priming"
          % (len(IMAGES), NCYC))
    print("=" * 78)
    with open(GOLDEN, encoding="utf-8") as fh:
        gold = json.load(fh)
    print("  golden recorded from: %s" % gold["_recorded_from"])
    rc = 0
    vvp = build(os.path.join(ROOT, "src"))
    if vvp is None:
        return 1
    same, bad, moved = compare(vvp, gold, "clean")
    print("  --- this RTL ---")
    print("    identical streams: %d of %d" % (same, len(IMAGES)))
    for img, why in bad:
        print("    *** STREAM MOVED: %-20s %s" % (img, why))
    for img, a, b in moved:
        print("    priming time %-20s %d -> %d (reported, not compared)"
              % (img, a, b))
    if bad:
        rc = 1

    for define, what in MUST_FIRE:
        print("  --- must-fire: %s (%s) ---" % (define, what))
        mvvp = build(os.path.join(ROOT, "src"), (define,), define.lower())
        if mvvp is None:
            return 1
        msame, mbad, _ = compare(mvvp, gold, "mutant")
        print("    streams that moved under the mutant: %d of %d (%s)"
              % (len(mbad), len(IMAGES),
                 ", ".join(i for i, _w in mbad) or "none"))
        if not mbad:
            print("    *** MUST-FIRE FAILED: %s left every stream identical "
                  "-- this gate does not see the schedule" % define)
            rc = 1
    print()
    print("  GATE lockstep: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
