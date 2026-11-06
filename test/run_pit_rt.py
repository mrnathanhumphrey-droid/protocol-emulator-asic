#!/usr/bin/env python3
"""v2 PIT item 2 (Wilson 11-06): THE ROUND TRIP -- sniff -> spec -> assemble ->
emulate -> sniff the emulation -> compare the records.

Per case:
  1. ORIGINAL: the case's bus sniffed on tb_pit (the pit gates' own run); its
     results bytes 0..135 (bit-exact with the frozen golden, gated elsewhere).
  2. SPEC: pit_emit.emit(results), then pit_emit.parse(spec) -- the round trip
     works from the PARSED SPEC only, never from the original bytes.
  3. EMULATE: a program pe_asm assembles from the spec's claims AT THE TARGET
     CLOCK (real-time rates converted by clock.hz()), with seeded random
     payloads at the claimed frame length and the CRC computed from the spec's
     parameters (D3). No CRC claimed -> payloads with no CRC.
  4. SNIFF IT: test/tb_rt.v, the emulator chip's pins wired to a second chip
     in SNIFF mode with the original case's sniff image (mask, budget).
  5. COMPARE (D2, one-sided): every field the spec CLAIMED must come back --
     roles, change level, class, idle, frame bits, CRC width / poly / refin /
     refout / frame exact; init / xorout as the same class (the record holds
     the class's canonical member, so equal); the bit period within
     max(1/16 cycle, the scheduler-jitter bound) in real time. Every field
     the spec left UNKNOWN must not come back confident. Phase and the
     evidence counts are not claimed and not compared.
A claim the emulator cannot drive is NOT EMULABLE (D4): counted apart, never
a pass, and red only for a ruled case.
                                                    token: GATE pit-rt: PASSED
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner, tool          # noqa: E402
import pe_isa as I                          # noqa: E402
import pe_asm                               # noqa: E402
import clock                                # noqa: E402
import sim_run                              # noqa: E402
import run_pit_capture as RP                # noqa: E402
import run_pit_s0 as R0                     # noqa: E402
import run_pit_s12 as R12                   # noqa: E402
import run_pit_s3 as R3                     # noqa: E402  (patches R12.sim to keep the whole dump)
import pit_s0_golden as S0                  # noqa: E402
import pit_emit as E                        # noqa: E402
from gate_j_program import D_STAR           # noqa: E402
from make_smoke_image import OP_LEVEL, OP_REARM, OP_SHIFT, PIN_NONE   # noqa: E402

BENCH, TOP = "test/tb_rt.v", "tb_rt"
P_TX_UO = 0                 # the UART-tx lane's pin: uo_out[0] (pinmap P_TX_UO, pe pin 8)
P_TX = 8
GAP_BITS = 40               # idle between messages: > async_bytes' 20-bit message gap
SEED = 20261106
MSG_GAP_BITS = 20          # pit_golden.async_bytes' message gap
STOP_MIN = 13              # the lane's tightest admissible delay here (pe_asm's 1.6a verdict)
LOOP_W = I.BR_W_MIN        # LOOP's wait: the shortest the ISA allows (33)

#: the ruled cases (Wilson 11-06, D4): these must PASS -- NOT EMULABLE is red here
RULED = {"s3_uart", "s3_modbus", "s3_crc32_full"}


# ---------------------------------------------------------------------------
# the emulation, from the PARSED spec
# ---------------------------------------------------------------------------
class NotEmulable(Exception):
    pass


def uart_program(T, lens):
    """the UART-tx 8N1 lane (test/uart_tx.py's frame): one message per entry of
    `lens` -- GAP_BITS of idle, then that many byte frames written ONCE and run
    by the chip's own LOOP (primitive 2; Wilson 11-06: the store holds any L).
    Between two bytes of a message the line idles the stop bit plus LOOP's
    wait W (LOOP_W cycles), far under async_bytes' 20-bit message gap -- the
    run measures it. Too big for the store -> NOT EMULABLE (program size)."""
    seq = []
    for L in lens:
        # the idle FIRST: uo_out[0] leaves reset low, so the line must go high
        # before the first start bit, and the sniffer opens inside this gap
        g = GAP_BITS * T
        while g > I.D_MAX:
            seq.append((OP_LEVEL, P_TX, 1, I.D_MAX, 0))
            g -= I.D_MAX
        seq.append((OP_LEVEL, P_TX, 1, g, 0))
        head = len(seq)
        seq += [(OP_LEVEL, P_TX, 0, T, 0)] + [(OP_SHIFT, P_TX, 0, T, 0, 7)] * 8
        # the stop bit + LOOP's wait idle a WHOLE number of bit times (k T):
        # a 1.4-bit run between bytes is not a multiple of the bit and pulled
        # stage 1's period off by 2/16 cycle (measured, s3_crc32_full)
        k = max(2, -(-(LOOP_W + STOP_MIN) // T))
        seq += [(OP_LEVEL, P_TX, 1, k * T - LOOP_W, 0), (I.OP_LOOP, L, head, LOOP_W, 0)]
    # the REARM's D* is idle time too: taken from the loop's first gap
    seq[0] = seq[0][:3] + (seq[0][3] - D_STAR,) + seq[0][4:]
    seq.append((OP_REARM, 0, 1, D_STAR, 0))
    try:
        return pe_asm.assemble({0: seq}, {0: (P_TX, PIN_NONE, 1, T, min(T, 255), min(2 * T, 255))})
    except pe_asm.Reject as e:
        raise NotEmulable("program size / timing: %d-message loop %s at T=%d -- %s" % (len(lens), list(lens), T, e))


def target_cycles(p16, cap_hz):
    """the claimed bit period (real time) in whole cycles of the target clock"""
    return round(p16 / 16.0 / cap_hz * clock.hz())


def emulation(cl, rng, nbytes=4000):
    """-> (emulator image, feed bytes, ROUTE, what, warm cycles) from the parsed claims."""
    ua = [w for w, v in cl["wires"].items() if v["cls"] == "NRZ_ASYNC"]
    if not ua:
        raise NotEmulable("no NRZ_ASYNC wire claimed (clocked buses: the next step)")
    if len(ua) > 1:
        raise NotEmulable("%d UART wires: the round trip drives one" % len(ua))
    w = ua[0]
    v = cl["wires"][w]
    if v["fb"] != 10 or v["idle"] != 1:
        raise NotEmulable("frame %s bits idle %s: the UART-tx lane is 8N1, idle high" % (v["fb"], v["idle"]))
    T = target_cycles(v["p16"], cl["clock_hz"])
    c = cl["crc"]
    msgs = []
    if c is not None and c["wire"] == w and c["init"] is not None:
        nb = c["width"] // 8
        L = c["frame"]
        if L <= nb:
            raise NotEmulable("CRC frame %d bytes leaves no payload" % L)
        p = (c["width"], c["poly"] | 0, c["init"], c["xorout"], c["reflected"])
        # D3 as amended twice (Wilson 11-06): L, L+1, L repeating -- >= 4 frames
        # of L for the polynomial and >= 2 of L+1 for init / xorout (the
        # solver's two lengths) inside the ~6 frames the edge capture holds
        lens = (L, L + 1, L)
        while sum(map(len, msgs)) < nbytes:
            msgs.append(R3.frame([rng.getrandbits(8) for _ in range(lens[len(msgs) % 3] - nb)], *p))
        what = "8N1 T=%d, %d/%d-byte frames, CRC-%d poly %#x init %#x xorout %#x%s" % (
            T, L, L + 1, c["width"], c["poly"], c["init"], c["xorout"], " refl" if c["reflected"] else "")
    elif c is not None and c["wire"] == w:
        raise NotEmulable("CRC poly claimed with init / xorout UNKNOWN: no payload rule ruled yet")
    else:
        L = 6
        lens = (L,)
        while sum(map(len, msgs)) < nbytes:
            msgs.append([rng.getrandbits(8) for _ in range(L)])
        what = "8N1 T=%d, %d-byte frames, NO CRC (the spec claims none)" % (T, L)
    img = uart_program(T, lens)
    feed = [b for m in msgs for b in m]
    route = 0x10 | P_TX_UO
    # the sniffer opens half-way into the first message's leading idle
    return img, feed, route << (8 * w), what, GAP_BITS * T // 2


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
def build(out):
    if RP.SIM == "verilator":
        return RP.vl_build(out, bench=BENCH, top=TOP)
    r = RP.run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", TOP, BENCH] + RP.RTL)
    if r.returncode != 0:
        raise RuntimeError("build failed: %s" % (r.stdout + r.stderr)[-400:])


def sim(vvp, tmp, tag, simg, eimg, feed, route, ncyc, warm):
    ip = os.path.join(tmp, "pitcap_rt_%s.hex" % tag)
    I.write_image(ip, simg)
    sim_run.scratch_image(RP.GEN, ip)
    ep = os.path.join(tmp, "rt_%s_emu.hex" % tag)
    I.write_image(ep, eimg)
    fp = os.path.join(tmp, "rt_%s.feed" % tag)
    with open(fp, "w", encoding="ascii", newline="\n") as fh:
        fh.write("".join("%02x\n" % b for b in feed))
    op = os.path.join(tmp, "rt_%s.out" % tag)
    args = [vvp, "+IMG=%s" % ip, "+EIMG=%s" % ep, "+NBYTES=%d" % I.STORE_BYTES, "+OUT=%s" % op,
            "+FEED=%s" % fp, "+ROUTE=%016x" % route, "+NCYC=%d" % ncyc, "+WARM=%d" % warm]
    cmd = RP.simcmd(args, images=[ip, ep])
    if RP.SIM == "verilator":               # simcmd translates only its own path plusargs
        cmd = [a.split("=", 1)[0] + "=" + RP.wsl_path(a.split("=", 1)[1])
               if isinstance(a, str) and a.startswith(("+EIMG=", "+FEED=")) else a for a in cmd]
    r = RP.run(cmd)
    mem, st, h, lv0, log = {}, None, None, None, []
    if not os.path.isfile(op):
        raise RuntimeError("tb_rt wrote no dump: %s" % (r.stdout + r.stderr)[-600:])
    with open(op, encoding="ascii") as fh:
        for ln in fh:
            t = ln.split()
            if t and t[0] == "M":
                mem[int(t[1])] = int(t[2], 16) if all(ch in "0123456789abcdefABCDEF" for ch in t[2]) else -1
            elif t and t[0] == "S":
                st = dict(kv.split("=") for kv in t[1:])
            elif t and t[0] == "L":
                lv0 = int(t[1], 16)
            elif t and t[0] == "E":
                log.append((int(t[1]), int(t[2], 16)))
            elif t and t[0] == "H":
                h = dict(kv.split("=") for kv in t[1:])
    if h is not None:
        h["lv0"], h["log"] = lv0, log
    return mem, st, h


def idle_runs(log, lv0, w, bit):
    """the measured idle (high) runs on wire w, in bit times, split at the
    decoder's message gap (pit_golden.async_bytes: msg_gap_bits = 20)
    -> (longest run INSIDE a message, shortest run BETWEEN messages)"""
    lv, t0, runs = (lv0 >> w) & 1, None, []
    for t, m in log:
        if not m >> w & 1:
            continue
        if lv == 1 and t0 is not None:
            runs.append((t - t0) / bit)
        lv ^= 1
        t0 = t
    inside = [r for r in runs if r < MSG_GAP_BITS]
    between = [r for r in runs if r >= MSG_GAP_BITS]
    return max(inside, default=None), min(between, default=None)


def lens_of(what):
    import re
    m = re.search(r"([\d/]+)-byte frames", what)
    return [int(x) for x in m.group(1).split("/")] if m else []


def results_of(mem):
    if any(mem.get(i, -1) < 0 for i in range(E.RESULTS_BYTES)):
        return None
    return bytes(mem[i] for i in range(E.RESULTS_BYTES))


def compare(a, b, tol16):
    """one-sided: every claim of `a` (the original spec) must come back in `b`
    (the regenerated record); every UNKNOWN of `a` must not come back confident.
    -> [problems], [notes]"""
    bad, notes = [], []
    for w, v in a["roles"].items():
        if b["roles"].get(w) != v:
            bad.append("uio%d role %s -> %s" % (w, v, b["roles"].get(w)))
    for w, v in a["wires"].items():
        u = b["wires"].get(w)
        if u is None:
            bad.append("uio%d: claimed %s, came back with no claim" % (w, v["cls"]))
            continue
        for k in ("cls", "idle", "fb", "given"):
            if u[k] != v[k]:
                bad.append("uio%d %s %s -> %s" % (w, k, v[k], u[k]))
        # in real time, as 16ths of the ORIGINAL capture's cycle
        d = abs(u["p16"] * a["clock_hz"] / b["clock_hz"] - v["p16"])
        notes.append("uio%d period %s -> %s (16ths of a cycle; tolerance %d)" % (w, v["p16"], u["p16"], tol16))
        if d > tol16:
            bad.append("uio%d bit period %d/16 -> %d/16 cycles, off by %.1f/16 > %d/16"
                       % (w, v["p16"], u["p16"], d, tol16))
    c, d = a["crc"], b["crc"]
    if c:
        if not d:
            bad.append("crc on uio%d claimed, came back with none" % c["wire"])
        else:
            for k in ("wire", "width", "reflected", "poly", "frame"):
                if d[k] != c[k]:
                    bad.append("crc %s %s -> %s" % (k, c[k], d[k]))
            if c["init"] is not None and (d["init"], d["xorout"]) != (c["init"], c["xorout"]):
                bad.append("crc init/xorout %#x/%#x -> %s/%s (not the same class)" % (
                    c["init"], c["xorout"], d["init"], d["xorout"]))
    # one-sided: an UNKNOWN must not come back as a confident value
    bk = {f for f, _ in b["unknown"]}
    for f, why in a["unknown"]:
        if f in bk:
            continue
        w = f.split(".")[0]
        conf = None
        if f == "crc" and d:
            conf = "crc on uio%d poly %#x" % (d["wire"], d["poly"])
        elif f.endswith(".crc") and d:
            conf = "poly %#x" % d["poly"]
        elif f.endswith((".crc.init", ".crc.xorout")) and d and d["init"] is not None:
            conf = "init %#x" % d["init"]
        elif f.endswith(".encoding") and w[3:].isdigit() and (b["wires"].get(int(w[3:])) or {}).get("cls"):
            conf = b["wires"][int(w[3:])]["cls"]
        elif f.endswith(".rate") and w[3:].isdigit() and int(w[3:]) in b["wires"]:
            conf = "a rate"
        if conf:
            bad.append("UNKNOWN %s came back confident: %s" % (f, conf))
        else:
            notes.append("UNKNOWN %s stays undetermined (reason now differs)" % f)
    return bad, notes


def originals():
    """[(name, case)] -- the UART cases (gate pit-s3)."""
    return [(c[0], c) for c in R3.cases()]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("PIT ROUND TRIP -- sniff -> spec -> pe_asm -> emulate -> sniff -> compare (Wilson 11-06)")
    print("=" * 78)
    only = set(filter(None, os.environ.get("PE_RT_CASES", "").split(",")))
    tmp = tempfile.mkdtemp(prefix="pe_pitrt_")
    vo = os.path.join(tmp, "orig.vvp")
    RP.build(vo)
    vr = os.path.join(tmp, "rt.vvp")
    build(vr)
    tol16 = 1                    # 1/16 cycle; the scheduler-jitter bound if larger (measured below)
    probs, counts = [], {"PASS": 0, "FAIL": 0, "NOT EMULABLE": 0}
    for name, case in originals():
        if only and name not in only:
            continue
        t0 = time.time()
        R12.run_case(vo, tmp, case, name)
        orig = results_of(R3.R12_MEM.get(name, {}))
        if orig is None:
            probs.append("%s: the original run left results bytes unwritten" % name)
            continue
        spec = E.emit(orig)
        cl = E.parse(spec)
        print("  --- %s: the spec" % name)
        for ln in spec.splitlines()[1:]:
            print("      " + ln)
        try:
            eimg, feed, route, what, warm = emulation(cl, random.Random("%d|%s" % (SEED, name)))
        except NotEmulable as e:
            counts["NOT EMULABLE"] += 1
            print("  %-16s NOT EMULABLE: %s" % (name, e))
            if name in RULED:
                probs.append("%s: NOT EMULABLE, but a ruled case: %s" % (name, e))
            continue
        mem, st, h = sim(vr, tmp, name, RP.sniff_image(case[2], case[3]), eimg, feed, route,
                         R0.NCYC_MAX * 40, warm)
        regen = results_of(mem)
        bad, notes = [], []
        if regen is None:
            bad.append("the emulation's sniff left results bytes unwritten (pc %s)" % (st or {}).get("pc"))
        else:
            cl2 = E.parse(E.emit(regen))
            bad, notes = compare(cl, cl2, tol16)
            notes.append("stop: original %s, regenerated %s (partial is not compared)" % tuple(
                "partial %s after %d records" % x["partial"] if x["partial"] else "budget / complete"
                for x in (cl, cl2)))
        for w, v in cl["wires"].items():
            if h and v["cls"] == "NRZ_ASYNC" and regen is not None:
                # what the frozen decoder made of the emulation's capture: a
                # message split by a gap inside it shows as a length outside
                # the emulated set
                G = S0.frozen_model()
                cap = S0.stored_capture(h["log"], h["lv0"] or 0, RP.PG.budget_cycles(case[3]), R0.NCYC_MAX)
                c2 = cl2["wires"].get(w)
                if cap and c2 and c2["fb"]:
                    dm = G.async_bytes(G.wire_ivs(cap, w, h["lv0"] or 0), c2["p16"], c2["fb"])
                    notes.append("uio%d decoded message lengths %s (emulated %s)" % (
                        w, [len(m) for m in dm], "/".join(map(str, sorted(set(lens_of(what)))))))
            if h and v["cls"] == "NRZ_ASYNC":
                mi, mb = idle_runs(h["log"], h["lv0"] or 0, w, v["p16"] / 16.0)
                notes.append("uio%d high runs: longest %s bit times inside a message (data 1s included), "
                             "shortest %s between messages (the decoder splits at %d)" % (
                                 w, "%.2f" % mi if mi is not None else "-",
                                 "%.2f" % mb if mb is not None else "-", MSG_GAP_BITS))
                if mi is not None and mi >= MSG_GAP_BITS:
                    bad.append("uio%d: a gap inside a message reaches the message gap" % w)
        idle = sum(1 << w for w, v in cl["wires"].items() if v.get("idle") == 1)
        if h and h.get("lv0") is not None and (h["lv0"] & idle) != idle:
            bad.append("the sniffer opened on a non-idle line (start levels %02x)" % h["lv0"])
        if h and (h.get("underrun") != "00000" or h.get("full") != "0"):
            bad.append("host feed: underrun %s, overrun %s -- the emulation was starved" % (h["underrun"], h["full"]))
        verdict = "FAIL" if bad else "PASS"
        counts[verdict] += 1
        print("  %-16s %-6s %6.1fs  emulated: %s" % (name, verdict, time.time() - t0, what))
        for n in notes:
            print("      . " + n)
        if regen is not None and bad:
            print("      regenerated spec:")
            for ln in E.emit(regen).splitlines()[2:-1]:
                print("        " + ln)
        probs += ["%s: %s" % (name, b) for b in bad]
    print("  round trips: %d PASS, %d FAIL, %d NOT EMULABLE" % (counts["PASS"], counts["FAIL"], counts["NOT EMULABLE"]))
    for p in probs:
        print("  *** " + p)
    print("  GATE pit-rt: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
