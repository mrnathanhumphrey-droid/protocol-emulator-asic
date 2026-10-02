"""GATE 0 -- the external decoder as a third authority.

⛔⛔ WHY THIS GATE EXISTS AND WHY IT RUNS FIRST. `uart_ta.py` contains two models
written by the same hand from the same understanding of UART. The must-fire arm
proves the monitor is not VACUOUS; it does NOT prove the monitor is CORRECT. A
shared misconception -- believing the stop bit is two bits, or that data is sent
MSB-first -- passes determinism, totality, conformance and every mutant, and
TA-01 goes green on a protocol that is not UART.

sigrok's `uart` protocol decoder is foreign code, written by other people from
the standard. It is the only genuinely independent authority in this stack.

⭐ IT IS NOT A SMOKE TEST ON ONE BYTE. The decoder runs on EVERY waveform and
must AGREE WITH `S_UART`'s verdict on each -- which validates both sides at once:
that `E_UART` emits real UART, and that `S_UART` decides the way an independent
decoder decides.

⛔ AND THE TEST BYTES ARE NOT ARBITRARY. A byte equal to its own bit-reversal
cannot catch an LSB/MSB swap. Of the obvious set, 0x00, 0xFF and 0xA5 are ALL
palindromes -- only 0x55 discriminates. Bytes below are chosen so that at least
two are bit-order-sensitive, because "the waveform decodes to the right value" is
a weaker statement than it looks when the value reads the same backwards.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uart_ta import (BAUD_DEFAULT, F_CLK, UartExecutor, UartReceiver,
                     bit_period, conformance, dump_binary)

HERE = os.path.dirname(os.path.abspath(__file__))


def rev8(b: int) -> int:
    return int(format(b, "08b")[::-1], 2)


def wsl_path(p: str) -> str:
    """D:\\x -> /mnt/d/x for the decoder running inside WSL."""
    p = os.path.abspath(p).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        return "/mnt/" + p[0].lower() + p[2:]
    return p


def sigrok_decode(binpath: str, baud: int = BAUD_DEFAULT) -> dict:
    """Run sigrok's uart PD over our waveform. Returns its view of the frame.

    ⭐ The binary is taken from `$SIGROK_CLI` so that "tool absent => gate red"
    is a testable proposition rather than a hope. `price_gates.sh` points it at a
    path that does not exist and requires every gate that depends on sigrok to go
    red; a gate that stays green with its foreign authority removed was never
    using it. The returned `rc` is what makes that detectable -- callers MUST
    check it, because a failed invocation produces no annotations, which is
    indistinguishable from a legitimate refusal unless the status is read.
    """
    exe = os.environ.get("SIGROK_CLI", "sigrok-cli")
    cmd = ("%s -i %s -I binary:numchannels=1:samplerate=%d "
           "-P uart:baudrate=%d:rx=0 -A uart"
           % (exe, wsl_path(binpath), F_CLK, baud))
    r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", cmd],
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    lines = [l.strip() for l in out.replace("\r", "").split("\n") if l.strip()]
    payload = [l.split(":", 1)[1].strip() for l in lines if l.startswith("uart-1:")]
    # the decoder emits the individual bits, then the byte as hex, plus framing
    bytes_hex = [tok for tok in payload
                 if re.fullmatch(r"[0-9A-Fa-f]{2}", tok) and tok not in ("0", "1")]
    saw_start = any("Start bit" in t for t in payload)
    saw_stop = any("Stop bit" in t for t in payload)
    frame_err = any("error" in t.lower() or "Frame" in t for t in payload)
    bits = [int(t) for t in payload if t in ("0", "1")]
    return {"rc": r.returncode, "raw": payload, "bytes": bytes_hex, "bits": bits,
            "start": saw_start, "stop": saw_stop, "frame_error": frame_err}


def run_case(name: str, ex: UartExecutor, expected: int, rx: UartReceiver,
             baud_for_decoder: int = BAUD_DEFAULT) -> dict:
    """One waveform: our verdict, the foreign decoder's verdict, and agreement."""
    ours = conformance(ex, rx, expected)
    path = os.path.join(HERE, "wave_%s.bin" % name)
    dump_binary(ex, path, idle_cycles=2)
    theirs = sigrok_decode(path, baud_for_decoder)

    decoded = None
    if theirs["bytes"]:
        decoded = int(theirs["bytes"][0], 16)
    # the foreign decoder "conforms" iff it saw a clean frame carrying `expected`
    theirs_ok = bool(theirs["start"] and theirs["stop"]
                     and decoded == expected and not theirs["frame_error"])
    return {"name": name, "expected": expected,
            "ours": ours["conforms"], "theirs": theirs_ok,
            "decoded": decoded, "bits": theirs["bits"],
            "agree": ours["conforms"] == theirs_ok,
            "ours_detail": ours, "theirs_raw": theirs["raw"][:14]}


def main() -> int:
    T = bit_period()
    rx = UartReceiver(T)
    print("=== GATE 0 -- external decoder (sigrok uart PD) as third authority ===")
    print("    T = %d cycles/bit @ %d Hz, baud %d" % (T, F_CLK, BAUD_DEFAULT))
    print()
    print("  %-10s %-9s %-7s %-8s %-8s %s" %
          ("case", "byte", "ours", "sigrok", "decoded", "agree"))
    rows = []
    # ⛔ at least two bit-order-SENSITIVE bytes; palindromes are kept but labelled
    for b in (0x55, 0x0F, 0x01, 0x00, 0xFF, 0xA5):
        tag = "" if rev8(b) != b else " (palindrome)"
        r = run_case("%02X" % b, UartExecutor(b, T), b, rx)
        rows.append(r)
        print("  %-10s 0x%02X%-4s %-7s %-8s %-8s %s"
              % ("good", b, tag[:4], "CONF" if r["ours"] else "VIOL",
                 "CONF" if r["theirs"] else "VIOL",
                 "0x%02X" % r["decoded"] if r["decoded"] is not None else "-",
                 "OK" if r["agree"] else "*** DISAGREE ***"))
    print()
    disagreements = [r for r in rows if not r["agree"]]
    sensitive = [r for r in rows if rev8(r["expected"]) != r["expected"]]
    print("  bit-order-SENSITIVE bytes exercised: %d of %d  (%s)"
          % (len(sensitive), len(rows),
             ", ".join("0x%02X" % r["expected"] for r in sensitive)))
    print("  disagreements: %d" % len(disagreements))
    for r in disagreements:
        print("    %s expected 0x%02X ours=%s theirs=%s decoded=%s raw=%s"
              % (r["name"], r["expected"], r["ours"], r["theirs"],
                 r["decoded"], r["theirs_raw"]))
    ok = not disagreements and all(r["ours"] for r in rows)
    print()
    print("  GATE 0: %s" % ("PASSED -- an independent decoder reads our line and "
                            "agrees with S_UART on every waveform" if ok
                            else "FAILED -- do not trust anything downstream"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
