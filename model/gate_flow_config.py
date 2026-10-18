"""THE LOCK'S FLOW CONFIG IS THE ONE THE TIMING OF RECORD WAS MEASURED WITH.

⛔⛔ WHY (Wilson, 10-17). The 10-14 hold fix -- GRT_RESIZER_HOLD_SLACK_MARGIN
0.10 and RUN_POST_GRT_RESIZER_TIMING 1 -- lived only on the canary branch where
the timing of record was measured (canary-rst 04253a2 and its 57 / 63 % twins).
The lock branch kept margin 0.05 and no post-GRT resizer step for three days,
and nothing noticed: a harden of record taken from it would not have reproduced
the published timing. Found by hand while building the 60 MHz study base.
⇒ This gate makes the drift impossible to miss: `model/timing_of_record.json`
  records, BESIDE THE PUBLISHED TIMING, the SHA-256 of the hardening config it
  was measured with; the gate recomputes that hash from `src/config.json` and is
  red on any difference.

THE HASH: every non-comment key of src/config.json (keys "//" are comments and
excluded), PL_TARGET_DENSITY_PCT excluded -- the three layouts of record differ
only there, so it is recorded separately and checked against the ship density
-- serialised as canonical JSON (sorted keys, no whitespace) and hashed.
CHECKED FIELDS beside the hash (Wilson 10-18, closing the scope gap):
  * info.yaml `tiles` == the record's (the die size the timing was measured on)
  * every `TinyTapeout/tt-gds-action...@<ref>` in .github/workflows/gds.yaml ==
    the record's `ci_harden_action` -- a COMMIT SHA since the pin, not a branch
  * every `tools-ref:` in gds.yaml == the record's `ci_tools_ref`, which must
    equal `tools_of_record.tt_support_tools` (d66cf17: the tt-support-tools the
    timing of record was measured with), and it is set on BOTH steps that
    accept it (the main action and precheck).
⚠ LIMIT, STATED (what is left after the pin): LibreLane and the PDK are fixed
BY tt-support-tools d66cf17 and the action SHA (their own pins), not re-read
here -- the gate trusts two commit SHAs to name fixed content. gl_test and
viewer take no tools input; their tooling is fixed by the action SHA alone.

LOCAL CROSS-CHECK (informative, NOT counted toward the pass): when the record's
source commit exists locally, its config is hashed too and must equal the
record. CI's checkout does not carry the canary branch, so there it is skipped
and SAYS SO -- an absent check is never a pass.
MUST-FIRES: the hold margin back to 0.05; the post-GRT step dropped; a key
added; a comment-only edit (must stay GREEN); the density changed.
POSITIVE TOKEN: `GATE flow-config: PASSED`.
"""
from __future__ import annotations

import copy
import hashlib
import json
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
CONFIG = os.path.join(ROOT, "src", "config.json")
RECORD = os.path.join(HERE, "timing_of_record.json")
INFO = os.path.join(ROOT, "info.yaml")
GDS = os.path.join(ROOT, ".github", "workflows", "gds.yaml")
DENSITY = "PL_TARGET_DENSITY_PCT"


def tiles_of(info_text):
    """info.yaml's `tiles:` value, or None."""
    import re
    m = re.search(r'^\s*tiles:\s*"?([^"\s#]+)"?', info_text, re.M)
    return m.group(1) if m else None


def action_refs(gds_text):
    """Every tt-gds-action `uses:` in the GDS workflow -> its @ref."""
    import re
    return re.findall(r"uses:\s*TinyTapeout/tt-gds-action[^@\s]*@(\S+)", gds_text)


def env_audit(info_text, gds_text, rec):
    import re
    probs = []
    t = tiles_of(info_text)
    if t != rec["tiles"]:
        probs.append("info.yaml tiles is %r; the timing of record was measured on "
                     "%r" % (t, rec["tiles"]))
    want = rec["ci_harden_action"].split("@", 1)[1]
    refs = action_refs(gds_text)
    if not refs:
        probs.append("no tt-gds-action step found in .github/workflows/gds.yaml")
    for r in refs:
        if r != want:
            probs.append("gds.yaml uses tt-gds-action@%s; the record names @%s"
                         % (r, want))
    if not re.fullmatch(r"[0-9a-f]{40}", want):
        probs.append("the recorded action ref %r is not a commit SHA" % want)
    tr = re.findall(r"^\s*tools-ref:\s*(\S+)", gds_text, re.M)
    if rec.get("ci_tools_ref") != rec["tools_of_record"]["tt_support_tools"]:
        probs.append("the record's ci_tools_ref %r is not the tools of record %r"
                     % (rec.get("ci_tools_ref"), rec["tools_of_record"]["tt_support_tools"]))
    if len(tr) != 2:
        probs.append("gds.yaml sets tools-ref on %d step(s); the main action and "
                     "precheck both accept it -- expected 2" % len(tr))
    for t in tr:
        if t != rec.get("ci_tools_ref"):
            probs.append("gds.yaml tools-ref %s; the timing of record used %s"
                         % (t, rec.get("ci_tools_ref")))
    return probs


def load_pairs(text):
    """Every (key, value) pair in order -- json.loads would keep only the
    LAST "//" comment, and duplicate real keys must not hide either."""
    return json.loads(text, object_pairs_hook=lambda kv: kv)


def flow_keys(text):
    pairs = load_pairs(text)
    out = {}
    for k, v in pairs:
        if k == "//":
            continue
        if k in out:
            raise ValueError("src/config.json sets %s twice" % k)
        out[k] = v
    return out


