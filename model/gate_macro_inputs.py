"""MACRO INPUTS: no top-level input reaches the SRAM macro's input pins through combinational logic (Wilson 11-10).

⛔⛔ WHY. Many SRAM macros register their address / data / control inputs on
EVERY enabled clock edge, write or not. A raw (unsynchronised) pin sitting on
a macro input while a read in another slot enables the macro is sampled by
the macro's own input register -- a metastability exposure INSIDE A BLACK BOX,
which no property (model/gate_cdc_qual.py proves flops; the macro is not one)
can see into. So the rule is structural and absolute: every macro input pin is
driven only by flops (or constants) through combinational logic; no `ui_in` /
`uio_in` / `ena` / `rst_n` bit reaches one; `clk` only directly onto the clock.
MEASURED before the CDC bundle (73a387a logic): 75 of the 76 macro input bits
had a raw path -- `ui_in[4:1]` through `ub_in` into the write data, and through
the length check / refusal (`ub_len_ok`, `ub_refuse`) into the write strobe,
hence the address, byte mask and enables. The fix registered the strobe and
index and took the data from `tx_asm` (captured on nib_lo).

THE BUILD IS THE HARDENED ONE: info.yaml's source_files with src/config.json's
VERILOG_DEFINES (PE_SRAM_MACRO binds the IHP macro, a `(* blackbox *)` cell),
yosys `synth -flatten`, the pinned suite. Both lists are READ, never typed.
A STATE BOUNDARY is a primitive flop / latch, the macro itself, or a kept
submodule whose own module holds one (the keep-list twins) -- derived from the
netlist, so a new kept cell needs no edit here.

ARMS:  clean -> 0 raw paths, exactly one macro cell, >= 70 input bits checked;
       M_MACRO_RAW_BWD (`.bwd(ub_in)` restored) -> red on A_DIN.
Judge must-fires on planted netlists. A missing tool is COULD NOT RUN, red.
POSITIVE TOKEN: `GATE macro-inputs: PASSED`.
"""
from __future__ import annotations

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
sys.path.insert(0, HERE)
import gate_formal_miters as FM          # noqa: E402  (the suite resolver)

MACRO = "RM_IHPSG13_1P_256x32_c2_bm_bist"
MIN_BITS = 70
ARMS = (("clean", None, "PASS", None),
        ("raw_bwd", "M_MACRO_RAW_BWD", "FAIL", "A_DIN"))


def build_spec():
    """(top, [sources], [defines]) from info.yaml and src/config.json."""
    info = open(os.path.join(ROOT, "info.yaml"), encoding="utf-8").read()
    top = re.search(r'^\s*top_module:\s*"([^"]+)"', info, re.M)
    block = re.search(r"^\s*source_files:\s*\n((?:\s*-\s*\"[^\"]+\"\s*\n)+)", info, re.M)
    if not top or not block:
        raise ValueError("info.yaml: no top_module / source_files")
    cfg = open(os.path.join(ROOT, "src", "config.json"), encoding="utf-8").read()
    d = re.search(r'"VERILOG_DEFINES"\s*:\s*\[([^\]]*)\]', cfg)
    if not d:
        raise ValueError("src/config.json has no VERILOG_DEFINES")
    return (top.group(1), re.findall(r'"([^"]+)"', block.group(1)),
            re.findall(r'"([^"]+)"', d.group(1)))


def prim_seq(t):
    u = t.upper()
    return "DFF" in u or "DLATCH" in u or u.startswith("$_SR_") or u.startswith("$_ALDFF")


def judge(nl, top):
    """(problems, info) for one yosys JSON netlist."""
    mods = nl.get("modules", {})
    if top not in mods:
        return ["the netlist has no module %s" % top], {}
    m = mods[top]
    inbit = {}
    for pn, p in m.get("ports", {}).items():
        if p["direction"] == "input":
            for i, b in enumerate(p["bits"]):
                inbit[b] = "%s[%d]" % (pn, i)
    seq_mods = {mn for mn, mm in mods.items()
                if any(prim_seq(c["type"]) for c in mm.get("cells", {}).values())}
    driver, seq = {}, set()
    for cn, c in m.get("cells", {}).items():
        t = c["type"]
        if prim_seq(t) or t == MACRO or t in seq_mods:
            seq.add(cn)
        for pn, d in c.get("port_directions", {}).items():
            if d == "output":
                for b in c["connections"][pn]:
                    if isinstance(b, int):
                        driver[b] = cn
    macros = [cn for cn, c in m.get("cells", {}).items() if c["type"] == MACRO]
    if len(macros) != 1:
        return ["expected exactly one %s cell, found %d" % (MACRO, len(macros))], {}
    mc = m["cells"][macros[0]]
    bad, checked = defaultdict(set), 0
    for pn, d in mc["port_directions"].items():
        if d != "input":
            continue
        for i, b in enumerate(mc["connections"][pn]):
            if not isinstance(b, int):
                continue
            checked += 1
            if pn == "A_CLK" and inbit.get(b) == "clk[0]":
                continue
            stack, seen = [b], set()
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                if x in inbit:
                    bad["%s[%d]" % (pn, i)].add(inbit[x])
                    continue
                cn = driver.get(x)
                if cn is None or cn in seq:
                    continue
                c = m["cells"][cn]
                for qn, dd in c["port_directions"].items():
                    if dd == "input":
                        stack.extend(y for y in c["connections"][qn] if isinstance(y, int))
    info = {"macro": macros[0], "checked": checked, "bad": bad}
    if checked < MIN_BITS:
        return ["only %d macro input bits checked (want >= %d): the macro is "
                "mostly tied off -- nothing to check" % (checked, MIN_BITS)], info
    return ["%s <- %s" % (p, ", ".join(sorted(bad[p]))) for p in sorted(bad)], info


