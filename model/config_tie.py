"""CONFIG TIE -- a gate's EXPECTATION records the configuration it was established under
(Wilson 11-15, the select-copies ruling, item 1).

⛔⛔ WHY. gate_select_copies measures live on every run, but its pass condition (merged = 0)
was ESTABLISHED on SYNTH_STRATEGY "DELAY 4". The configuration of record moved to "AREA 0"
(9c0df0c, 11-14) and nothing said the expectation now stood on a configuration it was never
measured on -- it simply went red in CI, and the red read like a regression rather than a
question. A gate whose expectation depends on the flow configuration declares
ESTABLISHED_UNDER = {key: value} (keys of src/config.json); when the configuration of record
differs on any of them the gate reads STALE -- red, never a pass -- until the expectation is
re-measured on the configuration of record and the tie updated in the same change.

    tie_problems(established, config=None) -> [problem]   (empty: the tie holds)

Must-fires (self_test): a differing key is STALE; a key the configuration no longer carries is
STALE; the matching configuration is not; an empty tie is refused (a tie must name its keys).
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(ROOT, "src", "config.json")


def config_of_record(path=CONFIG):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def tie_problems(established, config=None):
    """[problem] -- STALE lines for every key whose value moved; refuses an empty tie."""
    if not established:
        return ["config tie is EMPTY: a tied gate must name the configuration keys it was "
                "established under"]
    cfg = config_of_record() if config is None else config
    out = []
    for k, v in sorted(established.items()):
        if k not in cfg:
            out.append("STALE: established under %s = %r; the configuration of record no "
                       "longer carries %s -- re-measure" % (k, v, k))
        elif cfg[k] != v:
            out.append("STALE: established under %s = %r; the configuration of record has "
                       "%r -- re-measure on it and update the tie" % (k, v, cfg[k]))
    return out


def self_test():
    """[(label, ok)] -- the judge rejects what it claims to."""
    cfg = {"SYNTH_STRATEGY": "AREA 0", "PL_TARGET_DENSITY_PCT": 60}
    return [
        ("a differing key is STALE", bool(tie_problems({"SYNTH_STRATEGY": "DELAY 4"}, cfg))),
        ("a key no longer carried is STALE", bool(tie_problems({"GONE_KEY": 1}, cfg))),
        ("the matching configuration holds", not tie_problems({"SYNTH_STRATEGY": "AREA 0"}, cfg)),
        ("an empty tie is refused", bool(tie_problems({}, cfg))),
    ]


if __name__ == "__main__":
    ok = all(v for _l, v in self_test())
    for label, v in self_test():
        print("  must-fire %-36s %s" % (label, "ok" if v else "*** MISSED"))
    raise SystemExit(0 if ok else 1)
