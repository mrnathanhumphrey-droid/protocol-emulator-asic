"""Rulings K and U -- every chip-driven SDA transition holds across the SCL
fall, per CLASS, and a delay that cannot fit the hold is refused wherever the
hold applies.

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
      `M_HOLD_CLOCKED_ONLY` (the old clocked-only scope) runs d = SDA_HOLD and
      Layer H reports the broken hold.
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
import hold_bound                                                 # noqa: E402

SRCS = ["test/tb_trace.v", "test/fram_i2c.v", "test/fram_spi.v",
        "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
OUT = os.path.join(ROOT, "probe_sda")
CLASS = {0: "LEVEL", 1: "SHIFT data", 2: "SHIFTIN release",
         3: "READBIT release", 4: "START", 5: "STOP", 6: "ARM", 7: "REARM",
         8: "SHIFT 1-bit (ACK/NACK)", 9: "other"}
DATA = {1, 2, 3, 8}
#: image -> (peer, required data classes, setup judged?).
#: ⛔ An empty required cell is RED.
#: ⛔ SETUP (a data move with SCL released) is judged only where a floor
#: promises it: clocked images the mode floor (`pe_asm.check_mode_floor`)
#: covers and passes -- checked below, not assumed -- and the CERTIFIED frame,
#: whose certification is the claim. `corpus_all5` is OVERLOADED (the mode
#: floor refuses it: no finite worst-case response), so it is reported only.
IMAGES = {
    "corpus_i2c": ("i2c", {1, 2}, True),
    "corpus_all5": ("none", {1, 2}, False),
    "ckod_image": ("none", {1}, True),
    "ckread_image": ("none", {1, 2, 8}, True),
    "i2cframe_image": ("i2c", {1}, True),
}
ROW = re.compile(r"clocked_conform\[H\] class (\d+): n=(\d+) hold_min=(-?\d+) "
                 r"hold_max=(-?\d+) moved_while_released=(\d+)")
CFG = re.compile(r"clocked_conform\[M5\]: store_full=\d config_err=(\d)")


def build(defs, name):
    out = os.path.join(OUT, name + ".vvp")
    r = subprocess.run([tool("iverilog"), "-g2012", "-I", "test", "-I", "."]
                       + ["-D" + d for d in defs] + ["-o", out, "-s",
                                                      "tb_trace"] + SRCS,
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("build %s failed: %s" % (name, r.stderr[-400:]))
    return out


def run(vvp, img, peer):
    import benchset
    a2 = benchset.a2_slack_arg(img) if img.startswith("test/") else None
    r = subprocess.run([tool("vvp"), vvp, "+IMG=%s" % img, "+NBYTES=256",
                        "+PEER=%s" % peer, "+NCYC=60000",
                        "+OUT=%s" % os.path.join(OUT, "t.txt"), "+SEED=1",
                        "+ASYNC=0", "+STAYLOAD=0", "+SCLHOLD=0"]
                       + ([a2] if a2 else []),
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    o = r.stdout
    rows = {int(m.group(1)): tuple(int(x) for x in m.groups()[1:])
            for m in ROW.finditer(o)}
    cfg = CFG.search(o)
    return {"rows": rows, "hfail": "*** FAIL clocked_conform[H]" in o,
            "anyfail": "*** FAIL" in o,
            "config_err": int(cfg.group(1)) if cfg else None,
            "exercised": "clocked_conform[H]: 0 chip-driven" not in o}


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
    print("  K + U -- EVERY CHIP-DRIVEN SDA MOVE HOLDS ACROSS THE SCL FALL")
    print("=" * 78)
    os.makedirs(OUT, exist_ok=True)
    hold = hold_bound.bound()
    print("  SDA_HOLD = %d cycles (read from src/pe_engine.v)" % hold)
    rc = 0
    clean = build([], "clean")

    # ---- K2: the class x image table; K1/K4 via Layer H -----------------------
    print()
    print("  %-16s %-24s %6s %8s %8s %8s" % ("image", "class", "n", "min",
                                           "max", "high"))
    import gate_degenerate_fields as dgf
    import pe_asm
    for img, (peer, need, judged) in IMAGES.items():
        res = run(clean, "test/%s.hex" % img, peer)
        if judged:
            # ⛔ "judged" must be TRUE of the image, not asserted: a clocked
            # image marked judged must pass the mode floor it is judged by.
            try:
                floors = pe_asm.check_mode_floor(dgf.load(
                    os.path.join(ROOT, "test", img + ".hex")))
            except Exception as e:
                print("  *** %s is marked setup-judged but the mode floor "
                      "REJECTS it: %s" % (img, str(e)[:80]))
                rc = 1
                floors = None
            setup = sum(res["rows"].get(c, (0, 0, 0, 0))[3] for c in DATA)
            if setup:
                print("  *** %s: %d data move(s) with SCL released -- t_SU;DAT "
                      "<= 0 on a program a floor promises setup for"
                      % (img, setup))
                rc = 1
        for c in sorted(res["rows"]):
            n, lo, hi, high = res["rows"][c]
            print("  %-16s %-24s %6d %8d %8d %8d" % (img, CLASS[c], n, lo, hi,
                                                   high))
        for c in sorted(need):
            if res["rows"].get(c, (0,))[0] == 0:
                print("  *** %s: required class %r is EMPTY -- nothing checked "
                      "it" % (img, CLASS[c]))
                rc = 1
        if res["hfail"]:
            print("  *** %s: Layer H reports a data move under SDA_HOLD or with "
                  "SCL released" % img)
            rc = 1
        if res["config_err"] != 0:
            print("  *** %s: refused (CONFIG_ERR) -- a shipped image must run"
                  % img)
            rc = 1
    if rc == 0:
        print("  ⇒ every required cell exercised; every data move held >= %d"
              % hold)

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
    # ⚠ REPORTED, NOT JUDGED: the refusal fixes the HOLD on the held path;
    # at d = SDA_HOLD + 1 release jitter leaves no SETUP, and the UNCLOCKED
    # SHIFTIN release is not held at all (its hold is the inter-dispatch
    # delay). No floor promises this program anything -- the mode floor does
    # not cover unclocked lanes -- so the numbers are recorded as the finding.
    for c in (1, 2):
        r = ro["rows"].get(c)
        if r:
            print("      d = %d %-16s hold %d..%d, %d move(s) with SCL released"
                  % (hold + 1, CLASS[c], r[1], r[2], r[3]))

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
    setup4 = sum(r4["rows"].get(c, (0, 0, 0, 0))[3] for c in DATA)
    hit4 = r4["config_err"] == 0 and setup4 > 0
    print("    U   M_HOLD_CLOCKED_ONLY RUNS d = %d (clean refuses), %d data "
          "move(s) with SCL released   %s"
          % (hold, setup4, "ok" if hit4 else "*** MISSED"))
    if not (hit3 and hit4):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE sda-hold: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
