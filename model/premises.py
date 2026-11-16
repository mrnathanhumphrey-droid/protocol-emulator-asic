"""premises -- NAMED peer premises a certificate may rest on (Wilson 11-15, call 1).

A certificate is a function of the image ALONE unless it names its premises. Wilson's
conditions for a spec / peer premise in a certificate:
  * named and cited: an ID, the source, the source's SHA-256, and a label (read / assumed);
  * the stamp records the premise IDs (no premise: the image-only certificate, as before);
  * the premise is also checked on the chip (a `within` bound is a WINDOW predicate for the
    validator), so a peer that breaks its datasheet is detected at run time.

Two kinds of source:
  document  an external copy pinned by its SHA-256 (usb_20.pdf, as clock.py pins it). It is
            usable only when the file is on disk AND its SHA-256 matches the pin.
  repo      a symbol in a repo file; the citation carries the file's SHA-256 computed when
            cited (the file is under git, so the citation names the exact text read).
STAMP-USABLE: label "read", the source present, a document's pin matching. An "assumed"
premise is reported in the counterfactual table (model/drain_table.py) and never stamped.

DATASHEETS maps a part name, as a spec writes it (`source datasheet "<part>"`), to the
premise ID of that part's datasheet. EMPTY TODAY: no peer datasheet is on disk, so a
`within` naming a part is compiled with the image-only certificate and says so.
"""
from __future__ import annotations

import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

REGISTRY = {
    "USB20": {
        "kind": "document",
        "what": "USB 2.0 low-speed timing (TIPD, TLEOPR, TRSPIPD1, TLDRATE): lane_cert.premises",
        "source": r"D:\ProtocolEmulator_internal\refs\usb_20.pdf",
        # the pin model/clock.py carries for the same copy (Wilson 11-13)
        "sha256": "d39698a33486c399124af92bd02e4f978fd9a836b5cf4e52e6e4633eb1d89f61",
        "label": "read",
    },
    "UART_PEER_BAND": {
        "kind": "repo",
        "what": "a UART peer's bit is within T * (1 +- max|ERRS| / 1000) -- the band the receiver "
                "is verified to decode back to back; the frame is 8N1",
        "source": "test/run_uartrx.py", "symbol": "ERRS",
        "label": "read (the band) + assumed (8N1 framing)",
    },
    # Wilson 11-15 (call 4): the bench SPI master is the Pico. The RP2040 / RP2350 datasheet
    # bounds its SPI clock only from ABOVE (clk_peri / 2); the 1 MHz (MISO) / 500 kHz (MOSI) the
    # SPI-target arming check needs is what OUR FIRMWARE programs -- a firmware premise. It stays
    # `assumed` (out of every certificate) until a hardware witness -- a logic-analyser capture
    # of CS and SCK on the bench -- makes it `measured`. Which part (Pico = RP2040, or Pico 2 =
    # RP2350: docs/HOST_FIRMWARE.md and fpga/host/load.py disagree) is Nathan's to confirm.
    "PICO_SPI_SCK": {
        "kind": "repo",
        "what": "the bench SPI master (the Pico) drives SCK no faster than its firmware's setting "
                "(the declared T_EXT_HZ), so two SCK edges of one polarity are at least one period "
                "apart",
        "source": "model/a2/program_a2.py", "symbol": "T_EXT_HZ",
        "label": "assumed (firmware-set; no Pico SPI firmware in the repo yet)",
        "owed": "hw: a logic-analyser capture of CS and SCK on the Pico bench (then `measured`)",
        "part": "RP2040 or RP2350 -- to confirm",
    },
}

#: part name (a spec's `source datasheet "<part>"`) -> premise ID. Empty: no peer datasheet
#: is on disk (see the module doc).
DATASHEETS = {}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def cite(pid):
    """{id, source, sha256 (computed), label, ok, why}: the citation a stamp or table carries"""
    e = REGISTRY[pid]
    path = e["source"] if os.path.isabs(e["source"]) else os.path.join(ROOT, e["source"])
    out = {"id": pid, "source": e["source"], "label": e["label"], "sha256": None, "ok": False}
    if not os.path.isfile(path):
        return dict(out, why="source not on disk")
    out["sha256"] = _sha(path)
    if e["kind"] == "document" and out["sha256"] != e["sha256"]:
        return dict(out, why="SHA-256 differs from the pin")
    return dict(out, ok=True, why="")


def stamp_usable(pid):
    """a premise may enter a certificate when its source checks out and it is `read` (a
    datasheet) or `measured` (a recorded hardware witness, Wilson 11-15)"""
    c = cite(pid)
    return c["ok"] and REGISTRY[pid]["label"].split(" ")[0] in ("read", "measured"), c


def datasheet_part(part):
    """the premise ID a spec's `source datasheet "<part>"` resolves to, or None"""
    return DATASHEETS.get(part)


def problems():
    """[problem] for the gate: every entry well formed; every document's pin a SHA-256"""
    out = []
    for pid, e in REGISTRY.items():
        for f in ("kind", "what", "source", "label"):
            if not e.get(f):
                out.append("%s: no %s" % (pid, f))
        if e.get("kind") == "document" and len(e.get("sha256") or "") != 64:
            out.append("%s: a document premise needs a SHA-256 pin" % pid)
        if e.get("kind") == "repo" and not e.get("symbol"):
            out.append("%s: a repo premise names its symbol" % pid)
    for part, pid in DATASHEETS.items():
        if pid not in REGISTRY:
            out.append("datasheet %r -> %s: not registered" % (part, pid))
    return out
