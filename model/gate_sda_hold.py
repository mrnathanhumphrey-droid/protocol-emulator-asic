"""Rulings K, U and W -- every chip-driven SDA transition holds across the SCL
fall, lands before the next SCL release, and a delay that cannot fit the hold
is refused wherever the hold applies.

⛔⛔ WHY. Ruling H put the transmit path's SDA change through a hold pipeline
and measured it -- on `ckod`, a SHIFT-only image. The clocked SHIFTIN's
release into the ACK slot was never held: `t_HD;DAT = 0` on every one (found
by a falsifier set, `{0: 20, ...}` on corpus_i2c). The measurement set could
not see it because no image in it HAD that transition. So this gate is about
CLASSES, not images:

  K1  every chip-driven SDA move of a DATA class (SHIFT data, the 1-bit SHIFT
      a master ACK/NACK is, SHIFTIN's release, READBIT's release) lands
      >= SDA_HOLD after the chip's own SCL fall, and never while SCL is
      released -- `clocked_conform.vh` Layer H, which attributes each move to
      the opcode that caused it (directly, or by loading the hold pipeline).
  K2  the class x image table below, with REQUIRED cells: an empty required
      cell is RED, because a class the table never saw is a class nothing
      checked. `ckread_image` exists for class 8 and the release after it.
  K3  must-fire: `M_SHIFTIN_UNHELD` restores the unheld release, and
      corpus_i2c's SHIFTIN class must read hold 0 and go red.
  K4  post-fix: no data move on corpus_i2c below SDA_HOLD (the Layer H verdict,
      and the wire-level `gate_um10204` arm on corpus_i2c).
  U2  the unclocked open-drain frame (`build_i2cframe`) at d = SDA_HOLD is
      REFUSED; at SDA_HOLD + 1 it RUNS and holds. Must-fire:
      `M_HOLD_CLOCKED_ONLY` (the old clocked-only scope) RUNS d = SDA_HOLD.

⛔⛔ RULING W -- NO SDA CHANGE WHILE SCL IS HIGH, IN SILICON. The refusal
`d > SDA_HOLD` fixes the HOLD and nothing fixed the SETUP: MEASURED, ckhold_over
(d = 16) moved data with SCL released 11 times in 562, i2cframe 10 at d = 16
and 3 at d = 17, and the unclocked SHIFTIN release held only 14 at d = 16.

  W1  a lane is ineligible while its own hold + SDA_SETUP is pending; Layer H
      now reds any data move with SCL released (when SDA_HOLD != 0)
  W2  the unclocked SHIFTIN/READBIT release goes through the hold pipeline
  W4  ckhold_over (d = 16) and i2cframe at d = 16/17/18: zero data moves with
      SCL released, every hold >= SDA_HOLD, setup >= SDA_SETUP; and how often
      W1 actually delayed a dispatch, on every image in the table
  W5  must-fires: `M_NO_HOLD_GATE` reproduces the setup moves (11/562 on
      ckhold_over, 10 and 3 on i2cframe d = 16/17; ckhold_over is 14/688
      since silicon fix #2 corrected its bytes, and 15/691, 11, 6 since
      silicon fix #8 made the first byte the host's), `M_SHIFTIN_UC_UNHELD`
      reproduces the unclocked release hold of 14 -- on a feed that drives
      SDA low before every ACK, so the condition is built, not lucky
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
sys.path.insert(0, HERE)
from toolchain import banner, tool                                # noqa: E402
import sim_run                                                    # noqa: E402
import hold_bound                                                 # noqa: E402

SRCS = ["test/tb_trace.v", "test/fram_i2c.v", "test/fram_spi.v",
        "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
OUT = os.path.join(ROOT, "probe_sda")
CLASS = {0: "LEVEL", 1: "SHIFT data", 2: "SHIFTIN release",
         3: "READBIT release", 4: "START", 5: "STOP", 6: "ARM", 7: "REARM",
         8: "SHIFT 1-bit (ACK/NACK)", 9: "other"}
DATA = {1, 2, 3, 8}
#: image -> (peer, required data classes, mode floor must pass?).
#: ⛔ An empty required cell is RED.
#: ⛔ SETUP is no longer judged here per image: since W1 it is a SILICON
#: promise on every program and Layer H reds it itself. The third column now
#: asserts what the image CLAIMS -- that it passes the mode floor
#: (`pe_asm.check_mode_floor`, clocked and, since W7, unclocked frames).
#: `corpus_all5` is OVERLOADED (no finite worst-case response), so it claims
#: nothing.
IMAGES = {
    "corpus_i2c": ("i2c", {1, 2}, True),
    "corpus_all5": ("none", {1, 2}, False),
    "ckod_image": ("none", {1}, True),
    "ckread_image": ("none", {1, 2, 8}, True),
    "i2cframe_image": ("i2c", {1}, True),
}
#: W4's subjects: the programs the findings were measured on.
W4 = [("ckhold_over_image", "test/ckhold_over_image.hex", "none")]
#: W5's recorded findings, reproduced by the mutant without W1:
#: subject -> data moves with SCL released (and of how many, where recorded).
#: ⛔ RE-RECORDED, RULING TX5 (silicon fix #2): ckhold_over was (11, 562).
#: The clocked SHIFT's bytes were misaligned, so the SDA move count was the
#: wrong bytes' count. MEASURED: built with M_TX_LOAD_ANYPHASE as well, the
#: mutant still gives exactly 11 of 562; on the fixed RTL 14 of 688. The two
#: unclocked frames do not use the clocked SHIFT and did not move.
#: ⛔ RE-RECORDED A SECOND TIME (WF2, silicon fix #8): the first TX byte is
#: now the host's, not the reset 0x00, so the SDA bit stream -- and the count
#: of moves the mutant exposes -- changed on all three. MEASURED: built with
#: M_TX_PRELOAD (#8 undone) as well, the mutant gives exactly 14/688, 10 and
#: 3 again; on the fixed RTL 15/691, 11 and 6.
W5_FOUND = {"ckhold_over_image": (15, 691), "i2cframe_d16": (11, None),
            "i2cframe_d17": (6, None)}
#: the unheld-SHIFTIN must-fire's feed: bit 0 and bit 7 = 0 in every byte
UC_FEED = [0x34, 0x2C, 0x16, 0x68]
ROW = re.compile(r"clocked_conform\[H\] class (\d+): n=(\d+) hold_min=(-?\d+) "
                 r"hold_max=(-?\d+) moved_while_released=(\d+)")
CFG = re.compile(r"clocked_conform\[M5\]: store_full=\d config_err=(\d)")
SU = re.compile(r"clocked_conform\[W\] setup_min=(-?\d+) over (\d+)")
WB = re.compile(r"clocked_conform\[W\] w1_binds=(\d+) w1_cycles=(\d+)")


def build(defs, name):
    out = os.path.join(OUT, name + ".vvp")
    r = subprocess.run([tool("iverilog"), "-g2012", "-I", "test", "-I", "."]
                       + ["-D" + d for d in defs] + ["-o", out, "-s",
                                                      "tb_trace"] + SRCS,
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("build %s failed: %s" % (name, r.stderr[-400:]))
    return out


def run(vvp, img, peer, feed=None):
    """`feed`: queue 0's bytes (tb_trace `+FEED`), or the bench default."""
    import benchset
    a2 = benchset.a2_slack_arg(img) if img.startswith("test/") else None
    fa = (["+FEEDN=%d" % len(feed), "+FEED=%s" % "".join(
        "%02x" % b for b in feed)] if feed else [])
    cmd = sim_run.vvp([vvp, "+IMG=%s" % img, "+NBYTES=256",
                       "+PEER=%s" % peer, "+NCYC=60000",
                       "+OUT=%s" % os.path.join(OUT, "t.txt"), "+SEED=1",
                       "+ASYNC=0", "+STAYLOAD=0", "+SCLHOLD=0"]
                      + ([a2] if a2 else []) + fa, images=[img])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    o = r.stdout
    # ⛔ R3: a run that did not FINISH has no verdict -- its layer H line still
    # prints from `final` (10-23: this gate read only that line)
    why = sim_run.trace_incomplete(o, cmd)
    if why:
        raise SystemExit("*** gate_sda_hold: %s on %s: %s" % (vvp, img, why))
    rows = {int(m.group(1)): tuple(int(x) for x in m.groups()[1:])
            for m in ROW.finditer(o)}
    cfg, su, wb = CFG.search(o), SU.search(o), WB.search(o)
    return {"rows": rows, "hfail": "*** FAIL clocked_conform[H]" in o,
            "anyfail": "*** FAIL" in o,
            "config_err": int(cfg.group(1)) if cfg else None,
            "exercised": "clocked_conform[H]: 0 chip-driven" not in o,
            "su": int(su.group(1)) if su else None,
            "binds": (int(wb.group(1)), int(wb.group(2))) if wb else None}


