"""rtl_contracts -- the run-level contract list (Wilson 11-19, the registry's premise check, step 2).

The run-level theorems behind READY_RULES (gate_lean_build.PREMISES) take two kinds of premise
besides the theorem's own events: the conditions a rule must establish per image ("applies",
compared by gate_lane_cert check 13) and CONTRACT premises -- properties of the hardware and the
run, the same for every rule. This file closes the chain for the second kind:

    theorem  ->  contract premise (PREMISES[thm]["contract"])  ->  RTL contract (CONTRACT_PREMISES)
             ->  that contract's RTL must-fire (RTL_CONTRACTS[...]["must_fire"])

gate_lane_cert check 21 turns red on (problems() below):
  - a contract premise some PREMISES theorem uses that is not listed here, or listed with no RTL
    contract;
  - a listed premise naming an RTL contract that RTL_CONTRACTS does not define;
  - an RTL contract with no must-fire entry, a must-fire "present" with no name, or a "present"
    must-fire not registered with its killer in gate_mutant_kills (KILLERS / SCRATCH);
  - a must-fire status other than "present" / "owed (RTL batch)".
Until the RTL exists a contract's must-fire is "owed (RTL batch)": the gap stays visible, never
blank. Agent 1: this list is the index for the RTL design note -- each K-contract there names the
premise it discharges (CONTRACT_PREMISES, read backwards).
"""
from __future__ import annotations

OWED = "owed (RTL batch)"
PRESENT = "present"

#: RTL contract -> what the RTL must do, the Lean it is modelled by, its must-fire.
#: must_fire: {"status": PRESENT, "name": <mutant registered in gate_mutant_kills>} or
#:            {"status": OWED, "name": None}
RTL_CONTRACTS = {
    "bufeng_cycle": {
        "what": "the lane's fetch path is BufEng cycle for cycle: depth-2 buffer, first fetch to "
                "the latched slot, a second into capSlot (head, spare, buffer), filed in capture "
                "order (HeadFirst); the replay compares the RTL's run against stepB",
        "lean": "BufEng.stepB / WfB (wfB_run)",
        "must_fire": {"status": OWED, "name": None}},
    "K1": {
        "what": "at a FALLTHROUGH edge the edge word (its fetch index) is kept, in a slot, the "
                "buffer, or being captured",
        "lean": "FlushKeep.edge_survives_flush, FlushKill.edge_survives_flushK",
        "must_fire": {"status": OWED, "name": None}},
    "K2": {
        "what": "every other word of the flushed lane (the timeout word and behind it) is cleared; "
                "the buffer is empty after the flush cycle",
        "lean": "FlushKeep.flush_keeps_only_edge / flush_drops_timeout / flush_buf_empty",
        "must_fire": {"status": OWED, "name": None}},
    "K3": {
        "what": "a word already in a slot stays in that slot (only the head select moves); a "
                "buffered edge word moves to the head in the flush cycle",
        "lean": "FlushKeep.flush_keep_slot",
        "must_fire": {"status": OWED, "name": None}},
    "K4": {
        "what": "the flushed lane is released the cycle after the edge (FlushStep.tsF)",
        "lean": "FlushKeep (K4), RestartB.restart_runBK",
        "must_fire": {"status": OWED, "name": None}},
    "K5": {
        "what": "a fetch for the flushed lane in flight at the edge (REQ / WAIT) is killed and "
                "files nothing (the RTL's pkill)",
        "lean": "FlushKill.kill_files_nothing, RestartB.kill_prov_runBK",
        "must_fire": {"status": OWED, "name": None}},
    "K6": {
        "what": "on the FALLTHROUGH timeout path the head select swaps to the timeout word "
                "(PC+1), fetched second behind the edge word (Wilson 11-19)",
        "lean": "OrderB.ft_timeout_order (owed; READY_RULES ft_timeout)",
        "must_fire": {"status": OWED, "name": None}},
    "K7": {
        "what": "one fetch pointer per lane, shared by the slot fetches and the base refill; the "
                "replay compares fetch indices (Wilson 11-19)",
        "lean": "BufEng fetch indices (issue_index, order_kept)",
        "must_fire": {"status": OWED, "name": None}},
    "issue_at_capture": {
        "what": "an ARM's slot request is raised at its capture and held, cycle by cycle, until "
                "the slot issues for it",
        "lean": "SlotReadyB.slot_issue_cap_T / slot_issue_within_T (sreq requests y)",
        "must_fire": {"status": OWED, "name": None}},
    "slot_fcfs_capture": {
        "what": "the slot serves requesters first come, first served by capture: only lanes "
                "captured earlier are ahead of y",
        "lean": "ContendB.slot_wait_fcfs_two (hold: w = y or old w)",
        "must_fire": {"status": OWED, "name": None}},
    "slot_below_usb_rx": {
        "what": "the slot's priority is below USB receive only; nothing else preempts it",
        "lean": "Slot.slot_wait_bound / SlotForB (usb charged separately)",
        "must_fire": {"status": OWED, "name": None}},
    "no_fetch_past_branch": {
        "what": "no slot fetch while the lane holds a no-prefetch (branch) word: the requester "
                "is BufEng.SReqB (Wilson 11-19)",
        "lean": "BufEng.SReqB (hq2 / hold2 dischargeable only for a non-npf PC+1)",
        "must_fire": {"status": OWED, "name": None}},
    "disp_released_only": {
        "what": "the dispatcher picks only a live lane whose release time has passed "
                "(ts <= now)",
        "lean": "hwin (SlotReadyB.ready_pc2_arm_T, disp_pick_T)",
        "must_fire": {"status": OWED, "name": None}},
    # DRIVE_SAMPLE (Wilson 11-20, option (A); entries added by agent 1 with the RTL, per the
    # ruling -- agent 2's file, theirs to reword)
    "ds_sample_before_drive": {
        "what": "DRIVE_SAMPLE's sampled bit is pinb's pad as latched clock.DS_SAMPLE_AGE edges "
                "before the edge its own drive reaches the pad -- the sample comes before the "
                "drive, never its own bit (measured by test/run_drive_sample.py)",
        "lean": "the order lemma (agent 2, owed); DRIVE_SAMPLE an ordinary word of the fragment",
        "must_fire": {"status": PRESENT, "name": "M_DS_SAMPLE_AFTER"}},
    "ds_tx_advance": {
        "what": "DRIVE_SAMPLE with mod[1] drives the TX register's next bit and advances it as "
                "SHIFT does (byte load, underrun, tx_bitp): a full-duplex byte goes out bit for bit",
        "lean": "none (a writeback effect of an ordinary word)",
        "must_fire": {"status": PRESENT, "name": "M_DS_NO_TXADV"}},
}

