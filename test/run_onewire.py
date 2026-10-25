"""CE5 gate -- 1-Wire (DS18B20) on the FROZEN RTL, a pe_asm program only.

THE CLAIM: with `src/` frozen (`model/gate_ce5_freeze.py`), a pe_asm program
(`model/pe_proto.OneWire`, built by `test/onewire.py`) runs the DS18B20
transaction -- reset + presence, READ ROM (33h, 64 bits), SKIP ROM + CONVERT T
(CCh 44h) polled to completion (VDD mode), SKIP ROM + READ SCRATCHPAD (CCh
BEh, 9 bytes) -- with every slot inside the datasheet's windows.

TIMING SOURCE: Analog Devices (Maxim) DS18B20 datasheet 19-7487; Rev 6; 7/19,
"AC Electrical Characteristics" (p. 3) and "1-Wire Signaling" (pp. 15-16),
quoted in `test/ds18b20_model.v` and docs/CE5_LOG.md. Not vendored.

THE PEER is `test/ds18b20_model.v`: SAME-HAND, labelled so. The real DS18B20
(on order) is the foreign witness at FPGA bring-up.

RECEIVED BYTES ARE WHAT THE CHIP PUSHED, decoded from the 3-pin serial host
stream (`OW-RX`). Dallas CRC-8 is checked HERE, host-side (sub-v1: on-chip CRC
belongs to the reach branch), by an implementation separate from the model's,
itself checked against Maxim AN27's worked ROM example (02 1C B8 01 00 00 00
-> A2).

ARMS
  ok          the TT image, the whole transaction, RISE 0.5 us
  fpga        the PA100T image (2 us init, 13 us sample), RISE 2 us, READ ROM
MUST-FIRES (each needs POSITIVE evidence of red, and the run must reach its
END token, so a crash is not mistaken for a kill)
  w0short     write-0 low 50 us: the model's tLOW0 window check fires
  latesample  the read sample at 20 us: the master-sample check fires AND the
              ROM fails its CRC (the part released its 0 at tRDV = 15 us)
  romflip     one ROM bit flipped in the peer after its CRC: CRC red and the
              ROM differs from the intended one
  underrun_reset / underrun_slot   OW6, STANDING: the host stalls mid-READ
              ROM (100k / 45k cycles), the lane underruns and holds DQ low;
              the chip's underrun sticky must be set AND the host's CRC-8 on
              the pushed bytes must go red (the short one leaves the peer
              model with zero violations -- only the host sees it)

POSITIVE TOKEN: `CE5-ONEWIRE: PASSED` only on the success path.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
from pe_isa import STORE_BYTES as _STORE_BYTES  # noqa: E402  v2: never a typed 256
from toolchain import banner, tool          # noqa: E402
import sim_run                              # noqa: E402
import onewire                               # noqa: E402
import pe_proto as P                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# scratch under a `probe_*` name, which .gitignore covers
TMP = os.environ.get("PE_OW_TMP") or os.path.join(ROOT, "test", "probe_onewire")

#: the ROM the model is BUILT with (family 28h + serial), before any flip --
#: what a correct transfer must deliver. Its CRC byte is computed, not typed.
INTENDED_ROM56 = [0x28, 0xA2, 0xC3, 0x4D, 0x05, 0x00, 0x00]
#: Maxim AN27's worked example (family 02h, serial 0000 0001 B81C, CRC A2h),
#: the self-test of `crc8` below
AN27_ROM56, AN27_CRC = [0x02, 0x1C, 0xB8, 0x01, 0x00, 0x00, 0x00], 0xA2
TEMP_RAW = 0x0191                       # the model's result: +25.0625 C
#: the timing classes test/ds18b20_model.v reports as `OW-T <name>` (R4 #18):
#: every one must appear, or the timing checks below ran on nothing
OW_T_NAMES = frozenset(("tLOW1", "tLOW0", "tRSTL", "tRSTH", "tREC",
                        "tSLOT+tREC"))
ROM_TXN = [("reset",), ("write", 0x33), ("read", 8, "rom")]


def crc8(data):
    """Dallas/Maxim CRC-8, X^8 + X^5 + X^4 + 1, LSB first, init 0."""
    c = 0
    for b in data:
        for i in range(8):
            fb = (c ^ (b >> i)) & 1
            c >>= 1
            if fb:
                c ^= 0x8C
    return c


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def vvp_path(rise_ns, ph=0):
    return os.path.join(TMP, "tb_onewire_r%d_p%d.vvp" % (rise_ns, ph))


#: ⭐ THE FILES CE5'S SIMULATION COMPILES -- ONE LIST, read by build_vvp below
#: AND by model/gate_ce5_freeze.py, whose freeze is exactly these plus their
#: `include closure and the tracked images (Wilson 10-18). Add a file here and
#: the freeze covers it; there is no second copy to forget.
CE5_SIM_SOURCES = ["test/tb_onewire.v", "test/ds18b20_model.v",
                   "src/pe_engine.v", "src/pe_store.v", "src/project.v"]


def build_vvp(rise_ns, ph=0):
    """`ph`: the part's phase offset (tb_onewire T_PH_NS, Wilson 10-21)."""
    out = vvp_path(rise_ns, ph)
    r = run([tool("iverilog"), "-g2012", "-o", out, "-s", "tb_onewire",
             "-Ptb_onewire.RISE_NS=%d" % rise_ns,
             "-Ptb_onewire.T_PH_NS=%d" % ph] + CE5_SIM_SOURCES)
    if r.returncode != 0:
        raise SystemExit("*** build failed\n" + r.stdout + r.stderr)
    return out


