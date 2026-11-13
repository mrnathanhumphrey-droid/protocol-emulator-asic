"""NO CONSUMER OF THE STORE TYPES ITS SIZE (F1.5, Wilson 11-09).

⛔ WHY -- PREVENTION. On 10-25 v2 doubled the store (256 -> 512 bytes) and the
loader began refusing a short load or a missing MAGIC. The board glue
(`fpga/rtl/pe_fpga_core.v`: `rom[0:255]`, `laddr == 9'd255`), its loader bench
and the PC loader kept the v1 size; the debt was declared (stale_records,
10-25), but a consumer that TYPES the size is left behind silently by the next
change. Every consumer takes the size from the one encoder instead:
`test/pe_isa.py` (STORE_BYTES, AW) or the generated `test/store_filler.vh`
(PE_STORE_BYTES).

THE CHECK. Over `fpga/` (rtl, sim, host, pa100t) and `test/` -- every tracked
.v / .vh / .sv / .py / .tcl -- a 255 / 256 / 511 / 512 literal IN A STORE-SIZE
ROLE is red unless ALLOWED below with a written reason:
  * a Verilog array bound      [0:255]  [0:511]
  * an index compare           == 9'd255, == 255, != 511 ...
  * a loop bound               i < 256,  i <= 511
  * a Python length / range    len(x) != 256, range(512), read(256)
  * a slice / size             [:256], [256:], * 256  (Python)
Literals in comments are not read. A byte VALUE (randrange(256), & 255) or a
pointer domain that is not the store are the typical allowed entries.
ALLOWED entries that match nothing are red too (a stale reason is inherited by
the next file of that name).

MUST-FIRE: the glue's v1 ROM typed back (`rom [0:255]` in a scratch copy of
pe_fpga_core.v) is red.
                                              token: GATE store-size-literals: PASSED
"""
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCOPE = ("fpga", "test")
EXT = (".v", ".vh", ".sv", ".py", ".tcl")
N = r"(?:255|256|511|512)"
ROLES = [
    ("array bound", re.compile(r"\[\s*0\s*:\s*%s\s*\]" % N)),
    ("index compare", re.compile(r"[=!<>]=\s*(?:\d+'[dh])?%s\b|\b%s\s*[=!]=" % (N, N))),
    ("loop bound", re.compile(r"<\s*%s\b" % N)),
    ("length / range", re.compile(r"\b(?:len\([^)]*\)\s*[!=<>]=?\s*%s|range\(\s*%s\s*\)|read\(\s*%s\s*\))" % (N, N, N))),
    # `8*256` is a STRING register's width (a file name), never the store:
    # excluded by the idiom, so no entry per bench is needed
    ("slice / size", re.compile(r"\[\s*:?\s*%s\s*:?\s*\]|(?<!8)(?<!8 )\*\s*%s\b" % (N, N))),
]

_BYTE = "a BYTE's range (0..255) in the encoder's field checks, not the store"
_SER = "a serial read's chunk size (bytes per pyserial read), not the store"
#: (repo path, a substring of the line) -> why it is not the store's size.
#: Each entry must match at least one flagged line.
ALLOWED = {
    ("fpga/host/i2c_run.py", "s.read(256)"): _SER,
    ("fpga/host/ow_run.py", "s.read(256)"): _SER,
    ("fpga/rtl/pe_fpga_core.v", "fallsm [0:255]"):
        "OW 2's per-fed-byte SCL-fall table (one entry per feed byte, NFEED <= "
        "256), sized to the feed, not the store",
    ("test/clocked_conform.vh", "* 256 + ("):
        "the conformance monitor's per-queue ring of 256 pushes (q * 256 + "
        "write index mod 256): a monitor buffer, not the store",
    ("test/pe_isa.py", "if not 1 <= n <= 255:"): _BYTE,
    ("test/pe_isa.py", "bit (<= 255), 8 bits in ONE action"): _BYTE,
    ("test/pe_isa.py", "if not 0 <= b <= 255 or not 0 < d <= 255:"): _BYTE,
}


def files():
    r = subprocess.run(["git", "ls-files", "--"] + list(SCOPE), cwd=ROOT,
                       capture_output=True, text=True)
    return sorted(p for p in r.stdout.splitlines() if p.endswith(EXT))


def strip_comment(line, path):
    if path.endswith(".py") or path.endswith(".tcl"):
        return re.split(r"(?<!['\"])#", line, 1)[0]
    s = line.split("//", 1)[0]
    return "" if s.lstrip().startswith("*") or s.lstrip().startswith("/*") else s


def scan(path, text):
    out = []
    for k, line in enumerate(text.splitlines(), 1):
        code = strip_comment(line, path)
        for role, rx in ROLES:
            if rx.search(code):
                out.append((path, k, role, line.strip()))
                break
    return out


def judge(hits, allowed):
    bad, used = [], set()
    for path, k, role, line in hits:
        key = next((a for a in allowed if a[0] == path and a[1] in line), None)
        if key:
            used.add(key)
        else:
            bad.append("%s:%d [%s] %s" % (path, k, role, line[:110]))
    stale = ["ALLOWED (%s, %r) matches no flagged line" % a for a in sorted(set(allowed) - used)]
    return bad, stale


def main():
    print("GATE store-size-literals: no consumer of the store types its size")
    hits = []
    for p in files():
        with open(os.path.join(ROOT, p), encoding="utf-8", errors="replace") as fh:
            hits += scan(p, fh.read())
    bad, stale = judge(hits, ALLOWED)
    print("  %d file(s) scanned, %d flagged line(s), %d allowed" % (len(files()), len(hits),
                                                                     len(hits) - len(bad)))
    for b in bad + stale:
        print("  *** " + b)
    rc = 1 if bad or stale else 0

    # must-fire: the v1 ROM typed back into the glue
    core = "fpga/rtl/pe_fpga_core.v"
    src = open(os.path.join(ROOT, core), encoding="utf-8").read()
    if "rom [0:SB-1]" not in src.replace("reg  [7:0] rom", "rom"):
        print("  *** must-fire landmark `rom [0:SB-1]` not found in %s" % core)
        rc = 1
    else:
        planted = src.replace("[0:SB-1];\n  initial $readmemh(IMG, rom);", "[0:255];\n  initial $readmemh(IMG, rom);", 1)
        mb, _ = judge(scan(core, planted), ALLOWED)
        hit = any("[0:255]" in m for m in mb)
        print("  must-fire: rom[0:255] typed back into the glue   %s" % ("red  ok" if hit else "*** STAYED GREEN"))
        rc |= 0 if hit else 1
    print()
    print("  GATE store-size-literals: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
