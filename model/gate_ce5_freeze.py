"""CE5 FREEZE -- every file CE5's simulation reads is byte-for-byte the frozen one.

CE5 (the 1-Wire DS18B20 demo, `test/run_onewire.py`) is a claim about what
the FROZEN chip can do with a program alone. If anything the simulation reads
moved, CE5 is VOID -- the program might be leaning on a change. So:

    git diff --name-only FREEZE_SHA -- <the frozen set>      must print nothing
    git ls-files --others --exclude-standard -- <the set>    (nothing untracked)

⭐ THE FROZEN SET IS EXACTLY WHAT CE5'S SIMULATION READS (Wilson 10-18), taken
from the runner, never a glob: `run_onewire.CE5_SIM_SOURCES` (the files its
build compiles -- the RTL, the bench, the peer model), their `include closure
(resolved from the source text), and the tracked program images it checks its
generated images against (`onewire.TRACKED`).
⛔ IT WAS `src/` UNTIL 10-18, and that is why the hold-fix port (5607b88, a
flow setting in src/config.json, read by no simulation) voided CE5. CE5 was
re-certified under that rule first (06d4e29: 74 of 74 output lines identical),
THEN narrowed here. src/config.json is now covered by model/gate_flow_config.py
(the flow config the timing of record was measured with): src/ holds the three
RTL files, frozen here, and config.json, guarded there -- between the two gates
every file under src/ is checked.

⭐ FREEZE_SHA IS ONE NAMED CONSTANT so it can be re-pinned when this branch is
rebased onto the formally-equivalent "commit 1": change it here and nowhere
else.

⛔ POSITIVE TOKEN ONLY (Wilson's standing rule). The pass needs: git's
version banner printed, FREEZE_SHA resolved to a commit object, both git
commands exiting 0 with EMPTY output, and the planted must-fire seen RED by
NAME. Only then is `CE5-FREEZE: PASSED` printed. A missing freeze commit (a
shallow CI checkout) is fetched once by SHA; if it still cannot be resolved
the gate is RED, never a skip.

MUST-FIRES, on a COPY of the frozen set (and src/config.json) in a temp
directory, checked against FREEZE_SHA through a TEMPORARY index (read from
FREEZE_SHA) and `--work-tree` pointed at the copy -- the real tree and the real
index are never touched:
  * control: the unmodified copy lists nothing;
  * one character changed in a simulated file (src/pe_engine.v) -> listed, RED;
  * src/config.json's hold margin changed -> the freeze stays GREEN (it is not
    simulated) AND model/gate_flow_config.py's audit of that config is RED --
    the two gates together, priced in one place.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
sys.path.insert(0, HERE)


def frozen_set():
    """-> sorted repo-relative paths: run_onewire.CE5_SIM_SOURCES, their
    `include closure, and the tracked CE5 images."""
    import re
    import run_onewire
    import onewire
    inc = re.compile(r'^\s*`include\s+"([^"]+)"', re.M)
    todo, seen = list(run_onewire.CE5_SIM_SOURCES), set()
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        with open(os.path.join(ROOT, p), encoding="utf-8", errors="replace") as fh:
            for m in inc.finditer(fh.read()):
                todo.append(m.group(1))
    seen |= {"test/" + fn for fn in onewire.TRACKED.values()}
    return sorted(seen)

