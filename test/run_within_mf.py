#!/usr/bin/env python3
"""run_within_mf -- the `within` / `else` SIMULATION must-fires (Wilson 11-15, agent 2).

The poset compiler lowers `pattern Fall(uio3) -> Fall(uio5) within (2000 ns, 10000 ns) else X
source datasheet "X"` onto the SPI slice (host/poset/run_poset_compile.WIN); test/tb_within.v
runs it on one chip with a PEER that pulls B low DLY cycles after each CS fall it sees.

  W1 abort,    B inside the window: no timeout, the lane live, every frame's first SCK edge
               after its CS fall comes AFTER B (the program waited for B)
  W2 abort,    B late (past hi): lane 0's timeout sticky rises, the lane halts (live = 0,
               no SCK edge after the timeout), the host's ovr is set
  W3 continue, B inside the window: as W1 (the edge path, PC+2)
  W4 continue, B late: the lane stays live; every frame's first SCK edge comes after the
               deadline and BEFORE B (the timeout path, PC+1 -> PC+2)
Each case also reports the measured gaps against the lowering's own numbers (pre, T).

iverilog on Windows (never WSL). Every run under a psutil watchdog: killed above CAP_MB or
CAP_S. POSITIVE TOKEN: `GATE within_mf: PASSED`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model"), os.path.join(ROOT, "host", "poset")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import psutil  # noqa: E402

CAP_MB, CAP_S = 4096, 900
BENCH, TOP = "test/tb_within.v", "tb_within"
NCYC = 20000
PEAK = []


def run(cmd):
    t0 = time.time()
    p = psutil.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                     encoding="utf-8", errors="replace")
    peak, why = 0, None
    while p.poll() is None:
        try:
            peak = max(peak, sum(q.memory_info().rss for q in [p] + p.children(recursive=True)))
        except psutil.Error:
            pass
        why = ("RAM cap %d MB" % CAP_MB if peak > CAP_MB * 2 ** 20 else
               "time cap %d s" % CAP_S if time.time() - t0 > CAP_S else None)
        if why:
            for q in [p] + p.children(recursive=True):
                try:
                    q.kill()
                except psutil.Error:
                    pass
            break
        time.sleep(0.05)
    out, err = p.communicate()
    PEAK.append((os.path.basename(str(cmd[0])), peak / 2 ** 20, time.time() - t0, why))
    if why:
        raise RuntimeError("killed: %s" % why)
    return p.returncode, out + err


def build(tmp):
    import run_pit_capture as RP
    from toolchain import tool
    vvp = os.path.join(tmp, "tb_within.vvp")
    rc, out = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", vvp, "-s", TOP, BENCH] + RP.RTL)
    if rc != 0:
        raise RuntimeError("iverilog: %s" % out[-600:])
    return vvp


def sim(vvp, tmp, tag, img, cs, sck, b, dly):
    import pe_isa as I
    from toolchain import tool
    ip = os.path.join(tmp, "%s.hex" % tag)
    I.write_image(ip, img)
    fp = os.path.join(tmp, "%s.feed" % tag)
    with open(fp, "w", encoding="ascii", newline="\n") as fh:
        fh.write("5a\n" * 256)
    op = os.path.join(tmp, "%s.log" % tag)
    import sim_run      # gate_sim_runs: no raw vvp outside the helper (agent 1, 11-15)
    rc, out = run(sim_run.vvp(["-n", vvp, "+IMG=%s" % ip, "+NBYTES=%d" % I.STORE_BYTES,
                               "+OUT=%s" % op, "+FEED=%s" % fp, "+CS=%d" % cs, "+SCK=%d" % sck,
                               "+B=%d" % b, "+DLY=%d" % dly, "+NCYC=%d" % NCYC], images=[ip]))
    if not os.path.isfile(op):
        raise RuntimeError("tb_within wrote no log: %s" % out[-600:])
    ev = {"A": [], "B": [], "K": [], "T": []}
    st = {}
    with open(op, encoding="ascii") as fh:
        for ln in fh:
            t = ln.split()
            if t and t[0] in ev:
                ev[t[0]].append(int(t[1]))
            elif t and t[0] == "S":
                st = {k: int(v) for k, v in (kv.split("=") for kv in t[1:])}
    return ev, st


def frames(ev):
    """[(A, B or None, first SCK edge after A or None)] for each CS fall"""
    out = []
    for n, a in enumerate(ev["A"]):
        nxt = ev["A"][n + 1] if n + 1 < len(ev["A"]) else 10 ** 12
        b = next((x for x in ev["B"] if a <= x < nxt), None)
        k = next((x for x in ev["K"] if a < x < nxt), None)
        out.append((a, b, k))
    return out


def main() -> int:
    import compile as C
    import run_poset_compile as RPC
    hz = C.clock.hz()
    lo, hi = 2000 * hz // 10 ** 9, -(-10000 * hz // 10 ** 9)
    probs, rows = [], []
    with tempfile.TemporaryDirectory(prefix="pe_within_mf_") as tmp:
        vvp = build(tmp)
        for kind in ("abort", "continue"):
            r = C.compile_spec(RPC.body(RPC.WIN % kind), seed=7)
            cs = C._route_pin(r["route"], 3) - C.I.UO0
            sck = C._route_pin(r["route"], 1) - C.I.UO0
            b = C._route_pin(r["route"], 5)
            w = r["windows"][0]
            deadline = w["pre"] + w["T"]                 # cycles after A's release
            for when, dly in (("inside", (lo + hi) // 2), ("late", hi + 150)):
                tag = "%s_%s" % (kind, when)
                ev, st = sim(vvp, tmp, tag, r["image"], cs, sck, b, dly)
                fr = frames(ev)
                done = [f for f in fr if f[2] is not None]
                gaps = [(f[2] - f[0], (f[2] - f[1]) if f[1] is not None else None) for f in done]
                rows.append("  %-9s B %-6s DLY %4d: %d CS falls, %d with SCK, timeout %s, live %s, "
                            "ovr %s; first SCK after A (after B): %s"
                            % (kind, when, dly, len(fr), len(done), ev["T"][:1] or "-",
                               st.get("live0"), st.get("ovr"), gaps[:4]))
                name = {("abort", "inside"): "W1", ("abort", "late"): "W2",
                        ("continue", "inside"): "W3", ("continue", "late"): "W4"}[(kind, when)]
                if not st:
                    probs.append("%s: no final status line" % name)
                    continue
                if when == "inside" or kind == "continue":
                    if ev["T"] and kind == "abort":
                        probs.append("%s: lane 0 timed out at %s" % (name, ev["T"]))
                    if st["live0"] != 1:
                        probs.append("%s: lane 0 not live at the end" % name)
                    if len(done) < 3:
                        probs.append("%s: only %d frames ran" % (name, len(done)))
                if when == "inside":
                    bad = [f for f in done if f[1] is None or f[2] <= f[1]]
                    if bad:
                        probs.append("%s: SCK before B in %d frame(s): %s" % (name, len(bad), bad[:3]))
                if kind == "abort" and when == "late":
                    if not ev["T"]:
                        probs.append("W2: no timeout")
                    else:
                        after = [k for k in ev["K"] if k > ev["T"][0]]
                        if after or st["live0"] != 0 or st["ovr"] != 1:
                            probs.append("W2: after the timeout: %d SCK edges, live %s, ovr %s"
                                         % (len(after), st["live0"], st["ovr"]))
                        if fr and not fr[0][0] + deadline - 40 <= ev["T"][0] <= fr[0][0] + deadline + 40:
                            probs.append("W2: timeout at %d, A at %d + deadline %d"
                                         % (ev["T"][0], fr[0][0], deadline))
                if kind == "continue" and when == "late":
                    bad = [f for f in done if not (f[0] + deadline - 40 <= f[2]
                                                   and (f[1] is None or f[2] < f[1]))]
                    if bad:
                        probs.append("W4: frames not on the timeout path: %s" % bad[:3])
    print("within must-fires (tb_within, iverilog; lo %d, hi %d cycles)" % (lo, hi))
    for ln in rows:
        print(ln)
    for name, mb, s, why in PEAK:
        print("  run %-14s peak RSS %6.0f MB  wall %6.1f s %s" % (name, mb, s, why or ""))
    for p in probs:
        print("  ***", p)
    print("GATE within_mf: %s" % ("PASSED" if not probs else "FAILED (%d)" % len(probs)))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
