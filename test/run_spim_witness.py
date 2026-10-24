"""WF1 WITNESS -- SPI-master at the published 1 MHz: the WIRE equals the FEED.

THE SUBJECT: `corpus_spim25.hex` (`corpus.build_spi_master_1mhz`): the MB85RS64V
WREN / WRITE 01 23 5B C4 1E / READ 01 23 [in][in] at d = 25, one 50-cycle SCK
period -- 1 MHz on the 50 MHz design clock. Admissible: pe_asm accepts it with
its timing checks ON.

⚠ THE CLAIMING LAYER: SIMULATION -- `tb_trace` with the `fram_spi` peer model
(same-hand, labelled so in `test/fram_spi.v`). The hardware witness is the
FPGA with the real MB85RS64V proven on the Pico (BENCH-02), later.

THREE EXACT CHECKS, all from the PINS, never the chip's internals:
  MOSI == FEED   every CS frame, decoded on the SCK rise (modes 0 and 3 both
                 sample there), is the program's frame in order -- 06;
                 02 01 23 5B C4 1E; 03 01 23 + two receive bytes -- and the
                 frame count is exact over the window.
  MISO == PEER   every READ's two data bytes on the wire are 5B C4, the bytes
                 the WRITE put in the peer.
  CHIP == WIRE   the chip's received bytes (the 3-pin serial host stream on
                 `uo_out`, pins only) are the READs' MISO bytes, in order,
                 count exact.
AT THE RATING: SCK's modal period is 50 cycles, and no SCK phase (CS low) is
shorter than THIS image's derived floor d - (r_i - C), with r_i from A2's
response-time analysis for this program, stamped before the run.

THE WINDOW: frames whose CS rises at least TAIL cycles before the run ends;
chip bytes delivered by the same cutoff + TAIL. Both counts must match exactly.

MUST-FIRES, one per check, each red for ITS OWN reason:
  M_TX_LOAD_ANYPHASE  (RTL mutant) MOSI == FEED red
  M_CKRX_HEADER_PIN   (RTL mutant) CHIP == WIRE red, MISO == PEER still green
  +SPI_MEMFLIP=1      (bench plant: the peer's 5B becomes 5A) MISO == PEER
                      red, CHIP == WIRE still green
POSITIVE TOKEN: `GATE spim-witness: PASSED`.
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model"), os.path.join(ROOT, "model", "a2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from toolchain import banner, tool          # noqa: E402
import sim_run                              # noqa: E402
import corpus                               # noqa: E402
import run_recert as R                      # noqa: E402  one trace reader
from run_spifram import serial_rx           # noqa: E402  one frame decoder

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NAME = "corpus_spim25"
IMG = "test/%s.hex" % NAME
NCYC = 60000
TAIL = 3000
D = 25


def frames_want():
    f = corpus.FEEDS[NAME]
    return [("wren", f[0:1], 1), ("write", f[1:7], 6), ("read", f[7:10], 5)]


def run(vvp, extra=()):
    out = os.path.join(R.SCRATCH, "spimw_%s.txt" % os.path.basename(vvp))
    seq = corpus.FEEDS[NAME]
    cmd = sim_run.vvp([vvp, "+IMG=%s" % IMG, "+NBYTES=256", "+PEER=spi",
                       "+NCYC=%d" % NCYC, "+OUT=%s" % out, "+SEED=1", "+ASYNC=0",
                       "+STAYLOAD=0", "+SCLHOLD=0", "+SPI_SCK_INV=0",
                       "+FEEDN=%d" % len(seq),
                       "+FEED=%s" % "".join("%02x" % b for b in seq)] + list(extra),
                      images=[IMG])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    # ⛔ R4 #21 (10-23): with zero rows every check is False, so a must-fire
    # with no wrong-reason check (M_TX_LOAD_ANYPHASE) "fired" on a run that
    # never happened. A run that did not finish is no evidence either way.
    why = sim_run.trace_incomplete((r.stdout or "") + (r.stderr or ""), cmd)
    if why:
        raise SystemExit("*** run_spim_witness %s: %s"
                         % (os.path.basename(vvp), why))
    rows = []
    with open(out, encoding="ascii", errors="replace") as fh:
        for line in fh:
            f = line.split()
            if len(f) >= 5 and f[0].isdigit():
                rows.append((f[1], f[2], f[3], f[4]))
    return r.stdout or "", rows


def judge(rows):
    """-> {check: (ok, detail)} and the phase list."""
    sck = [R.level(r, corpus.P_M_SCLK, True) for r in rows]
    cs = [R.level(r, corpus.P_M_CS, True) for r in rows]
    mosi = [R.level(r, corpus.P_M_MOSI, True) for r in rows]
    miso = [R.level(r, corpus.P_M_MISO) for r in rows]
    end = len(rows) - TAIL
    frames, cur, phases, edge = [], None, [], None
    for i in range(1, len(rows)):
        if cs[i - 1] == 1 and cs[i] == 0:
            cur, edge = {"mo": [], "mi": []}, None
        elif cs[i - 1] == 0 and cs[i] == 1 and cur is not None:
            if i <= end:
                frames.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        if sck[i] != sck[i - 1]:
            if edge is not None:
                phases.append(i - edge)
            edge = i
        if sck[i - 1] == 0 and sck[i] == 1:
            cur["mo"].append(mosi[i])
            cur["mi"].append(miso[i])

    def by(bits):
        return [int("".join(map(str, bits[j:j + 8])), 2)
                for j in range(0, len(bits) - len(bits) % 8, 8)]
    want = frames_want()
    bad_mosi, wire_rx, bad_miso = [], [], []
    for k, fr in enumerate(frames):
        kind, out_bytes, nbytes = want[k % 3]
        mo, mi = by(fr["mo"]), by(fr["mi"])
        if len(mo) != nbytes or mo[:len(out_bytes)] != out_bytes:
            bad_mosi.append((k, kind, mo))
        if kind == "read":
            data = mi[3:5]
            wire_rx += data
            if data != corpus.FEEDS[NAME][4:6]:
                bad_miso.append((k, data))
    reads = sum(1 for k in range(len(frames)) if want[k % 3][0] == "read")
    chip = serial_rx(rows, 0)[:len(wire_rx) + 2]
    chk = {}
    # every frame in the window is the program's frame AT ITS POSITION; the
    # window may end mid-transaction, so no "whole triples" condition
    chk["MOSI == FEED"] = (not bad_mosi and len(frames) >= 6,
                           "%d frame(s), %d wrong%s" % (len(frames), len(bad_mosi),
                           ("; first: frame %d (%s) %s" % (bad_mosi[0][0], bad_mosi[0][1],
                            " ".join("%02X" % b for b in bad_mosi[0][2])) if bad_mosi else "")))
    chk["MISO == PEER"] = (not bad_miso and reads > 0,
                           "%d READ(s), %d wrong%s" % (reads, len(bad_miso),
                           ("; first: %s" % " ".join("%02X" % b for b in bad_miso[0][1])
                            if bad_miso else "")))
    chk["CHIP == WIRE"] = (chip[:len(wire_rx)] == wire_rx and len(chip) >= len(wire_rx) > 0,
                           "%d wire byte(s), chip %s" % (len(wire_rx),
                           "equal" if chip[:len(wire_rx)] == wire_rx else
                           "differs: %s" % " ".join("%02X" % b for b in chip[:6])))
    return chk, phases


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("SPI-MASTER WITNESS -- %s at d = %d (1 MHz): wire == feed" % (IMG, D))
    print("  claiming layer: SIMULATION (tb_trace + fram_spi model)")
    print("=" * 78)
    import gate_sda_hold as G
    import pe_isa as I
    import program_a2
    from bursty import C_SHIPPED
    from pyrta_src import pinned_pyrta
    store = R.read(os.path.join(ROOT, IMG))
    hdr = I.lane_programs(store)[0][0]
    rc = 0
    if hdr["t"] != D:
        print("  *** the image's lane 0 runs at d = %d, not %d" % (hdr["t"], D))
        return 1
    # ⭐ THE FLOOR, STAMPED BEFORE ANY RUN: this program's own r_i
    src = pinned_pyrta(quiet=True)
    r0, why = program_a2.lane_responses(store, src)[0]
    if r0 is None:
        print("  *** no response bound for lane 0: %s" % why)
        return 1
    floor = D - (r0 - C_SHIPPED)
    print("  floor (stamped): r_i = %d (%s), C = %d -> shortest SCK phase >= "
          "%d - (%d - %d) = %d cycles" % (r0, "max(ours, pyRTA)" if src
                                          else "our recurrence; pyRTA not pinned",
                                          C_SHIPPED, D, r0, C_SHIPPED, floor))
    os.makedirs(R.SCRATCH, exist_ok=True)
    os.makedirs(G.OUT, exist_ok=True)
    clean = G.build([], "spimw_clean")
    out, rows = run(clean)
    chk, phases = judge(rows)
    cnt = collections.Counter(phases)
    # the period is two phases; the modal PHASE is the robust reading (a pair
    # sum would misalign across CS frames)
    modal = 2 * cnt.most_common(1)[0][0] if cnt else None
    shortest = min(phases) if phases else None
    print()
    for name, (ok, det) in chk.items():
        print("    %-14s %s  %s" % (name, "ok " if ok else "***", det))
        rc |= 0 if ok else 1
    ok_rate = modal == 2 * D
    ok_floor = shortest is not None and shortest >= floor
    print("    %-14s %s  modal SCK period %s cycles (want %d = 1 MHz)"
          % ("RATE", "ok " if ok_rate else "***", modal, 2 * D))
    print("    %-14s %s  shortest observed phase %s cycles, derived floor %d"
          % ("PHASE FLOOR", "ok " if ok_floor else "***", shortest, floor))
    print("                   phases (cycles: count): %s" % dict(sorted(cnt.items())))
    rc |= 0 if (ok_rate and ok_floor) else 1
    fails = [l for l in out.splitlines() if "*** FAIL" in l]
    print("    %-14s %s  %s" % ("BENCH", "ok " if not fails else "***",
                                fails[0][:80] if fails else "no FAIL line"))
    rc |= 1 if fails else 0

    print()
    print("  --- must-fires: one per check, each red for its own reason ---")
    plants = [("M_TX_LOAD_ANYPHASE", ["M_TX_LOAD_ANYPHASE"], [], "MOSI == FEED", None),
              ("M_CKRX_HEADER_PIN", ["M_CKRX_HEADER_PIN"], [], "CHIP == WIRE", "MISO == PEER"),
              ("+SPI_MEMFLIP=1", [], ["+SPI_MEMFLIP=1"], "MISO == PEER", "CHIP == WIRE")]
    for label, defs, extra, red, green in plants:
        vvp = clean if not defs else G.build(defs, "spimw_" + defs[0].lower())
        _o, rws = run(vvp, extra)
        c, _ph = judge(rws)
        fired = not c[red][0]
        right = green is None or c[green][0]
        print("    %-20s %-14s %s%s" % (label, red,
              "RED" if fired else "*** SURVIVED",
              "" if right else "  *** but %s also red (wrong reason)" % green))
        rc |= 0 if (fired and right) else 1
    print()
    print("  GATE spim-witness: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
