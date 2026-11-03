"""GATE clock-consistency -- every copy of the clock agrees, and every derived
real-time count meets its spec at that clock (Wilson 11-03).

⛔⛔ WHY. The chip moved to 60 MHz in its harden config while the RTL kept
an integer CLK_PERIOD_NS of 20 and nothing compared them: the SDA hold came out 15 cycles
= 250 ns against a 300 ns minimum, and every gate stayed green because each
read its own copy. A clock is now written in exactly two board configs
(info.yaml for the chip, fpga/board.yaml for the FPGA) and DERIVED everywhere
else. The places that must still carry a number -- the RTL parameter defaults,
the harden period, the generated bench headers, the board's MMCM -- are held
to the board config HERE.

  1. CHIP: info.yaml clock_hz == project.v and pe_engine.v CLK_PERIOD_PS
     (whole ps, rounded down) == config.json CLOCK_PERIOD (ns, to 1 ps)
     == test/pe_clock.vh's default.
  2. BAND: pe_engine.v BAND_NUM/BAND_DEN == model/clock.py BAND.
  3. FPGA: fpga/board.yaml clock_hz == the MMCM in pa100t_top.v
     == fpga/sim/fpga_clock.vh's default; build.tcl reads board.yaml.
  4. SPEC, PER TARGET, at the nominal clock: the RTL's SDA hold and setup
     (computed by hold_bound from the RTL's own formula) meet 300 / 50 ns with
     the band; the hold stays under Fm+'s t_VD;DAT with the rise charged; the
     stretch bound brackets 35 ms; every UM10204 floor the assembler enforces
     (gate_um10204.table_cycles) meets its minimum with the band.
  5. MUST-FIRES: each check is run against a mutated copy and must go red.

`--write` regenerates the two bench headers' defaults from the board configs.
"""

from __future__ import annotations

import json
import os
import re
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "a2"))

import clock                                            # noqa: E402
import hold_bound                                       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT = os.path.join("src", "project.v")
ENGINE = os.path.join("src", "pe_engine.v")
CONFIG = os.path.join("src", "config.json")
CHIP_VH = os.path.join("test", "pe_clock.vh")
FPGA_VH = os.path.join("fpga", "sim", "fpga_clock.vh")
FPGA_TOP = os.path.join("fpga", "pa100t", "pa100t_top.v")
FPGA_TCL = os.path.join("fpga", "pa100t", "build.tcl")

#: UM10204 / SMBus numbers this gate holds the derived counts to, in ns.
HOLD_NS, SETUP_NS = 300, 50
FMP_VD_DAT_NS, FMP_TR_NS = 450, 120
STRETCH_NS = 35_000_000


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def param(text, name):
    m = re.search(r"parameter\s+integer\s+%s\s*=\s*(\d+)\s*[,)\n]" % name, text)
    return int(m.group(1)) if m else None


def vh_default(text, macro):
    m = re.search(r"`define\s+%s\s+(\d+)" % macro, text)
    return int(m.group(1)) if m else None


def mmcm_hz(text):
    """CLKOUT0 of the MMCM: 1/CLKIN1_PERIOD x MULT / DIVCLK / OUT0."""
    g = {}
    for k in ("CLKIN1_PERIOD", "DIVCLK_DIVIDE", "CLKFBOUT_MULT_F",
              "CLKOUT0_DIVIDE_F"):
        m = re.search(r"\.%s\(\s*([\d.]+)\s*\)" % k, text)
        if not m:
            return None
        g[k] = Fraction(m.group(1))
    f = (Fraction(10 ** 9) / g["CLKIN1_PERIOD"] * g["CLKFBOUT_MULT_F"]
         / g["DIVCLK_DIVIDE"] / g["CLKOUT0_DIVIDE_F"])
    return int(f) if f.denominator == 1 else float(f)