#: the frozen RTL. Re-pinned from ae15d2c to commit 1 (62390e9) on the rebase
#: (Wilson): valid because commit 1's src/ change is declaration-only and
#: formally equivalent to ae15d2c (model/rtl_equiv.py: 4,102/4,102 proven).
#: ⛔ RE-PINNED AGAIN, to b3cf898 (WF2, silicon fixes #8-#11) -- NOT a
#: bookkeeping move: the RTL changed behaviour (the first TX byte, reloads),
#: and CE5's own feed changed with it (the first reset block lost its 2-RST
#: workaround). CE5 was therefore RE-CERTIFIED on this SHA -- the full set,
#: presence, ROM + scratchpad with CRC, per-slot timing windows and every
#: must-fire -- and docs/CE5_LOG.md records the move and why (Wilson).
#: Re-pinned to 5f59d25 on a FORMAL EQUIVALENCE (the rebase precedent): the
#: queue pop became a per-queue vector, and model/rtl_equiv.py proved it
#: against 2b34dc0, 4,466 of 4,466 cells -- the change moves nothing. CE5
#: was re-run on it anyway (docs/CE5_LOG.md).
#: ⛔ RE-PINNED to effe478 (the reset-network adoption) -- RE-CERTIFIED, not an
#: equivalence: the engine leaves reset one cycle later. The full CE5 set
#: passes; 71 of 72 output lines match the previous freeze's run, the 72nd an
#: absolute timestamp moved exactly one cycle (docs/CE5_LOG.md, with the
#: prediction miss recorded).
#: ⛔ RE-PINNED to c95af23 (2026-10-18) -- RE-CERTIFIED under the rule as
#: written: 5607b88 changed src/config.json (the hold-fix port; a flow setting,
#: no .v file). Prediction stamped first: identical output. Result: 74 of 74
#: CE5 output lines byte-identical to the effe478 run, the timestamp included
#: (docs/CE5_LOG.md).
#: ⛔ RE-PINNED to 0fb37a0 (2026-10-21) -- RE-CERTIFIED: the 1-Wire phase-
#: coverage change edited two frozen BENCH files (ds18b20_model.v T_PH_NS,
#: default 0; tb_onewire.v coverage display). No RTL. 0fb37a0 was red on this
#: gate only, by design (the pin cannot name a commit before it exists).
#: Prediction stamped first; the stamped filter MISSED by 2 blank lines (the
#: new arms' own print() separators), a narrow addendum then held: freeze 72
#: lines, current 72, byte-identical, the timestamp included (docs/CE5_LOG.md).
#: The blob-hash pin (step 3) removes the need for a red commit.
FREEZE_SHA = "0fb37a0002ab773d12d992500f927c584e32a1ea"


def git(args, env=None):
    r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, r.stdout, r.stderr


def resolve():
    rc, out, _ = git(["cat-file", "-t", FREEZE_SHA])
    if rc == 0 and out.strip() == "commit":
        return True
    # a shallow checkout (CI) may not hold it: fetch that one commit by SHA
    git(["fetch", "--no-tags", "--depth=1", "origin", FREEZE_SHA])
    rc, out, _ = git(["cat-file", "-t", FREEZE_SHA])
    return rc == 0 and out.strip() == "commit"


def changed(work_tree=None, paths=None):
    """-> (ok_ran, [changed paths]) for the frozen set against FREEZE_SHA."""
    paths = paths if paths is not None else frozen_set()
    env, pre = None, []
    tmp_index = None
    if work_tree is not None:
        fd, tmp_index = tempfile.mkstemp(prefix="ce5_index_")
        os.close(fd)
        os.remove(tmp_index)
        env = dict(os.environ, GIT_INDEX_FILE=tmp_index)
        rc, _o, e = git(["read-tree", FREEZE_SHA], env=env)
        if rc != 0:
            return False, ["<read-tree failed: %s>" % e.strip()[:80]]
        pre = ["--work-tree=" + work_tree]
    try:
        rc1, out1, e1 = git(pre + ["diff", "--name-only", FREEZE_SHA, "--"]
                            + paths, env=env)
        rc2, out2, e2 = git(pre + ["ls-files", "--others",
                                   "--exclude-standard", "--"] + paths, env=env)
    finally:
        if tmp_index and os.path.exists(tmp_index):
            os.remove(tmp_index)
    if rc1 != 0 or rc2 != 0:
        return False, ["<git failed: %s %s>" % (e1.strip()[:60], e2.strip()[:60])]
    names = [l for l in (out1 + out2).splitlines() if l.strip()]
    return True, names


