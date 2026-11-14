/-!
# Parameters of the PE engine
Values fixed to the built configuration of `src/pe_engine.v`
(`N_LANES = 5`, `SPL = 2` in both pe_engine.v and project.v; 50 MHz).
-/
namespace JLane

/-- Number of lanes, `N_LANES`. -/
abbrev K : Nat := 5

/-- Refill latency: `P_SCAN → P_REQ → P_WAIT → P_CAP`, unconditional after the scan,
non-preemptible (PORT_SPEC §2; `M_PFETCH_NOWAIT` is a mutant, not a configuration). -/
abbrev L_REFILL : Nat := 4

/-- Slots per lane, `SPL`. -/
abbrev SPL : Nat := 2

/-- Dispatch occupancy per action: `ST_DRIVE` + `ST_WB`. NOT what a response-time analysis charges. -/
abbrev C_OCC : Nat := 2

/-- Dispatch spacing `C`: `ST_IDLE → ST_DRIVE → ST_WB` is a three-state cycle, so dispatches are
≥ 3 cycles apart. This is what RTA charges (pe_engine.v anchor `C IS 3, NOT 2`; measured by
`test/run_csat.py`). -/
abbrev C_SPACING : Nat := 3

/-- A lane index. -/
abbrev Lane := Fin K

/-- `D* = k · L_REFILL`. -/
abbrev DSTAR : Nat := K * L_REFILL

theorem dstar_val : DSTAR = 20 := rfl

/-- At `d = D*` for every lane, port demand per period equals port capacity. Load is exactly 1. -/
theorem port_saturated_at_dstar : K * L_REFILL = DSTAR := rfl

/-! ### The proof's constants (Wilson 11-12)
The primitives are stored once, in `lean/JLane/proof_constants.json`; `gate_lean_build`
evaluates every value below and compares it with that file and with `model/proof_constants.py`'s
derivations. The derived thresholds are definitions here, never second literals. -/

/-- Lemma A's window, no re-anchoring lane: `3(k − 1) + 2 + 1`. -/
abbrev LEMMA_A_WINDOW : Nat := 15
/-- The response bound with every other lane decided at most once per window. -/
abbrev R_BASE : Nat := 14
/-- Cycles per dispatch charged by Lemma A (= `C_SPACING`). -/
abbrev DISPATCH_CYCLES : Nat := 3
/-- Extra decisions per window the USB lane may take under re-anchor (twice, not once). -/
abbrev USB_EXTRA_DECISIONS : Nat := 1
/-- `pending_bound`'s slack: a pending refill is at most `R + 25` past its release (B = 0). -/
abbrev PENDING_SLACK : Nat := 25
/-- Re-anchor floor, pipeline part: a writeback at `r + 2` is visible to `rean_cap` at `r + 3`. -/
abbrev REAN_PIPE : Nat := 3
/-- Re-anchor floor, the target `now + d / 2`. -/
abbrev REAN_HALVING : Nat := 2

/-- The response bound with a re-anchoring USB lane. -/
abbrev R_USB : Nat := R_BASE + DISPATCH_CYCLES * USB_EXTRA_DECISIONS
/-- Per-dispatch spacing a lane needs for no writeback inside its own wait (clock row 1). -/
abbrev NOWB_MIN : Nat := R_USB + DISPATCH_CYCLES
/-- Retirement spacing without a re-anchoring lane (`dstar39`). -/
abbrev DSTAR_RETIRE : Nat := R_BASE + PENDING_SLACK
/-- Retirement spacing with the USB receive in the image (Wilson 11-12, option (i)). -/
abbrev DSTAR_RETIRE_USB : Nat := R_USB + PENDING_SLACK
/-- The re-anchor floor at bit period `d`: the next release is at least this far after the
last one (`test/run_rean_floor.py`, exact on the RTL at d = 40 and 48). -/
def reanFloor (d : Nat) : Nat := REAN_PIPE + d / REAN_HALVING

/-- USB-lane branch-1 refills in any window of `23 + BR1_BUDGET` cycles, at most (Wilson 11-13,
revised no-stall ruling; proved in `UsbNoStall.lean`, `usb_br1_window`). -/
abbrev USB_BR1_PER_WINDOW : Nat := 2
/-- Port cycles the USB lane's branch-1 refills can take from another lane's refill in such a
window: one `L_REFILL` each (SCAN → REQ → WAIT → CAP, `pe_engine.v` l.2703, read). -/
abbrev BR1_BUDGET : Nat := USB_BR1_PER_WINDOW * L_REFILL
/-- Per-action spacing every other lane needs in an image with the USB receive (replaces 42). -/
abbrev CORESIDENT_USB : Nat := R_USB + PENDING_SLACK + BR1_BUDGET
/-- The co-resident lanes' delay floor from `head_valid_ret` (`D* + B`); implied by
`CORESIDENT_USB` (`coresident_implies_min_d`). -/
abbrev CORESIDENT_MIN_D : Nat := DSTAR + BR1_BUDGET

