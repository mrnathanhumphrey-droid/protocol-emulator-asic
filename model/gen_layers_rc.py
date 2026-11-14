"""gen_layers_rc -- THE PER-LAYER WIRE RC THE FLOW ESTIMATES WITH, GENERATED FROM EXTRACTION
(Wilson 11-13: "generated, never typed").

    python model/gen_layers_rc.py <source run dir> <check run dir> [--write]
        (WSL: run dirs under /opt/c1/<tag>, each with runs/wokwi/final/def and the RCX spef)

⛔⛔ WHY. With no LAYERS_RC the flow estimates wires with the tech LEF's RC, ~0.093
fF/um on Metal2-4 -- parallel-plate + fringe, no lateral coupling. RCX on the routed
s12 design measures 0.16-0.20 fF/um. The post-global-route repair therefore saw
half the capacitance: w027 estimated +4.03 ns where extraction read -0.385, and the
repair inserted no buffers. With these values kh27a_w027rc closed at +3.983 (estimate
+3.194: now 0.79 ns on the safe side).

THE DERIVATION (per run, Metal2 / Metal3 / Metal4):
  * C: the MEDIAN extracted wire capacitance per um (SPEF *D_NET total: ground +
    coupling) over signal nets routed >= SHARE on one layer and >= MIN_LEN um long
    (final DEF). The median, not the worst case, so the estimate does not swing to
    pessimism and over-buffer (Wilson).
  * R: NOT a median -- R/um carries the vias (~20 ohm each) and falls with net
    length. A least-squares fit R_net = r_layer * len + r_via * vias separates them;
    r_layer is written (it matches the LEF: 0.103 ohm/sq / 0.2 um = 0.515 ohm/um).
  * Units as LibreLane dev4's LAYERS_RC wants them (steps/openroad.py: "per unit
    length as defined in the first lib file"): kOhm/um, pF/um.
THE CHECK: the same derivation on a DIFFERENT netlist's run must agree per layer
within TOL (C and R); otherwise the coupling depends on density and the values
would need a margin -- REFUSED, nothing is written.
--write: model/layers_rc_of_record.json (values + derivation) and src/config.json's
LAYERS_RC / SIGNAL_WIRE_RC_LAYERS / CLOCK_WIRE_RC_LAYERS (Metal2..Metal4: signal and
clock routing both stop at Metal4, so TopMetal1 leaves the averaging).
model/gate_layers_rc.py checks the config against the record on every run.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RECORD = os.path.join(HERE, "layers_rc_of_record.json")
CONFIG = os.path.join(ROOT, "src", "config.json")
LAYERS = ("Metal2", "Metal3", "Metal4")
MIN_LEN, SHARE, TOL = 20.0, 0.90, 0.10
_KW = {"ROUTED", "NEW", "RECT", "VIRTUAL", "MASK", "+", ";", "-", "SHAPE", "STRIPE", "FIXED", "COVER"}


def _norm(n):
    return n.replace("\\", "")


def def_nets(path):
    """{net: (Counter(layer -> routed um), vias)} from a routed DEF's NETS section"""
    dbu, res, inn, cur, last = 1000.0, {}, False, None, None
    for ln in open(path):
        if ln.startswith("UNITS DISTANCE MICRONS"):
            dbu = float(ln.split()[3])
        if ln.startswith("NETS "):
            inn = True
            continue
        if ln.startswith("END NETS"):
            break
        if not inn:
            continue
        t = ln.split()
        if t and t[0] == "-":
            cur = _norm(t[1])
            res[cur] = [collections.Counter(), 0]
            last = None
            continue
        if cur is None:
            continue
        m = re.search(r"(?:ROUTED|NEW)\s+(Metal\d|TopMetal\d)", ln)
        if not m:
            continue
        lay, last = m.group(1), None
        for x, y in re.findall(r"\(\s*([-\d*]+)\s+([-\d*]+)(?:\s+[-\d]+)?\s*\)", ln):
            if last is not None:
                px, py = last
                xx = px if x == "*" else float(x)
                yy = py if y == "*" else float(y)
                res[cur][0][lay] += (abs(xx - px) + abs(yy - py)) / dbu
                last = (xx, yy)
            else:
                last = (float(x), float(y))
        s = re.sub(r"\([^)]*\)", " ", ln)
        res[cur][1] += sum(1 for w in s.split() if w not in _KW
                           and not re.match(r"^(Metal\d|TopMetal\d)$", w) and re.match(r"^[A-Za-z]", w))
    return res


