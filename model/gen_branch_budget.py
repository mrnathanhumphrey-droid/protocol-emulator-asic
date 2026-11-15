"""gen_branch_budget -- the CERTIFIED branch-1 budget B of every branch image, generated.

Wilson 11-14 (option 1): B per image, written by a generator, compared by the gate, checked for
staleness -- like usb_other_R. For every image in the image universe that has a branch lane,
model/branch_budget.image_budget evaluates the per-image certificate; the record keeps the
image's identity (program_a2.image_sha), B (or null: "no finite B" -> A2-UNCERTIFIED with the
reason, not refused) and the reason. A2 reads B from model/branch_budget.json.

Usage: python model/gen_branch_budget.py            (writes)
       python model/gen_branch_budget.py --check    (exit 1 if any entry is stale or missing)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "a2"), os.path.join(os.path.dirname(HERE), "test")]
import branch_budget as BB  # noqa: E402

RECORD = os.path.join(HERE, "branch_budget.json")


def corpus():
    """[(name, image)]: the image universe, plus run_branch_check's own corpus (built in code,
    named run_branch_check:<name>; Wilson 11-14) -- every image a branch J is quoted for"""
    import image_universe as U
    out = list(U.images())
    import run_branch_check as RB
    out += [("run_branch_check:%s" % n, bytes(f())) for n, f in RB.IMAGES.items()]
    return out


def current():
    """{image name: {sha, branch_lanes, B, reason, lanes}} for every branch image, now"""
    import program_a2 as P
    out = {}
    for name, img in corpus():
        bl = P.branch_lanes(img)
        if not bl:
            continue
        r = BB.image_budget(img)
        out[name] = {"sha": P.image_sha(img), "branch_lanes": bl, "B": r["B"],
                     "reason": r["reason"],
                     "lanes": {str(l): {"max_late": v["max_late"], "R": v["R"]}
                               for l, v in r["lanes"].items()}}
    return out


def load():
    with open(RECORD, encoding="utf-8") as fh:
        return json.load(fh)


def stale(rec, cur):
    """[problem] where the record is not today's certificate"""
    out = []
    for name, v in sorted(cur.items()):
        r = rec.get("images", {}).get(name)
        if r is None:
            out.append("%s: no record" % name)
        elif (r.get("sha"), r.get("B"), r.get("reason"), r.get("lanes")) != (
                v["sha"], v["B"], v["reason"], v["lanes"]):
            out.append("%s: recorded B %s (%s), certificate now B %s (%s)"
                       % (name, r.get("B"), r.get("reason"), v["B"], v["reason"]))
    for name in sorted(set(rec.get("images", {})) - set(cur)):
        out.append("%s: recorded but no longer a branch image in the universe" % name)
    return out


def main():
    cur = current()
    if "--check" in sys.argv:
        probs = stale(load(), cur)
        for p in probs:
            print("STALE", p)
        print("branch budget record %s" % ("current" if not probs else "STALE"))
        return 1 if probs else 0
    rec = {"_doc": "CERTIFIED branch-1 budget B per branch image (Wilson 11-14, option 1): "
                   "written by model/gen_branch_budget.py from model/branch_budget.py; "
                   "gate_lane_cert checks it is current. B null = no finite B: A2-UNCERTIFIED "
                   "with the reason, not refused.",
           "images": cur}
    with open(RECORD, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    for name, v in sorted(cur.items()):
        print("%-28s lanes %-10s B = %-5s %s" % (name, ",".join(map(str, v["branch_lanes"])),
              v["B"] if v["B"] is not None else "-", v["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
