"""THE ONE REGISTRY of declared non-admissible images, and of the timing
exemptions any of them may take.

⛔⛔ WHY ONE FILE (Wilson, SP2/P4 + HC1-B). Two switches let a program skip a
per-program timing verdict:

  * `pe_asm.assemble(timing_checks=False)` -- skips the mode floor and 1.6a,
    so a trace image that fails them can still be EMITTED for a byte-identity
    comparison (SP2: `corpus_spim` at d = 7);
  * `program_a2.NO_RTA_BUDGET` -- lets a stress image with no pyRTA bound
    carry an EMPIRICAL bench budget (HC1-B: `ckdense`).

Either one, used on an image nobody declared, is a non-admissible program
running with its refusal switched off -- the silent class. So the switch is
ACCEPTED ONLY THROUGH THIS REGISTRY: `pe_asm` refuses `timing_checks=False`
for any name not in `TIMING_EXEMPT` with that permit, and `program_a2` refuses
(at import) a `NO_RTA_BUDGET` whose membership differs from this file's.

⭐ UNIFIED WITH N1, NOT BESIDE IT. `NON_ADMISSIBLE` (N1's by-name declaration
of every non-admissible tracked image, with the conditions it breaks and why)
MOVED HERE from `model/gate_admissible_images.py`, which now reads it from
this file -- so "which images are non-admissible" and "which may skip a
timing verdict" are one table, and an exemption must point at an N1 entry that
declares the condition the skipped verdict would have refused (`QUEUE`, 1.6a).
`program_a2.NO_RTA_BUDGET` keeps its MEASURED data (widest gap, margin) --
that is a measurement, owned by `test/measure_a2_widest.py` -- but its
MEMBERSHIP is this file's.

Checked by `model/gate_admissible_images.py` (N1 + this registry, with
must-fires) and by `pe_asm.main` (an unregistered `timing_checks=False`).
"""

from __future__ import annotations

OVERLOAD, PORT, PINMAP, QUEUE = "OVERLOAD", "PORT", "PINMAP", "QUEUE"

