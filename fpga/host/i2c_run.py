"""I2C FRAM on the real board -- the PC side of the OW = 2 build (Wilson 10-17).

Picks 4 FRESH RANDOM bytes, sends 'G' + those 4; the board loads the
one-pass program (read old 0x0010..13, write the 4 bytes, read them back) and
forwards every byte the chip received, then the status trailer. THIS SCRIPT
JUDGES THEM with the simulation's own checks (fpga/sim/run_fpga_i2c.pc_judge):
every ACK slot ACK, the readback == the bytes sent, the contents changed, the
trailer clean (no underrun / TX-full ...).

WILSON 2a: the bytes are re-rolled if they equal the contents the FRAM should
hold now (the previous run's bytes), so a failed write cannot pass.
WILSON 2b: every run is LOGGED (probe_bench/i2c_fram_runs.log, one JSON line
per run); the next run's OLD contents must equal the previous run's bytes --
FRAM keeps data with the power off.
Also prints the SHA-256 of the bitstream file (which build ran).

Usage:  python fpga/host/i2c_run.py COM6
Needs pyserial.
"""
import hashlib
import json
import os
import sys
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "fpga", "sim"))
import run_fpga_i2c as RI                    # noqa: E402

BAUD = 115200
TIMEOUT_S = 3.0              # the pass is ~1 ms; the UART reply ~3 ms
LOG = os.path.join(os.path.dirname(ROOT) if os.path.basename(ROOT).startswith("probe_wt")
                   else ROOT, "probe_bench", "i2c_fram_runs.log")


def last_run():
    if not os.path.exists(LOG):
        return None
    lines = [l for l in open(LOG, encoding="utf-8").read().splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def main():
    port = sys.argv[1]
    bit = os.path.join(ROOT, "fpga", "build", "pa100t_i2c", "pa100t_i2cfram.bit")
    sha = None
    if os.path.exists(bit):
        sha = hashlib.sha256(open(bit, "rb").read()).hexdigest()
        print("bitstream %s  sha256 %s  built %s" % (
            os.path.relpath(bit, ROOT), sha,
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(bit)))))
    else:
        print("bitstream: *** %s not found -- which build is on the board?" % bit)

    prev = last_run()
    expect_old = int(prev["data"], 16) if prev and prev.get("pass") else None
    print("previous logged run: %s" % (
        "none" if prev is None else "%s data %s (%s)" % (
            prev["time"], prev["data"], "passed" if prev.get("pass") else "FAILED")))
    while True:                                  # Wilson 2a: re-roll on equality
        data = int.from_bytes(os.urandom(4), "big")
        if data != expect_old:
            break
    print("fresh bytes: %08X" % data)

    s = serial.Serial(port, BAUD, timeout=0.1)
    s.reset_input_buffer()
    s.write(b"G" + data.to_bytes(4, "big"))
    s.flush()
    rx, t0, quiet = [], time.time(), None
    while time.time() - t0 < TIMEOUT_S:          # read until quiet for 0.3 s
        got = list(s.read(256))
        rx += got
        if rx and not got:
            quiet = quiet or time.time()
            if time.time() - quiet > 0.3:
                break
        elif got:
            quiet = None
    s.close()
    print("received %d byte(s): %s" % (len(rx), " ".join("%02X" % b for b in rx)))

    ck, got_old, got_new, st = RI.pc_judge(rx, data, expect_old)
    for n, ok, det in ck:
        print("  %-62s %s %s" % (n, "ok " if ok else "***", det))
    if expect_old is None:
        print("  (no previous passing run logged: the old-contents check starts next run)")
    ok = all(o for _n, o, _d in ck)
    hx = lambda bs: " ".join("--" if b is None else "%02X" % b for b in bs)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "data": "%08X" % data, "old_read": hx(got_old),
                             "new_read": hx(got_new),
                             "status": None if st is None else "%02X" % st,
                             "pass": ok, "bit_sha256": sha}) + "\n")
    print("logged to %s" % LOG)
    print("FPGA-I2C-HW: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
