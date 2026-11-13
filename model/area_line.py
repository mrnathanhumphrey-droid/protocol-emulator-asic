"""THE AREA LINE -- one definition, computed here and nowhere else (Wilson 11-10).

    python model/area_line.py <runs/wokwi/final/metrics.json> ...   (report)
    python model/area_line.py                                        (the gate: must-fires)
Token: GATE area-line: PASSED

DERIVATION. The line is our own yardstick for "how full is the chip":

    line = LINE_FRACTION x die area = 0.60 x 1724.16 x 710.64 um^2 = 735,156 um^2

  * 0.60 is the flow's PL_TARGET_DENSITY_PCT of record (src/config.json: 60).
    It is FIXED here on purpose: density canaries (57 / 63) move the config,
    and a yardstick that moves with the thing it measures measures nothing.
  * The die is the 8x4 tile's DIEAREA as the flow reports it
    (design__die__area), read from the run, never typed.
  * Placed = standard cells + macros (design__instance__area__stdcell +
    design__instance__area__macros). NOT design__instance__area, which also
    counts the fill cells (~580k) and would put every run near 163 %.
  * History: rulings/pit_timing_look.txt T4 (10-28) typed the die as
    1,225,277 um^2 -> 735,166; the flow's own die is 1,225,260 -> 735,156.
    Every figure quoted against 735,166 moves by < 0.002 points.

THE CORE FIGURE, REPORTED ALONGSIDE (Wilson 11-10). The placer's density and
routing congestion work on the CORE, not the die:

    core utilisation = placed / design__core__area  (= LibreLane's
                       design__instance__utilization; 51.2 % on the
                       five-bundle flow, 1648cf9)

If the two disagree about how much room is left, the CORE figure says whether
the design still routes. The line says how much of our budget is spent.
"""
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LINE_FRACTION = 0.60

_KEYS = ("design__die__area", "design__core__area",
         "design__instance__area__stdcell", "design__instance__area__macros")


def problems(metrics):
    """[problem] for one LibreLane metrics dict -- the JUDGE (gate_meta seam).
    A run that did not report its area is never read as zero."""
    out = []
    for k in _KEYS:
        if k not in metrics:
            out.append("metrics lack %s" % k)
        elif not isinstance(metrics[k], (int, float)):
            out.append("%s is not a number: %r" % (k, metrics[k]))
    if out:
        return out
    if metrics["design__die__area"] <= 0 or metrics["design__core__area"] <= 0:
        out.append("non-positive die/core area")
    if metrics["design__core__area"] > metrics["design__die__area"]:
        out.append("core larger than the die")
    if metrics["design__instance__area__stdcell"] <= 0:
        out.append("no standard-cell area")
    if metrics["design__instance__area__macros"] < 0:
        out.append("negative macro area")
    return out


def area_line(metrics):
    """dict from one LibreLane metrics dict; ValueError if `problems` objects."""
    bad = problems(metrics)
    if bad:
        raise ValueError("; ".join(bad))
    die = float(metrics["design__die__area"])
    core = float(metrics["design__core__area"])
    std = float(metrics["design__instance__area__stdcell"])
    mac = float(metrics["design__instance__area__macros"])
    line = LINE_FRACTION * die
    placed = std + mac
    return {"die_um2": die, "core_um2": core, "stdcell_um2": std,
            "macro_um2": mac, "placed_um2": placed, "line_um2": line,
            "line_ratio": placed / line, "headroom_um2": line - placed,
            "core_util": placed / core}


def fmt(r):
    return ("placed %s (std %s + macro %s) = %.1f %% of the line %s "
            "(headroom %s); core utilisation %.1f %%"
            % (f"{r['placed_um2']:,.0f}", f"{r['stdcell_um2']:,.0f}",
               f"{r['macro_um2']:,.0f}", 100 * r["line_ratio"],
               f"{r['line_um2']:,.0f}", f"{r['headroom_um2']:,.0f}",
               100 * r["core_util"]))


def load(path):
    return area_line(json.load(open(path, encoding="utf-8")))


def must_fires():
    """[(label, caught?)] -- each wrong construction must give a different
    answer from area_line, or raise."""
    m = {"design__die__area": 1225260, "design__core__area": 1208170,
         "design__instance__area__stdcell": 567873,
         "design__instance__area__macros": 49488.5,
         "design__instance__area": 1201140}
    good = area_line(m)
    out = []
    out.append(("anchor: 73a387a @ ttihp27a = 84.0 % / core 51.1 %",
                round(100 * good["line_ratio"], 1) == 84.0
                and round(100 * good["core_util"], 1) == 51.1))
    out.append(("macro left out (stdcell only)",
                abs(m["design__instance__area__stdcell"] / good["line_um2"]
                    - good["line_ratio"]) > 0.05))
    out.append(("fill counted (design__instance__area)",
                abs(m["design__instance__area"] / good["line_um2"]
                    - good["line_ratio"]) > 0.05))
    out.append(("core used as the line's base",
                abs(good["placed_um2"] / (LINE_FRACTION * m["design__core__area"])
                    - good["line_ratio"]) > 0.005))
    for k in _KEYS:
        bad = {kk: v for kk, v in m.items() if kk != k}
        out.append(("missing %s is refused" % k, bool(problems(bad))))
    out.append(("zero die is refused", bool(problems(dict(m, design__die__area=0)))))
    out.append(("core larger than the die is refused",
                bool(problems(dict(m, design__core__area=2e6)))))
    out.append(("a string area is refused",
                bool(problems(dict(m, design__instance__area__stdcell="567873")))))
    return out


def main():
    args = [a for a in sys.argv[1:] if a != "--self-test"]
    if args:
        for p in args:
            print("%s\n  %s" % (p, fmt(load(p))))
        return 0
    print("GATE area-line: one definition of the area line (0.60 x the run's die; "
          "placed = stdcell + macro)")
    ok = True
    for label, caught in must_fires():
        print("  must-fire: %-55s %s" % (label, "ok" if caught else "MISSED"))
        ok &= caught
    print("  GATE area-line: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
