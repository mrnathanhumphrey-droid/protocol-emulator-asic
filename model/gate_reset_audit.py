"""RESET FULL-CLEAR AUDIT -- Wilson's amendment A1, before any cycle-exact compare.

THE ONE CLAIM: every flop in the design either has reset in its reset path, or
is on an allowlist with a stated write-before-read reason -- so a two-simulator
disagreement cannot be an artefact of initial state.

⛔⛔ WHY THIS COMES FIRST. iverilog starts a flop at X; Verilator starts it at 0
or at a random pattern depending on `--x-initial`. If ANY flop is read before it
is written, the two simulators will disagree, and the disagreement will look
exactly like a design bug in whichever signal happens to propagate it first.
A2's cycle-exact arm would then spend its first run chasing an initialisation
artefact. ⭐ This is the `rst_fullclear_audit` lesson carried over: the audit is
cheaper than the false lead it prevents.

⛔ AND IT IS AN ALLOWLIST, NOT A COUNT. "39 unreset flops, all fine" is an
assertion; naming each group with the reason it is safe is a check, and a NEW
unreset flop then fails instead of being absorbed into a total that still
looks about right.

HOW THE FLOPS ARE CLASSIFIED: from the yosys JSON netlist, by cell type.
Generic reset-bearing cells carry the reset polarity in their name
(`$_DFF_PN0_`, `$_DFFE_PN0P_`, ...); `$_DFFE_PP_` has no reset port at all.
⚠ That is a STRUCTURAL reading of the synthesised netlist, not of the source --
which is the point: a flop whose reset the RTL assigns but synthesis optimises
into the data path would still show here as reset-bearing or not, as built.
"""

from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NETLIST = os.environ.get("PE_NETLIST_JSON", r"C:\tmp\local_netlist.json")

# ---------------------------------------------------------------------------
# THE ALLOWLIST. (signal prefix, expected bits or None, why it is safe unreset)
# ⛔ Anything unreset and NOT here is a finding.
# ---------------------------------------------------------------------------
ALLOWED = {
    "u_store.mem": (
        2048,
        "THE STORE. Explicitly loaded before `run` is asserted -- the loader "
        "walks every byte and `hdr_done` gates dispatch until the headers are "
        "in. ⭐ And it is left X rather than zeroed ON PURPOSE: a zero-filled "
        "store makes a read of an unwritten address return a plausible 0, so a "
        "program that reads past its end looks correct. The image loader "
        "asserts its own length for the same reason."),
    "s_wrdata": (
        22,
        "the store's WIDE action read. Written by the store on a read and "
        "captured at P_CAP, which only runs after a real P_REQ -- so it is "
        "write-before-read. ⛔ If that ordering ever broke, an X action word "
        "would reach `l_act`, and the engine has already shown what that costs: "
        "`l_timestamp + a_dly` with a_dly X made a lane PERMANENTLY unready."),
    "s_rdata": (
        8,
        "the store's BYTE read, for the header FSM AND for the load-mode "
        "serial readback. H_CAP only runs after H_REQ, and the readback now "
        "PRIMES -- its first two visits issue the read and let it land without "
        "queueing a frame -- so both consumers read it only after a real read. "
        "⛔⛔ THIS REASON WAS FALSE UNTIL D1 WAS FIXED, and the "
        "entry named only the header FSM. The load-mode readback also consumed "
        "s_rdata, and there the H_REQ ordering said nothing: the first frame "
        "carried the register unwritten, which put X on uo_out[4] on a cold "
        "part and a stale byte after a rewind. An allowlist entry is only as "
        "good as the set of consumers it names, and a second consumer added "
        "later inherits a reason that was never about it."),
    "u_eng.paddr": (
        8,
        "the refill address, LATCHED AT THE SCAN and consumed at P_REQ. It is "
        "latched precisely so a writeback cannot move it between the request "
        "and the capture -- see the arbiter comment -- so it is always written "
        "in the cycle before it is read."),
    "u_eng.pslot": (
        1,
        "the refill's target slot, latched with `paddr` in the same cycle and "
        "for the same reason."),
}


