"""B6 SLACK -- select-copies re-based on b6's MEASURED slack (Wilson 11-15 select-copies ruling,
option (b); confirmed 11-16).

⛔⛔ WHY. gate_select_copies used to pass on "merged = 0": the per-group select copies of the s12
swap step surviving LibreLane's synthesis. That expectation was established on SYNTH_STRATEGY
"DELAY 4"; under the configuration of record ("AREA 0", 9c0df0c) CI measures merged = 2. The
copies existed to protect b6's slow-corner path, so the ruling judges the thing itself: b6's
slack, measured in the post-route STA of the configuration of record, must be at least
THRESHOLD_NS on every run of the spread that reached STA. The merged count stays a REPORTED
number (gate_select_copies prints it), not the pass condition.

The record (model/b6_slack.json) is GENERATED from the runs' own reports:

    python3 model/b6_slack.py --write <run dir> [<run dir> ...]     (in WSL, beside /opt/c1)

Each run dir is a LibreLane run root (<dir>/runs/wokwi/...); the scan reads its slow-corner
max.rpt and, for each b6 net, the worst slack of a reported path through it. A net absent from
the report's top paths is recorded as a LOWER BOUND (the report's last slack), marked "ge".

The record is TIED to the configuration it was measured on (model/config_tie.py, da001d8): every
key of src/config.json at the harden commit, except comments and the spread variable
PL_WIRE_LENGTH_COEF. Any key that moves, disappears or is added reads STALE -- red, never a pass --
until the runs are re-measured on the new configuration and the record regenerated.

    problems(record=None, config=None) -> [problem]   (empty: b6 holds on the configuration of record)

Must-fires (self_test): a run below the threshold is red; a net with no slack is red; an empty
record is red; a moved key is STALE; an added key is STALE; the record as measured passes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RECORD = os.path.join(HERE, "b6_slack.json")
sys.path.insert(0, HERE)

#: Wilson 11-15 (select-copies ruling): b6's slack must clear this at every coefficient and margin
THRESHOLD_NS = 1.5
#: b6's two nets in the s12 swap step (the path the select copies protected)
NETS = ("u_s0.u_s12.op_anz", "u_s0.u_s12.p_lt_s0")
#: the spread variable: each run sets it; it is not part of the configuration of record
SPREAD_KEY = "PL_WIRE_LENGTH_COEF"
MAX_RPT = os.path.join("runs", "wokwi", "58-openroad-stapostpnr", "nom_slow_1p08V_125C", "max.rpt")


def scan(rpt_text):
    """{net: (slack, bound)} -- bound "eq" for the worst reported path through the net, "ge" (the
    report's last slack) when no reported path crosses it; None if the report has no paths."""
    blocks = re.split(r"\n(?=Startpoint: )", rpt_text)
    via, last = {n: None for n in NETS}, None
    for b in blocks:
        m = re.search(r"(-?\d+\.\d+)\s+slack \((?:MET|VIOLATED)\)", b)
        if not m:
            continue
        s = float(m.group(1))
        last = s
        for k in NETS:
            if (k + " (net)") in b and (via[k] is None or s < via[k]):
                via[k] = s
    if last is None:
        return None
    return {k: ([via[k], "eq"] if via[k] is not None else [last, "ge"]) for k in NETS}


def tie_of(config):
    return {k: v for k, v in config.items() if not k.startswith("//") and k != SPREAD_KEY}


def write(run_dirs, commit):
    # PE_B6_CONFIG: the harden commit's src/config.json, exported beforehand (`git show
    # <commit>:src/config.json`) -- WSL's git cannot open a worktree whose .git names a Windows path
    if os.environ.get("PE_B6_CONFIG"):
        with open(os.environ["PE_B6_CONFIG"], encoding="utf-8") as fh:
            cfg = json.load(fh)
    else:
        cfg = json.loads(subprocess.run(["git", "-C", ROOT, "show", "%s:src/config.json" % commit],
                                        capture_output=True, text=True, check=True).stdout)
    runs = {}
    for d in run_dirs:
        name = os.path.basename(os.path.normpath(d))
        with open(os.path.join(d, MAX_RPT), errors="replace") as fh:
            sl = scan(fh.read())
        with open(os.path.join(d, "runs", "wokwi", "resolved.json")) as fh:
            coef = json.load(fh).get(SPREAD_KEY)
        runs[name] = {"coef": coef, "slack_ns": sl}
    rec = {"what": "b6 slow-corner slack per run of the spread (model/b6_slack.py)",
           "commit": commit, "threshold_ns": THRESHOLD_NS, "nets": list(NETS),
           "runs": runs, "config": tie_of(cfg)}
    with open(RECORD, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return rec


def load():
    with open(RECORD, encoding="utf-8") as fh:
        return json.load(fh)


def problems(record=None, config=None):
    import config_tie as CT
    rec = load() if record is None else record
    cfg = CT.config_of_record() if config is None else config
    out = []
    runs = rec.get("runs") or {}
    if not runs:
        out.append("b6 slack record has NO runs: nothing measured")
    for name, r in sorted(runs.items()):
        sl = r.get("slack_ns")
        if not sl:
            out.append("%s: no slack read from its report" % name)
            continue
        for net in NETS:
            v = sl.get(net)
            if not v or v[0] is None:
                out.append("%s: no slack for %s" % (name, net))
            elif v[0] < THRESHOLD_NS:
                out.append("%s: b6 slack through %s %+.3f ns is below %.1f ns"
                           % (name, net.split(".")[-1], v[0], THRESHOLD_NS))
    tie = rec.get("config") or {}
    out += CT.tie_problems(tie, cfg)
    for k in sorted(tie_of(cfg)):
        if k not in tie:
            out.append("STALE: the configuration of record gained %s = %r after b6 was measured "
                       "-- re-measure on it and regenerate the record" % (k, cfg[k]))
    return out


def self_test():
    good = {"runs": {"r": {"coef": 0.025, "slack_ns": {n: [THRESHOLD_NS + 1.0, "eq"] for n in NETS}}},
            "config": {"SYNTH_STRATEGY": "AREA 0"}}
    cfg = {"SYNTH_STRATEGY": "AREA 0", SPREAD_KEY: 0.026, "// note": "x"}
    low = json.loads(json.dumps(good))
    low["runs"]["r"]["slack_ns"][NETS[0]] = [THRESHOLD_NS - 0.001, "eq"]
    nonet = json.loads(json.dumps(good))
    del nonet["runs"]["r"]["slack_ns"][NETS[1]]
    return [
        ("a run below the threshold is red", bool(problems(low, cfg))),
        ("a net with no slack is red", bool(problems(nonet, cfg))),
        ("an empty record is red", bool(problems(dict(good, runs={}), cfg))),
        ("a moved key is STALE", bool(problems(good, dict(cfg, SYNTH_STRATEGY="DELAY 4")))),
        ("an added key is STALE", bool(problems(good, dict(cfg, GRT_LAYER_ADJUSTMENTS=[0, 0.5])))),
        ("the record as measured passes", not problems(good, cfg)),
    ]


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if "--write" in argv:
        i = argv.index("--write")
        commit = os.environ.get("PE_B6_COMMIT", "9c0df0c")
        rec = write(argv[i + 1:], commit)
        for n, r in sorted(rec["runs"].items()):
            print("%-22s coef %s  %s" % (n, r["coef"], r["slack_ns"]))
        return 0
    print("GATE b6_slack: b6's measured slow-corner slack on the configuration of record")
    ok = True
    for label, v in self_test():
        print("  must-fire %-36s %s" % (label, "ok" if v else "*** MISSED"))
        ok &= v
    for p in problems():
        print("  *** %s" % p)
        ok = False
    print()
    print("  GATE b6_slack: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
