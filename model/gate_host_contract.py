"""THE HOST CONTRACT CANNOT DRIFT FROM THE CHIP (F1.5, Wilson 11-09).

⛔ WHY. docs/HOST_INTERFACE.md is what a demo-board loader (the Pico) is written
from. On 10-25 v2 doubled the store and added the MAGIC check, and the document
kept saying "Load the FULL store: all 256 bytes" with no MAGIC -- a loader
written from it would have been refused by the silicon (CONFIG_ERR).

THE CHECK. The `load-contract` table in docs/HOST_INTERFACE.md, row by row,
against the one encoder (test/pe_isa.py) and the RTL (src/project.v):
  store size          == pe_isa.STORE_BYTES
  header region       == bytes 0 .. HDR_REGION - 1
  MAGIC               == bytes HDR_REGION .. ACT_BASE - 1 = pe_isa.MAGIC
  first action byte   == pe_isa.ACT_BASE
  action word         == pe_isa.ACT_BYTES
  store filler word   == pe_isa.STORE_FILLER
  refusal             == CONFIG_ERR at the status bit src/project.v gives
                         cfg_err_any in `status_byte <= {...}`
A missing row, an unparsable one, or an extra one is red. And outside the
table, a v1 store-size phrase ("256 bytes", "256 consecutive", "256-byte
store") is red unless it is on ALLOWED_V1 with its reason (history, said so).

MUST-FIRES: the table's store size put back to 256 -> red; a "256 consecutive
writes" sentence put back -> red.
                                              token: GATE host-contract: PASSED
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
import pe_isa                                           # noqa: E402

DOC = os.path.join(ROOT, "docs", "HOST_INTERFACE.md")
V1_PHRASE = re.compile(r"\b256(?:[- ]byte| bytes| consecutive)\b")
#: a v1 phrase allowed outside the table: a substring of its line -> why
ALLOWED_V1 = {
    "a full v1 (256-byte) walk": "history: v1's readback cost, labelled v1",
    "v1 loaded 256 bytes with no MAGIC": "history: what v2 changed, labelled v1",
}


def cfg_err_bit():
    src = open(os.path.join(ROOT, "src", "project.v"), encoding="utf-8").read()
    m = re.search(r"status_byte\s*<=\s*\{([^}]*)\}", src)
    if not m:
        raise SystemExit("*** src/project.v: no `status_byte <= {...}`")
    parts = [p.strip() for p in m.group(1).replace("\n", " ").split(",")]
    if len(parts) != 8 or "cfg_err_any" not in parts:
        raise SystemExit("*** status_byte is not 8 one-bit fields with cfg_err_any: %r" % parts)
    return 7 - parts.index("cfg_err_any")


def want():
    f = pe_isa.STORE_FILLER
    return {
        "store size": "%d bytes" % pe_isa.STORE_BYTES,
        "header region": "bytes 0–%d" % (pe_isa.HDR_REGION - 1),
        "MAGIC": "bytes %d–%d = %s" % (pe_isa.HDR_REGION, pe_isa.ACT_BASE - 1,
                                       " ".join("0x%02X" % b for b in pe_isa.MAGIC)),
        "first action byte": "%d" % pe_isa.ACT_BASE,
        "action word": "%d bytes" % pe_isa.ACT_BYTES,
        "store filler word": " ".join("%02X" % b for b in f),
        "refusal": "CONFIG_ERR, status bit %d" % cfg_err_bit(),
    }


def table(text):
    m = re.search(r"<!-- load-contract:.*?-->(.*?)<!-- /load-contract -->", text, re.S)
    if not m:
        return None
    rows = {}
    for line in m.group(1).splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) != 2 or c[0] in ("item", "---") or set(c[0]) <= set("- "):
            continue
        # the value as written, bold and parentheticals removed
        v = re.sub(r"\(.*?\)", "", c[1]).replace("**", "").replace("`", "")
        v = re.sub(r"\s+", " ", v).strip().rstrip(".")
        rows[c[0]] = v.replace("\"V2\"", "").strip()
    return rows


def judge(text):
    probs = []
    rows = table(text)
    if rows is None:
        return ["docs/HOST_INTERFACE.md has no load-contract table"]
    w = want()
    for k in w:
        if k not in rows:
            probs.append("load-contract row %r missing" % k)
        elif rows[k] != w[k]:
            probs.append("load-contract %r says %r, the chip is %r" % (k, rows[k], w[k]))
    for k in sorted(set(rows) - set(w)):
        probs.append("load-contract row %r is not checked here (add it to want())" % k)
    outside = re.sub(r"<!-- load-contract:.*?<!-- /load-contract -->", "", text, flags=re.S)
    for n, line in enumerate(outside.splitlines(), 1):
        if V1_PHRASE.search(line) and not any(a in line for a in ALLOWED_V1):
            probs.append("a v1 store-size phrase outside the table: %r" % line.strip()[:110])
    used = [a for a in ALLOWED_V1 if a in outside]
    for a in sorted(set(ALLOWED_V1) - set(used)):
        probs.append("ALLOWED_V1 %r matches no line" % a)
    return probs


def main():
    print("GATE host-contract: docs/HOST_INTERFACE.md's load contract == the chip")
    text = open(DOC, encoding="utf-8").read()
    for k, v in want().items():
        print("    %-18s %s" % (k, v))
    probs = judge(text)
    for p in probs:
        print("  *** " + p)
    rc = 1 if probs else 0
    sz = "| store size | **%d bytes** |" % pe_isa.STORE_BYTES
    for tag, a, b in (("store size typed back to 256", sz, "| store size | **256 bytes** |"),
                      ("a v1 sentence put back", "## Loading a program",
                       "## Loading a program\n\nLoad all 256 consecutive writes.")):
        if a not in text:
            print("  *** must-fire %s: landmark %r not found" % (tag, a))
            rc = 1
            continue
        hit = bool(judge(text.replace(a, b, 1)))
        print("  must-fire: %-34s %s" % (tag, "red  ok" if hit else "*** STAYED GREEN"))
        rc |= 0 if hit else 1
    print()
    print("  GATE host-contract: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