#: ⛔ DECLARED BY NAME, each with the conditions it breaks and why that is
#: intended. PINMAP is NOT listed here -- it lives in corpus.PAD_COLLISION.
NON_ADMISSIBLE = {
    "corpus_all5.hex": ({OVERLOAD, PORT},
        "the scheduler stress image: four lanes at d = 9..13 beside a clocked "
        "lane at 70 (D5 raised only lane 0), deliberately oversubscribed. "
        "Ruling S reports its clocked lane UNBOUNDED for this reason. KNOWN "
        "WIRE BEHAVIOUR (WF2 V3, measured, exempt): ~20 % of its unclocked "
        "bits are not the feed over seeds 1-6 (1371/6558, 898/4478, "
        "663/3100, 1032/4874, 868/4252, 1050/5139), lane 1 drifting past the "
        "16-bit timestamp range -- no bound exists (U = 1.096)."),
    # ⛔ MECHANISM ONLY (ruling Q3), and the first version of this entry said
    # otherwise: it called the tracked file "the measurement base for T1's
    # per-lane J and Theorem 3's port-feasible cells". Those claims were
    # measured with the BUILDER at OTHER delays -- Theorem 3's 35 cells are
    # `run_dstar_check` at d = 20..60, every point admissible -- not with this
    # file at 12..16. Conflating the builder with the file is how a
    # non-admissible image starts to read as evidence.
    "five_image.hex": ({OVERLOAD, PORT},
        "MECHANISM ONLY. The tracked FIVE_STRESS image (d = 12..16, "
        "U = 1.083). Used by tb_witness's stall-chain trace (a floor, sub-D* "
        "regime), run_mutants' M_BUF_SWAP kill (needs stalls to discriminate), "
        "and gate_cj_bounds' sub-D* double-buffer number (that gate is "
        "RETIRED under CJ; the figure is history). No "
        "claim scoped to admissible programs was measured on it (Q3)."),
    "corpus_spim.hex": ({PORT, QUEUE},
        "the SPI-master TRACE image at d = 7, below D*: it exists to move the "
        "uo_out bank for the corpus witness, not as the shipped 1 MHz SPI "
        "lane (25 cycles)."),
    "corpus_sptgt.hex": ({PORT, QUEUE},
        "the SPI-target trace image at d = 6, below D*: it exists to exercise "
        "the target's async MISO release for the corpus witness. KNOWN WIRE "
        "BEHAVIOUR (WF2 V3, measured, exempt): 2,769 of 13,326 unclocked bits "
        "are not the feed -- by design, the peer's CS clears MISO mid-stream. "
        "⚠ It is a MECHANISM image, NOT an SPI-target transfer (self-timed "
        "SHIFTs, no clock pin, never synchronised to SCK), so it has no SCK "
        "rate; the published SPI-target lane has no exact witness "
        "(gate_wire_feed PUBLISHED, OWED)."),
    "corpus_uartrx.hex": ({PORT, QUEUE},
        "the UART-rx trace image at d = 11, below D*: it exercises the ARM "
        "and edge-capture path at a seeded phase."),
    "chain_image.hex": ({PORT, QUEUE},
        "`build_chain`, the chaining re-arm mechanism at d = 12: a mechanism "
        "test, not a schedulable program."),
    "edge_image.hex": ({PORT},
        "`tb_edge`'s reactive-release image at d = 12, below D*, because the "
        "edge-capture must-fires need tight spacing to discriminate."),
    "edge_image_noto.hex": ({PORT},
        "the no-timeout variant of the tb_edge image (d = 12)."),
    "edge_image_rise.hex": ({PORT},
        "the rising-edge variant of the tb_edge image (d = 12)."),
    "noop_image.hex": ({PORT, QUEUE},
        "the half-bit no-op idiom at d = 7: the no-op exists to offset a lane "
        "by less than one period, which is below D* by construction."),
    "noop_image_bad.hex": ({PORT, QUEUE},
        "the no-op idiom's must-fire image (d = 7)."),
    "noop_image_h19.hex": ({PORT},
        "the no-op idiom at the measured half value h = 19 (d = 12)."),
    # ⛔ RULING DT-B. ckdense's PINMAP is declared in corpus.PAD_COLLISION;
    # QUEUE is new: after W1 its clocked lanes reach r = 28/27/29/31 against
    # T = 20/21/22/23 (pyRTA), the regime where TChecker's `ovr` is reachable
    # and neither our recurrence nor pyRTA can be adjudicated. A STRESS image,
    # no longer Ruling S's must-fire subject.
    "ckdense_image.hex": ({QUEUE},
        "the A2 scheduler stress image (four dense clocked lanes, d = 20..23). "
        "Fails 1.6a under W1's jitter (DT-B), so no claim rests on it; kept "
        "because it is where W1 binds hardest and where W6's term is priced."),
    "ckhold_over_image.hex": ({QUEUE},
        "D4's 'must RUN' boundary point at d = SDA_HOLD + 1 = 16, below every "
        "mode floor: under W1 its lane's r = 18 > t = 16 (DT-A). It exists to "
        "show the silicon RUNS one cycle above the hold, not to be scheduled."),
    "tx_image.hex": ({PORT, QUEUE},
        "`tb_tx`'s TX-queue ownership image at d = 12-13, below D*: it tests "
        "routing of host bytes, not schedulability."),
}

#: the two exemption switches
TIMING_OFF = "timing_checks=False"
NO_RTA = "no_rta_budget"

