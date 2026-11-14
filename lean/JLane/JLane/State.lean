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
* **DECLARED EXCLUSION (Wilson 11-12): the USB re-anchor** (v2 bundle 3,
  `l_timestamp[USB_LANE] <= rean_ts`, `rean_ts = now + d/2` at an edge): it rewrites the
  USB lane's timestamp between the bits of a self-timed receive, so its release is not
  `+ dly` per writeback. Measured 11-12 (`run_usbrx` arms, 13 runs): minimum release spacing
  27 at d = 40. The self-timed theorems (`dstar39_st`) are stated for runs without it. The USB
  lane under re-anchor is covered by `UsbLane.lean` (`dstar_usb_st`, Wilson 11-12 option (i)):
  the lane is modelled by its re-anchor floor `reanFloor d` (the named hardware hypothesis
  `ReanFloorModel`, measured by `test/run_rean_floor.py`, minimum 23 at d = 40), the
  response bound becomes `R_USB = 17`, and co-resident lanes need `d ≥ DSTAR_RETIRE_USB = 42`;
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
  /-- Per slot: the word held there allows **no prefetch past it** — a branch (option A,
  `want_fetch` l.2798–2801: its successor is unknown until it writes back) or a chaining
  re-arm (l.2795: its successor is the head itself). Set at the capture (Wilson 11-13, the
  branch brick); all-false reproduces the v1 port exactly. -/
  npf   : Lane → Slot → Bool

/-- A program. A writeback of lane `l` at cycle `t` advances its timestamp by
`dly l + ext t l`: `dly` is the lane's minimum delay, `ext` the extra on that writeback.
It **retires** its action (invalidates the head, flips the select, owes a refill) iff
`ret t l`: a held clocked phase (7C) or a chaining re-arm (7A) does not.
`fnpf e`: the word captured at `e` allows no prefetch past it (a free input, like the word
itself). Defaults `ext = 0`, `ret = true`, `fnpf = false`: `{ live, dly }` is the program of v1. -/
structure Program where
  live : Lane → Bool
  dly  : Lane → Nat
  ext  : Nat → Lane → Nat := fun _ _ => 0
  ret  : Nat → Lane → Bool := fun _ _ => true
  fnpf : Engine → Bool := fun _ => false
  /-- The prefetch priority pick (Wilson 11-14 (b′), agent 1's batch 9c0df0c): `none` is the
  shipped rule -- branch 1 serves the registered dispatch winner (`winner_q`); `some f` is the
  batch's -- branch 1 serves the registered pick `pf_q`, the EDF-earliest **released lane with
  an empty head** (`pf_w`, l.1913–1924; `pf_rdy = now_inc & rdy_rel & ~l_actv[hix]`, l.1885).
  `f` is that choice, abstract (any order); `Step.pfPick` filters it by the candidate test, so
  the register holds exactly what the RTL's can. -/
  pick : Option (Engine → Option Lane) := none

namespace Engine
def headValid (e : Engine) (l : Lane) : Bool := e.actv l (e.sel l)
def spareValid (e : Engine) (l : Lane) : Bool := e.actv l (!e.sel l)
/-- §1 `want_fetch` (l.2778–2806): the head is empty, or the spare is empty **and the head
allows a prefetch past it**. -/
def wantFetch (e : Engine) (l : Lane) : Bool :=
  !e.headValid l || (!e.spareValid l && !e.npf l (e.sel l))
/-- No slot holds a no-prefetch word: the v1 port. -/
def NoNpf (e : Engine) : Prop := ∀ l s, e.npf l s = false
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

/-- With no no-prefetch word at the head, the port wants a lane exactly when it owes a slot. -/
theorem wantFetch_iff (e : Engine) (l : Lane) (h : e.npf l (e.sel l) = false) :
    e.wantFetch l = true ↔ 1 ≤ e.owed l := by
  unfold wantFetch headValid spareValid owed
  rw [h]
  cases hs : e.sel l <;> cases h0 : e.actv l false <;> cases h1 : e.actv l true <;>
    simp [h0, h1]

/-- Wanting implies owing, always. -/
theorem owed_of_want (e : Engine) (l : Lane) (h : e.wantFetch l = true) : 1 ≤ e.owed l := by
  unfold wantFetch headValid spareValid owed at *
  cases hs : e.sel l <;> cases h0 : e.actv l false <;> cases h1 : e.actv l true <;>
    simp_all

/-- An empty head is always wanted. -/
theorem want_of_head (e : Engine) (l : Lane) (h : e.headValid l = false) : e.wantFetch l = true := by
  unfold wantFetch
  rw [h]
  rfl
end Engine

/-- Sanity: the port never fetches into an already-valid slot. -/
theorem fetchSlot_invalid (e : Engine) (l : Lane) (h : e.wantFetch l = true) :
    e.actv l (e.fetchSlot l) = false := by
  unfold Engine.wantFetch Engine.headValid Engine.spareValid at h
  unfold Engine.fetchSlot Engine.headValid
  cases hh : e.actv l (e.sel l) <;> simp_all

end JLane