#: contract premise (the names in gate_lean_build.PREMISES[thm]["contract"]) -> the RTL
#: contracts that provide it, and how the Lean side uses it
CONTRACT_PREMISES = {
    "engine_model": {
        "rtl": ("bufeng_cycle", "K1", "K2", "K3", "K4", "K5", "K7"),
        "why": "hT: y's run agrees with stepB along the trajectory; between flushes runBK is "
               "such a trajectory (RestartB.trajY_runBK), the flush entering as a restart"},
    "engine_wf": {
        "rtl": ("bufeng_cycle", "K1", "K2", "K3", "K5"),
        "why": "hWf: WfB at every cycle; Lean discharges it from the engine (wfB_run, "
               "FlushKill.wfBK_run), so its RTL side is the engine's own contracts"},
    "slot_requester": {
        "rtl": ("issue_at_capture", "slot_fcfs_capture", "slot_below_usb_rx",
                "no_fetch_past_branch"),
        "why": "hq / hold (and hq1 / hold1 / hq2 / hold2): the requester asks for y on every "
               "cycle of the wait, with only y or older lanes ahead; for the second fetch only "
               "behind a non-npf PC+1 (SReqB)"},
    "disp_released_only": {
        "rtl": ("disp_released_only",),
        "why": "hwin: win picks only live, released lanes (pc2_arm's PC+1 ARM picked at release)"},
}

#: must-fire switches (gate_lane_cert M_RC_PREMISE_ORPHAN / M_RC_CONTRACT_NO_MF)
ORPHAN_MUT = False
NO_MF_MUT = False


def _registered():
    """{mutant name}: every must-fire gate_mutant_kills ties to a killer"""
    import gate_mutant_kills as MK
    return set(MK.KILLERS) | set(MK.SCRATCH)


def problems(premises, contracts=None, cprem=None, registered=None):
    """check 21: [problem] for the chain theorem -> contract premise -> RTL contract -> must-fire.
    `premises`: gate_lean_build.PREMISES (or a copy)."""
    contracts = RTL_CONTRACTS if contracts is None else contracts
    cprem = CONTRACT_PREMISES if cprem is None else cprem
    if ORPHAN_MUT:
        premises = dict(premises)
        t0 = sorted(premises)[0]
        premises[t0] = dict(premises[t0],
                            contract=dict(premises[t0]["contract"], orphan_premise=("hT",)))
    if NO_MF_MUT:
        contracts = dict(contracts)
        contracts["K6"] = {k: v for k, v in contracts["K6"].items() if k != "must_fire"}
    probs = []
    used = {}
    for thm, spec in sorted(premises.items()):
        for p in spec["contract"]:
            used.setdefault(p, []).append(thm)
    for p, thms in sorted(used.items()):
        if p not in cprem:
            probs.append("contract premise %s (%s) has no RTL contract listed"
                         % (p, ", ".join(thms)))
        elif not cprem[p].get("rtl"):
            probs.append("contract premise %s maps to no RTL contract" % p)
    for p, v in sorted(cprem.items()):
        for c in v.get("rtl", ()):
            if c not in contracts:
                probs.append("contract premise %s names RTL contract %s, which is not defined"
                             % (p, c))
    reg = None
    for c, v in sorted(contracts.items()):
        mf = v.get("must_fire")
        if not mf:
            probs.append("RTL contract %s has no must-fire entry" % c)
        elif mf.get("status") == PRESENT:
            if not mf.get("name"):
                probs.append("RTL contract %s: must-fire present but unnamed" % c)
            else:
                if reg is None:
                    reg = registered if registered is not None else _registered()
                if mf["name"] not in reg:
                    probs.append("RTL contract %s: must-fire %s is not registered in "
                                 "gate_mutant_kills" % (c, mf["name"]))
        elif mf.get("status") != OWED:
            probs.append("RTL contract %s: must-fire status %r is neither %r nor %r"
                         % (c, mf.get("status"), PRESENT, OWED))
    return probs


def summary(premises):
    """(premises used, contracts, must-fires present, must-fires owed, contracts no premise uses)"""
    used = {p for spec in premises.values() for p in spec["contract"]}
    via = {c for p in used if p in CONTRACT_PREMISES for c in CONTRACT_PREMISES[p]["rtl"]}
    st = [v["must_fire"]["status"] for v in RTL_CONTRACTS.values() if v.get("must_fire")]
    return (sorted(used), len(RTL_CONTRACTS), st.count(PRESENT), st.count(OWED),
            sorted(set(RTL_CONTRACTS) - via))