def image_problems(img, res, need, claims, setup, floor=None, load=None):
    """[problem] for one shipped image's run. The gate and its must-fires both
    call this (F8, meta-test 10-24: the mode-floor claim, the setup check and
    the rest were inline and nothing planted against them). `floor` / `load`
    default to pe_asm.check_mode_floor on the image file."""
    probs = []
    if claims:
        # ⛔ a claim must be TRUE of the image, not asserted
        if floor is None:
            import gate_degenerate_fields as dgf
            import pe_asm
            floor = pe_asm.check_mode_floor
            load = load or (lambda: dgf.load(os.path.join(ROOT, "test",
                                                           img + ".hex")))
        try:
            floor(load())
        except Exception as e:      # a refusal IS the finding: named below
            probs.append("%s claims a mode but the mode floor REJECTS it: %s"
                         % (img, str(e)[:80]))
    for c in sorted(need):
        if res["rows"].get(c, (0,))[0] == 0:
            probs.append("%s: required class %r is EMPTY -- nothing checked it"
                         % (img, CLASS[c]))
    if res["hfail"] or released(res):
        probs.append("%s: Layer H reports a data move under SDA_HOLD or with "
                     "SCL released" % img)
    if res["su"] is not None and res["su"] < setup:
        probs.append("%s: setup %d < SDA_SETUP %d" % (img, res["su"], setup))
    if res["config_err"] != 0:
        probs.append("%s: refused (CONFIG_ERR) -- a shipped image must run" % img)
    return probs