def main() -> int:
    if not os.path.isfile(NETLIST):
        print("  *** netlist JSON not found: %s" % NETLIST)
        print("  Produce it first:")
        print("    MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash "
              "/mnt/d/ProtocolEmulator/test/local_netlist.sh")
        print("  ⛔ RED rather than skipped: an audit that cannot see the design")
        print("     has not audited it.")
        return 1

    with open(NETLIST, encoding="utf-8") as fh:
        d = json.load(fh)
    top = "tt_um_protocol_emulator"
    if top not in d.get("modules", {}):
        print("  *** %s absent from the netlist" % top)
        return 1
    m = d["modules"][top]

    bit2name = {}
    for nm, info in m["netnames"].items():
        for b in info["bits"]:
            if isinstance(b, int):
                bit2name.setdefault(b, nm)

    FF = ("$_dff", "$_sdff", "$_dffe", "$_aldff")
    by_type = collections.Counter()
    unreset = collections.Counter()
    for _n, c in m["cells"].items():
        t = c["type"]
        if not t.lower().startswith(FF):
            continue
        by_type[t] += 1
        # a reset-bearing generic cell names its reset polarity
        has_rst = any(k in t for k in ("N0", "N1", "P0", "P1"))
        if has_rst:
            continue
        pd = c.get("port_directions", {})
        for port, bits in c["connections"].items():
            if pd.get(port) == "output":
                for b in bits:
                    nm = bit2name.get(b, "<unnamed>")
                    # ⛔ GROUP BY BASE NAME. A memory appears in the netlist as
                    # 256 separate netnames (`u_store.mem[0]`, `[1]`, ...), so
                    # keying on the raw name turned ONE allowlisted group into
                    # 256 unlisted ones and the gate reported 256 findings
                    # about a signal it had an entry for. A per-bit view of an
                    # array is not 256 signals.
                    unreset[nm.split("[")[0]] += 1

    total = sum(by_type.values())
    n_unreset = sum(unreset.values())
    print()
    print("=" * 78)
    print("RESET FULL-CLEAR AUDIT (A1)")
    print("=" * 78)
    print("  netlist: %s" % NETLIST)
    print("  flop cells by type:")
    for t, n in by_type.most_common():
        rst = any(k in t for k in ("N0", "N1", "P0", "P1"))
        print("    %-20s %5d  %s" % (t, n, "reset" if rst else "NO RESET"))
    print()
    print("  total flops     : %d" % total)
    print("  with reset      : %d" % (total - n_unreset))
    print("  WITHOUT reset   : %d" % n_unreset)

    print()
    print("  --- unreset flops, against the allowlist ---")
    bad, drift = [], []
    for nm, n in sorted(unreset.items(), key=lambda kv: -kv[1]):
        if nm in ALLOWED:
            want, why = ALLOWED[nm]
            flag = ""
            if want is not None and n != want:
                flag = "*** %d expected %d" % (n, want)
                drift.append((nm, want, n))
            print("    %-24s %5d  ALLOWED %s" % (nm, n, flag))
            for line in _wrap(why, 64):
                print("        %s" % line)
        else:
            bad.append((nm, n))
            print("    %-24s %5d  *** NOT ON THE ALLOWLIST" % (nm, n))

    rc = 0
    print()
    if bad:
        print("  ⛔⛔ %d UNRESET SIGNAL GROUP(S) ARE NOT ALLOWLISTED: %s"
              % (len(bad), ", ".join(n for n, _ in bad)))
        print("      Each needs reset in its reset path, or an entry here")
        print("      stating WHY it is written before it is read. Until then a")
        print("      two-simulator disagreement cannot be told apart from an")
        print("      initialisation artefact -- iverilog starts a flop at X,")
        print("      Verilator at 0 or random.")
        rc = 1
    if drift:
        print("  ⛔ %d allowlisted group(s) changed WIDTH: %s"
              % (len(drift), drift))
        print("      A group that grew has new bits nobody classified.")
        rc = 1
    if not bad and not drift:
        print("  ⭐ every unreset flop is allowlisted with a stated")
        print("     write-before-read reason, and none changed width.")
        print("     ⇒ the cycle-exact two-simulator comparison can begin")
        print("       without its first disagreement being an init artefact.")

    # ---- the Verilator setting A1 asks to be RECORDED ------------------
    print()
    print("  --- Verilator initial-state setting, RECORDED (A1) ---")
    print("    COMPILE: --x-initial unique")
    print("    RUNTIME: +verilator+rand+reset+2  +verilator+seed+<n>")
    print("    ⛔⛔ BOTH, AND THIS ENTRY ONCE NAMED ONLY THE FIRST. The compile")
    print("    flag emits the randomisation hooks and nothing more; the runtime")
    print("    reset mode still defaults to ALL-ZEROS, so a seed sweep built on")
    print("    `--x-initial unique` alone compares three runs that were all")
    print("    zero-initialised and reports agreement. Measured: a 32-bit")
    print("    never-written reg read 00000000 under every seed; with")
    print("    +verilator+rand+reset+2 it read fffffffc / fffffff0 / ffff9f8c.")
    print("    ⭐ The sweep now ASSERTS that precondition on such a reg before")
    print("    comparing anything -- see test/verilator_trace.sh.")
    print("    ⛔ NOT `--x-initial 0`. Zero-init makes an unreset flop read as")
    print("    a plausible 0, which is exactly the failure the allowlist above")
    print("    exists to prevent -- and it would make Verilator DISAGREE with")
    print("    iverilog (X) on any flop the allowlist got wrong, while looking")
    print("    like the more sensible setting.")
    print("    ⭐ `unique` randomises per-flop, so a read-before-write shows up")
    print("    as a NON-DETERMINISTIC result across seeds rather than a stable")
    print("    wrong answer. A stable wrong answer is the one that ships.")
    print("    ⚠ The seed must be recorded with any result, or a passing run is")
    print("    not reproducible.")

    print()
    print("=" * 78)
    print("  GATE reset-audit: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * %d flops, %d unreset across %d group(s); %d allowlisted, "
          "%d not" % (total, n_unreset, len(unreset),
                      len(unreset) - len(bad), len(bad)))
    print("    * ⛔ structural: read from the SYNTHESISED netlist, so a reset")
    print("      the RTL writes but synthesis folds away still shows as built")
    return rc


def _wrap(t, w):
    out, cur = [], ""
    for x in str(t).split():
        if cur and len(cur) + 1 + len(x) > w:
            out.append(cur)
            cur = x
        else:
            cur = (cur + " " + x) if cur else x
    if cur:
        out.append(cur)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