theorem br1_budget_val : BR1_BUDGET = 8 := rfl
theorem coresident_usb_val : CORESIDENT_USB = 50 := rfl
theorem coresident_min_d_val : CORESIDENT_MIN_D = 28 := rfl
theorem coresident_implies_min_d : CORESIDENT_MIN_D ≤ CORESIDENT_USB := by decide

theorem lemmaA_window_val : LEMMA_A_WINDOW = 3 * (K - 1) + 2 + 1 := rfl
theorem r_base_val : R_BASE + 1 = LEMMA_A_WINDOW := rfl
theorem dispatch_cycles_val : DISPATCH_CYCLES = C_SPACING := rfl
theorem r_usb_val : R_USB = 17 := rfl
theorem r_usb_lemmaA : R_USB = 3 * K + 2 := rfl
theorem nowb_min_val : NOWB_MIN = 20 := rfl
theorem dstar_retire_val : DSTAR_RETIRE = 39 := rfl
theorem dstar_retire_usb_val : DSTAR_RETIRE_USB = 42 := rfl
theorem reanFloor_40 : reanFloor 40 = 23 := rfl
theorem reanFloor_48 : reanFloor 48 = 27 := rfl

/-- The head-valid slack: a pending refill is at most `R + PENDING_SLACK + B` past its release,
so the head is valid when the next release is strictly later — `R + HEAD_SLACK + B` (the
`26` of every head-valid condition; `HEAD_SLACK + DSTAR` is condition F's `46`). -/
abbrev HEAD_SLACK : Nat := PENDING_SLACK + 1

theorem head_slack_val : HEAD_SLACK = 26 := rfl

/-- The priority lane's response with an on-time head (`PrioResp.prio_resp`, `L = 0`): it is
decided at the first idle cycle, within `DISPATCH_CYCLES − 1` (`idle3`), so `Rr = 2`. -/
abbrev USB_RR_ON_TIME : Nat := DISPATCH_CYCLES - 1
/-- Wilson 11-14, the corrected next-SOP requirement: `GapRun`'s head-valid condition for the
first receive word after `arm_sop` (`Z = Rr` on time, `L = 0`) asks `arm_sop`'s gap before the
SOP plus the half-bit nop's gap to cover `SOP_FETCH_SLACK + B`. -/
abbrev SOP_FETCH_SLACK : Nat := USB_RR_ON_TIME + HEAD_SLACK

theorem usb_rr_on_time_val : USB_RR_ON_TIME = 2 := rfl
theorem sop_fetch_slack_val : SOP_FETCH_SLACK = 28 := rfl
theorem pending_slack_val : PENDING_SLACK = 25 := rfl

/-- The RTL's branch-wait floor (`BR_W_MIN = N_LANES*4 + (N_LANES-1)*3 + 1`, `pe_engine.v`
l.743): `K · L_REFILL + (K − 1) · DISPATCH_CYCLES + 1`. -/
abbrev BR_W_MIN : Nat := K * L_REFILL + (K - 1) * DISPATCH_CYCLES + 1
/-- The lateness of the word after a branch at the floor wait, base part (`OptRun.head_late_optA`,
condition D with `Rn = R_BASE`, `Wn = BR_W_MIN`): `LD = BR_SUCC_LATE + B`. -/
abbrev BR_SUCC_LATE : Nat := R_BASE + PENDING_SLACK + 1 - BR_W_MIN
/-- Wilson 11-13, interim (until the dispatcher fix (b′)): the dispatcher-wide stall bound
`J = 1 + LD` at `B = BR1_BUDGET`, quoted by `run_branch_check`. -/
abbrev J_INTERIM_HEAD_LATE_OPTA : Nat := 1 + BR_SUCC_LATE + BR1_BUDGET

theorem br_w_min_val : BR_W_MIN = 33 := rfl
theorem br_succ_late_val : BR_SUCC_LATE = 7 := rfl
theorem j_interim_val : J_INTERIM_HEAD_LATE_OPTA = 16 := rfl

/-- FALLTHROUGH (F5, `FlushLate.flush_head_late`): a flushed lane's head is valid by its release
plus this plus `B` -- the port's `L_REFILL - 1` cycles back to a clean state, the one-pass window
`23 + B` of `restart_hit`, less the cycle from the flush to the release. -/
abbrev FLUSH_REFILL_LATE : Nat := (L_REFILL - 1) + 23 - 1

theorem flush_refill_late_val : FLUSH_REFILL_LATE = 25 := rfl

end JLane
