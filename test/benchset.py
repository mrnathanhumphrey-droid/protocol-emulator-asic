"""THE BENCH SET -- one declaration of how every Verilog bench is built and run.

⛔⛔ WHY THIS EXISTS. The coverage sweep has to build and run every bench, and
the invocations were scattered across eight scripts (`run_csat.py`,
`run_dstar_check.py`, `run_rxbw.py`, `run_i2c.py`, `clean_room.py`,
`gate_corpus_trace.py`, `price_j_sweep.sh`, the cocotb Makefile). A sweep that
re-typed them would be a NINTH copy, and the lesson already paid for here is
that two lists drift -- "all 8 CI gates green" was reported from a loop pasted
in two places while CI went red.

⇒ So the sweep reads THIS, and this file is guarded against drift in the only
way that holds: it ENUMERATES `test/tb*.v` from disk and refuses to run if a
bench exists that nobody has classified. A bench may be IN the sweep or
EXCLUDED WITH A REASON; it may not be silently absent. ⛔ That is Wilson's
ruling 3 applied to the bench set itself -- "must-fires over small parameter
spaces enumerate; they don't use hand-picked lists."

⚠ WHAT A CONFIG HERE IS AND IS NOT. It is the arm set the COVERAGE sweep runs,
chosen to execute as much RTL as the tracked artefacts allow. It is NOT the
gate's own arm set: `run_csat.py` sweeps four release vectors and
`gate_corpus_trace.py` three phases because their CLAIMS need that, and those
claims stay with those gates. Coverage asks only "did this line ever execute",
so one representative arm per distinct path is the right shape -- and anything
still uncovered becomes a waiver with a written reason, not a silent zero.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ENGINE = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]

# ---------------------------------------------------------------------------
# EXCLUSIONS, each with the reason it is not a self-checking Verilog bench.
# ⛔ An exclusion is a DECLARATION, checked below against what is on disk.
# ---------------------------------------------------------------------------
EXCLUDED = {
    "tb.v": (
        "THE COCOTB TOPLEVEL. It has no self-checking `initial` block at all -- "
        "`test/test.py` drives it from Python, so there is no PASS line for a "
        "Verilator `--binary` run to read. ⭐ Its coverage is not lost: the "
        "cocotb suite exercises `project.v` and `pe_engine.v` through the same "
        "ports, and the RTL coverage of those paths is attributed to the "
        "benches that do self-check. ⚠ What IS unmeasured here is `tb.v`'s own "
        "two lines and the cocotb-only host pacing."),
}

# ---------------------------------------------------------------------------
# THE ARMS. (label, extra plusargs) per bench. `$IMG` entries get their
# `+NBYTES` computed from the file, because an image that never loaded emits
# nothing and "no bytes" reads as a queue fault rather than a missing file.
# ---------------------------------------------------------------------------
#: benches whose `+NBYTES` must be supplied (they refuse to start without it)
NEEDS_NBYTES = {"tb_tx", "tb_half", "tb_i2c", "tb_csat", "tb_jlane",
                "tb_rxbw", "tb_trace", "tb_witness"}

CONFIG = {
    # ⭐⭐ THE SPL = 1 ARM IS HERE BECAUSE COVERAGE ASKED FOR IT. The sweep's
    # first run left `pe_engine.v:867 else if (SPL == 1)` and the two
    # `if (SPL > 1)` slot-flip arms (1580, 1588) at ZERO -- not because nothing
    # tests the single-buffer engine, but because the sweep only ever BUILT
    # SPL = 2. `run_param_points.py` has been running both depths all along;
    # the measurement simply could not see it.
    # ⛔ ONLY `tb_smoke` TAKES THIS ARM, and the reason is in
    # `run_param_points.py`'s own expectation map: `tb_edge` at SPL = 1 FAILS
    # must-fire 5b by design (a programmed delay shorter than the refill
    # latency does not reach the pin at single-buffer depth). That is a
    # recorded design consequence, so an SPL = 1 arm there would be an
    # expected-fail arm, and the per-bench SPL matrix stays with the sweep that
    # already declares those expectations.
    # ⛔⛔ THE PLUSARGS ARE THE BENCH'S OWN DEFAULTS, SPELLED OUT, AND THE
    # FIRST DRAFT INVENTED `+NCYC=200000` INSTEAD -- which CLOBBERED the
    # tracked `test/cj_measured.txt`. `tb_smoke` writes that artefact to a
    # hardcoded path whenever the image and depth are canonical, and the
    # pinned numbers were measured at the DEFAULT budget: jobs came back
    # 344 -> 17642, cycles 4000 -> 200000. ⇒ Reuse the certified invocation,
    # do not improvise one. The values are written out rather than left to
    # defaults so the drift guard can see them and so a change to a default
    # cannot silently change what the sweep measured.
    "tb_smoke": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/smoke_image.hex", "+NCYC=4000",
                              "+WARMUP=200"]),
                 ("spl1", ["+IMG=test/smoke_image.hex", "+NCYC=4000",
                           "+WARMUP=200"], {"SPL_CFG": 1})],
    },
    # ⛔ ONE ARM, AND THE OTHER TWO IMAGES ARE NOT MISSING FROM IT. `tb_edge`
    # `$readmemh`s `edge_image_noto.hex` and `edge_image_rise.hex` ITSELF, at
    # lines 236 and 291, reloading the store mid-run for must-fires 2 and 4.
    # ⚠ The sweep's first draft gave each image its own arm, and the rise arm
    # FAILED must-fire 1 -- correctly: that program produces no output edge
    # after the peer edge, so the claim "`t_out - t_edge` is phase-invariant"
    # has nothing to measure. Feeding a bench an image it loads for itself
    # measures a run nobody certifies, and reports the mismatch as a defect.
    "tb_edge": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/edge_image.hex"])],
    },
    # ⛔ THE BADCLK ARM IS NOT OPTIONAL. `tx_badclk_image.hex` is the program
    # that aliases a SHIFT lane's clock pin onto its data pin, and the refusal
    # path (`config_err` sticky + lane halt) exists ONLY for it. Without this
    # arm the entire 1.6s silicon backstop reads as uncovered.
    "tb_tx": {
        "srcs": [],
        "arms": [("clean", ["+IMG=test/tx_image.hex", "+NCYC=6000"]),
                 ("badclk", ["+IMG=test/tx_badclk_image.hex", "+NCYC=6000",
                             "+BADCLK=1"])],
    },
    "tb_half": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/half_image.hex", "+NCYC=40000"])],
    },
    "tb_i2c": {
        "srcs": ["test/fram_i2c.v"],
        # ⛔ THE DUMP GOES TO A SCRATCH NAME. `probe_*` is gitignored by rule,
        # and a sweep that wrote a tracked artefact would be the clobber this
        # project has already shipped once (`rxfast_image.hex` left at the
        # swept `d` under a manifest entry for a different one).
        # ⭐ `+DIAG=0` IS DECLARED RATHER THAN DEFAULTED, and the drift guard
        # below is what asked for it: `run_i2c.py` supplies no `+DIAG` either,
        # so the certified run takes the bench's own default. Writing the value
        # down means a change to that default cannot silently change what the
        # sweep measured.
        "arms": [("default", ["+IMG=test/i2cframe_image.hex", "+NCYC=40000",
                              "+DIAG=0", "+DUMP=probe_cov_i2c.bin"])],
    },
    "tb_witness": {
        "srcs": [],
        "arms": [("five", ["+IMG=test/five_image.hex", "+NCYC=200000",
                           "+WARMUP=4000"]),
                 ("stress", ["+IMG=test/stress_image.hex", "+NCYC=200000",
                             "+WARMUP=4000"])],
    },
    # ⛔⛔ THESE TWO NEED A PURPOSE-BUILT PROGRAM, and the sweep's first draft
    # fed them `five_image.hex` instead. `tb_jlane` then reported "complete
    # intervals: 6 (need >= 100)" and `tb_csat` could not measure a floor:
    # both benches need SIMULTANEOUS RELEASE at a port-feasible period, which
    # is the shape `run_csat.py`'s arm S builds. ⇒ The sweep builds the image
    # with THE SAME BUILDER those gates call (`make_smoke_image.py --five`)
    # rather than carrying a second recipe, and writes it to a `probe_*` name.
    "tb_csat": {
        "srcs": [],
        "gen": ["--five", "40", "40", "40", "40", "40", "probe_cov_sim40"],
        "arms": [("sim40", ["+IMG=test/probe_cov_sim40.hex", "+NCYC=200000",
                            "+WARMUP=4000"])],
    },
    # ⚠ AND `tb_jlane` WANTS THE OPPOSITE SHAPE TO `tb_csat`, which is why it
    # has its own image rather than sharing one. `run_dstar_check.py` builds
    # its arms as `[d, d+1, d+2, d+3, d+4]` -- DISTINCT per-lane periods at or
    # above `D* = 20`. Handed the simultaneous-release image it reported
    # "complete intervals: 0", so a shared image is not a saving here.
    "tb_jlane": {
        "srcs": [],
        "gen": ["--five", "20", "21", "22", "23", "24", "probe_cov_ds20"],
        "arms": [("lane0", ["+IMG=test/probe_cov_ds20.hex", "+LANE=0",
                            "+NCYC=200000", "+WARMUP=20000"])],
    },
    "tb_rxbw": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/rxfast_image.hex", "+NCYC=200000"])],
    },
    # ⭐⭐ THE PEER MODELS ARE COVERED HERE, AND THAT IS THE POINT WILSON MADE:
    # the I2C peer's address-match branch had never fired, and coverage would
    # have shown it as a zero. The arms are ENUMERATED FROM `corpus.CORPUS`
    # rather than listed, so a sixth corpus program joins the sweep by being
    # added to the corpus.
    "tb_trace": {
        "srcs": ["test/fram_i2c.v", "test/fram_spi.v"],
        "arms": "FROM_CORPUS",
    },
}


def image_bytes(rel: str):
    """Token count of a hex image, or None if it is not on disk."""
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="ascii", errors="replace") as fh:
        return len([w for w in fh.read().split() if w])


def corpus_arms():
    """tb_trace's arms, enumerated from the corpus rather than listed."""
    sys.path.insert(0, HERE)
    try:
        import corpus
    except Exception as exc:                      # pragma: no cover
        return None, "corpus.py did not import: %s" % exc
    out = []
    for name, (_builder, peer) in sorted(corpus.CORPUS.items()):
        out.append((name, ["+IMG=test/%s.hex" % name, "+PEER=%s" % peer,
                           "+OUT=probe_cov_trace_%s.txt" % name,
                           "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                           "+STAYLOAD=0", "+SCLHOLD=0"]))
    # ⭐ THE TWO CLOCK-STRETCH ARMS, both of which `gate_corpus_trace.py`
    # already certifies: `+SCLHOLD` is a BENCH-DRIVEN hold on SCL (its line
    # 365), and the PEER-driven stretch is a second instance,
    # `fram_i2c #(.STRETCH(12)) u_i2cs`, selected by `+PEER=i2cs`. They are
    # different mechanisms and the first draft here conflated them.
    #
    # ⛔⛔ AND NEITHER ARM COVERS `fram_i2c.v:235`, WHICH IS THE FINDING. I
    # added them expecting the uncovered `if (STRETCH != 0)` to go green and it
    # did not move -- 37 points before, 37 after. The reason is worth more than
    # the arms: line 235 sits at the end of the `byte_done` block, so it needs
    # a COHERENT BYTE clocked into the stretching instance, and no program ever
    # delivers one. `i2cframe_image.hex` is the only program that produces
    # coherent I2C bytes and it runs in `tb_i2c` against the NON-stretching
    # peer; the corpus I2C program drives the bus but never assembles a byte
    # the peer accepts. ⇒ The stretching peer has never had a byte clocked into
    # it at all, and that is an owed test, not a measurement gap.
    # ⚠ The arms stay because they are certified arms that do execute the
    # bench-side stretch path -- but they are NOT the fix for 235, and saying
    # so here is the point: an arm added in the expectation of covering
    # something must be checked against whether it did.
    out.append(("corpus_i2c_sclhold",
                ["+IMG=test/corpus_i2c.hex", "+PEER=i2c",
                 "+OUT=probe_cov_trace_i2c_sclhold.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=200"]))
    out.append(("corpus_i2cs_stretch",
                ["+IMG=test/corpus_i2c.hex", "+PEER=i2cs",
                 "+OUT=probe_cov_trace_i2cs_stretch.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=0"]))
    return out, None


def discovered():
    """Every `test/tb*.v` on disk. The enumeration, not a list."""
    return sorted(n for n in os.listdir(HERE)
                  if re.fullmatch(r"tb.*\.v", n))


def plusargs_read(bench: str):
    """Every plusarg the bench's own source reads, including its includes."""
    names = set()
    srcs = [os.path.join(HERE, bench + ".v")]
    with open(srcs[0], encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    for inc in re.findall(r'`include\s+"([^"]+)"', body):
        p = os.path.join(ROOT, inc)
        if not os.path.isfile(p):
            p = os.path.join(HERE, os.path.basename(inc))
        if os.path.isfile(p):
            srcs.append(p)
    for p in srcs:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for m in re.finditer(r'\$value\$plusargs\("([A-Z_]+)=', fh.read()):
                names.add(m.group(1))
    return names


def generate(cfg, top):
    """Build a bench's purpose-made probe image, via the gates' own builder.

    ⛔ IT RUNS BEFORE `+NBYTES` IS RESOLVED, because NBYTES is counted from the
    file on disk. A generator that ran after would leave the arm carrying the
    byte count of whatever image happened to be there -- which is the clobber
    class already shipped once here, when a sweep left a tracked image at the
    wrong `d` under a manifest entry for a different one.
    """
    args = cfg.get("gen")
    if not args:
        return None
    import subprocess
    r = subprocess.run([sys.executable,
                        os.path.join(HERE, "make_smoke_image.py")] + args,
                       capture_output=True, text=True, cwd=ROOT,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return "%s: make_smoke_image %s failed: %s" % (
            top, " ".join(args), (r.stdout + r.stderr).strip()[-200:])
    return None


def plan():
    """(records, problems). A record is one runnable arm, fully resolved.

    ⛔ A MISSING CONFIG IS A PROBLEM, NOT A SKIP. The whole value of this file
    is that a new bench cannot join the tree without joining the sweep or being
    excluded in writing, and `can_run`-style silence is how a gate quietly
    stops covering something.
    """
    recs, probs = [], []
    found = discovered()
    for name in found:
        top = name[:-2]
        if name in EXCLUDED:
            continue
        if top not in CONFIG:
            probs.append("%s is on disk but has no CONFIG entry and no "
                         "declared exclusion" % name)
            continue
    for top, cfg in sorted(CONFIG.items()):
        if top + ".v" not in found:
            probs.append("CONFIG names %s but test/%s.v is not on disk"
                         % (top, top))
            continue
        gerr = generate(cfg, top)
        if gerr:
            probs.append(gerr)
            continue
        arms = cfg["arms"]
        if arms == "FROM_CORPUS":
            arms, err = corpus_arms()
            if err:
                probs.append("%s: %s" % (top, err))
                continue
        srcs = [os.path.join("test", top + ".v")] + cfg["srcs"] + ENGINE
        missing_src = [s for s in srcs
                       if not os.path.isfile(os.path.join(ROOT, s))]
        if missing_src:
            probs.append("%s: sources absent: %s" % (top, missing_src))
            continue
        # an arm is (label, plusargs) or (label, plusargs, build-parameters)
        arms = [(a[0], a[1], a[2] if len(a) > 2 else {}) for a in arms]
        declared = set()
        for _label, pargs, _g in arms:
            for a in pargs:
                declared.add(a.lstrip("+").split("=")[0])
        if top in NEEDS_NBYTES:
            declared.add("NBYTES")
        unsupplied = plusargs_read(top) - declared
        for u in sorted(unsupplied):
            probs.append("%s reads +%s and no arm supplies it -- a bench "
                         "running on an undeclared default is a different "
                         "run from the one the gates certify" % (top, u))
        for label, pargs, gparams in arms:
            img = None
            for a in pargs:
                if a.startswith("+IMG="):
                    img = a.split("=", 1)[1]
            full = list(pargs)
            if top in NEEDS_NBYTES:
                if img is None:
                    probs.append("%s/%s needs +NBYTES but names no image"
                                 % (top, label))
                    continue
                nb = image_bytes(img)
                if nb is None:
                    probs.append("%s/%s: image %s is not on disk"
                                 % (top, label, img))
                    continue
                full.append("+NBYTES=%d" % nb)
            elif img is not None and image_bytes(img) is None:
                probs.append("%s/%s: image %s is not on disk"
                             % (top, label, img))
                continue
            # ⛔ THE BUILD KEY CARRIES THE PARAMETERS. Two arms that differ in
            # a build-time parameter are two BINARIES, and keying the build on
            # the top module alone would have silently run the SPL = 1 arm
            # against the SPL = 2 binary -- an arm that reports a pass for a
            # configuration it never built.
            key = top + ("" if not gparams else
                         "_" + "_".join("%s%s" % (k.lower(), v)
                                        for k, v in sorted(gparams.items())))
            recs.append({"top": top, "label": label, "srcs": srcs,
                         "args": full, "gparams": gparams, "build": key})
    return recs, probs


def main() -> int:
    recs, probs = plan()
    if "--json" in sys.argv:
        # ⛔ THE PLAN GOES OUT AS DATA so the shell sweep and the Python gate
        # consume ONE declaration. A second hand-typed arm list in the shell
        # script would be the drift this file exists to prevent.
        import json
        if probs:
            sys.stderr.write("benchset: %d problem(s)\n" % len(probs))
            for p in probs:
                sys.stderr.write("  %s\n" % p)
            return 1
        json.dump(recs, sys.stdout, indent=1)
        return 0
    print()
    print("=" * 78)
    print("THE BENCH SET -- %d arms over %d benches"
          % (len(recs), len({r["top"] for r in recs})))
    print("=" * 78)
    for name, why in sorted(EXCLUDED.items()):
        print("  excluded  %-14s %s" % (name, why.split(".")[0] + "."))
    print()
    for r in recs:
        print("  %-11s %-14s %s" % (r["top"], r["label"],
                                    " ".join(a for a in r["args"]
                                             if not a.startswith("+OUT"))))
    if probs:
        print()
        print("  *** %d PROBLEM(S):" % len(probs))
        for p in probs:
            print("      %s" % p)
    print()
    print("  BENCH SET: %s" % ("ok" if not probs else "FAILED"))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