def copies(files):
    """[(what, ok, detail)] for the agreement checks (1-3), on `files`
    ({rel: text}) so a must-fire can hand in a mutated copy."""
    out = []
    chip = int(re.search(r"^\s*clock_hz:\s*(\d+)", files["info.yaml"], re.M).group(1))
    ps = clock.period_ps(chip)
    for rel in (PROJECT, ENGINE):
        v = param(files[rel], "CLK_PERIOD_PS")
        out.append(("%s CLK_PERIOD_PS" % rel, v == ps,
                    "%s, want %d (info.yaml %d Hz)" % (v, ps, chip)))
    cp = json.loads(files[CONFIG]).get("CLOCK_PERIOD")
    exact = Fraction(10 ** 9, chip)
    ok = cp is not None and abs(Fraction(str(cp)) - exact) <= Fraction(1, 1000)
    out.append(("%s CLOCK_PERIOD" % CONFIG, ok,
                "%s ns, want %.4f to 1 ps" % (cp, float(exact))))
    v = vh_default(files[CHIP_VH], "PE_CLK_PS")
    out.append(("%s PE_CLK_PS" % CHIP_VH, v == ps, "%s, want %d" % (v, ps)))
    num, den = param(files[ENGINE], "BAND_NUM"), param(files[ENGINE], "BAND_DEN")
    ok = bool(num and den) and Fraction(num, den) == clock.BAND
    out.append(("%s BAND_NUM/BAND_DEN" % ENGINE, ok,
                "%s/%s, want %s (model/clock.py)" % (num, den, clock.BAND)))
    fpga = int(re.search(r"^\s*clock_hz:\s*(\d+)", files["fpga/board.yaml"], re.M).group(1))
    m = mmcm_hz(files[FPGA_TOP])
    out.append(("%s MMCM CLKOUT0" % FPGA_TOP, m == fpga,
                "%s Hz, want %d (fpga/board.yaml)" % (m, fpga)))
    v = vh_default(files[FPGA_VH], "PE_FPGA_CLK_HZ")
    out.append(("%s PE_FPGA_CLK_HZ" % FPGA_VH, v == fpga, "%s, want %d" % (v, fpga)))
    ok = "board.yaml" in files[FPGA_TCL] and "CLK_HZ=$clk_hz" in files[FPGA_TCL]
    out.append(("%s passes board.yaml clock_hz" % FPGA_TCL, ok,
                "reads board.yaml and passes CLK_HZ" if ok else "does not"))
    return out