def spef_nets(path):
    """({net: total C pF}, {net: sum R ohm}) from an RCX SPEF"""
    names, cap, rsum, sec, cur = {}, {}, collections.Counter(), None, None
    for ln in open(path):
        if ln.startswith("*NAME_MAP"):
            sec = "map"
            continue
        if sec == "map":
            t = ln.split()
            if ln.startswith("*") and len(t) == 2 and t[0][1:].isdigit():
                names[t[0]] = _norm(t[1])
                continue
            if not ln.strip():
                continue
            sec = None
        if ln.startswith("*D_NET"):
            t = ln.split()
            cur = names.get(t[1], _norm(t[1]))
            cap[cur] = float(t[2])
            sec = "net"
        elif ln.startswith("*RES"):
            sec = "res"
        elif ln.startswith(("*CAP", "*CONN")):
            sec = "net"
        elif ln.startswith("*END"):
            cur, sec = None, None
        elif sec == "res" and cur:
            t = ln.split()
            if len(t) == 4:
                rsum[cur] += float(t[3])
    return cap, rsum


def derive(run):
    """{layer: {n, cap (pF/um), res (kOhm/um), r_via (ohm)}} for one routed run"""
    d = glob.glob(os.path.join(run, "runs/wokwi/final/def/*.def"))[0]
    s = glob.glob(os.path.join(run, "runs/wokwi/*-openroad-rcx/nom/*.nom.spef"))[0]
    nets, (C, R) = def_nets(d), spef_nets(s)
    out = {}
    for lay in LAYERS:
        cs, X = [], []
        for n, (ly, nv) in nets.items():
            tot = sum(ly.values())
            if tot < MIN_LEN or n not in C or ly.most_common(1)[0][0] != lay or ly[lay] / tot < SHARE:
                continue
            cs.append(C[n] / tot)
            X.append((tot, nv, R[n]))
        sll = sum(a * a for a, b, r in X); svv = sum(b * b for a, b, r in X)
        slv = sum(a * b for a, b, r in X); slr = sum(a * r for a, b, r in X)
        svr = sum(b * r for a, b, r in X); det = sll * svv - slv * slv
        out[lay] = {"n": len(cs), "cap": statistics.median(cs),
                    "res": (slr * svv - svr * slv) / det / 1000.0,
                    "r_via": (sll * svr - slv * slr) / det}
    return {"run": run, "def": d, "spef": s, "layers": out}


def agreement(src, chk, tol=TOL):
    """[problem] where the check run's per-layer C or R differs from the source by > tol"""
    bad = []
    for lay in LAYERS:
        for k in ("cap", "res"):
            a, b = src["layers"][lay][k], chk["layers"][lay][k]
            if abs(b / a - 1) > tol:
                bad.append("%s %s: check / source = %.3f, outside +-%d %%" % (lay, k, b / a, tol * 100))
    return bad


def config_keys(rec):
    """the src/config.json keys the record implies"""
    return {"LAYERS_RC": {"*": {l: {"res": round(v["res"], 8), "cap": round(v["cap"], 8)}
                                for l, v in rec["source"]["layers"].items()}},
            "SIGNAL_WIRE_RC_LAYERS": list(LAYERS), "CLOCK_WIRE_RC_LAYERS": list(LAYERS)}


def main(argv):
    src_run, chk_run = argv[0], argv[1]
    src, chk = derive(src_run), derive(chk_run)
    for nm, r in (("source", src), ("check", chk)):
        print("== %s %s" % (nm, r["run"]))
        for l, v in r["layers"].items():
            print("  %-7s n %5d  C %.4f fF/um  R %.4f ohm/um  via %.1f ohm"
                  % (l, v["n"], v["cap"] * 1e3, v["res"] * 1e6, v["r_via"]))
    bad = agreement(src, chk)
    if bad:
        print("REFUSED -- the calibration does not hold on the check run:\n  " + "\n  ".join(bad))
        return 1
    print("check: every layer within +-%d %% (C and wire R)" % (TOL * 100))
    if "--write" in argv:
        rec = {"source": src, "check": chk, "min_len_um": MIN_LEN, "share": SHARE, "tol": TOL,
               "units": "res kOhm/um, cap pF/um, r_via ohm"}
        json.dump(rec, open(RECORD, "w", encoding="utf-8"), indent=1)
        # ⛔ src/config.json is NEVER round-tripped through json: its repeated "//"
        # comment keys would collapse. The keys are printed for a TEXT insertion
        # (beside their derivation comment); gate_layers_rc then holds them to the record.
        print("wrote %s; insert into src/config.json:" % RECORD)
        for k, v in config_keys(rec).items():
            print('  "%s": %s,' % (k, json.dumps(v)))
    return 0


if __name__ == "__main__":
    r = main(sys.argv[1:])
    sys.exit(r if isinstance(r, int) else 0)
