import JLane.Params
/-!
# Brick 0 — the engine state
Registers of `src/pe_engine.v` that the port/dispatch timing depends on,
per docs/PORT_SPEC.md (RTL after Ruling TF / TF2-R; cite by substring anchor).

TF1/TF2/R1–R3 change no observable behaviour (lockstep byte-identical; TF2
proved by SymbiYosys), so the model uses the *values* the registered
readiness and key hold in each cycle.

Abstracted away in v1 (auditable scoping):
* data/addresses (paddr, l_pc, l_fpc, l_base) — they decide *what*, never *when*;
* header load & priming (§5) — the model starts primed;
* W1 hold: `l_hcnt = 0` (P9w measured 0 on admissible arms);
* held clocked re-dispatch and chaining re-arm (owe no refill) are excluded;
  looping re-arm is timing-identical to ordinary retire (§4);
* clocked actions excluded: the WB advance is `wb_dly`, which halves on a
  HALF_HIGH lane's HIGH phase (CE1) and is overridden by the open-drain park
  rebase — both break the periodic release `t₀ + j·d` the slack argument uses;
* timestamps are `Nat`; the RTL compares 16-bit timestamps by signed
  difference, so the model is faithful while every lane stays inside ±2^15
  of `now` (PS3: only exceeded in overload, below `D*`);
* armed/timeout term of `rel_q`, HALT, config_err.
-/
namespace JLane

inductive PState where
  | scan | req | wait | cap
  deriving DecidableEq, Repr

inductive DState where
  | idle | drive | wb
  deriving DecidableEq, Repr

abbrev Slot := Bool

/-- A program. A writeback of lane `l` at cycle `t` advances its timestamp by
`dly l + ext t l`: `dly` is the lane's minimum delay, `ext` the extra on that writeback
(0 for a plain lane; the LOW phases of a HALF_HIGH clocked lane; a park or armed-edge
rebase). `ext` defaults to 0, so `{ live, dly }` is the constant-delay program of v1. -/
structure Program where
  live : Lane → Bool
  dly  : Lane → Nat
  ext  : Nat → Lane → Nat := fun _ _ => 0

structure Engine where
  now   : Nat
  actv  : Lane → Slot → Bool
  sel   : Lane → Slot
  ts    : Lane → Nat
  pst   : PState
  /-- `pl`: lane the in-flight refill serves. -/
  pl    : Lane
  /-- `prr`: round-robin pointer, its own register since TF3. -/
  prr   : Lane
  /-- `pbr1`: the in-flight refill was issued by branch 1 (capture leaves `prr`). -/
  pbr1  : Bool
  pslot : Slot
  /-- `winner_q`: last cycle's EDF winner, read by branch 1 (TF3). -/
  winq  : Option Lane
  st    : DState
  cur   : Lane

namespace Engine
def headValid (e : Engine) (l : Lane) : Bool := e.actv l (e.sel l)
def spareValid (e : Engine) (l : Lane) : Bool := e.actv l (!e.sel l)
/-- §1 `want_fetch`, chaining re-arm excluded in v1. -/
def wantFetch (e : Engine) (l : Lane) : Bool := !e.headValid l || !e.spareValid l
/-- §1 branch 2: head if the head is empty, else the spare. -/
def fetchSlot (e : Engine) (l : Lane) : Slot := if e.headValid l then !e.sel l else e.sel l
/-- §3 release: `now == l_timestamp`, held thereafter. -/
def relDue (P : Program) (e : Engine) (l : Lane) : Bool := P.live l && decide (e.ts l ≤ e.now)
/-- §3 `ready = rel_due & hz_q`, with `l_hcnt = 0` in v1. -/
def ready (P : Program) (e : Engine) (l : Lane) : Bool := e.relDue P l
/-- Number of empty slots the lane owes (0, 1 or 2). -/
def owed (e : Engine) (l : Lane) : Nat :=
  (if e.actv l false then 0 else 1) + (if e.actv l true then 0 else 1)

theorem owed_le_two (e : Engine) (l : Lane) : e.owed l ≤ 2 := by
  unfold owed; split <;> split <;> omega

theorem wantFetch_iff (e : Engine) (l : Lane) : e.wantFetch l = true ↔ 1 ≤ e.owed l := by
  unfold wantFetch headValid spareValid owed
  cases hs : e.sel l <;> cases h0 : e.actv l false <;> cases h1 : e.actv l true <;>
    simp [h0, h1]
end Engine

/-- Sanity: the port never fetches into an already-valid slot. -/
theorem fetchSlot_invalid (e : Engine) (l : Lane) (h : e.wantFetch l = true) :
    e.actv l (e.fetchSlot l) = false := by
  unfold Engine.wantFetch Engine.headValid Engine.spareValid at h
  unfold Engine.fetchSlot Engine.headValid
  cases hh : e.actv l (e.sel l) <;> simp_all

end JLane
