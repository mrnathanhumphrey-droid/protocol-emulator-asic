"""ONE FLOW FOR EVERY MEASUREMENT (Wilson 11-12): a local synthesis / placement /
routing run that informs a decision runs the SHIPPING flow -- the pins in
.github/workflows/gds.yaml (tools-ref, librelane-version) and ci/pdk.sha -- or
it does not run.

    python ci/flow_pins.py --py <python> --tt <tt-support-tools dir> --pdk-root <dir> [--wsl]
    python ci/flow_pins.py --self-test

Prints each pin against what the flow has, and exits 1 on any mismatch. The
pins are READ from gds.yaml / ci/pdk.sha, never typed here.
WHY: on 11-12 the s12 copy check read 0 merged on the local dev3 flow and 6 on
CI's dev4 -- a decision (keep on nets, 0dd6777) was made on a flow that does
not ship. The local dev3 flow is retired.
MUST-FIRE (--self-test, and model/gate_select_copies.py): the retired dev3 flow
(LibreLane 3.1.0.dev3, tt d66cf17, a manual PDK) is refused; the pins
themselves pass; an unparseable gds.yaml is refused.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pins(gds_text=None, pdk_text=None):
    """{'librelane', 'tt', 'pdk'} from gds.yaml and ci/pdk.sha; ValueError if absent."""
    if gds_text is None:
        gds_text = open(os.path.join(ROOT, ".github", "workflows", "gds.yaml"), encoding="utf-8").read()
    if pdk_text is None:
        pdk_text = open(os.path.join(ROOT, "ci", "pdk.sha"), encoding="utf-8").read()
    ll = re.search(r"^\s*librelane-version:\s*['\"]?([0-9][\w.]*)", gds_text, re.M)
    tt = re.search(r"^\s*tools-ref:\s*['\"]?([0-9a-f]{40})", gds_text, re.M)
    pdk = re.fullmatch(r"\s*([0-9a-f]{40})\s*", pdk_text)
    if not (ll and tt and pdk):
        raise ValueError("gds.yaml / ci/pdk.sha: a pin is missing (librelane %s, tools-ref %s, pdk %s)"
                         % (bool(ll), bool(tt), bool(pdk)))
    return {"librelane": ll.group(1), "tt": tt.group(1), "pdk": pdk.group(1)}


def problems(have, want):
    """[problem] comparing a flow's {'librelane', 'tt', 'pdk_versions'} with the pins."""
    out = []
    if have.get("librelane") != want["librelane"]:
        out.append("LibreLane %s, the shipping flow pins %s" % (have.get("librelane"), want["librelane"]))
    if not (have.get("tt") or "").startswith(want["tt"]) or len(have.get("tt") or "") < 7:
        out.append("tt-support-tools %s, the shipping flow pins %s" % (have.get("tt"), want["tt"]))
    if want["pdk"] not in (have.get("pdk_versions") or []):
        out.append("PDK versions %s, the shipping flow pins %s (Ciel)"
                   % (have.get("pdk_versions") or "none", want["pdk"][:8]))
    return out


def probe(py, tt, pdk_root, wsl=False):
    """What a flow HAS: its LibreLane version, its tt checkout's commit, the Ciel
    PDK versions under pdk_root. Run inside WSL when `wsl`."""
    sh = ('%s -c "import importlib.metadata as m; print(m.version(\'librelane\'))" 2>/dev/null; '
          'echo "@@"; git -C %s rev-parse HEAD 2>/dev/null; echo "@@"; '
          'ls -d %s/ciel/*/versions/*/ 2>/dev/null | xargs -n1 basename 2>/dev/null' % (py, tt, pdk_root))
    argv = (["wsl.exe", "-e", "bash", "-c", sh] if wsl else ["bash", "-c", sh])
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    parts = (r.stdout.replace("\r", "") + "@@@@").split("@@")
    return {"librelane": parts[0].strip() or None, "tt": parts[1].strip() or None,
            "pdk_versions": parts[2].split()}


#: the retired local flow (the must-fire): what /opt/c1/venv + pitc2chk/tt + the manual PDK were
DEV3 = {"librelane": "3.1.0.dev3", "tt": "d66cf17", "pdk_versions": []}


def self_test():
    want = pins()
    ok_pins = not problems({"librelane": want["librelane"], "tt": want["tt"],
                            "pdk_versions": [want["pdk"]]}, want)
    red_dev3 = bool(problems(DEV3, want))
    try:
        pins("name: gds\n", want["pdk"])
        red_parse = False
    except ValueError:
        red_parse = True
    return [("the retired dev3 flow is refused", red_dev3),
            ("an unparseable gds.yaml is refused", red_parse)], ok_pins


def main(argv):
    if "--self-test" in argv:
        mf, ctl = self_test()
        for label, red in mf:
            print("  must-fire: %-40s %s" % (label, "red  ok" if red else "*** STAYED GREEN"))
        print("  control:   %-40s %s" % ("the pins themselves", "green ok" if ctl else "*** RED"))
        return 0 if all(r for _, r in mf) and ctl else 1
    wsl = "--wsl" in argv
    kv = [x for x in argv if x != "--wsl"]
    a = dict(zip(kv[::2], kv[1::2]))
    want = pins()
    have = probe(a.get("--py", "python3"), a.get("--tt", "tt"), a.get("--pdk-root", ""), wsl=wsl)
    print("  flow pins (gds.yaml / ci/pdk.sha): librelane %s, tt %s, pdk %s"
          % (want["librelane"], want["tt"][:7], want["pdk"][:8]))
    print("  this flow                        : librelane %s, tt %s, pdk %s"
          % (have["librelane"], (have["tt"] or "?")[:7], ",".join(v[:8] for v in have["pdk_versions"]) or "none"))
    p = problems(have, want)
    for x in p:
        print("  *** REFUSED: %s" % x)
    print("  FLOW PINS: %s" % ("MATCH" if not p else "MISMATCH -- this flow may not inform a decision"))
    return 1 if p else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
