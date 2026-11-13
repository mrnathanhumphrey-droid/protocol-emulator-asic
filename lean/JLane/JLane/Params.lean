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

end JLane
