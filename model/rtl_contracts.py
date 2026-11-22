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
        "what": "the lane's fetch path is BufEng cycle for cycle: a one-word buffer per lane "
                "(Wilson 11-20 depth ruling; 'depth 2' = two fetches per ARM), first fetch to "
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
        "what": "a fetch for the flushed lane in flight at the edge is killed and files nothing "
                "(the RTL's pkill); in flight under issue path (A) (Wilson 11-20): the held slot "
                "request plus REQ / WAIT -- the refill mask's and the kill's must-fires cover "
                "exactly that list",
        "issue_path": "(A) scan issue (Wilson 11-20)",
        "lean": "FlushKill.kill_files_nothing, RestartB.kill_prov_runBK",
        "must_fire": {"status": OWED, "name": None}},
    "K6": {
        "what": "at a FALLTHROUGH timeout the head select moves to the timeout word (PC+1, "
                "fetched second behind the edge word) and the edge word (PC+2) is dropped -- K2 "
                "mirrored; if the path reaches PC+2 it is refetched normally (Wilson 11-20 "
                "ruling 1a, correcting the 11-19 'PC+2 the next word'). PC+1 captured by the "
                "deadline is a lemma (from T >= FILL + L, ruling 1b), so no late PC+1 exists to "
                "kill. Must-fire (agent 1): PC+2 left valid after the swap, caught",
        "lean": "OrderT.ready_ft_timeout_T / ft_timeout_captured_T (READY_RULES ft_timeout): "
                "the swap is the keep-flush keeping PC+1",
        "must_fire": {"status": OWED, "name": None}},
    "K7": {
        "what": "one fetch pointer per lane, shared by the slot fetches and the base refill; the "
                "replay compares fetch indices (Wilson 11-19)",
        "lean": "BufEng fetch indices (issue_index, order_kept); on the flushed run "
                "OrderK.ordBK_run",
        "must_fire": {"status": OWED, "name": None}},
    "issue_at_capture": {
        "what": "an ARM's slot request is raised in the CAP cycle of the ARM's own fetch, held as "
                "a flag, cycle by cycle, and issued by the next scan (Wilson 11-20 ruling: the "
                "wait at capture is rem .cap = 1, the 1 in P1B_FILL_SCAN; SLOT_WAIT_BASE = 3 "
                "bounds only requests raised outside the CAP cycle, which this design never "
                "raises). Must-fire (agent 1): a raise delayed by one cycle is caught -- the "
                "cycle-exact check measures the raise cycle, not only the arrival",
        "issue_path": "(A) scan issue (Wilson 11-20); in flight under (A): the held request "
                      "plus REQ / WAIT",
        "lean": "Slot.RaiseAtCapture / p1b_capture (from pst = .cap); "
                "SlotReadyB.slot_issue_cap_T / slot_issue_within_T (sreq requests y)",
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
    "K8": {
        "what": "a lane is never flushed again within 2 cycles of its last flush (Wilson 11-19). "
                "Must-fire (agent 1): a simulation assertion firing on any lane flushed twice "
                "within the window, plus a planted case it catches",
        "lean": "ComposeB (flush_spacing behind hedge); proof (b) from FALLTHROUGH arming owed",
        "must_fire": {"status": OWED, "name": None}},
    "post_at_wb": {
        "what": "an event-flag POST counts only at a lane's writeback, so (one writeback per "
                "cycle) at most one POST per cycle (Wilson 11-19 flag ruling). RTL side: agent "
                "1's 93ddd43, sim assertion FLAG1, planted M_FLAG_POST2 -- present once "
                "registered in gate_mutant_kills on the merged tree",
        "lean": "Count.wb_unique",
        "must_fire": {"status": OWED, "name": None}},
    "K9": {
        "what": "ScanOk (Wilson 11-20 ruling 2: the RTL text is the Lean premise transcribed). "
                "LEAN (FlushHeld.ScanOk, verbatim): `def ScanOk (A : EngBA) : Prop := "
                "forall l, A.hit l = true -> A.X.x.e.pst = .scan -> "
                "(stepB P (winA win A.armed) usb sreq A.X.base).e.pst != .scan -> "
                "(stepB P (winA win A.armed) usb sreq A.X.base).e.pl != l` -- in a cycle where "
                "lane l is flushed (its edge hits) and the port is at its scan, if the scan "
                "issues a fetch, that fetch is not for l. RTL MEANING (agent 1, to write and "
                "confirm): the 11-14 scan fix -- the scan never selects a lane whose slots are "
                "being flushed. Must-fire (agent 1): a planted scan selection of a flushed lane, "
                "caught",
        "lean": "FlushHeld.ScanOk; premise of ComposeB.flushOk_runBA / flush_spacing_runBA, "
                "OrderH.ready_ft_edge_head",
        "must_fire": {"status": OWED, "name": None}},
    "K10": {
        "what": "edge timing (Wilson 11-20 ruling 3): a lane's edge detector fires only when its "
                "armed flag was set in an earlier cycle, so the earliest edge a lane can act on "
                "is its arming writeback + 1 (Lean: hedge, forall t l, t + 1 <= edge t l). A "
                "hardware property, separate from the peer-side 'armed before the earliest SOP' "
                "premise. Must-fire (agent 1): a planted edge recognised in the arming writeback "
                "cycle itself, caught",
        "lean": "hedge (ComposeB.flushOk_runBA / flush_spacing_runBA / armInvB_runBA, "
                "OrderH.ready_ft_edge_head)",
        "must_fire": {"status": OWED, "name": None}},
    "K11": {
        "what": "the scheduler never chooses an armed lane while an unarmed lane is ready "
                "(Wilson 11-21 ruling, hS option (b)). The RTL meets it by construction: it masks "
                "before choosing (rdy_rel = ... & ~armed); agent 1 confirms that line is the "
                "whole story in RTL. Must-fire (agent 1): a planted chooser that can pick an "
                "armed lane while another is ready, caught. The keep-flush replay referees it: "
                "every chosen lane checked against the model's",
        "lean": "SchedK11.K11At; premise of SchedK11.winA_eq_of_K11 / winS_eq_of_K11",
        "must_fire": {"status": OWED, "name": None}},
    # Wilson 11-21 (closure ruling, ask 1): the two scheduler premises wb_closeBK_K11 rests on
    "sched_bprime": {
        "what": "(b') the dispatcher's winner always has a valid head -- the (b') readiness fix in "
                "RTL since 9c0df0c. Must-fire (agent 1): a planted dispatcher that can pick a "
                "lane with an empty head, caught",
        "lean": "BPrime.BPrimeWin; premise hb of CloseBK.noDec_zero_K11 / wb_closeBK_K11 "
                "(through the mask: SchedK11.winA_bprime)",
        "must_fire": {"status": OWED, "name": None}},
    "sched_names_ready": {
        "what": "in an idle cycle with some lane ready, the dispatcher names a lane. Must-fire "
                "(agent 1): a planted idle cycle with a ready lane and no decision, caught",
        "lean": "premise hws of CloseBK.noDec_zero_K11 / wb_closeBK_K11 (LemmaA's hws)",
        "must_fire": {"status": OWED, "name": None}},
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
    "sched_k11": {
        "rtl": ("K11",),
        "why": "hK: K11At at every cycle of the armed run, so winA win armed chooses as win "
               "whenever an unarmed lane is ready (SchedK11.winS_eq_of_K11): the window bound's "
               "no-decision count S has no masked-pick stall (composition L4 hS)"},
    "sched_bprime": {
        "rtl": ("sched_bprime",),
        "why": "hb: the winner's head is valid (BPrimeWin), so with an unarmed ready lane no idle "
               "cycle goes undecided (CloseBK.noDec_zero_K11: hS = 0)"},
    "sched_names_ready": {
        "rtl": ("sched_names_ready",),
        "why": "hws: an idle cycle with a ready lane names one (CloseBK.noDec_zero_K11: hS = 0)"},
    "flush_spacing": {
        "rtl": ("K8",),
        "proof": "contract K8; proof (b) proved on the armed run (ComposeB.flush_spacing_runBA, "
                 "carried to runBK by runBA_proj: flush_spacing_runBK) under hedge-timing and "
                 "ScanOk; K8 stays as the RTL check (Wilson 11-19)",
        "why": "the composition restarts from y's LAST flush (ComposeB.flush_cut), so "
               "restart_runBK's 'no flush at f+1, f+2' holds by construction; the spacing enters "
               "through hedge -- y's edge word present at every flush restarted from -- which a "
               "second flush within 2 cycles could break (composition L1, d03bf22)"},
    "scan_ok": {
        "rtl": ("K9",),
        "why": "hscan: the scan never issues for a lane in the cycle its edge flushes it "
               "(FlushHeld.ScanOk), so the flush's FlushOk holds on the armed run "
               "(flushOk_runBA) and no flush comes within 2 cycles of another (flush_spacing)"},
    "edge_timing": {
        "rtl": ("K10",),
        "why": "hedge: an arming's edge is at least one cycle after its writeback, so the armed "
               "invariant holds (armInvB_runBA) and the ARM has retired before its edge"},
    "timeout_order": {
        "rtl": ("K6", "K7"),
        "why": "OrderT.ready_ft_timeout_T's hidx2 / hord: the K6 swap keeps the word fetched "
               "SECOND after the ARM (PC+1; kept index = the second slot fetch's) and no "
               "retirement consumes it before the deadline (the armed lane is not dispatched; "
               "on the armed run as hord_runBK does for the edge). K6 as ruled 11-20 + K7"},
    "fetch_order": {
        "rtl": ("K1", "K7"),
        "why": "OrderK's keep premise (K6 build, Nate 11-20): KeepOk at every flush and hkeep at "
               "the edge -- the kept word's fetch index is the lane's retirement count, i.e. the "
               "edge word is the lane's oldest unretired word and the lane does not retire in "
               "the edge cycle (agent 1's 'K3(a): the edge word heads the lane at f+1'). Under "
               "it the order holds on the flushed run (OrderK.ordBK_run), hord is proved "
               "(hord_runBK) and hidx is not needed (ready_ft_edge_K). Proved from the arming "
               "chain (Nate 11-20 option 1, OrderK keep_at_hit / keepOk_runBK / hkeep_runBK: the "
               "ARM retires at its arming and the armed lane is frozen) down to one premise per "
               "arming, hidxA, itself proved (OrderH.hidxA_of_head: order and keep together, by "
               "strong induction on the arming time) from the hardware's part, hidxH: AT AN FT "
               "EDGE THE FLUSH KEEPS THE WORD FETCHED IMMEDIATELY AFTER THE ARM (kept index = "
               "the ARM's fetch index + 1) -- K1 made exact, with K7 (one fetch pointer per "
               "lane, consecutive indices) and the edge-first order (the requester fetches the "
               "edge word first). ready_ft_edge_head asks hidxH only at the arming whose edge "
               "it is, so other armings may end in a K6 timeout swap (fetch order holds across "
               "both, OrderK.ordBK_run)"},
}