def flow_hash(keys):
    body = {k: v for k, v in keys.items() if k != DENSITY}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def audit(cfg_text, rec):
    probs = []
    try:
        keys = flow_keys(cfg_text)
    except ValueError as e:
        return [str(e)], None
    h = flow_hash(keys)
    if h != rec["flow_config_sha256"]:
        probs.append("src/config.json's hardening keys hash to %s..., the timing "
                     "of record was measured with %s... -- the lock would not "
                     "harden what was measured" % (h[:12], rec["flow_config_sha256"][:12]))
        want = rec["flow_keys"]
        for k in sorted(set(keys) | set(want)):
            if k == DENSITY:
                continue
            if keys.get(k, "<absent>") != want.get(k, "<absent>"):
                probs.append("  %s: tree %r, record %r" % (
                    k, keys.get(k, "<absent>"), want.get(k, "<absent>")))
    if keys.get(DENSITY) != rec["ship_density_pct"]:
        probs.append("%s is %r; the ship density of record is %r"
                     % (DENSITY, keys.get(DENSITY), rec["ship_density_pct"]))
    return probs, h


def main() -> int:
    print("=" * 78)
    print("FLOW CONFIG -- the lock hardens with the config the timing of record used")
    print("=" * 78)
    with open(RECORD, encoding="utf-8") as fh:
        rec = json.load(fh)
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = fh.read()
    print("  record: measured on %s; ship density %d %%; flow config sha256 %s"
          % (", ".join(rec["measured_on"]), rec["ship_density_pct"],
             rec["flow_config_sha256"]))
    for row in rec["timing"]:
        print("    %-24s slow setup %+.2f ns, worst hold %+.3f ns"
              % (row["layout"], row["slow_setup_ns"], row["worst_hold_ns"]))
    probs, h = audit(cfg, rec)
    print("  tree:   src/config.json hardening keys sha256 %s" % h)
    with open(INFO, encoding="utf-8") as fh:
        info = fh.read()
    with open(GDS, encoding="utf-8") as fh:
        gds = fh.read()
    print("  tiles:  info.yaml %s (record %s)" % (tiles_of(info), rec["tiles"]))
    print("  CI harden action refs: %s (record %s)"
          % (sorted(set(action_refs(gds))), rec["ci_harden_action"]))
    t = rec["tools_of_record"]
    print("  tools of record (local C1 flow): tt-support-tools %s, LibreLane %s, "
          "PDK %s" % (t["tt_support_tools"], t["librelane"], t["ihp_open_pdk"][:12]))
    print("  CI tools-ref: %s (record %s)" % (
        sorted(set(re.findall(r"^\s*tools-ref:\s*(\S+)", gds, re.M))),
        rec.get("ci_tools_ref")))
    print("  ⚠ LIMIT: LibreLane and the PDK are fixed by tt-support-tools %s and the "
          "action SHA, not re-read here" % rec.get("ci_tools_ref"))
    probs += env_audit(info, gds, rec)
    for p in probs:
        print("  *** %s" % p)
    if not probs:
        print("  the tree's flow config is the one the timing of record was measured with")

    # informative cross-check against the record's own source commit
    src = rec["source_commit"]
    r = subprocess.run(["git", "show", "%s:src/config.json" % src], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode == 0:
        hs = flow_hash(flow_keys(r.stdout))
        print("  cross-check (informative): %s's config hashes to %s -- %s"
              % (src, hs[:12], "matches the record" if hs == rec["flow_config_sha256"]
                 else "*** DIFFERS from the record"))
        if hs != rec["flow_config_sha256"]:
            probs.append("the record's source commit %s does not hash to the record" % src)
    else:
        print("  cross-check SKIPPED: %s is not in this checkout (CI carries no "
              "canary branch) -- informative only, not counted" % src)

    print("  --- must-fire ---")
    rc = 1 if probs else 0

    def mutate(fn):
        d = copy.deepcopy(load_pairs(cfg))
        return json.dumps(fn(d), indent=1)

    def setk(k, v):
        return lambda d: [(kk, v if kk == k else vv) for kk, vv in d]

    cases = [
        ("hold margin back to 0.05", setk("GRT_RESIZER_HOLD_SLACK_MARGIN", 0.05), True),
        ("post-GRT resizer dropped",
         lambda d: [(k, v) for k, v in d if k != "RUN_POST_GRT_RESIZER_TIMING"], True),
        ("a key added", lambda d: d + [("PL_TIME_DRIVEN", 0)], True),
        ("density changed to 63", setk(DENSITY, 63), True),
        ("comment-only edit (must stay GREEN)",
         lambda d: d + [("//", "a new comment")], False),
    ]
    for label, fn, want_red in cases:
        ps, _h = audit(mutate(fn), rec)
        ok = bool(ps) == want_red
        print("    %-38s %s" % (label, ("red  ok" if want_red else "green ok") if ok
                                 else "*** WRONG (%s)" % ("green" if not ps else "red")))
        rc |= 0 if ok else 1
    # the checked fields (Wilson 10-18): tile size, the action SHA, tools-ref
    sha = rec["ci_harden_action"].split("@", 1)[1]
    env_cases = [
        ("tile size changed to 8x2",
         re.sub(r'(tiles:\s*)"[^"]*"', r'\1"8x2"', info, count=1), gds),
        ("CI action back to the branch ref",
         info, gds.replace("tt-gds-action@" + sha, "tt-gds-action@ihp-cmos5l", 1)),
        ("tools-ref changed",
         info, re.sub(r"(tools-ref:\s*)\S+", r"\g<1>main", gds, count=1)),
        ("tools-ref dropped from one step",
         info, re.sub(r"\n\s*tools-ref:\s*\S+", "", gds, count=1)),
    ]
    for label, inf, gd in env_cases:
        ps = env_audit(inf, gd, rec)
        print("    %-38s %s" % (label, "red  ok" if ps else "*** NOT RED"))
        rc |= 0 if ps else 1
    print()
    print("  GATE flow-config: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
