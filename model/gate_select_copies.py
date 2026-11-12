"""SELECT COPIES: the per-group select copies survive LibreLane's own synthesis (Wilson 11-12, option b).

⛔⛔ WHY. The s12 swap step drives three register groups -- A = acc,
B = dv_r / dv_q, D = dv_d -- from one compare. b6's slow-corner path ran
through ONE merged select net feeding all three (`_24011_`); the fix keeps a
copy per group with `(* keep *)` on the five select nets in src/project.v
(pa_op, pb_op, pu_op_lo, pu_op_hi, pv_op; 0dd6777).
MEASURED 11-12 (LibreLane 3.1.0.dev3 synthesis, DELAY 4, depth 6 from acc[13]):
keep on the nets 0 merged, keep_hierarchy 0, neither 13.
⛔ THE MERGE ONLY HAPPENS IN LIBRELANE'S SYNTHESIS. CI's generic netlist
(test/local_netlist.sh) and yosys + dfflibmap / abc -liberty read keep and
no-keep the SAME -- a check on them cannot fail. So this gate runs LibreLane's
own Yosys.Synthesis step (dockerized, the pinned version) on the tree, twice:
  clean   -> the tree as it is: merged must be 0
  nokeep  -> the same tree with `(* keep *)` stripped from exactly those five
             declarations: merged must be > 0. Without this arm the gate
             proves nothing (Wilson 11-12).
"merged" = a net in the forward cone of u_s0.u_s12.acc[13] (combinational,
flops stop the walk) that reaches flops of ALL of A, B and D within 6 levels.
The group flops must be found (floors below) or the walk is vacuous: red.

ENVIRONMENT. Linux (CI): python with librelane on PE_LL_PY (default: this
python), the PDK through Ciel at $PDK_ROOT, tt-support-tools at $PE_TT_DIR
(default ./tt), docker with the image. Windows: the local WSL flow
(/opt/c1: LibreLane 3.1.0.dev3, manual PDK) -- a DEVELOPMENT reading; CI's
pinned 3.1.0.dev4 is the one of record. A missing tool is COULD NOT RUN, red.
Judge must-fires on planted netlists run first, without any tool.
POSITIVE TOKEN: `GATE select-copies: PASSED`.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

START = "u_s0.u_s12.acc[13]"
DEPTH = 6
GROUPS = (("A", r"u_s0\.u_s12\.acc\["), ("B", r"u_s0\.u_s12\.dv_[rq]\["), ("D", r"u_s0\.u_s12\.dv_d\["))
#: group flops found 11-12: A 75, B 53, D 23. Floors well under, so an RTL
#: change that renames or drops a group reads red rather than vacuously green.
FLOORS = {"A": 64, "B": 40, "D": 16}
#: the five kept select declarations (src/project.v), stripped in the nokeep arm
KEPT = ("pa_op", "pb_op", "pu_op_lo", "pu_op_hi", "pv_op")
KEEP_RX = re.compile(r"\(\*\s*keep\s*\*\)\s*(wire\s*\[\d+:0\]\s*(%s)\s*;)" % "|".join(KEPT))
STEP = "Yosys.Synthesis"
ARMS = (("clean", False, "PASS"), ("nokeep", True, "FAIL"))

# the local WSL flow (pr_cto.sh's environment)
WSL_PY, WSL_PDK, WSL_TT = "/opt/c1/venv/bin/python", "/opt/c1/pdk", "/opt/c1/pitc2chk/tt"


class CouldNotRun(Exception):
    pass


def _seq(t):
    return bool(re.match(r"\$_(S?DFF|DFFE|SDFFE|SDFFCE|DLATCH|ALDFF)", t)) \
        or t in ("$dff", "$adff", "$sdff", "$dffe") \
        or bool(re.match(r"sg13cmos5l_(s?df|dlh|dll)", t))


def judge(nl, top, start=START, depth=DEPTH):
    """(problems, info) for one yosys JSON netlist: problems is empty iff the
    walk is real (start found, every group's flops found) and NO net in the
    start's forward cone reaches all of A, B and D within `depth` levels."""
    mods = nl.get("modules", {})
    if top not in mods:
        return ["the netlist has no module %s" % top], {}
    m = mods[top]
    names = {}
    for n, v in m.get("netnames", {}).items():
        for i, b in enumerate(v["bits"]):
            if isinstance(b, int):
                names.setdefault(b, "%s[%d]" % (n, i) if len(v["bits"]) > 1 else n)
    sinks, outs, isff, grp = defaultdict(list), {}, {}, {}
    for cn, c in m.get("cells", {}).items():
        dirs = c.get("port_directions", {})
        o = [b for p, bs in c["connections"].items() if dirs.get(p) == "output"
             for b in bs if isinstance(b, int)]
        ff = _seq(c["type"])
        outs[cn], isff[cn] = o, ff
        if ff and o:
            grp[cn] = next((k for k, rx in GROUPS if re.match(rx, names.get(o[0], ""))), None)
        for p, bs in c["connections"].items():
            if dirs.get(p) == "input":
                for b in bs:
                    if isinstance(b, int):
                        sinks[b].append(cn)
    found = {k: sum(1 for v in grp.values() if v == k) for k, _ in GROUPS}
    info = {"groups": found, "cone": 0, "merged": []}
    probs = ["group %s: %d flops found (floor %d) -- the walk would be vacuous"
             % (k, found[k], FLOORS.get(k, 1)) for k, _ in GROUPS if found[k] < FLOORS.get(k, 1)]
    st = [b for b, n in names.items() if n == start]
    if not st:
        return probs + ["start net %s not in the netlist" % start], info
    if probs:
        return probs, info

    def reach(b):
        seen, front, got = {b}, [b], set()
        for _ in range(depth):
            nxt = []
            for x in front:
                for cn in sinks.get(x, ()):
                    if isff[cn]:
                        if grp.get(cn):
                            got.add(grp[cn])
                        continue
                    for y in outs[cn]:
                        if y not in seen:
                            seen.add(y)
                            nxt.append(y)
            front = nxt
        return got

    seen, front, cone = {st[0]}, [st[0]], []
    for _ in range(80):
        nxt = []
        for x in front:
            for cn in sinks.get(x, ()):
                if isff[cn]:
                    continue
                for y in outs[cn]:
                    if y not in seen:
                        seen.add(y)
                        nxt.append(y)
                        cone.append(y)
        front = nxt
    merged = [b for b in cone if reach(b) >= {"A", "B", "D"}]
    info.update(cone=len(cone), merged=[names.get(b, "bit%d" % b) for b in merged])
    return ["%d net(s) reach all of A, B, D within %d levels: %s"
            % (len(merged), depth, ", ".join(info["merged"][:4]))] if merged else [], info


def strip_keep(text):
    """(text with `(* keep *)` removed from the five select declarations, count)."""
    return KEEP_RX.subn(r"\1", text)


# ---------------------------------------------------------------------------
# judge must-fires: planted netlists
# ---------------------------------------------------------------------------
def _planted(merged=False, start="s", drop=None, top="top"):
    """start -> buf -> per-group nets -> flops of A / B / D (FLOORS of each);
    `merged` adds one net feeding a flop of every group."""
    nn, cells, bit = {}, {}, [10]

    def new(name):
        bit[0] += 1
        nn[name] = {"bits": [bit[0]]}
        return bit[0]

    s = new(start)
    regs = {"A": "u_s0.u_s12.acc", "B": "u_s0.u_s12.dv_r", "D": "u_s0.u_s12.dv_d"}
    for g, base in regs.items():
        if g == drop:
            continue
        sel = new("sel_" + g)
        cells["b_" + g] = {"type": "$_BUF_", "port_directions": {"A": "input", "Y": "output"},
                           "connections": {"A": [s], "Y": [sel]}}
        for i in range(FLOORS[g]):
            q = bit[0] + 1
            nn.setdefault(base, {"bits": []})["bits"].append(q)
            bit[0] = q
            cells["f_%s%d" % (g, i)] = {"type": "$_DFF_P_",
                                         "port_directions": {"D": "input", "Q": "output"},
                                         "connections": {"D": [sel], "Q": [q]}}
    if merged:
        mg = new("merged")
        cells["b_m"] = {"type": "$_BUF_", "port_directions": {"A": "input", "Y": "output"},
                        "connections": {"A": [s], "Y": [mg]}}
        for g in regs:
            cells["f_%s0"% g]["connections"]["D"] = [mg]
    return {"modules": {top: {"netnames": nn, "cells": cells}}}


def must_fires():
    """([(label, red?)], control green?) -- the planted start net has its own
    name (the planted acc flops already carry acc[13])"""
    st = "u_s0.u_s12.p_start"
    return [("one select net feeds A, B and D", bool(judge(_planted(True, st), "top", start=st)[0])),
            ("start net missing", bool(judge(_planted(False, st), "top", start="u_s0.u_s12.absent")[0])),
            ("group D has no flops", bool(judge(_planted(False, st, drop="D"), "top", start=st)[0])),
            ("top module missing", bool(judge(_planted(False, st), "nope", start=st)[0]))], \
        not judge(_planted(False, st), "top", start=st)[0]


# ---------------------------------------------------------------------------
# the LibreLane synthesis arms
# ---------------------------------------------------------------------------
def environment():
    """(how, settings) -- 'native' on Linux, 'wsl' on Windows; CouldNotRun."""
    if os.name == "nt":
        if not shutil.which("wsl.exe"):
            raise CouldNotRun("Windows without wsl.exe: no LibreLane to run")
        r = subprocess.run(["wsl.exe", "--", "test", "-x", WSL_PY])
        if r.returncode:
            raise CouldNotRun("no LibreLane python at %s in WSL" % WSL_PY)
        return "wsl", {"py": WSL_PY, "pdk_root": WSL_PDK, "tt": WSL_TT,
                       "pdk_args": "--manual-pdk", "tt_args": "--ihp",
                       "label": "LOCAL WSL flow (development reading; CI is the record)"}
    py = os.environ.get("PE_LL_PY", sys.executable)
    tt = os.environ.get("PE_TT_DIR", os.path.join(ROOT, "tt"))
    pdk = os.environ.get("PDK_ROOT")
    if not pdk:
        raise CouldNotRun("PDK_ROOT is not set")
    if not os.path.isfile(os.path.join(tt, "tt_tool.py")):
        raise CouldNotRun("no tt-support-tools at %s (PE_TT_DIR)" % tt)
    if subprocess.run([py, "-c", "import librelane"], capture_output=True).returncode:
        raise CouldNotRun("%s cannot import librelane (PE_LL_PY)" % py)
    if not shutil.which("docker"):
        raise CouldNotRun("docker is not on PATH")
    return "native", {"py": py, "pdk_root": pdk, "tt": tt, "pdk_args": "",
                      "tt_args": "--pdk ihp-sg13cmos5l", "label": "native"}


BUILD = r"""#!/usr/bin/env bash
# one LibreLane synthesis of the design copy in this directory
set -u
cd "$(dirname "$0")" || exit 2
export PATH="$(dirname "$PY"):$PATH"
# a COPY, not a link: the merged config names tt/tech/... files, and the
# dockerized flow mounts only this directory (a link out of it dangles there)
cp -r "$TT" tt || exit 2
"$PY" ./tt/tt_tool.py --create-user-config $TT_ARGS > cfg.log 2>&1 || { tail -5 cfg.log; exit 3; }
rm -rf runs/wokwi && mkdir -p runs/wokwi
"$PY" -m librelane --pdk-root "$PDK_ROOT" --docker-no-tty --dockerized --pdk ihp-sg13cmos5l $PDK_ARGS \
  --run-tag wokwi --force-run-dir runs/wokwi --to "$STEP" --hide-progress-bar src/config_merged.json > ll.log 2>&1
rc=$?
echo "librelane $("$PY" -c 'import importlib.metadata as m; print(m.version("librelane"))') rc=$rc"
[ $rc -eq 0 ] || tail -8 ll.log
exit $rc
"""


def run_arm(how, env, strip, top):
    """(netlist json, stripped count, note) or (None, count, error)."""
    # ⛔ UNDER THE REPO, NOT /tmp (CI 43305666324): the pinned tt-support-tools
    # reads the ports with yowasp-yosys, whose sandbox cannot see /tmp -- the
    # first CI run failed at create-user-config ("src/project.v not found").
    # The canary builds in the checkout too. Removed below, run or fail.
    work = tempfile.mkdtemp(prefix=".selcopies_", dir=ROOT)
    try:
        shutil.copytree(os.path.join(ROOT, "src"), os.path.join(work, "src"))
        # info.yaml, and every root-level .py: LibreLane imports any
        # librelane_plugin_*.py in the design directory (Project.ExtendPowerStripes,
        # which src/config.json's flow substitutes in) and that loads odb_stripes.py
        for f in ["info.yaml"] + sorted(glob.glob(os.path.join(ROOT, "*.py"))):
            shutil.copy(os.path.join(ROOT, f), work)
        n = 0
        if strip:
            p = os.path.join(work, "src", "project.v")
            text = open(p, encoding="utf-8").read()
            text, n = strip_keep(text)
            open(p, "w", encoding="utf-8", newline="\n").write(text)
        sh = os.path.join(work, "build.sh")
        open(sh, "w", newline="\n").write(BUILD)
        vals = {"PY": env["py"], "TT": env["tt"], "PDK_ROOT": env["pdk_root"],
                "PDK_ARGS": env["pdk_args"], "TT_ARGS": env["tt_args"], "STEP": STEP}
        if how == "wsl":
            from gate_formal_miters import wslpath
            argv = ["wsl.exe", "--", "env"] + ["%s=%s" % kv for kv in vals.items()] \
                + ["bash", wslpath(sh)]
            r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
        else:
            e = dict(os.environ)
            e.update(vals)
            r = subprocess.run(["bash", sh], capture_output=True, text=True, env=e,
                               encoding="utf-8", errors="replace")
        out = (r.stdout + r.stderr).strip()
        js = glob.glob(os.path.join(work, "runs", "wokwi", "*-yosys-synthesis", "%s.nl.v.json" % top))
        if r.returncode or not js:
            return None, n, "LibreLane synthesis failed (rc %d): %s" % (
                r.returncode, " | ".join(out.splitlines()[-4:]))
        return json.load(open(js[0], encoding="utf-8")), n, out.splitlines()[-1] if out else ""
    finally:
        cleanup(how, work)


def cleanup(how, work):
    """remove the work dir: it sits in the checkout now. rmtree can lose a race
    with WSL's file handles (11-12, 3 files left per arm) and cannot remove the
    root-owned files a dockerized flow writes on Linux -- so retry, then `rm -rf`,
    then name what is left (a leftover is untidy, not a wrong verdict)."""
    import time
    for _ in range(3):
        shutil.rmtree(work, ignore_errors=True)
        if not os.path.exists(work):
            return
        time.sleep(1)
    if how == "wsl":
        from gate_formal_miters import wslpath
        subprocess.run(["wsl.exe", "--", "rm", "-rf", wslpath(work)], capture_output=True)
    else:
        subprocess.run(["rm", "-rf", work], capture_output=True)
        if os.path.exists(work) and shutil.which("sudo"):
            subprocess.run(["sudo", "-n", "rm", "-rf", work], capture_output=True)
    if os.path.exists(work):
        print("  (work dir left behind: %s)" % work)


def top_module():
    info = open(os.path.join(ROOT, "info.yaml"), encoding="utf-8").read()
    t = re.search(r'^\s*top_module:\s*"([^"]+)"', info, re.M)
    if not t:
        raise ValueError("info.yaml: no top_module")
    return t.group(1)


def main():
    print("GATE select-copies: the per-group select copies survive LibreLane's synthesis")
    rc = 0
    print("  --- judge must-fires ---")
    mf, control = must_fires()
    for label, red in mf:
        print("  must-fire: %-40s %s" % (label, "red  ok" if red else "*** STAYED GREEN"))
        rc |= 0 if red else 1
    print("  control:   %-40s %s" % ("one select net per group", "green ok" if control else "*** RED"))
    rc |= 0 if control else 1
    text = open(os.path.join(ROOT, "src", "project.v"), encoding="utf-8").read()
    n = strip_keep(text)[1]
    ok = n == len(KEPT)
    print("  kept select declarations in src/project.v: %d of %d  %s"
          % (n, len(KEPT), "ok" if ok else "*** the nokeep arm would not strip what it names"))
    rc |= 0 if ok else 1
    try:
        top = top_module()
        how, env = environment()
    except (OSError, ValueError, CouldNotRun) as e:
        print("  *** COULD NOT RUN: %s\n\n  GATE select-copies: FAILED" % e)
        return 1
    print("  flow    : %s, --to %s (%s)" % (how, STEP, env["label"]))
    print("  --- arms (merged = nets from %s reaching A, B and D within %d levels) ---" % (START, DEPTH))
    for arm, strip, expect in ARMS:
        nl, stripped, note = run_arm(how, env, strip, top)
        if nl is None:
            print("  %-7s *** %s" % (arm, note))
            rc = 1
            continue
        probs, info = judge(nl, top)
        merged = len(info.get("merged", []))
        if expect == "PASS":
            ok = not probs
        else:   # red for its OWN reason: the walk is real and the copies merged
            ok = merged > 0 and stripped == len(KEPT)
        print("  %-7s %-4s groups A %d / B %d / D %d, cone %d, merged %d, keep stripped %d  [%s]  %s"
              % (arm, expect, info.get("groups", {}).get("A", 0), info.get("groups", {}).get("B", 0),
                 info.get("groups", {}).get("D", 0), info.get("cone", 0), merged, stripped, note,
                 "ok" if ok else "***"))
        for p in probs[:3]:
            print("      %s %s" % ("***" if expect == "PASS" else "|", p))
        rc |= 0 if ok else 1
    print("\n  GATE select-copies: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
