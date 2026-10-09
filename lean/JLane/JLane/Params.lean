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

end JLane