#: ⛔⛔ WHICH IMAGES MAY SKIP WHICH TIMING VERDICT, and why. A TRACKED entry
#: must be an N1 entry declaring QUEUE (the 1.6a failure the skipped verdict
#: would refuse); its reason is N1's, not restated. A VARIANT (`of`) is an
#: UNTRACKED image built from the same program with a header bit changed --
#: it must name a registered parent with the same permit, and say what moved.
TIMING_EXEMPT = {
    "corpus_spim.hex": {"permits": {TIMING_OFF}, "of": None,
        "why": "fails 1.6a (and PORT) at d = 7; emitted with the timing pair "
               "skipped ONLY for SP2's byte identity against the tracked "
               "trace image. The same transaction at d = 25 passes."},
    "ckdense_image.hex": {"permits": {NO_RTA}, "of": None,
        "why": "DT-B: fails 1.6a under W1; pyRTA's W1 fixed point gives no "
               "bound under HS + 2 (HC1-B), so its bench budget is EMPIRICAL "
               "(program_a2.NO_RTA_BUDGET holds the measurement).",
        # ⭐ WILSON: the +4 margin is ACCEPTED; the number carries its origin.
        # The measurement itself (measured_widest 6/7/10/5, margin 4) stays
        # in program_a2.NO_RTA_BUDGET, unchanged.
        "budget_origin":
            "empirical: measured max over 25 runs (iverilog seeds 1-3; pinned "
            "Verilator 5.053 reset modes 0/1 + mode 2 seeds 1-20), widest "
            "6/7/10/5, plus 4 = 10/11/14/9; flake-free over 25 (spread 0); "
            "catches: M_NO_HOLD_GATE on this image via Layer H + V1/V2 "
            "(budget itself not broken: widest 4/7/10/8); M_RX_CAPGATE_LATE "
            "not applicable to this image (no push-pull capture lane; caught "
            "by EX1 on the d=4 SPI image); HOLD_PICK_LAG=1 caught by "
            "model/gate_hold_offset.py. LEDGER NOTE (Wilson): the budget "
            "itself is a WEAK TRIPWIRE on this image -- none of these "
            "mutants breaks it; the named gates above are what catch them."},
    "corpus_spim_mode0": {"permits": {TIMING_OFF}, "of": "corpus_spim.hex",
        "why": "run_spifram's scratch variant: SCK parked low before CS "
               "(one extra OP_LEVEL per frame), d = 7 unchanged."},
    "corpus_spim_inv": {"permits": {TIMING_OFF}, "of": "corpus_spim.hex",
        "why": "run_spifram's scratch variant: FLAG_CLK_INV, d = 7 "
               "unchanged."},
    "corpus_spim_mode0_inv": {"permits": {TIMING_OFF}, "of": "corpus_spim.hex",
        "why": "run_spifram's scratch variant: both of the above."},
}


class ExemptionError(Exception):
    """A timing exemption asked for by an image the registry does not name."""


def require(name, permit):
    """Raise unless `name` is registered with `permit`. The ONE gatekeeper
    both switches call."""
    e = TIMING_EXEMPT.get(name)
    if e is None or permit not in e["permits"]:
        raise ExemptionError(
            "%s asked for `%s` but model/nonadmissible.py TIMING_EXEMPT does "
            "not register it with that permit. A timing verdict may be skipped "
            "only for a DECLARED non-admissible image, with its reason; "
            "register it there (and in NON_ADMISSIBLE if it is tracked), or "
            "fix the program." % (name if name is not None else "an unnamed "
                                  "image", permit))
    return e


def names_with(permit):
    return {n for n, e in TIMING_EXEMPT.items() if permit in e["permits"]}


def registry_problems(registry=None, n1=None):
    """-> [str]: the registry's own consistency. Pure, so a must-fire can
    price it on a planted registry."""
    reg = TIMING_EXEMPT if registry is None else registry
    n1 = NON_ADMISSIBLE if n1 is None else n1
    probs = []
    for name, e in sorted(reg.items()):
        if not e.get("why"):
            probs.append("%s: no reason" % name)
        if not e.get("permits") or not e["permits"] <= {TIMING_OFF, NO_RTA}:
            probs.append("%s: permits %r" % (name, e.get("permits")))
        # ⭐ an empirical budget must carry its origin (Wilson, ckdense +4)
        if NO_RTA in e.get("permits", ()) and \
                not str(e.get("budget_origin", "")).startswith("empirical:"):
            probs.append("%s: no_rta_budget without a stated budget_origin "
                         "('empirical: ...')" % name)
        par = e.get("of")
        if par is None:
            if name not in n1:
                probs.append("%s is exempt but not declared non-admissible "
                             "in NON_ADMISSIBLE" % name)
            elif QUEUE not in n1[name][0]:
                probs.append("%s is exempt but its N1 entry does not declare "
                             "QUEUE (the 1.6a failure an exemption covers)"
                             % name)
        else:
            if par not in reg or reg[par].get("of") is not None:
                probs.append("%s is a variant of %s, which is not a "
                             "registered tracked entry" % (name, par))
            elif not e["permits"] <= reg[par]["permits"]:
                probs.append("%s asks for more than its parent %s permits"
                             % (name, par))
    return probs


def no_rta_problems(no_rta_budget, registry=None):
    """-> [str]: `program_a2.NO_RTA_BUDGET` membership vs the registry."""
    reg = TIMING_EXEMPT if registry is None else registry
    want = {n for n, e in reg.items() if NO_RTA in e["permits"]}
    got = set(no_rta_budget)
    return (["%s is in NO_RTA_BUDGET but not registered for %s in "
             "model/nonadmissible.py" % (n, NO_RTA) for n in sorted(got - want)]
            + ["%s is registered for %s but has no NO_RTA_BUDGET measurement"
               % (n, NO_RTA) for n in sorted(want - got)])