def run_arm(how, sby, define, top, files, defines):
    work = tempfile.mkdtemp(prefix="macroin_")
    try:
        path = (lambda p: FM.wslpath(p)) if how == "wsl" else (lambda p: p)
        ds = " ".join("-D%s" % d for d in defines + ([define] if define else []))
        srcs = " ".join(path(os.path.join(ROOT, "src", f)).replace("\\", "/") for f in files)
        with open(os.path.join(work, "nl.ys"), "w", newline="\n") as fh:
            fh.write("read_verilog -sv %s %s\nhierarchy -top %s\nsynth -top %s -flatten\n"
                     "write_json nl.json\n" % (ds, srcs, top, top))
        ydir = sby.rsplit("/", 1)[0] if how == "wsl" else os.path.dirname(sby)
        argv = (["wsl.exe", "--cd", FM.wslpath(work), "--", ydir + "/yosys", "-q",
                 "-l", "nl.log", "-s", "nl.ys"] if how == "wsl"
                else [os.path.join(ydir, "yosys"), "-q", "-l", "nl.log", "-s", "nl.ys"])
        r = subprocess.run(argv, cwd=work, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        p = os.path.join(work, "nl.json")
        if r.returncode or not os.path.isfile(p):
            tail = (r.stdout + r.stderr).strip().splitlines()[-2:]
            return None, "yosys failed (rc %d): %s" % (r.returncode, " | ".join(tail))
        return json.load(open(p, encoding="utf-8")), None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _planted(raw_on_din, macros=1, nbits=76):
    """a tiny netlist: input ui_in[0] (bit 2), a flop (bit 3 -> Q bit 4), and a
    macro whose A_DIN bits read either the flop Q or (planted) ui_in through an
    AND gate."""
    cells = {"ff": {"type": "$_DFF_P_", "port_directions": {"C": "input", "D": "input", "Q": "output"},
                    "connections": {"C": [5], "D": [3], "Q": [4]}},
             "g": {"type": "$_AND_", "port_directions": {"A": "input", "B": "input", "Y": "output"},
                   "connections": {"A": [2 if raw_on_din else 4], "B": [4], "Y": [6]}}}
    for k in range(macros):
        cells["mac%d" % k] = {"type": MACRO,
                              "port_directions": {"A_CLK": "input", "A_DIN": "input", "A_DOUT": "output"},
                              "connections": {"A_CLK": [5], "A_DIN": [6] * (nbits - 1), "A_DOUT": [7]}}
    return {"modules": {"top": {"ports": {"ui_in": {"direction": "input", "bits": [2]},
                                          "clk": {"direction": "input", "bits": [5]}},
                                "cells": cells}}}


def must_fires():
    return [("a raw pin through an AND onto A_DIN", bool(judge(_planted(True), "top")[0])),
            ("no macro cell", bool(judge(_planted(False, macros=0), "top")[0])),
            ("two macro cells", bool(judge(_planted(False, macros=2), "top")[0])),
            ("macro mostly tied off", bool(judge(_planted(False, nbits=10), "top")[0])),
            ("top module missing", bool(judge(_planted(False), "nope")[0]))], \
        not judge(_planted(False), "top")[0]


def main():
    print("GATE macro-inputs: no top-level input reaches the SRAM macro's inputs combinationally")
    rc = 0
    try:
        top, files, defines = build_spec()
    except (OSError, ValueError) as e:      # the spec could not be read: red
        print("  *** %r\n\n  GATE macro-inputs: FAILED" % e)
        return 1
    print("  build   : %s from %s, defines %s (info.yaml + src/config.json)"
          % (top, " ".join(files), " ".join(defines)))
    print("  --- judge must-fires ---")
    mf, control = must_fires()
    for label, red in mf:
        print("  must-fire: %-40s %s" % (label, "red  ok" if red else "*** STAYED GREEN"))
        rc |= 0 if red else 1
    print("  control:   %-40s %s" % ("flop-driven macro inputs", "green ok" if control else "*** RED"))
    rc |= 0 if control else 1
    try:
        how, sby = FM.resolve()
    except FM.CouldNotRun as e:
        print("  *** COULD NOT RUN: %s\n\n  GATE macro-inputs: FAILED" % e)
        return 1
    print("  --- arms ---")
    for arm, define, expect, must in ARMS:
        nl, err = run_arm(how, sby, define, top, files, defines)
        if err:
            print("  %-8s *** %s" % (arm, err))
            rc = 1
            continue
        probs, info = judge(nl, top)
        n = len(info.get("bad", {}))
        if expect == "PASS":
            ok = not probs
        else:
            ok = n > 0 and any(p.startswith(must) for p in probs)
        print("  %-8s %-16s %-4s %d input bits, %d with a raw path  %s"
              % (arm, define or "-", expect, info.get("checked", 0), n, "ok" if ok else "***"))
        for p in (probs if expect == "PASS" else probs[:3]):
            print("      %s %s" % ("***" if expect == "PASS" else "|", p))
        rc |= 0 if ok else 1
    print("\n  GATE macro-inputs: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