#: THE MILESTONE (Wilson 11-18 / 11-19): slot_on_composition -- GapRun on the buffered engine with
#: flushes, one certificate over a whole run. status "proved" only when every step is; a proved
#: step names its theorems (each at the Lean gate, gate_lean_build.KEY); an owed step says what it
#: owes. gate_lane_cert check 21 turns red on a proved milestone with an owed step, a proved step
#: with a theorem not at the Lean gate or none, or an owed step with no "what".
COMPOSITION = {
    "slot_on_composition": {
        "status": "owed",
        "steps": [
            {"step": "trajectory between flushes (3a-3c)", "status": "proved",
             "theorems": ("trajY_runBK", "trajY_runBK_noflush", "kill_prov_runBK")},
            {"step": "the restart (3c part 2)", "status": "proved",
             "theorems": ("restart_runBK",)},
            {"step": "certificate from either start (3b)", "status": "proved",
             "theorems": ("head_late_gapT", "pending_bound_gapT")},
            {"step": "L1 cut at the last flush", "status": "proved",
             "theorems": ("flush_cut", "restart_head_runBK", "stretch_after_flush")},
            {"step": "L2 the first stretch", "status": "proved",
             "theorems": ("stretch_first",)},
            {"step": "L3 head_valid_runBK", "status": "proved",
             "theorems": ("head_of_cert", "head_valid_runBK")},
            {"step": "L4 hR on a stretch", "status": "proved",
             "theorems": ("hR_stretch", "hstart_after_flush")},
            # L4 hfree split 11-21: the induction and the gap case proved; HrelS for an ARM
            # writeback (by its edge, not its gap) on runBK owed
            {"step": "L4 hfree: the stretch induction and non-ARM writebacks (gap >= Rr + 3, "
                     "lane-cert check 22)", "status": "proved",
             "theorems": ("hpre_after_flush", "hrel_of_gap", "hR_stretch_gap",
                          "hR_stretch_nofree")},
            {"step": "L4 hfree: ARM writebacks on runBK (vacuous: armed until the edge, which "
                     "flushes y)", "status": "proved",
             "theorems": ("armed_after_arm", "arm_no_dec", "flS_runBK", "hrel_bridged")},
            # L4 hM / hS split 11-21 (Wilson ruling: wb_closeBK in four parts; part 4 by K11)
            {"step": "L4 hM part 2: decision spacing on the bridged run (hsepBK)",
             "status": "proved",
             "theorems": ("ts_wb_bridged", "ts_mono_bridged", "hsep_bridged")},
            {"step": "L4 hS: the K11 scheduler lemma (contract K11, must-fire owed by agent 1)",
             "status": "proved",
             "theorems": ("winA_eq_of_K11", "winA_ne_none_of_K11", "winA_bprime",
                          "winA_released", "winS_eq_of_K11")},
            # closure 11-21: counting on runBK (CountBK), hnf / hfree in run coordinates
            # (HfreeR), hS handed the decision + no-flush (4a), the closure + hS = 0 (CloseBK)
            # Wilson 11-21 (span ruling): the certificate counts other-lane decisions by the span
            # rule (branch_budget._decisions: span_min(m) >= K + 1 + R_z), so the closure that
            # backs it is the span form (CloseBKSpan), not the sigma form (wb_closeBK_K11, kept
            # proved but not the backing theorem). hspan on runBK (anchored at a writeback) is
            # the span checker's premise, as under RespSpan.wb_close_span; nonarm_gap is the R + 3
            # part only (check 22) -- no sigma + R <= gap condition remains.
            {"step": "L4 hM / hS closure in span form: wb_closeBK_span; hS = 0 under K11 + (b')",
             "status": "proved",
             "theorems": ("cntBK_add", "cntBK_reach", "cntBK_decOther_split",
                          "cntBK_decAny_split", "hnf_runBK", "hfree_runBK", "hrelR_bridged",
                          "dec_sepBK", "cntBK_wb_shift", "wb_closeBK_span", "unarmed_in_window",
                          "noDec_zero_K11", "wb_closeBK_span_K11")},
            {"step": "bridge: the armed run is a runBK run", "status": "proved",
             "theorems": ("runBA_proj", "flushOk_runBA")},
            {"step": "flush spacing (K8), proof (b)", "status": "proved",
             "theorems": ("flush_spacing_runBA", "flush_spacing_runBK")},
            {"step": "hedge on the bridged run", "status": "proved",
             "theorems": ("armed_origin", "hedge_runBK", "hedge_runBK_armed")},
            {"step": "hword: the edge word in time", "status": "proved",
             "theorems": ("slot_cap_index", "held_persist_runBK")},
            {"step": "fetch order on the flushed run (K6 steps 1-2)", "status": "proved",
             "theorems": ("ordBK_run", "hord_runBK", "ready_ft_edge_K")},
            {"step": "keep premise KeepOk / hkeep", "status": "proved",
             "theorems": ("keep_at_hit", "keepOk_runBK", "hkeep_runBK", "ready_ft_edge_armed")},
            {"step": "hidxA: the edge word is the ARM's next fetch", "status": "proved",
             "theorems": ("hidxA_of_head", "hidxA_runBA", "ready_ft_edge_head")},
            {"step": "contracts for hedge-timing and ScanOk (K10, K9; Wilson 11-20)",
             "status": "proved",
             "theorems": ("flushOk_runBA", "flush_spacing_runBA", "ready_ft_edge_head")},
            {"step": "spare-capture readiness (ready_*_spare_T)", "status": "proved",
             "theorems": ("ready_pc1_spare_T", "ready_pc2_plain_spare_T",
                          "ready_pc2_arm_spare_T")},
            {"step": "ready_ft_edge_T", "status": "proved",
             "theorems": ("ready_ft_edge_T",)},
            # Wilson 11-21 (hspan ruling): on run hspan stays the span checker's premise; on runBK a
            # flush can lower a timestamp (FT deadline D, then edge + 1 < D), so span_min =>
            # hspan there is its own lemma, owed
            # 11-21 (flush lemma): on runF flushes only add (FlushChain, proved). On runBK there is
            # no view: an arming writeback sets ts + dly + ext (ts_wb_bridged), and the edge's
            # flush sets now + 1 (ts_flush_stepBK) -- an FT ARM whose edge precedes its deadline
            # D drops the release from D to edge + 1. "Flushes only add" does not hold there.
            # proved 11-22 (ChainBK, Nate's go): the release chain on the bridged run with an
            # arming writeback counted as the checker's ARM gap gA, not dly + ext: hgw (gA <=
            # dly + ext, the timeout path) is the checker's per-word gap fact, the standing the
            # per-word gaps have on run; hge (release + gA <= edge + 1, the edge path) is the
            # edge-timing contract. armed_origin ties each flush to its ARM; the chain is anchored
            # at a writeback of the lane, so it never starts inside an armed stretch.
            {"step": "span_min => hspan on runBK (the flush lemma)", "status": "proved",
             "theorems": ("gsumBA_skip", "tsBA_hit", "tsBA_nohit", "ts_chainBA_ge",
                          "ts_chainBK_ge")},
            {"step": "hRdy", "status": "owed",
             "what": "the ready_*_T lifted onto runBK through the stretches"},
            {"step": "hZS", "status": "owed",
             "what": "step 5: hZS0 established, not only gate-checked (lane-cert check 20)"},
        ]},
    # Wilson 11-21 (usbdev ruling, top priority): the two shipped images have a FALLTHROUGH ARM
    # on the USB lane, so their slot-off run is run3T -> runF (flushes, disarm cycles), not run;
    # wb_close_span does not reach them
    # proved 11-21 (Nate's go): backs the slot-off stamps; a slot-on figure for these images
    # rests on slot_on_composition's runBK flush lemma (owed) -- agent 1 to confirm which run ships
    "usbdev_flush_stamps": {
        "status": "proved",
        "steps": [
            {"step": "usbdev_dev.hex / usbdev_fpga.hex: hM from the span rule on the flush run",
             "status": "proved",
             "theorems": ("cntF_reach", "cntF_wb_shift", "dec_sepF", "wb_close_spanF",
                          "wb_close_spanT")},
            # 11-21 (hRz check): the USB lane's own R is PrioResp.prio_resp's, stated on run only;
            # on usbdev the USB lane is the flushed lane -- re-derived with flushes (PrioRespF)
            {"step": "USB-lane bound on the flush run (wb_close_spanT's hRz)", "status": "proved",
             "theorems": ("relT_le_fl", "ts_monoF_fl", "ts_constF", "idle3F", "prio_respF",
                          "prio_respT")},
            {"step": "hpri on run3T (prio_respT's: the USB lane wins when ready, head valid)",
             "status": "proved",
             "theorems": ("dec_tsF1", "hpri_bF", "prio_resp_edfF", "prio_resp_edfT")},
            # the flush lemma, runF half (Wilson 11-21 hspan ruling): flushes only add, so on the
            # flush run span_min => hspan stands as on run (the release chain vs the checker's
            # per-word gaps)
            {"step": "the flush lemma for hspan on runF: the release chain across flushes",
             "status": "proved",
             "theorems": ("relT_le_fl", "ts_flushF", "ts_chainF_ge", "ts_chainT_ge")},
        ]},
    # 11-21 (hfree_measure, RTL traces): the EDF theorems (EdfB, RespEdf) carry their own hfree;
    # the gap route does not give it on two EDF-certified images although the RTL meets it
    "edf_hfree": {
        "status": "owed",
        "steps": [
            {"step": "hfree under the EDF response bounds", "status": "owed",
             "what": "EdfB / RespEdf's hfree on EDF-certified images: pair_busy lane 0 (gap 40, "
                     "EDF R 38: one cycle short of gap >= Rr + 3; RTL edges on the grid, load "
                     "delays the start 29) and uart_tx_busy lane 0 (REARM gap 20, EDF R 158; RTL "
                     "worst response 14, V3-T) -- a tighter bound or another route"},
        ]},
}

