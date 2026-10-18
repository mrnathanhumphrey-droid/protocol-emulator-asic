"""1-Wire on the real board -- the PC side of the OW = 1 build (Wilson 10-17).

Sends 'G'; the board loads the CE5 program, feeds the DS18B20 transaction
(reset, READ ROM; reset, SKIP ROM + CONVERT T polled to done; reset, SKIP ROM
+ READ SCRATCHPAD) and forwards every byte the chip received. THIS SCRIPT
JUDGES THEM, with the same parse the simulation's runner uses
(fpga/sim/run_fpga_onewire.walk) and the same CRC-8 (test/run_onewire.crc8):

  presence after every reset; the bus idle after it; the command echoes;
  the ROM's CRC-8, family 28h, and == the probe's known ROM (--rom);
  Convert T busy (00) first, done last; the scratchpad's CRC-8;
  the temperature, printed (compare it with the Pico's reading).

Usage:  python fpga/host/ow_run.py COM3 [--rom 288A7AA911000030]
Needs pyserial. Default --rom: the probe's ROM (Wilson, 10-17).
"""
import os
import sys
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for d in ("test", "model", os.path.join("fpga", "sim")):
    sys.path.insert(0, os.path.join(ROOT, d))
import onewire                               # noqa: E402
import pe_proto as P                         # noqa: E402
import run_onewire as RO                     # noqa: E402
import run_fpga_onewire as RF                # noqa: E402

BAUD = 115200
PROBE_ROM = "288A7AA911000030"
TIMEOUT_S = 5.0            # Convert T is <= 750 ms; the rest is ~40 ms


def main():
    port = sys.argv[1]
    rom_want = PROBE_ROM
    if "--rom" in sys.argv:
        rom_want = sys.argv[sys.argv.index("--rom") + 1]
    rom_want = list(bytes.fromhex(rom_want))
    e = onewire.engine("fpga")
    lines, rxmap, pidx = onewire.feed("fpga")
    # the board runs the TRACKED feed; it must be this one
    trk = open(RF.TRK_FEED, encoding="ascii").read().replace("\r\n", "\n")
    if trk != "\n".join(lines) + "\n":
        raise SystemExit("*** fpga/feeds/onewire_fpga_feed.hex is not the feed "
                         "this script parses -- rebuild")

    s = serial.Serial(port, BAUD, timeout=0.1)
    s.reset_input_buffer()
    s.write(b"G")
    s.flush()
    rx, t0 = [], time.time()
    while time.time() - t0 < TIMEOUT_S:
        rx += list(s.read(256))
        seq, full = RF.walk(rx, rxmap)
        if full:
            break
    s.close()
    seq, full = RF.walk(rx, rxmap)
    print("received %d byte(s) in %.2f s" % (len(rx), time.time() - t0))

    ck = []

    def chk(n, ok, det=""):
        ck.append((n, bool(ok), det))
        print("  %-52s %s %s" % (n, "ok " if ok else "***", det))

    chk("received every byte of the transaction", full, "%d bytes" % len(rx))
    resets = [b for r, b in seq if r == ("reset", 0)]
    chk("presence after every reset (bit %d == 0)" % P.OneWire.PRESENCE_BIT,
        len(resets) == 3 and all(not (b >> P.OneWire.PRESENCE_BIT) & 1 and (b & 0x1F) == 0
                                 for b in resets),
        " ".join("%02X" % b for b in resets))
    chk("bus idle after presence (FF)",
        all(b == 0xFF for r, b in seq if r == ("reset", 1)))
    ech = [(r[1], b) for r, b in seq if r[0] == "echo"]
    chk("command echoes == the commands written",
        ech and all(a == b for a, b in ech), " ".join("%02X" % b for _a, b in ech))
    rom = [b for r, b in seq if r[0] == "read" and r[1] == "rom"]
    chk("ROM CRC-8 valid", len(rom) == 8 and RO.crc8(rom[:7]) == rom[7],
        " ".join("%02X" % b for b in rom))
    chk("ROM family 28h (DS18B20)", len(rom) == 8 and rom[0] == 0x28)
    chk("ROM == the probe's ROM", rom == rom_want,
        " ".join("%02X" % b for b in rom_want))
    pol = [b for r, b in seq if r[0] == "poll"]
    chk("Convert T polled: busy (00) first, done last",
        len(pol) >= 2 and pol[0] == 0 and pol[-1] != 0,
        "%d poll byte(s), last %s" % (len(pol), "%02X" % pol[-1] if pol else "--"))
    sp = [b for r, b in seq if r[0] == "read" and r[1] == "sp"]
    chk("scratchpad CRC-8 valid", len(sp) == 9 and RO.crc8(sp[:8]) == sp[8],
        " ".join("%02X" % b for b in sp))
    if len(sp) == 9:
        raw = sp[0] | sp[1] << 8
        raw = raw - 0x10000 if raw & 0x8000 else raw
        print("  TEMPERATURE: %.4f C   (compare with the Pico's reading)" % (raw / 16.0))
    ok = all(o for _n, o, _d in ck)
    print("FPGA-ONEWIRE-HW: %s" % ("PASSED (bytes); temperature vs Pico is yours to compare"
                                   if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
