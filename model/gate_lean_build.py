#!/usr/bin/env python3
"""gate_lean_build -- the Lean proofs, built and audited in CI (Wilson 11-12, approved).

  1. `lake build` in lean/JLane exits 0
  2. no `sorry` token in lean/JLane/JLane/*.lean outside comments
  3. no `axiom` declaration in those sources
  4. `#print axioms` for every theorem in KEY (the published results) -- run through
     `lake env lean` on a generated file, because a CACHED `lake build` prints no axiom lines
     and their absence would read as a pass. Every KEY theorem must REPORT (presence, not
     absence), and its axioms must be a subset of ALLOWED.
  5. the proof's constants: every Lean value in CONSTS (Params.lean) is EVALUATED in the same
     generated file and must equal model/proof_constants.load() on the tree's
     proof_constants.json -- the primitives stored there, the derivations computed by the
     loader. One source: a JSON edit the proofs were not rebuilt for turns this red.
  6. the premise lists (Wilson 11-19, the registry's premise check): for every run-level
     theorem in PREMISES, the Prop binders of its REAL signature (read in the same generated
     file by a MetaM walk of the constant's type, no parsing of source text) must be exactly
     the binders PREMISES lists for it -- an unlisted premise and a listed binder the signature
     lacks both turn this red. gate_lane_cert check 13 compares each READY_RULES rule's
     `applies` against its theorem's "applies" names here; the "contract" names form the
     run-level contract list, each to be mapped to its RTL contract and must-fire (next step).
ALLOWED = {propext, Quot.sound}. Classical.choice is NOT allowed: the build does not depend on
it today (11-12, measured), and admitting it needs a ruling with its reason.

MUST-FIRES, on a temporary copy of the tree:
  M_LEAN_SORRY   a theorem proved by `sorry` appended to SelfTimed.lean   -> check 2 red
  M_LEAN_AXIOM   an axiom, and a KEY-listed theorem that uses it           -> checks 3 and 4 red
  M_LEAN_CONST   proof_constants.json's pending_slack moved by one          -> check 5 red
  M_LEAN_PREMISE_UNLISTED  an extra hypothesis `hplant` planted in ready_pc1_plain_T's
                 signature (the proof still builds)                         -> check 6 red
All four are judged by the same `judge` as the clean arm (gate_meta's stub on it turns the gate
red). The other direction (a listed binder the signature lacks) is shown red on the clean
build's binders with a stale name added to a copy of PREMISES (no rebuild).

POSITIVE TOKEN: `GATE lean-build: PASSED`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEAN = os.path.join(ROOT, "lean", "JLane")
ALLOWED = {"propext", "Quot.sound"}
#: the published results: what the README / notes claim was proved (SPEC, not a measurement)
KEY = ("dstar", "dstar29", "dstar39", "dstar39_v2", "dstar39_st", "dstar39_hold",
       "hold_window", "runH_nohold", "runH_coinc", "step2_proj", "step2_proj_st",
       "run2_proj_st", "holdCycles_meets",
       "lemmaA_usb", "wb_bound_usb", "dstar_usb", "dstar_usb_rean", "dstar_usb_st",
       "retSpaced2", "retSpaced_of_pairs", "dstar_usb_pairs", "usb_wins", "usb_j2",
       "usb_nostall", "usb_j2_nb", "usb_br1_window",
       "npf_unlock", "pending_bound_optA", "head_valid_optA", "head_late_optA",
       "step2_proj_br", "run2_proj_br", "brP_wn", "head_late_br",
       "pending_bound_gap", "head_late_gap",
       "step3_proj", "arm_step", "run3_proj", "arm_release", "head_late_arm",
       "lemmaA_s", "wb_bound_win", "cnt_sparse_g", "wb_close", "j_interim_D",
       "hsep_words", "hrel_words", "wb_close_arm", "cnt_wb_shift", "wb_close_span",
       "prio_resp", "ts_chain", "rd_eq", "stall_free_bprime", "lemmaA_b",
       "hpri_b", "prio_resp_edf", "br1_empty", "head_valid_no_ret",
       "halfEdge_ok", "arm_release_half",
       "runH_coinc_st", "dstar39_hold_st",
       "stepF_noflush", "stepF_fill", "stepF_kill_set",
       "struct_stepF", "killInv_step", "runF_seg",
       "invF_step", "headFirst_stepF", "restart_hit", "flush_head_refill", "lemmaA_n",
       "relT_step", "step3T_proj", "invT_step", "run3T_proj", "arm_release_T", "disarm_noDec",
       "wb_bound_win_n", "lemmaA_nF", "wb_bound_winF",
       "hit_head", "head_of_hits", "flush_head_late",
       "invF_run3T", "wb_bound_T", "flush_head_late_T",
       "winq_step", "liveFl_noflush",
       "winq2_eq", "winq3_view", "winqT_view", "relT_le_of_ready",
       "branch_ld_D", "branch_j_interim",
       "br1_once", "br1_count", "head_valid_nonbranch",
       "first_stable", "arm_release_bus", "arm_release_T_bus",
       "ord_wbDly", "ord_release", "ord_late_free",
       "cnt_mono_run", "wb_bound_edf", "cnt_le_sum5", "wb_close_edf",
       "arm_release_ge", "arm_rd", "cap_zc", "cap_hn",
       # Slot.lean (Wilson 11-16): the guaranteed slot below USB receive
       "struct_stepS", "chargeS_le", "chargeS_own", "port_wait_boundS", "slot_waitS",
       "slot_once", "usb_once_S", "cntS_once", "slot_count", "usb_count", "slot_wait_bound",
       "usbSum_eq_cnt",
       # P1b from the fill (Wilson 11-16): both requester variants and their margins
       "p1b_capture", "p1b_direct", "p1b_margin_scan", "p1b_margin_direct",
       # Buf.lean (Wilson 11-16): the depth-2 buffer, always two fetches per ARM
       "two_fetch_scan", "two_fetch_direct", "buf_load", "buf_load_margin",
       "p1b2_margin_arm_scan", "p1b2_margin_arm_direct", "p1b2_margin_plain_scan",
       "p1b2_margin_plain_direct", "p1b2_margin_timeout_scan", "p1b2_margin_timeout_direct",
       # HeadS.lean (Wilson 11-16, carry-through C1): the head-valid chain on the slot run
       "spareFill_stepS", "wf_runS", "owed_runS", "head_valid_of_countsS", "pending_boundS",
       "head_valid_when_readyS",
       # BufEng.lean (Wilson 11-17, carry-through C2): the buffer in the engine, cycle-exact
       "wfB_run", "held_run", "head_valid_of_countsB", "port_wait_boundB", "pending_boundB",
       "head_valid_when_readyB", "empty_cycle_after_ret", "empty_cycle_disp", "empty_cycle_load",
       "mask_buf_next", "mask_flight_next", "ordB_run", "order_kept", "issue_index",
       "nr_held_run", "slot_countB", "slot_count_two",
       # FlushKeep.lean (Wilson 11-17, K1): the edge word survives the flush
       "edge_survives_flush", "flush_keeps_only_edge", "flush_buf_empty", "flush_drops_timeout",
       "flush_empty_of_absent", "flush_keep_slot", "stepBK_other", "edge_capture_by_edge",
       "edge_capture_by_edge_direct", "edge_valid_by_release", "ft_edge_margin_scan",
       "ft_edge_margin_direct", "ft_edge_cap_before_edge_direct",
       # FlushKill.lean (Wilson 11-17, K2a): BufEng's invariant across the keep-flush, with K5
       "wfBK_step", "wfBK_run", "wfBK_init", "stepBKK_noflush", "edge_survives_flushK",
       "flushK_keeps_only_edge", "flushK_buf_empty", "kill_files_nothing",
       # FlushHeld.lean (Wilson 11-17, K2b): the buffered armed view; held at the edge
       "heldB_step", "armed_step", "armInvB_step", "flushOk_hit", "edge_held_at_edge",
       "ft_edge_at_release", "edge_held_armed", "ft_edge_at_release_armed",
       # ContendB.lean (Wilson 11-17, C3): the slot under contention, FCFS by capture
       "slot_wait_fcfs", "oldSum_split", "slot_wait_fcfs_two", "slot_wait_fcfs_ret",
       "contend_margin", "contend_per_lane_val",
       # RespWinB.lean (Wilson 11-18, slot_on_composition part A): the window bound on the
       # buffered engine with flushes and kill; A2 for a lane flushed at its own edges
       "stepBKK_ts_y", "ts_ge_startBK", "lemmaA_nBK", "wb_bound_winBK", "wb_bound_winBK_fl",
       # NpfB.lean (Wilson 11-18, slot_on_composition step 1): the no-prefetch hold on runB
       "held_le_one", "want_frozenB", "npf_holdB", "npf_unlockB",
       # GapRunB.lean (Wilson 11-18, slot_on_composition step 2): GapRun on runB, hZC charging
       "ts_monoB", "ts_gapB", "rdB_eq", "pb_defer_gB", "pending_bound_gapB", "head_late_gapB",
       # TrajB.lean (Wilson 11-18, slot_on_composition step 3a): the buffered engine as lane y
       # sees it, along any trajectory that agrees with stepB for y (the flush as a restart)
       "now_T", "ts_monoT", "port_waitT", "window_leT", "window_le_19T", "held_runT",
       "head_valid_of_countsT", "npf_holdT", "npf_unlockT",
       # GapRunT.lean (Wilson 11-18, step 3b): GapRun along a trajectory from 2 words or from
       # the restart's 1 (the start's refill timed from the start cycle); GapRunB's two
       # theorems are its instances along runB (trajY_runB, cntT_runB, chargeSumT_runB)
       "rdT_eq", "ts_gapT", "pb_defer_gT", "pending_startT", "pending_bound_gapT",
       "head_late_gapT", "trajY_runB", "cntT_runB", "chargeSumT_runB",
       # RestartB.lean (Wilson 11-18, step 3c): runBK between y's flushes is a trajectory
       "agree_stepBKK", "trajY_runBK", "wfB_runBK",
       # RestartB.lean (step 3c part 2): at f + 3 the flushed lane holds exactly its edge word
       "frozen_stepBKK", "restart_three", "restart_runBK",
       # RestartB.lean: a killed capture for y needs a flush of y one or two cycles before, so a
       # stretch with y unflushed (from two cycles back) is a trajectory
       "kill_prov", "kill_prov_runBK", "trajY_runBK_noflush",
       # SlotReadyB.lean (step 4, R1): slot readiness on the buffered engine along a trajectory --
       # the run-level link behind READY_RULES (counting core, port, FCFS wait, issue in the wait)
       "held_of_head", "held_of_ret", "ready_of_capture_T", "slot_issue_cap_T", "slot_wait_T",
       "slot_issue_within_T", "slot_ready_T",
       # SlotReadyB.lean (R2): READY_RULES pc1_plain on the buffered engine (p1b_margin_scan cited)
       "wb_after_empty_T", "ready_pc1_plain_T",
       # SlotReadyB.lean (R2b): the second fetch, READY_RULES pc2_plain / pc2_arm
       # (p1b2_margin_plain_scan / p1b2_margin_arm_scan cited)
       "head_of_counts_T", "cnt_three_hits", "slot_two_fetch_T", "ready_pc2_plain_T",
       "disp_pick_T", "ready_pc2_arm_T",
       # SlotReadyB.lean (Wilson 11-19): the no-prefetch bridge behind READY_RULES pc1_not_npf
       "npf_no_slot", "npf_no_issue_T",
       # ComposeB.lean (Wilson 11-19, composition L1): the run cut at y's last flush -- the
       # restart window f+1 / f+2, and the stretch from f+3 as a well-formed trajectory
       "last_true", "flush_cut", "restart_head_12", "restart_head_runBK", "stretch_after_flush",
       # ComposeB.lean (composition L2): the first stretch, from a start with no kill pending
       "no_kill_one", "stretch_first",
       # ComposeB.lean (composition L3): the head over a whole run with flushes
       "head_of_cert", "head_valid_runBK",
       # ComposeB.lean (composition L4): hR on a stretch from wb_bound_winBK_fl
       "hR_stretch", "hstart_after_flush",
       # ComposeB.lean (K8 proof (b) on the armed engine runBA): no re-flush at f+1 / f+2
       "no_rehit_two", "armInvB_runBA", "flush_spacing_runBA",
       # ComposeB.lean (the bridge): the armed run IS runBK with winS / flS; FlushOk and K8 on it
       "step_win_eq", "stepB_win_congr", "stepBKK_win_congr", "flushOk_win_congr", "now_runBA",
       "runBA_proj", "flushOk_runBA", "flush_spacing_runBK",
       # ComposeB.lean: hedge (the edge word at every flush) on the bridged run
       "runBA_add", "wfBK_runBA", "armed_origin", "hedge_runBK", "hedge_runBK_armed",
       # ComposeB.lean (ready_ft_edge_T step 2): the slot's capture for y on a stretch, unkilled
       "slot_cap_stretch")
#: proof_constants.load() key -> the Lean expression that must evaluate to it (SPEC: the map)
CONSTS = {
    "lemmaA_window": "LEMMA_A_WINDOW", "R_base": "R_BASE", "dispatch_cycles": "DISPATCH_CYCLES",
    "usb_extra_decisions": "USB_EXTRA_DECISIONS", "pending_slack": "PENDING_SLACK",
    "rean_pipe": "REAN_PIPE", "rean_halving": "REAN_HALVING", "R_usb": "R_USB",
    "noWB_min": "NOWB_MIN", "dstar_retire": "DSTAR_RETIRE", "dstar_retire_usb": "DSTAR_RETIRE_USB",
    "usb_deadline_margin": "USB_DEADLINE_MARGIN",
    "n_lanes": "K", "l_refill": "L_REFILL", "usb_br1_per_window": "USB_BR1_PER_WINDOW",
    "dstar": "DSTAR", "br1_budget": "BR1_BUDGET", "coresident_usb": "CORESIDENT_USB",
    "coresident_min_d": "CORESIDENT_MIN_D",
    "head_slack": "HEAD_SLACK", "usb_rr_on_time": "USB_RR_ON_TIME",
    "sop_fetch_slack": "SOP_FETCH_SLACK",
    "br_w_min": "BR_W_MIN", "br_succ_late": "BR_SUCC_LATE",
    "j_interim_head_late_optA": "J_INTERIM_HEAD_LATE_OPTA",
    "flush_refill_late": "FLUSH_REFILL_LATE",
    "usb_other_R": "USB_OTHER_R",
    "branch_j_wmin": "BRANCH_J_WMIN",
    "slot_wait_base": "SLOT_WAIT_BASE", "slot_charge": "SLOT_CHARGE",
    "arm_retire_gap": "ARM_RETIRE_GAP", "p1b_margin_scan": "P1B_MARGIN_SCAN",
    "p1b_margin_direct": "P1B_MARGIN_DIRECT",
    "slot_fetches_per_arm": "SLOT_FETCHES_PER_ARM",
    "p1b2_margin_arm_scan": "P1B2_MARGIN_ARM_SCAN", "p1b2_margin_arm_direct": "P1B2_MARGIN_ARM_DIRECT",
    "ft_edge_margin_scan": "FT_EDGE_MARGIN_SCAN", "ft_edge_margin_direct": "FT_EDGE_MARGIN_DIRECT",
    "contend_per_lane": "CONTEND_PER_LANE",
}
#: THE PREMISE LISTS (Wilson 11-19; SPEC, checked against the Lean signature by check 6). For
#: each run-level theorem a READY_RULES rule relies on (`run_thm`), EVERY Prop binder, in one or
#: more of three kinds:
#:   "applies"  {condition name: binders} -- what the certificate must establish per image for
#:              the rule to apply (gate_lane_cert check 13 compares the rule's `applies`);
#:   "contract" {contract premise: binders} -- properties of the hardware and the run, the same
#:              for every rule (the run-level contract list: each maps to its RTL contract and
#:              that contract's must-fire, Wilson 11-19);
#:   "shape"    (binders,) -- the events the theorem is about (the ARM's capture, the
#:              retirements, the release at t, the counts placing them): its statement, not a
#:              condition anyone checks.
#: A binder may carry two names: the second-fetch requester premises (hq2 / hold2) are the
#: slot_requester contract AND the reason pc1_not_npf is a condition -- BufEng.SReqB requests
#: for y only while its held words are not no-prefetch, so behind a branch PC+1 they cannot be
#: discharged.
_TRAJ_CONTRACT = {"engine_model": ("hT",), "engine_wf": ("hWf",)}
_PC2_SHAPE = ("ht", "hcap", "hcw", "hw12", "hw2t", "hw1", "hw2", "hfirst", "hmid", "hnr", "hrel")
PREMISES = {
    "ready_pc1_plain_T": {
        "applies": {"arm_capture_empty": ("hempty",), "plain_edge_arm": ("hgap",),
                    "wait_in_margin": ("hC", "hcm")},
        "contract": dict(_TRAJ_CONTRACT, slot_requester=("hq", "hold")),
        "shape": ("ht", "hcap", "hcw", "hw2t", "hw2", "hfirst", "hnr", "hrel"),
    },
    "ready_pc2_plain_T": {
        "applies": {"arm_capture_empty": ("hempty",), "plain_edge_arm": ("hgap",),
                    "pc1_not_npf": ("hq2", "hold2"), "d_ge_min": ("hd", "hd4"),
                    "wait_in_margin": ("hC1", "hW1", "hC2", "hW2", "hcm")},
        "contract": dict(_TRAJ_CONTRACT, slot_requester=("hq1", "hold1", "hq2", "hold2")),
        "shape": _PC2_SHAPE,
    },
    "ready_pc2_arm_T": {
        "applies": {"arm_capture_empty": ("hempty",), "plain_edge_arm": ("hgap1",),
                    "pc1_plain_edge_arm": ("hgap2",), "pc1_not_npf": ("hq2", "hold2"),
                    "wait_in_margin": ("hC1", "hW1", "hC2", "hW2", "hcm")},
        "contract": dict(_TRAJ_CONTRACT, slot_requester=("hq1", "hold1", "hq2", "hold2"),
                         disp_released_only=("hwin",)),
        "shape": _PC2_SHAPE,
    },
}
#: the M_LEAN_PREMISE_UNLISTED plant: (file, theorem, the signature text it extends, the binder)
PREMISE_PLANT = ("SlotReadyB.lean", "ready_pc1_plain_T",
                 "theorem ready_pc1_plain_T (T : Nat)", "(hplant : (0 : Nat) = 0)")
PLANT_THM = "planted_by_gate"
#: gate_mutant_kills' scratch-mutant registry (ruling AC2): this gate is the killer
SCRATCH_MUTANTS = {
    "M_LEAN_SORRY": "a theorem proved by `sorry`, planted in a temp copy of the tree",
    "M_LEAN_AXIOM": "an axiom and a theorem using it, planted in a temp copy of the tree",
    "M_LEAN_CONST": "proof_constants.json's pending_slack moved by one, in a temp copy of the tree",
    "M_LEAN_PREMISE_UNLISTED": "an extra hypothesis planted in ready_pc1_plain_T's signature, "
                               "in a temp copy of the tree",
}


def _strip_comments(src):
    src = re.sub(r"/-.*?-/", " ", src, flags=re.S)
    return re.sub(r"--[^\n]*", " ", src)


def scan(tree):
    """-> (sorry hits, axiom declarations), outside comments."""
    s, a = [], []
    d = os.path.join(tree, "JLane")
    for f in sorted(os.listdir(d)):
        if not f.endswith(".lean"):
            continue
        body = _strip_comments(open(os.path.join(d, f), encoding="utf-8").read())
        if re.search(r"\bsorry\b", body):
            s.append(f)
        if re.search(r"(?m)^\s*axiom\s", body):
            a.append(f)
    return s, a


def _binder_walk(thms):
    """Lean source: print `PREMISE <thm> <binder>` for every Prop binder of each theorem's type
    (forallTelescope, no unfolding: exactly the signature's binders), `NOTHM <thm>` if absent,
    then `PREMISES-DONE` (its absence means the walk did not run)."""
    lst = ", ".join("`JLane.%s" % t for t in thms)
    return ("open Lean Meta in\n#eval show MetaM Unit from do\n"
            "  for n in [%s] do\n"
            "    match (<- getEnv).find? n with\n"
            "    | none => IO.println s!\"NOTHM {n}\"\n"
            "    | some ci =>\n"
            "      forallTelescope ci.type fun xs _ => do\n"
            "        for x in xs do\n"
            "          let d <- x.fvarId!.getDecl\n"
            "          if <- isProp d.type then\n"
            "            IO.println s!\"PREMISE {n} {d.userName}\"\n"
            "  IO.println \"PREMISES-DONE\"\n" % lst)


def premise_problems(binders, done, premises=None):
    """check 6: each PREMISES theorem's listed binders against its signature's Prop binders"""
    premises = PREMISES if premises is None else premises
    if not done:
        return ["premise walk did not run (no PREMISES-DONE line)"]
    probs = []
    for thm, spec in sorted(premises.items()):
        if thm not in KEY:
            probs.append("premise list for %s, which is not in KEY" % thm)
        if thm not in binders:
            probs.append("premise list for %s: no such theorem in the build" % thm)
            continue
        listed = set(spec["shape"])
        for kind in ("applies", "contract"):
            for bs in spec[kind].values():
                listed |= set(bs)
        real = binders[thm]
        for b in real:
            if b not in listed:
                probs.append("premise %s of %s is unlisted (not applies / contract / shape)"
                             % (b, thm))
        for b in sorted(listed - set(real)):
            probs.append("premise list for %s names %s, which its signature lacks" % (thm, b))
    return probs


def axioms(tree, names, prem_thms=()):
    """-> ({name: [axioms]}, missing names, raw output, {Lean constant: evaluated value},
    ({theorem: [Prop binder names]}, the binder walk ran))."""
    fd, path = tempfile.mkstemp(suffix=".lean", prefix="gate_lean_axioms_")
    with os.fdopen(fd, "w") as fh:
        fh.write("import Lean\nimport JLane\n"
                 + "".join("#print axioms JLane.%s\n" % n for n in names)
                 + "".join('#eval IO.println s!"CONST %s {JLane.%s}"\n' % (c, c)
                           for c in CONSTS.values())
                 + (_binder_walk(prem_thms) if prem_thms else ""))
    try:
        r = subprocess.run(["lake", "env", "lean", path], cwd=tree, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    finally:
        os.remove(path)
    out = r.stdout + r.stderr
    got = {}
    for m in re.finditer(r"'JLane\.(\w+)' depends on axioms: \[([^\]]*)\]", out):
        got[m.group(1)] = [x.strip() for x in m.group(2).split(",") if x.strip()]
    for m in re.finditer(r"'JLane\.(\w+)' does not depend on any axioms", out):
        got[m.group(1)] = []
    consts = {m.group(1): int(m.group(2)) for m in re.finditer(r"(?m)^CONST (\w+) (\d+)\s*$", out)}
    binders = {}
    for m in re.finditer(r"(?m)^PREMISE JLane\.(\w+) (\S+)\s*$", out):
        binders.setdefault(m.group(1), []).append(m.group(2))
    done = bool(re.search(r"(?m)^PREMISES-DONE\s*$", out))
    return got, [n for n in names if n not in got], out, consts, (binders, done)


def const_problems(tree, consts):
    """check 5: the Lean values against proof_constants.load() on THIS tree's JSON."""
    sys.path.insert(0, HERE)
    import proof_constants
    want = proof_constants.load(os.path.join(tree, "proof_constants.json"))
    probs = []
    for key, lean in CONSTS.items():
        if lean not in consts:
            probs.append("constant %s: no value evaluated in Lean" % lean)
        elif key not in want:
            probs.append("constant %s: proof_constants has no %r" % (lean, key))
        elif consts[lean] != want[key]:
            probs.append("constant %s = %d in Lean, %s = %d in proof_constants"
                         % (lean, consts[lean], key, want[key]))
    return probs


def judge(tree, names=KEY):
    probs = []
    r = subprocess.run(["lake", "build"], cwd=tree, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return ["lake build failed: %s" % (r.stdout + r.stderr)[-300:]], {}
    s, a = scan(tree)
    if s:
        probs.append("`sorry` in %s" % ", ".join(s))
    if a:
        probs.append("an `axiom` declaration in %s" % ", ".join(a))
    got, missing, raw, consts, (binders, done) = axioms(tree, names, tuple(sorted(PREMISES)))
    if missing:
        probs.append("no axiom report for %s (%s)" % (", ".join(missing), raw.strip()[-200:]))
    for n, ax in sorted(got.items()):
        extra = set(ax) - ALLOWED
        if extra:
            probs.append("%s depends on %s, outside {%s}" % (n, sorted(extra), ", ".join(sorted(ALLOWED))))
    probs += const_problems(tree, consts)
    probs += premise_problems(binders, done)
    got["_consts"] = consts
    got["_binders"] = binders
    return probs, got


def _mutant_tree(kind):
    tmp = tempfile.mkdtemp(prefix="gate_lean_%s_" % kind)
    dst = os.path.join(tmp, "JLane")
    shutil.copytree(LEAN, dst)                    # .lake included: an incremental rebuild
    if kind == "const":
        import json
        jp = os.path.join(dst, "proof_constants.json")
        k = json.load(open(jp, encoding="utf-8"))
        k["pending_slack"] += 1
        with open(jp, "w", encoding="utf-8") as fh:
            json.dump(k, fh, indent=2)
        return tmp, dst
    if kind == "premise":
        f, _thm, sig, plant = PREMISE_PLANT
        p = os.path.join(dst, "JLane", f)
        src = open(p, encoding="utf-8").read()
        assert src.count(sig) == 1, sig
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(src.replace(sig, sig + " " + plant))
        return tmp, dst
    p = os.path.join(dst, "JLane", "SelfTimed.lean")
    src = open(p, encoding="utf-8").read().rstrip()
    assert src.endswith("end JLane")
    if kind == "sorry":
        plant = "theorem %s : (1 : Nat) = 2 := sorry\n" % PLANT_THM
    else:
        plant = "axiom planted_axiom : (1 : Nat) = 2\ntheorem %s : (1 : Nat) = 2 := planted_axiom\n" % PLANT_THM
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src[:-len("end JLane")] + plant + "\nend JLane\n")
    return tmp, dst


def main() -> int:
    print("Lean build audit: lean/JLane, %d published theorems, axioms within {%s}"
          % (len(KEY), ", ".join(sorted(ALLOWED))))
    probs, got = judge(LEAN)
    for n in KEY:
        print("    %-18s %s" % (n, got.get(n, "*** NO REPORT")))
    print("    constants (Lean = proof_constants): %s"
          % ", ".join("%s %s" % (c, v) for c, v in sorted(got.get("_consts", {}).items())))
    binders = got.get("_binders", {})
    for thm in sorted(PREMISES):
        spec = PREMISES[thm]
        print("    premises %-18s %d in the signature: applies {%s}; contract {%s}; shape %d"
              % (thm, len(binders.get(thm, ())), ", ".join(sorted(spec["applies"])),
                 ", ".join(sorted(spec["contract"])), len(spec["shape"])))
    for p in probs:
        print("  ***", p)
    for kind in ("sorry", "axiom", "const", "premise"):
        tmp, tree = _mutant_tree(kind)
        try:
            mp, _ = judge(tree, KEY + ((PLANT_THM,) if kind in ("sorry", "axiom") else ()))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        # each arm must be killed by ITS check: the sorry scan, the #print axioms limit
        # (not merely by the source grep for `axiom`), the constants comparison, and the
        # premise list (the planted binder named as unlisted)
        want = {"sorry": "`sorry` in", "axiom": "outside {", "const": "in proof_constants",
                "premise": "premise hplant of %s is unlisted" % PREMISE_PLANT[1]}[kind]
        name = "PREMISE_UNLISTED" if kind == "premise" else kind.upper()
        hit = [p for p in mp if want in p]
        red = bool(hit)
        print("  must-fire M_LEAN_%-6s %s  %s" % (name, "RED (killed)" if red else "*** SURVIVED",
                                                  (hit[0] if hit else (mp[0] if mp else ""))[:100]))
        if not red:
            probs.append("must-fire M_LEAN_%s survived" % name)
    # the other direction, on the clean build's binders: a listed name the signature lacks
    stale = {t: dict(v, shape=tuple(v["shape"]) + (("hstale",) if t == PREMISE_PLANT[1] else ()))
             for t, v in PREMISES.items()}
    sp = premise_problems(binders, True, stale)
    red = any("names hstale, which its signature lacks" in p for p in sp)
    print("  premise list, stale name (other direction): %s  %s"
          % ("RED (caught)" if red else "*** NOT CAUGHT", (sp[0] if sp else "")[:100]))
    if not red:
        probs.append("a stale premise-list name was not caught")
    if probs:
        print("GATE lean-build: FAILED (%d)" % len(probs))
        return 1
    print("GATE lean-build: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
