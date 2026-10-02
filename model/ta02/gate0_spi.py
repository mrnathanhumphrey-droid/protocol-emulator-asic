"""GATE 0 for TA-02 -- BEHAVIOURAL genericity. The falsifier that can actually fail.

⛔⛔ THE TEST IS: SPI COMES OFF THE UNCHANGED MACHINE AND A FOREIGN DECODER READS
IT. Not "the diff across table loads is empty" -- that is not-editing-a-file, and
it passes trivially. Not "no protocol literals in the file" -- that passes a
UART-shaped machine with `434` renamed to `BIT_PERIOD`. sigrok's `spi` PD is
foreign code written by other people from a different standard than its `uart` PD,
and it does not care what we believe about our own interpreter.

⭐ SPI IS CHOSEN FOR STRUCTURAL DISTANCE FROM UART: three pins instead of one, a
GENERATED clock instead of a sampled bit period, MSB-first instead of LSB-first,
and framing by a chip-select level instead of by start/stop bits. If the
interpreter had any UART in it, SPI is what would break.

⛔ AND THE BYTES ARE STILL CHOSEN FOR BIT-ORDER SENSITIVITY. SPI here is MSB-first
while the UART table is LSB-first, so a byte equal to its own bit-reversal cannot
distinguish them. 0x00/0xFF/0xA5 are palindromes; 0x55 reverses to 0xAA. The
sensitive bytes are what make "it decoded correctly" mean anything.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from interp import Interp, table_spi_write

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
F_CLK = 50_000_000
SCLK, MOSI, CS = 0, 1, 2


def rev8(b: int) -> int:
    return int(format(b, "08b")[::-1], 2)


def wsl_path(p: str) -> str:
    p = os.path.abspath(p).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        return "/mnt/" + p[0].lower() + p[2:]
    return p


def dump_bus(levels, path: str) -> int:
    """sigrok `binary` input, numchannels<=8: one byte per sample, ch0 = LSB.

    ⛔ TEMP FILE, VERIFY, REPLACE. `open(p,"wb")` truncates BEFORE the write can
    fail, so a crash mid-dump leaves a short file that the decoder will happily
    read as a different waveform.
    """
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(v & 0xFF for v in levels))
    n = os.path.getsize(tmp)
    assert n == len(levels), "short dump: %d of %d" % (n, len(levels))
    os.replace(tmp, path)
    return n


def sigrok_row(binpath: str, row: str, bitorder: str = "msb-first",
               nch: int = 3) -> dict:
    """Run sigrok's SPI PD and read ONE annotation row.

    ⛔ SELECT THE ROW, DO NOT REGEX-SCRAPE `-A spi`. Scraping read every case as a
    MISMATCH on the first run: `-A spi` also emits the `mosi-transfer` row, so a
    single-word transfer yields the word TWICE while `DE AD BE EF` has spaces and
    the regex silently dropped it. The decoder had been right all along -- a bench
    bug presenting as a model failure, the same shape as TA-01b's frame error.

    ⛔ AND `mosi-bits` IS NOT WIRE ORDER. For `msb-first` the PD builds its bit
    list by inserting each arriving bit at the FRONT, so iterating it hands back
    arrival order REVERSED (0x0F goes out 0,0,0,0,1,1,1,1 and prints
    1,1,1,1,0,0,0,0). Reading that row as the wire order would manufacture an
    MSB/LSB finding that is purely a display artefact of the decoder.
    """
    cmd = ("sigrok-cli -i %s -I binary:numchannels=%d:samplerate=%d "
           "-P spi:clk=0:mosi=1:cs=2:cpol=0:cpha=0:bitorder=%s:wordsize=8 "
           "-A spi=%s" % (wsl_path(binpath), nch, F_CLK, bitorder, row))
    r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", cmd],
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    lines = [l.strip() for l in out.replace("\r", "").split("\n") if l.strip()]
    payload = [l.split(":", 1)[1].strip() for l in lines if l.startswith("spi-1:")]
    return {"rc": r.returncode, "ann": payload,
            "stderr": (r.stderr or "").strip()[:300]}


def run_case(name: str, data, half: int) -> dict:
    """One SPI transfer off the UNCHANGED interpreter."""
    table = table_spi_write(data, half, sclk=SCLK, mosi=MOSI, cs=CS)
    machine = Interp(table)
    # one full pass, padded so the last clock edge is not clipped. ⛔ THE TA-01b
    # BENCH BUG: a dumper that stopped on the last transition truncated the final
    # frame, and the foreign decoder reported a framing error that was OURS.
    n = sum(e.g for e in table) + 4 * half
    levels = machine.run_bus(n)
    path = os.path.join(HERE, "wave_spi_%s.bin" % name)
    dump_bus(levels, path)

    words = [w.upper() for w in sigrok_row(path, "mosi-data")["ann"]]
    warn = sigrok_row(path, "warnings")
    # ⭐ THE WIRE-ORDER MUST-FIRE ARM. Re-read the SAME waveform telling the PD
    # `lsb-first`; a bit-order-sensitive byte must now decode to its REVERSAL.
    # This is the foreign decoder certifying the wire order, rather than us
    # reading a display row and calling it evidence.
    rev = [w.upper() for w in
           sigrok_row(path, "mosi-data", bitorder="lsb-first")["ann"]]

    want = ["%02X" % b for b in data]
    want_rev = ["%02X" % rev8(b) for b in data]
    sensitive = all(rev8(b) != b for b in data)
    return {"name": name, "want": want, "got": words,
            "match": words == want,
            "warnings": warn["ann"],
            "rev_got": rev, "rev_want": want_rev,
            "rev_ok": (rev == want_rev),
            "sensitive": sensitive,
            "cycles": n, "table_len": len(table)}


def main() -> int:
    half = 8
    print("=== TA-02 GATE 0 -- SPI off the UNCHANGED table interpreter ===")
    print("    machine: model/ta02/interp.py (no protocol); table: table_spi_write")
    print("    foreign authority: sigrok `spi` PD, mode 0, MSB-first, 8-bit words")
    print("    pins: SCLK=%d MOSI=%d CS=%d   half-period = %d cycles" %
          (SCLK, MOSI, CS, half))
    print()
    cases = [
        ("55",      [0x55]),          # reverses to 0xAA -- bit-order SENSITIVE
        ("0F",      [0x0F]),          # reverses to 0xF0 -- SENSITIVE
        ("01",      [0x01]),          # reverses to 0x80 -- SENSITIVE
        ("A5",      [0xA5]),          # palindrome -- cannot catch a bit swap
        ("multi",   [0xDE, 0xAD, 0xBE, 0xEF]),   # multi-word framing
    ]
    print("  %-8s %-14s %-14s %-6s %-6s %-11s %s"
          % ("case", "want", "sigrok read", "match", "warns", "lsb re-read", "tbl"))
    rows = []
    for name, data in cases:
        r = run_case(name, data, half)
        rows.append(r)
        print("  %-8s %-14s %-14s %-6s %-6s %-11s %d"
              % (name, " ".join(r["want"]), " ".join(r["got"]) or "-",
                 "OK" if r["match"] else "**MISMATCH**",
                 len(r["warnings"]),
                 (("OK " if r["rev_ok"] else "**FAIL** ") + " ".join(r["rev_got"]))
                 if r["sensitive"] else "n/a (palin)",
                 r["table_len"]))
    print()
    sens = [r for r in rows if r["sensitive"]]
    print("  bit-order-SENSITIVE cases: %d of %d  -- and on each, the SAME waveform"
          % (len(sens), len(rows)))
    print("    re-read as lsb-first decodes to the REVERSED byte, so the foreign")
    print("    decoder certifies the WIRE ORDER, not merely the value.")
    bad = ([("word", r) for r in rows if not r["match"]]
           + [("warning", r) for r in rows if r["warnings"]]
           + [("wire-order", r) for r in sens if not r["rev_ok"]])
    for why, r in bad:
        print("    [%s] %s want=%s got=%s warns=%s lsb=%s(want %s)"
              % (why, r["name"], r["want"], r["got"], r["warnings"],
                 r["rev_got"], r["rev_want"]))
    ok = not bad and len(sens) >= 3
    print()
    print("  GATE 0 (behavioural): %s" %
          ("PASSED -- a foreign SPI decoder reads real SPI off a machine that "
           "contains no protocol. Genericity is BEHAVIOURAL, not lexical."
           if ok else
           "FAILED -- the interpreter is not generic. NOTHING DOWNSTREAM IS "
           "WORTH BUILDING; this is the gate that was supposed to be able to fail."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