def sim(name, variant, txn, rise_ns, extra=(), ph=0):
    img = os.path.join(TMP, "ow_%s.hex" % name)
    onewire.write_hex(img, onewire.build(variant))
    lines, rxmap = onewire.engine(variant).feed_file(txn)
    pidx = next((i for i, r in enumerate(rxmap) if r[0] == "poll"), len(rxmap))
    fpath = os.path.join(TMP, "ow_%s_feed.hex" % name)
    with open(fpath, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    log = os.path.join(TMP, "ow_%s.log" % name)
    rel = lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")
    import time
    t0 = time.time() - 2.0
    r = run(sim_run.vvp(["-l", rel(log), rel(vvp_path(rise_ns, ph)),
                         "+IMG=" + rel(img), "+NBYTES=%d" % _STORE_BYTES, "+FEED=" + rel(fpath),
                         "+NFEED=%d" % len(lines), "+POLLIDX=%d" % pidx] + list(extra),
                        images=[rel(img)]))
    # ⛔ a log from an EARLIER run must not be judged as this one's
    if not os.path.exists(log) or os.path.getmtime(log) < t0:
        return "*** FAIL run_onewire: no fresh log for %s\n" % name, []
    with open(log, encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    return txt + (r.stderr or ""), rxmap


def parse(txt):
    d = {"rx": [int(v, 16) for _i, v in re.findall(r"^OW-RX (\d+) ([0-9a-fx]{2})",
                                                    txt, re.M)
                if "x" not in v],
         "rx_x": len(re.findall(r"^OW-RX \d+ \S*x", txt, re.M)),
         "end": "OW-BENCH: END" in txt,
         "fails": [l for l in txt.splitlines() if "*** FAIL" in l]}
    m = re.search(r"^OW-POLL groups=(\d+)", txt, re.M)
    d["poll"] = int(m.group(1)) if m else None
    m = re.search(r"^OW-MODEL ROM ((?:[0-9a-f]{2} ?){8})", txt, re.M)
    d["rom"] = [int(x, 16) for x in m.group(1).split()] if m else None
    m = re.search(r"^OW-MODEL SP ((?:[0-9a-f]{2} ?){9})", txt, re.M)
    d["sp"] = [int(x, 16) for x in m.group(1).split()] if m else None
    m = re.search(r"^OW-MODEL violations=(\d+)", txt, re.M)
    d["viol"] = int(m.group(1)) if m else None
    d["t"] = {}
    # (the six names ds18b20_model.v prints; R4 #18 requires every one)
    for nm, n, mn, mx, lo, hi in re.findall(
            r"^OW-T (\S+) n=(\d+) min_ns=([\d.]+) max_ns=([\d.]+) "
            r"lo_ns=([\d.]+) hi_ns=(\S+)", txt, re.M):
        d["t"][nm] = (int(n), float(mn), float(mx), float(lo),
                      None if hi == "inf" else float(hi))
    for key, pat in (("read", r"^OW-SAMPLE read n=(\d+) min_ns=([\d.]+) max_ns=([\d.]+)"),
                     ("pres", r"^OW-SAMPLE presence n=(\d+) min_ns=([\d.]+) max_ns=([\d.]+)"),
                     ("init", r"^OW-INIT n=(\d+) min_ns=([\d.]+) max_ns=([\d.]+)")):
        m = re.search(pat, txt, re.M)
        d[key] = (int(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None
    m = re.search(r"^OW-STICKY underrun=(\d) rx_drop=(\d) config_err=(\d) tx_full=(\d)",
                  txt, re.M)
    d["sticky"] = tuple(int(x) for x in m.groups()) if m else None
    d["stalled"] = bool(re.search(r"^OW-STALL ", txt, re.M))
    return d


def judge(d, rxmap):
    """-> [(check, ok, detail)]. Every check is positive: a missing reading
    is a failed check, never a skipped one."""
    out = []

    def chk(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    chk("bench END token", d["end"], "")
    chk("no X in received bytes", d["rx_x"] == 0, "%d" % d["rx_x"])
    # expand the receive map: the poll entry is `groups` bytes
    seq = []
    for r in rxmap:
        if r[0] == "poll":
            seq += [r] * (d["poll"] or 0)
        else:
            seq.append(r)
    chk("received byte count", len(d["rx"]) >= len(seq) > 0,
        "%d received, %d expected" % (len(d["rx"]), len(seq)))
    rx = d["rx"] + [None] * max(0, len(seq) - len(d["rx"]))
    resets = [k for k, r in enumerate(seq) if r == ("reset", 0)]
    pres = [rx[k] for k in resets]
    chk("presence detected after every reset (bit %d == 0)" % P.OneWire.PRESENCE_BIT,
        resets and all(b is not None and not (b >> P.OneWire.PRESENCE_BIT) & 1
                       and (b & 0x1F) == 0 for b in pres),
        " ".join("%02X" % b if b is not None else "--" for b in pres))
    chk("bus idle after presence (2nd reset byte == FF)",
        all(rx[k + 1] == 0xFF for k in resets), "")
    ech = [(r[1], rx[k]) for k, r in enumerate(seq) if r[0] == "echo"]
    chk("command echoes == the commands written",
        ech and all(a == b for a, b in ech),
        " ".join("%02X" % b if b is not None else "--" for _a, b in ech))
    rom = [rx[k] for k, r in enumerate(seq) if r[0] == "read" and r[1] == "rom"]
    want_rom = INTENDED_ROM56 + [crc8(INTENDED_ROM56)]
    if rom:
        ok_crc = None not in rom and crc8(rom[:7]) == rom[7]
        chk("ROM CRC-8 valid (host-side)", ok_crc,
            "rx %s, crc8 %s" % (" ".join("%02X" % b if b is not None else "--"
                                         for b in rom),
                                "%02X" % crc8(rom[:7]) if None not in rom else "-"))
        # ⛔ OW6: CRC-8 ALONE PASSES A BUS HELD LOW. Eight 00 bytes have a
        # valid Dallas CRC (crc8 of zeros is 0), and 00s are exactly what a
        # host reads while an underrunning lane holds DQ low. The host knows
        # it is talking to a DS18B20, so it checks the family code (28h) --
        # host knowledge, not the peer's memory.
        chk("ROM family code 28h (DS18B20), not an all-zero frame (host-side)",
            None not in rom and rom[0] == 0x28 and any(rom),
            "family %s" % ("%02X" % rom[0] if rom[0] is not None else "--"))
        chk("ROM == the model's ROM (pushed bytes vs peer)", rom == d["rom"], "")
        chk("ROM == the intended ROM (family 28h)", rom == want_rom,
            " ".join("%02X" % b for b in want_rom))
    sp = [rx[k] for k, r in enumerate(seq) if r[0] == "read" and r[1] == "sp"]
    if sp:
        chk("scratchpad CRC-8 valid (host-side)",
            None not in sp and crc8(sp[:8]) == sp[8],
            " ".join("%02X" % b if b is not None else "--" for b in sp))
        chk("scratchpad == the model's scratchpad", sp == d["sp"], "")
        chk("temperature read == +25.0625 C (0191h)",
            None not in sp and (sp[0] | sp[1] << 8) == TEMP_RAW,
            "%.4f C" % ((sp[0] | sp[1] << 8) / 16.0) if None not in sp else "")
    pol = [rx[k] for k, r in enumerate(seq) if r[0] == "poll"]
    if any(r[0] == "poll" for r in rxmap):
        chk("Convert T polled: busy (00) first, done last",
            len(pol) >= 2 and pol[0] == 0x00 and pol[-1] not in (None, 0x00),
            " ".join("%02X" % b if b is not None else "--" for b in pol))
    chk("peer model: zero timing violations", d["viol"] == 0, "%s" % d["viol"])
    # ⛔ R4 #18 (10-23): ALL SIX timing classes the peer model reports
    # (ds18b20_model.v) -- with none, the loop below checked nothing and passed
    chk("peer model reported all 6 timing classes",
        set(d["t"]) == OW_T_NAMES,
        "missing %s" % sorted(OW_T_NAMES - set(d["t"])) if set(d["t"]) != OW_T_NAMES
        else "")
    for nm, v in sorted(d["t"].items()):
        n, mn, mx, lo, hi = v
        chk("timing %s in [%s, %s] us" % (nm, lo / 1000,
                                          "inf" if hi is None else hi / 1000),
            n > 0 and mn >= lo and (hi is None or mx <= hi),
            "n=%d min %.3f max %.3f us" % (n, mn / 1000, mx / 1000))
    us = lambda v: (v[0], v[1] / 1000.0, v[2] / 1000.0) if v else None
    r_, p_, i_ = d["read"], d["pres"], d["init"]
    ru, pu, iu = us(r_), us(p_), us(i_)
    chk("master read sample <= 15 us after the fall (tRDV)",
        r_ and r_[0] > 0 and r_[2] <= 15000.0,
        "n=%d min %.3f max %.3f us" % ru if ru else "")
    chk("presence sample in [60, 75] us after release",
        p_ and p_[0] == len(resets) and p_[1] >= 60000.0 and p_[2] <= 75000.0,
        "n=%d min %.3f max %.3f us" % pu if pu else "")
    chk("master read-slot low >= 1 us (tINIT)",
        i_ and i_[0] > 0 and i_[1] >= 1000.0,
        "n=%d min %.3f max %.3f us" % iu if iu else "")
    chk("sticky flags clear (underrun, rx_drop, config_err, tx_full)",
        d["sticky"] == (0, 0, 0, 0), "%s" % (d["sticky"],))
    chk("no FAIL line in the bench log", not d["fails"],
        d["fails"][0][:90] if d["fails"] else "")
    return out


def main():
    print("CE5 -- 1-Wire DS18B20 on the frozen RTL (pe_asm program only)")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    rc = 0
    # the CRC implementation against a published example
    ok = crc8(AN27_ROM56) == AN27_CRC
    print("  host CRC-8 self-test (Maxim AN27 example -> A2): %s"
          % ("ok" if ok else "*** WRONG (%02X)" % crc8(AN27_ROM56)))
    rc |= 0 if ok else 1
    # the tracked images are what pe_asm assembles today
    for var, fn in sorted(onewire.TRACKED.items()):
        want = "\n".join("%02x" % b for b in onewire.build(var)) + "\n"
        with open(os.path.join(HERE, fn), encoding="ascii") as fh:
            same = fh.read().replace("\r\n", "\n") == want
        print("  tracked test/%s == pe_asm output: %s"
              % (fn, "yes" if same else "*** NO -- regenerate: python "
                 "test/onewire.py %s test/%s" % (var, fn)))
        rc |= 0 if same else 1
    e = onewire.engine("tt")
    print("  engine: P = %d cycles (%.1f us), W1/read low %d, sample %d, "
          "W0 low %d, presence sample %d cycles after release"
          % (e.P, e.P / 50.0, e.A, e.A + e.B, e.TW0, e.TAIL + e.A + e.B))

    arms = [("ok", "tt", P.DS18B20_TXN, 503, ()),
            ("fpga", "fpga", ROM_TXN, 2003, ()),
            # ⭐ PHASE COVERAGE (Wilson 10-21): each arm again with the release
            # rise 11 ns later and the part's own edges 7 ns off the grid --
            # OFF the diagonal, so the master-vs-part relative phase moves too.
            # The 120-run sweep (probe_reports/onewire_phase_outcome.txt) found
            # every byte and verdict identical across 20/20 phases.
            ("ok_ph", "tt", P.DS18B20_TXN, 503 + 11, ()),
            ("fpga_ph", "fpga", ROM_TXN, 2003 + 11, ())]
    PH = {"ok_ph": 7, "fpga_ph": 7}          # the part's offset, T_PH_NS
    mf = [("w0short", "w0short", ROM_TXN, 503, (),
           lambda d, ck: d["viol"] and any(
               "15..60 us sample window" in f or "tLOW0" in f for f in d["fails"])
           and not ck["timing tLOW0 in [60.0, 120.0] us"],
           "write-0 low 50 us"),
          ("latesample", "latesample", ROM_TXN, 503, (),
           lambda d, ck: not ck["master read sample <= 15 us after the fall (tRDV)"]
           and not ck["ROM CRC-8 valid (host-side)"],
           "read sample at 20 us"),
          ("romflip", "tt", ROM_TXN, 503, ("+FLIPROM=13",),
           lambda d, ck: not ck["ROM CRC-8 valid (host-side)"]
           and not ck["ROM == the intended ROM (family 28h)"],
           "ROM bit 13 flipped in the peer"),
          # ⛔⛔ OW6, STANDING (Wilson): AN INDUCED TX UNDERRUN MUST BE CAUGHT
          # BY THE HOST before the real part goes on. The host stops pushing
          # mid-READ-ROM (feed word 19 = ROM byte 2); the lane underruns and
          # holds DQ low. Red needs BOTH: the chip's underrun sticky set (the
          # stall really starved the lane -- not a no-op) AND a HOST-SIDE
          # check red (CRC-8 of the pushed bytes). Two lengths:
          #   long  100k cycles: ~1.2 ms low -> the part RESETS mid-read and
          #         answers with a presence pulse the host reads as data;
          #   short  45k cycles: one 128 us low slot -> no reset, the peer
          #         model sees NOTHING wrong (0 violations), the bit stream
          #         slips -- only the host's CRC catches it.
          ("underrun_reset", "tt", ROM_TXN, 503,
           ("+STALL_AT=19", "+STALL_CYC=100000"),
           lambda d, ck: d["sticky"] is not None and d["sticky"][0] == 1
           and d["stalled"] and not ck["ROM CRC-8 valid (host-side)"],
           "host stalls 100k cycles mid-ROM: underrun -> bus reset"),
          ("underrun_slot", "tt", ROM_TXN, 503,
           ("+STALL_AT=19", "+STALL_CYC=45000"),
           lambda d, ck: d["sticky"] is not None and d["sticky"][0] == 1
           and d["stalled"] and not ck["ROM CRC-8 valid (host-side)"],
           "host stalls 45k cycles mid-ROM: underrun -> one slot held low")]
    # ⛔ ONE SIMULATION AT A TIME BY DEFAULT (the machine-wide budget is
    # shared); CI, which owns its runner, sets PE_OW_JOBS=3
    jobs = int(os.environ.get("PE_OW_JOBS", "1"))
    for rise, ph in sorted({(a[3], PH.get(a[0], 0)) for a in arms + mf}):
        build_vvp(rise, ph)                # built once, before any sim
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        outs = dict(zip([a[0] for a in arms + mf], ex.map(
            lambda a: sim(a[0], a[1], a[2], a[3], a[4], PH.get(a[0], 0)),
            arms + mf)))
    res = {}
    for name, var, txn, rise, extra in arms:
        txt, rxmap = outs[name]
        d = parse(txt)
        checks = judge(d, rxmap)
        res[name] = (d, checks)
        print()
        print("  --- arm %s (%s image, RISE %d ns, part offset %d ns) ---"
              % (name, var, rise, PH.get(name, 0)))
        for c, okc, det in checks:
            print("    %-58s %s %s" % (c, "ok " if okc else "***", det))
            rc |= 0 if okc else 1
        m = re.search(r"OW-PHASE (rise=\d+/20 partfall=\d+/20)", txt)
        print("    phase coverage (this arm): %s" % (m.group(1) if m else "--"))
        if d["poll"] is not None:
            print("    poll groups: %d (8 read slots each)" % d["poll"])

    print()
    print("  --- must-fires ---")
    for name, var, txn, rise, extra, red, why in mf:
        txt, rxmap = outs[name]
        d = parse(txt)
        checks = judge(d, rxmap)
        ck = {c: okc for c, okc, _d in checks}
        try:
            fired = bool(d["end"] and red(d, ck))
        except KeyError as exc:
            fired = False
            print("    *** %s: the check %s was never produced" % (name, exc))
        reds = [c for c, okc, _d in checks if not okc]
        print("  must-fire %-10s (%s): %s" % (
            name, why, ("red  ok -- " + "; ".join(reds)[:150]) if fired
            else "*** MUST-FIRE FAILED (end=%s, red=%s)" % (d["end"], reds)))
        if fired:
            for f in d["fails"][:2]:
                print("      evidence: %s" % f.strip()[:110])
            if d["stalled"]:
                print("      evidence: underrun sticky %d, pushed ROM %s, "
                      "peer violations %s" % (
                          d["sticky"][0], " ".join("%02X" % b for b in
                                                   d["rx"][3:11]), d["viol"]))
        rc |= 0 if fired else 1

    print()
    if rc == 0:
        print("  CE5-ONEWIRE: PASSED")
        return 0
    print("  *** CE5-ONEWIRE: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