def main() -> int:
    print("=" * 78)
    print("CE5 FREEZE -- what CE5 simulates, against FREEZE_SHA %s" % FREEZE_SHA)
    print("=" * 78)
    rc, ver, _ = git(["--version"])
    print("  %s" % (ver.strip() if rc == 0 else "*** git did not run"))
    if rc != 0:
        print("  *** CE5-FREEZE: FAILED (no git)")
        return 1
    if not resolve():
        print("  *** FREEZE_SHA does not resolve to a commit here (shallow "
              "clone and the fetch failed?) -- RED, not a skip")
        print("  *** CE5-FREEZE: FAILED")
        return 1
    print("  FREEZE_SHA resolves to a commit")
    ok = True
    fs = frozen_set()
    print("  the frozen set (what CE5's simulation reads, from the runner): %d files"
          % len(fs))
    for p in fs:
        print("    %s" % p)
    ran, names = changed(paths=fs)
    if ran and not names:
        print("  real tree: git diff --name-only FREEZE_SHA -- <the set> is EMPTY, "
              "nothing untracked")
    else:
        ok = False
        print("  *** real tree: the frozen set differs from the freeze: %s -- CE5 VOID"
              % names)

    print("  --- must-fires, on a COPY of the frozen set + src/config.json ---")
    tmp = tempfile.mkdtemp(prefix="ce5_freeze_")
    try:
        for p in fs + ["src/config.json"]:
            os.makedirs(os.path.dirname(os.path.join(tmp, p)), exist_ok=True)
            shutil.copy2(os.path.join(ROOT, p), os.path.join(tmp, p))
        ran_c, names_c = changed(tmp, fs)
        if ran_c and not names_c:
            print("    control: the unmodified copy reads clean")
        else:
            ok = False
            print("    *** control: the unmodified copy reads %s" % names_c)
        # (1) a simulated file changed -> RED
        tgt = os.path.join(tmp, "src", "pe_engine.v")
        with open(tgt, "rb") as fh:
            orig = fh.read()
        data = bytearray(orig)
        k = data.index(b"localparam")             # a real token, mid-file
        data[k] = ord("L")
        with open(tgt, "wb") as fh:
            fh.write(bytes(data))
        ran_m, names_m = changed(tmp, fs)
        if ran_m and "src/pe_engine.v" in names_m:
            print("    a simulated file changed (src/pe_engine.v): freeze RED  ok")
        else:
            ok = False
            print("    *** MUST-FIRE FAILED: planted copy reads %s (ran=%s)"
                  % (names_m, ran_m))
        with open(tgt, "wb") as fh:
            fh.write(orig)
        # (2) the flow config changed -> freeze GREEN, gate_flow_config RED
        cfg = os.path.join(tmp, "src", "config.json")
        with open(cfg, encoding="utf-8") as fh:
            ctext = fh.read()
        mut = ctext.replace('"GRT_RESIZER_HOLD_SLACK_MARGIN": 0.10',
                            '"GRT_RESIZER_HOLD_SLACK_MARGIN": 0.05', 1)
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(mut)
        ran_g, names_g = changed(tmp, fs)
        import json
        import gate_flow_config as GFC
        with open(GFC.RECORD, encoding="utf-8") as fh:
            rec = json.load(fh)
        fc_probs, _h = GFC.audit(mut, rec)
        if mut == ctext:
            ok = False
            print("    *** MUST-FIRE FAILED: the config landmark was not found")
        elif ran_g and not names_g and fc_probs:
            print("    src/config.json changed: freeze GREEN and gate_flow_config "
                  "RED  ok -- the two gates cover it together")
        else:
            ok = False
            print("    *** MUST-FIRE FAILED: config edit -> freeze %s, flow-config %s"
                  % (names_g or "green", "red" if fc_probs else "GREEN"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # the real file was never opened for writing; prove it is still clean
    ran2, names2 = changed()
    if not (ran2 and not names2):
        ok = False
        print("  *** after the must-fire the real tree reads %s" % names2)
    print()
    if ok:
        print("  CE5-FREEZE: PASSED")
        return 0
    print("  *** CE5-FREEZE: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