#: must-fire switches (gate_lane_cert M_RC_PREMISE_ORPHAN / M_RC_CONTRACT_NO_MF /
#: M_RC_COMP_EARLY: the milestone marked proved with steps owed)
ORPHAN_MUT = False
NO_MF_MUT = False
COMP_EARLY_MUT = False


def composition_problems(key, comp=None):
    """check 21 (Wilson 11-19): [problem] in COMPOSITION. `key`: gate_lean_build.KEY."""
    comp = COMPOSITION if comp is None else comp
    probs = []
    for m, v in sorted(comp.items()):
        st = "proved" if COMP_EARLY_MUT else v.get("status")
        owed = [s["step"] for s in v["steps"] if s.get("status") != "proved"]
        if st == "proved" and owed:
            probs.append("%s marked proved with %d step(s) owed (%s)"
                         % (m, len(owed), "; ".join(owed[:2])))
        for s in v["steps"]:
            if s.get("status") == "proved":
                th = tuple(s.get("theorems") or ())
                if not th:
                    probs.append("%s / %s: proved, no theorem" % (m, s["step"]))
                probs += ["%s / %s: %s not at the Lean gate" % (m, s["step"], t)
                          for t in th if t not in key]
            elif s.get("status") == "owed":
                if not s.get("what"):
                    probs.append("%s / %s: owed, says nothing owed" % (m, s["step"]))
            else:
                probs.append("%s / %s: status %r" % (m, s["step"], s.get("status")))
    return probs


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