def spec(hz, engine_text=None, band=None, rtl_ps=None):
    """[(what, ok, detail)] for check 4 at clock `hz`. `band` overrides the
    band used to judge; `rtl_ps` sizes the RTL's counts for a DIFFERENT
    period than the one judged (a must-fire: the stale-period defect). The
    counts are always the RTL's own formula."""
    out = []
    ps = clock.period_ps(hz)
    band = clock.BAND if band is None else band
    hold = hold_bound.bound(period_ps=rtl_ps or ps, text=engine_text)
    setup = hold_bound.setup(period_ps=rtl_ps or ps, text=engine_text)
    real = lambda n: Fraction(n * 10 ** 9, hz)            # cycles -> ns, exact
    for name, n, need in (("SDA hold", hold, HOLD_NS), ("SDA setup", setup, SETUP_NS)):
        ok = real(n) >= need * band
        out.append(("%s @ %g MHz" % (name, hz / 1e6), ok,
                    "%d cycles = %.1f ns, need >= %d x %s = %.1f"
                    % (n, float(real(n)), need, band, float(need * band))))
    ok = real(hold) + FMP_TR_NS <= FMP_VD_DAT_NS
    out.append(("SDA hold under Fm+ t_VD;DAT @ %g MHz" % (hz / 1e6), ok,
                "%.1f + t_r %d = %.1f ns, max %d" % (float(real(hold)), FMP_TR_NS,
                                                    float(real(hold)) + FMP_TR_NS,
                                                    FMP_VD_DAT_NS)))
    tick_ns = (16384 * ps) // 1000                      # clock-ok: the RTL's shipped prescaler and its ns floor
    ticks = -(-STRETCH_NS // tick_ns)
    lo, hi = real((ticks - 1) * 16384 + 1), real(ticks * 16384)   # clock-ok: shipped prescaler
    ok = lo <= STRETCH_NS * Fraction(105, 100) and hi >= STRETCH_NS
    out.append(("stretch bound @ %g MHz" % (hz / 1e6), ok,
                "%d ticks: %.2f..%.2f ms, must reach 35 ms" % (ticks, float(lo) / 1e6,
                                                             float(hi) / 1e6)))
    import gate_um10204 as um
    with clock.at(hz):
        tc = um.table_cycles()
    bad = ["%s %s %d cyc = %.0f ns < %d x %s" % (m, k, n, float(real(n)), um.UM10204[m][k], band)
           for m, d in tc.items() for k, n in d.items()
           if real(n) < um.UM10204[m][k] * band]
    out.append(("UM10204 floors @ %g MHz (%d entries)" % (hz / 1e6, sum(len(d) for d in tc.values())),
                not bad, "; ".join(bad) or "every floor meets its minimum with the band"))
    return out


def write_headers():
    chip, fpga = clock.target_hz("chip"), clock.target_hz("fpga")
    for rel, macro, val in ((CHIP_VH, "PE_CLK_PS", clock.period_ps(chip)),
                            (FPGA_VH, "PE_FPGA_CLK_HZ", fpga)):
        t = read(rel)
        t2 = re.sub(r"(`define\s+%s\s+)\d+" % macro, r"\g<1>%d" % val, t)
        with open(os.path.join(ROOT, rel), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(t2)
        print("  wrote %s: %s %d%s" % (rel, macro, val, "" if t2 != t else " (unchanged)"))


def report(rows):
    rc = 0
    for what, ok, detail in rows:
        print("    %-52s %s  %s" % (what, "ok  " if ok else "*** RED", detail))
        rc |= 0 if ok else 1
    return rc


def main(argv):
    if "--write" in argv:
        write_headers()
        return 0
    rels = ["info.yaml", "fpga/board.yaml", PROJECT, ENGINE, CONFIG, CHIP_VH,
            FPGA_VH, FPGA_TOP, FPGA_TCL]
    files = {r: read(r) for r in rels}
    rc = 0
    print("  --- 1-3. every copy of the clock agrees with its board config ---")
    rc |= report(copies(files))
    print("  --- 4. derived counts meet their spec, per target ---")
    for t in sorted(clock.TARGETS):
        rc |= report(spec(clock.target_hz(t)))
    print("  --- 5. must-fires (a mutated copy must go red) ---")
    chip = clock.target_hz("chip")
    ps = clock.period_ps(chip)
    other = 60_000_000 if chip != 60_000_000 else 50_000_000   # clock-ok: the must-fire's mismatched clock
    mut = []
    f = dict(files)
    f[PROJECT] = re.sub(r"(parameter\s+integer\s+CLK_PERIOD_PS\s*=\s*)\d+",
                        r"\g<1>%d" % (ps + 1), files[PROJECT])
    mut.append(("project.v period off by 1 ps", f))
    f = dict(files)
    cfg = json.loads(files[CONFIG]); cfg["CLOCK_PERIOD"] = round(1e9 / other, 3)
    f[CONFIG] = json.dumps(cfg)
    mut.append(("config.json at the other clock", f))
    f = dict(files)
    f["info.yaml"] = re.sub(r"(clock_hz:\s*)\d+", r"\g<1>%d" % other, files["info.yaml"])
    mut.append(("info.yaml moved alone", f))
    f = dict(files)
    f[CHIP_VH] = re.sub(r"(`define\s+PE_CLK_PS\s+)\d+", r"\g<1>%d" % (ps * 2), files[CHIP_VH])
    mut.append(("bench header stale", f))
    f = dict(files)
    f[ENGINE] = re.sub(r"(parameter\s+integer\s+BAND_NUM\s*=\s*)\d+",
                       lambda m: m.group(1) + str(int(m.group(0).split("=")[1]) + 1), files[ENGINE])
    mut.append(("RTL band moved off clock.py's", f))
    f = dict(files)
    f[FPGA_TOP] = files[FPGA_TOP].replace("CLKOUT0_DIVIDE_F(20.000)", "CLKOUT0_DIVIDE_F(16.000)")
    mut.append(("MMCM retuned without board.yaml", f))
    for what, fm in mut:
        red = any(not ok for _w, ok, _d in copies(fm))
        print("    must-fire: %-40s %s" % (what, "red  ok" if red else "*** MISSED"))
        rc |= 0 if red else 1
    # the spec checks: THE DEFECT ITSELF -- the RTL's counts sized for a 20 ns
    # period, judged at a 60 MHz clock (15 cycles = 250 ns < 300)
    red = any(not ok for _w, ok, _d in spec(60_000_000, rtl_ps=20_000))   # clock-ok: the defect's two clocks
    print("    must-fire: %-40s %s" % ("hold sized for 20 ns, run at 60 MHz", "red  ok" if red else "*** MISSED"))
    rc |= 0 if red else 1
    # ... and the MAXIMUM (Wilson 11-03): slower is safe for minima only. A hold
    # sized for 60 MHz run on the 50 MHz board outlasts Fm+'s t_VD;DAT.
    red = any(not ok for w, ok, _d in spec(50_000_000, rtl_ps=16_666)   # clock-ok: the two targets' clocks
              if "t_VD;DAT" in w)
    print("    must-fire: %-40s %s" % ("60 MHz hold on the 50 MHz board (max)", "red  ok" if red else "*** MISSED"))
    rc |= 0 if red else 1
    # ... and the defect this gate exists for: the 20 ns RTL period at a 60 MHz
    # chip (project.v and pe_engine.v left at 50 MHz while info.yaml moved)
    f = dict(files)
    f["info.yaml"] = re.sub(r"(clock_hz:\s*)\d+", r"\g<1>%d" % other, files["info.yaml"])
    f[CONFIG] = json.dumps(dict(json.loads(files[CONFIG]),
                                CLOCK_PERIOD=round(1e9 / other, 3)))
    red = any(not ok for _w, ok, _d in copies(f))
    print("    must-fire: %-40s %s" % ("clock moved in config, not in RTL", "red  ok" if red else "*** MISSED"))
    rc |= 0 if red else 1
    print()
    print("  GATE clock-consistency: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