def released(res):
    """Data moves made with SCL released, summed over the data classes."""
    return sum(res["rows"].get(c, (0, 0, 0, 0))[3] for c in DATA)


def data_moves(res):
    return sum(res["rows"].get(c, (0, 0, 0, 0))[0] for c in DATA)


def frame_image(d):
    """`build_i2cframe(d)` written whole, under probe_sda/ (gitignored)."""
    import make_smoke_image as msi
    import pe_isa
    p = os.path.join(OUT, "i2cframe_d%d.hex" % d)
    pe_isa.write_image(p, msi.build_i2cframe(d))
    return os.path.relpath(p, ROOT).replace("\\", "/")


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("  K + U + W -- EVERY CHIP-DRIVEN SDA MOVE HOLDS ACROSS THE FALL AND")
    print("  LANDS BEFORE THE RELEASE")
    print("=" * 78)
    os.makedirs(OUT, exist_ok=True)
    hold = hold_bound.bound()
    setup = hold_bound.setup()
    print("  SDA_HOLD = %d, SDA_SETUP = %d cycles (read from src/pe_engine.v)"
          % (hold, setup))
    rc = 0
    clean = build([], "clean")

    # ---- K2: the class x image table; K1/K4 via Layer H -----------------------
    print()
    print("  %-16s %-24s %6s %8s %8s %8s" % ("image", "class", "n", "min",
                                           "max", "high"))
    binds = {}
    for img, (peer, need, claims) in IMAGES.items():
        res = run(clean, "test/%s.hex" % img, peer)
        binds[img] = (res["binds"], claims)
        for c in sorted(res["rows"]):
            n, lo, hi, high = res["rows"][c]
            print("  %-16s %-24s %6d %8d %8d %8d" % (img, CLASS[c], n, lo, hi,
                                                   high))
        for pr in image_problems(img, res, need, claims, setup):
            print("  *** %s" % pr)
            rc = 1
    # ⛔ F8 (meta-test, 10-24): the per-image checks, priced on synthetic run
    # results -- no simulation; each plants exactly one defect.
    print("  --- must-fire: the per-image checks ---")
    good = {"rows": {1: (9, 15, 15, 0)}, "hfail": False, "su": setup + 5,
            "config_err": 0}

    def refuse(_img):
        raise ValueError("under every t_LOW")
    for label, res, need, claims, fl in (
            ("setup below SDA_SETUP", dict(good, su=setup - 1), [1], False, None),
            ("a required class EMPTY", dict(good, rows={}), [1], False, None),
            ("a claimed mode the floor rejects", good, [1], True, refuse),
            ("CONFIG_ERR on a shipped image", dict(good, config_err=1), [1],
             False, None),
            ("Layer H red", dict(good, hfail=True), [1], False, None)):
        red = bool(image_problems("plant", res, need, claims, setup, floor=fl,
                                  load=lambda: b""))
        print("    %-44s %s" % (label, "red  ok" if red else "*** MISSED"))
        if not red:
            rc = 1
    ok = not image_problems("plant", good, [1], True, setup,
                            floor=lambda _i: None, load=lambda: b"")
    print("    %-44s %s" % ("a clean result passes (control)",
                            "ok" if ok else "*** REJECTED"))
    if not ok:
        rc = 1
    if rc == 0:
        print("  ⇒ every required cell exercised; every data move held >= %d "
              "and landed before the release" % hold)

    # ---- W4: the findings' programs, post-fix -----------------------------------
    print()
    print("  --- W4: no SDA move while SCL is high, at the programs that had them ---")
    print("    %-20s %6s %8s %8s %10s %12s" % ("program", "data", "hold_min",
                                              "released", "setup_min",
                                              "W1 binds/cy"))
    subjects = list(W4) + [("i2cframe_d%d" % d, frame_image(d), "i2c")
                           for d in (hold + 1, hold + 2, hold + 3)]
    for name, img, peer in subjects:
        res = run(clean, img, peer)
        hmin = min((res["rows"][c][1] for c in DATA
                    if res["rows"].get(c, (0,))[0] and res["rows"][c][1] >= 0),
                   default=-1)
        ok = (res["config_err"] == 0 and not res["hfail"] and released(res) == 0
              and hmin >= hold and res["su"] is not None and res["su"] >= setup
              and data_moves(res) > 0)
        b = res["binds"] or (0, 0)
        print("    %-20s %6d %8d %8d %10s %12s   %s"
              % (name, data_moves(res), hmin, released(res), res["su"],
                 "%d/%d" % b, "ok" if ok else "*** FAIL"))
        if not ok:
            rc = 1
    print("    (these programs are below every mode floor -- W7 refuses them in "
          "the toolchain -- so W1 binding often here is expected)")

    # ---- W4: how often W1 binds on the shipped/corpus images --------------------
    print()
    print("  --- W4: how often W1 delays a dispatch (shipped / corpus images) ---")
    for img, ((nb, cy), claims) in ((k, (v[0] or (0, 0), v[1]))
                                    for k, v in binds.items()):
        print("    %-16s %5d delay(s), %5d cycle(s)   %s"
              % (img, nb, cy, "mode-legal" if claims
                 else "overloaded, claims no mode"))

    # ---- U2: the unclocked frame at the boundary -------------------------------
    print()
    print("  --- U2: build_i2cframe at d = SDA_HOLD and SDA_HOLD + 1 ---")
    at, over = frame_image(hold), frame_image(hold + 1)
    ra, ro = run(clean, at, "i2c"), run(clean, over, "i2c")
    ok_at = ra["config_err"] == 1
    ok_over = ro["config_err"] == 0 and ro["rows"].get(1, (0,))[0] > 0
    print("    d = %-3d REFUSED (CONFIG_ERR)                    %s"
          % (hold, "ok" if ok_at else "*** NOT REFUSED"))
    print("    d = %-3d RUNS (%d SHIFT moves)                   %s"
          % (hold + 1, ro["rows"].get(1, (0,))[0], "ok" if ok_over
             else "*** WRONG"))
    if not (ok_at and ok_over):
        rc = 1

    # ---- must-fires -------------------------------------------------------------
    print()
    print("  --- must-fire ---")
    un = build(["M_SHIFTIN_UNHELD"], "unheld")
    r3 = run(un, "test/corpus_i2c.hex", "i2c")
    c2 = r3["rows"].get(2)
    hit3 = bool(c2) and c2[1] == 0 and r3["hfail"]
    print("    K3  M_SHIFTIN_UNHELD on corpus_i2c: SHIFTIN release hold %s, "
          "Layer H red   %s" % (c2[1] if c2 else "-", "ok" if hit3
                                else "*** MISSED"))
    co = build(["M_HOLD_CLOCKED_ONLY"], "clockedonly")
    r4 = run(co, at, "i2c")
    # ⚠ REDEFINED BY W: this mutant used to be caught by its setup moves, and
    # W1 now removes those in silicon. What still separates it from the clean
    # design is the refusal itself: clean refuses d = SDA_HOLD, it runs it.
    hit4 = r4["config_err"] == 0 and data_moves(r4) > 0
    print("    U   M_HOLD_CLOCKED_ONLY RUNS d = %d (clean refuses), %d data "
          "move(s), %d with SCL released   %s"
          % (hold, data_moves(r4), released(r4), "ok" if hit4
             else "*** MISSED"))
    ng = build(["M_NO_HOLD_GATE"], "nogate")
    hit5 = True
    for name, img, peer in subjects[:3]:
        r5 = run(ng, img, peer)
        want, of = W5_FOUND.get(name, (None, None))
        got = released(r5)
        same = (want == got) and (of is None or of == data_moves(r5))
        # ⛔ W5 asks the mutant to REPRODUCE the finding, so the recorded
        # count is a LIVE pin (`gate_stored_numbers`): drift is red, and a
        # legitimate change re-measures and re-records it, saying why.
        hit = got > 0 and r5["hfail"] and same
        hit5 = hit5 and hit
        print("    W5  M_NO_HOLD_GATE on %-16s %3d of %3d data move(s) with "
              "SCL released, Layer H red   %s%s"
              % (name, got, data_moves(r5), "ok" if hit else "*** MISSED",
                 "" if same else "  *** recorded finding was %s%s -- re-measure"
                 % (want, "/%s" % of if of else "")))
    uc = build(["M_SHIFTIN_UC_UNHELD"], "ucunheld")
    # ⛔⛔ THE STIMULUS GUARANTEES WHAT THE MUTANT NEEDS. An unheld SHIFTIN
    # release only shows when SDA was DRIVEN LOW before the ACK release; with
    # the bench's default feed the low came from the reset 0x00 that went
    # out first (silicon fix #8), and once that was fixed this must-fire went
    # SILENT (hold 16 >= SDA_HOLD, MEASURED). Every byte below has bit 0 AND
    # bit 7 = 0, so the last data bit before every ACK is low whichever order
    # the lane shifts: 162 releases judged, not 40 by luck.
    r6 = run(uc, frame_image(hold + 1), "i2c", feed=UC_FEED)
    c6 = r6["rows"].get(2)
    hit6 = bool(c6) and c6[1] < hold and r6["hfail"]
    print("    W5  M_SHIFTIN_UC_UNHELD on i2cframe d = %d: SHIFTIN release hold "
          "%s (recorded 14), Layer H red   %s"
          % (hold + 1, c6[1] if c6 else "-", "ok" if hit6 else "*** MISSED"))
    if not (hit3 and hit4 and hit5 and hit6):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE sda-hold: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
