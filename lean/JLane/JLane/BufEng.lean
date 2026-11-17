import JLane.HeadS
/-!
# Brick C2 — the buffer in the engine, cycle-exact (Wilson 11-17)

The engine of `Slot.lean` with the per-lane buffer, as the RTL does it (Wilson's three contracts):
* **(3) fill order.** A slot fetch issued while the lane's spare is full is a *second fetch*
  (`pb`): at its capture it lands in the first free place -- head, then spare, then the buffer
  (`capSlot`). A first fetch lands where the scan latched it (`pslot`), as every port fetch does.
* **(1) the load, one cycle later.** A retirement frees the head's slot (it is the new spare);
  the *next* cycle, a buffered word loads into it (`loadTo`). For that one cycle the freed slot is
  empty; `BufEng.empty_cycle_*` prove dispatch never reads it.
* **(2) the refill mask.** A lane holding a buffered word is not refilled by branch 2
  (`EngB.wantM`); a lane with a second fetch in flight is not refilled because the port is busy.

Ghost state for the order theorem: each held word's fetch index (`sq`, `bsq`, `psq`) and the
lane's retirement count `nr`. Nothing reads them.

Proved here (all under the requester's contract `SReqB`):
* `wfB_run` -- well-formedness with the buffer (a first fetch targets an empty slot, a lane with
  a fetch in flight has an empty buffer, a buffered word sits behind a valid head, HeadFirst,
  SpareFill, the dispatched head valid);
* `held_run` -- conservation: words held (slots + buffer) + retirements = start + captures;
* `head_valid_when_readyB` -- the head-valid theorem on this engine, `hB` on the per-victim
  charge `chargeSumB` (every slot fetch, first or second, charged to the other lanes);
* **(1)** `empty_cycle_after_ret`, `empty_cycle_disp`, `empty_cycle_load` -- the freed slot is
  empty only the cycle after a retirement; dispatch is idle then and reads only the valid head;
  the buffered word loads that cycle;
* **(2)** `phi_stepB`, `port_wait_boundB` -- the mask never holds a lane that needs a word (the
  port wait bound is unchanged); `mask_buf_next`, `mask_flight_next` -- while the mask is up the
  lane's next word is in the buffer or in flight;
* **(3)** `order_kept` -- the lane's `k`-th retirement retires fetch index `nr₀ + k`, wherever
  the word landed; `issue_index`, `nr_held_run` -- indices are handed out in capture order;
* `slot_countB`, `slot_count_two` -- per window, slot fetches ≤ retirements + 2
  ≤ `SLOT_FETCHES_PER_ARM` · (retirements + 1).
-/
namespace JLane

structure EngB where
  e    : Engine
  /-- the lane's buffer holds a word -/
  buf  : Lane → Bool
  /-- that word's no-prefetch flag -/
  bnpf : Lane → Bool
  /-- the in-flight fetch is a second fetch: its place is chosen at its capture -/
  pb   : Bool
  /-- ghost: fetch index of the word in each slot, in the buffer, in flight -/
  sq   : Lane → Slot → Nat
  bsq  : Lane → Nat
  psq  : Nat
  /-- ghost: the lane's retirements so far -/
  nr   : Lane → Nat

def bnum (b : Bool) : Nat := if b then 1 else 0

/-- Words in the lane's slots (0, 1 or 2). -/
def nslots (e : Engine) (l : Lane) : Nat := bnum (e.actv l false) + bnum (e.actv l true)

/-- Words the lane holds: slots and buffer. -/
def EngB.held (x : EngB) (l : Lane) : Nat := nslots x.e l + bnum (x.buf l)

/-- **(2)** The masked refill want: branch 2 does not refill a lane holding a buffered word. -/
def EngB.wantM (x : EngB) (l : Lane) : Bool := x.e.wantFetch l && !x.buf l

/-- The shipped port with branch 2 masked. -/
def portNextM (P : Program) (x : EngB) : Port :=
  match x.e.pst with
  | .scan =>
    match br1 P x.e with
    | some w => ⟨.req, w, x.e.prr, true, x.e.sel w⟩
    | none =>
      if (P.live x.e.prr && x.wantM x.e.prr) = true then
        ⟨.req, x.e.prr, x.e.prr, false, x.e.fetchSlot x.e.prr⟩
      else ⟨.scan, x.e.pl, nextLane x.e.prr, x.e.pbr1, x.e.pslot⟩
  | _ => portNext P x.e

/-- The port with the slot and the buffer: USB receive's branch 1, else the slot, else the
masked port. -/
def portNextB (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane) (x : EngB) : Port :=
  match x.e.pst with
  | .scan =>
    if usbFirst P usb x.e = true then portNextM P x
    else
      match sreq x with
      | some w => ⟨.req, w, x.e.prr, true, x.e.fetchSlot w⟩
      | none   => portNextM P x
  | _ => portNext P x.e

/-- A slot issue is a second fetch iff the spare is already full. -/
def pbNext (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane) (x : EngB) : Bool :=
  match x.e.pst with
  | .scan =>
    if usbFirst P usb x.e = true then false
    else
      match sreq x with
      | some w => x.e.spareValid w
      | none   => false
  | _ => x.pb

/-- **(3)** Where a second fetch lands at its capture: head, then spare; `none` = the buffer. -/
def capSlot (e : Engine) (l : Lane) : Option Slot :=
  if e.headValid l = false then some (e.sel l)
  else if e.spareValid l = false then some (!e.sel l) else none

/-- This cycle's capture writes slot `s` of lane `l`. -/
def capTo (x : EngB) (l : Lane) (s : Slot) : Bool :=
  decide (x.e.pst = .cap) && decide (l = x.e.pl) &&
    (if x.pb = true then decide (capSlot x.e l = some s) else decide (s = x.e.pslot))

/-- This cycle's capture writes lane `l`'s buffer. -/
def capBuf (x : EngB) (l : Lane) : Bool :=
  decide (x.e.pst = .cap) && decide (l = x.e.pl) && x.pb && decide (capSlot x.e l = none)

/-- **(1)** This cycle loads lane `l`'s buffered word into its empty spare `s`. -/
def loadTo (x : EngB) (l : Lane) (s : Slot) : Bool :=
  x.buf l && decide (s = !x.e.sel l) && !x.e.actv l s

def actvB (P : Program) (x : EngB) (l : Lane) (s : Slot) : Bool :=
  if x.e.st = .wb ∧ l = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true then false
  else if (capTo x l s || loadTo x l s) = true then true
  else x.e.actv l s

def npfB (P : Program) (x : EngB) (l : Lane) (s : Slot) : Bool :=
  if capTo x l s = true then P.fnpf x.e
  else if loadTo x l s = true then x.bnpf l
  else x.e.npf l s

def bufB (x : EngB) (l : Lane) : Bool :=
  if capBuf x l = true then true
  else if (x.buf l && !x.e.spareValid l) = true then false
  else x.buf l

def bnpfB (P : Program) (x : EngB) (l : Lane) : Bool :=
  if capBuf x l = true then P.fnpf x.e else x.bnpf l

def sqB (x : EngB) (l : Lane) (s : Slot) : Nat :=
  if capTo x l s = true then x.psq
  else if loadTo x l s = true then x.bsq l
  else x.sq l s

def bsqB (x : EngB) (l : Lane) : Nat := if capBuf x l = true then x.psq else x.bsq l

def psqB (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane) (x : EngB) : Nat :=
  if x.e.pst = .scan ∧ (portNextB P usb sreq x).pst = .req then
    x.nr (portNextB P usb sreq x).pl + x.held (portNextB P usb sreq x).pl
  else x.psq

def nrB (P : Program) (x : EngB) (l : Lane) : Nat :=
  if x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true then x.nr l + 1 else x.nr l

/-- One cycle with the slot and the buffer. -/
def stepB (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (x : EngB) : EngB :=
  let p := portNextB P usb sreq x
  let e1 := step P win x.e
  let e2 : Engine :=
    { now := e1.now, actv := actvB P x, sel := e1.sel, ts := e1.ts,
      pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot,
      winq := e1.winq, st := e1.st, cur := e1.cur, npf := npfB P x }
  { e := e2, buf := bufB x, bnpf := bnpfB P x, pb := pbNext P usb sreq x,
    sq := sqB x, bsq := bsqB x, psq := psqB P usb sreq x, nr := nrB P x }

def runB (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) : Nat → EngB → EngB
  | 0, x => x
  | n + 1, x => runB P win usb sreq n (stepB P win usb sreq x)

/-- The requester's contract with the buffer: a named lane is live, its head valid (the ARM)
and allowing a prefetch past it, and its buffer empty; a full spare also allows a prefetch past
it. With the spare empty the fetch fills the spare; with the spare full it is the second fetch. -/
def SReqB (P : Program) (sreq : EngB → Option Lane) : Prop :=
  ∀ x w, sreq x = some w → P.live w = true ∧ x.e.headValid w = true ∧ x.buf w = false ∧
    x.e.npf w (x.e.sel w) = false ∧
    (x.e.spareValid w = true → x.e.npf w (!x.e.sel w) = false)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-! ### The port, case by case -/

theorem portNextB_of_ne (x : EngB) (h : x.e.pst ≠ .scan) :
    portNextB P usb sreq x = portNext P x.e ∧ pbNext P usb sreq x = x.pb := by
  unfold portNextB pbNext
  cases hp : x.e.pst with
  | scan => exact absurd hp h
  | req => exact ⟨rfl, rfl⟩
  | wait => exact ⟨rfl, rfl⟩
  | cap => exact ⟨rfl, rfl⟩

theorem portNextM_of_ne (x : EngB) (h : x.e.pst ≠ .scan) : portNextM P x = portNext P x.e := by
  unfold portNextM
  cases hp : x.e.pst with
  | scan => exact absurd hp h
  | req => rfl
  | wait => rfl
  | cap => rfl

theorem stepB_e_actv (x : EngB) : (stepB P win usb sreq x).e.actv = actvB P x := rfl
theorem stepB_e_sel (x : EngB) : (stepB P win usb sreq x).e.sel = selNext P x.e := rfl
theorem stepB_e_st (x : EngB) : (stepB P win usb sreq x).e.st = (dispNext win x.e).st := rfl
theorem stepB_e_cur (x : EngB) : (stepB P win usb sreq x).e.cur = (dispNext win x.e).cur := rfl
theorem stepB_e_ts (x : EngB) : (stepB P win usb sreq x).e.ts = (step P win x.e).ts := rfl
theorem stepB_e_now (x : EngB) : (stepB P win usb sreq x).e.now = x.e.now + 1 := rfl
theorem stepB_e_winq (x : EngB) : (stepB P win usb sreq x).e.winq = winqNext P win x.e := rfl
theorem stepB_port (x : EngB) : portOf (stepB P win usb sreq x).e = portNextB P usb sreq x := rfl

end

/-! ### Well-formedness with the buffer -/

/-- The bundle on the buffered engine. -/
structure WfB (x : EngB) : Prop where
  disp : DispHeadValid x.e
  hf   : HeadFirst x.e
  /-- a first fetch in flight targets an empty slot -/
  fe   : x.e.pst ≠ .scan → x.pb = false → x.e.actv x.e.pl x.e.pslot = false
  /-- a lane with a fetch in flight has an empty buffer -/
  fnb  : x.e.pst ≠ .scan → x.buf x.e.pl = false
  /-- a buffered word sits behind a valid head -/
  bh   : ∀ l, x.buf l = true → x.e.headValid l = true
  /-- SpareFill, for first fetches -/
  sf   : x.e.pst ≠ .scan → x.pb = false → x.e.pslot ≠ x.e.sel x.e.pl →
    x.e.headValid x.e.pl = true

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

theorem capSlot_some_empty (e : Engine) (l : Lane) (s : Slot) (h : capSlot e l = some s) :
    e.actv l s = false := by
  unfold capSlot at h
  cases hh : e.headValid l <;> cases hs : e.spareValid l <;> simp [hh, hs] at h
  · subst h; exact hh
  · subst h; exact hh
  · have hs' : s = !e.sel l := by rw [h]; simp
    rw [hs']
    exact hs

theorem capSlot_some_spare (e : Engine) (l : Lane) (s : Slot) (h : capSlot e l = some s)
    (hne : s ≠ e.sel l) : e.headValid l = true := by
  unfold capSlot at h
  cases hh : e.headValid l
  · simp [hh] at h
    exact absurd h.symm hne
  · rfl

theorem capSlot_none (e : Engine) (l : Lane) (h : capSlot e l = none) :
    e.headValid l = true ∧ e.spareValid l = true := by
  unfold capSlot at h
  cases hh : e.headValid l <;> cases hs : e.spareValid l <;> simp [hh, hs] at h
  exact ⟨rfl, rfl⟩

theorem capTo_cap (x : EngB) (l : Lane) (s : Slot) (h : capTo x l s = true) :
    x.e.pst = .cap ∧ l = x.e.pl := by
  unfold capTo at h
  simp only [Bool.and_eq_true, decide_eq_true_eq] at h
  exact h.1

theorem capTo_first (x : EngB) (l : Lane) (s : Slot) (h : capTo x l s = true)
    (hpb : x.pb = false) : s = x.e.pslot := by
  unfold capTo at h
  simp [hpb] at h
  exact h.2

theorem capTo_second (x : EngB) (l : Lane) (s : Slot) (h : capTo x l s = true)
    (hpb : x.pb = true) : capSlot x.e l = some s := by
  unfold capTo at h
  simp [hpb] at h
  exact h.2

theorem capBuf_spec (x : EngB) (l : Lane) (h : capBuf x l = true) :
    x.e.pst = .cap ∧ l = x.e.pl ∧ x.pb = true ∧ capSlot x.e l = none := by
  unfold capBuf at h
  simp only [Bool.and_eq_true, decide_eq_true_eq] at h
  exact ⟨h.1.1.1, h.1.1.2, h.1.2, h.2⟩

theorem loadTo_spec (x : EngB) (l : Lane) (s : Slot) (h : loadTo x l s = true) :
    x.buf l = true ∧ s = !x.e.sel l ∧ x.e.actv l s = false := by
  unfold loadTo at h
  simp only [Bool.and_eq_true, decide_eq_true_eq, Bool.not_eq_true'] at h
  exact ⟨h.1.1, h.1.2, h.2⟩

theorem capTo_off (x : EngB) (l : Lane) (s : Slot) (hc : x.e.pst ≠ .cap) :
    capTo x l s = false := by
  unfold capTo
  simp [hc]

theorem capBuf_off (x : EngB) (l : Lane) (hc : ¬(x.e.pst = .cap ∧ l = x.e.pl)) :
    capBuf x l = false := by
  cases h : capBuf x l
  · rfl
  · have := capBuf_spec x l h
    exact absurd ⟨this.1, this.2.1⟩ hc

theorem loadTo_off (x : EngB) (l : Lane) (s : Slot) (hb : x.buf l = false) :
    loadTo x l s = false := by
  unfold loadTo
  simp [hb]

/-- **Every fill lands in an empty slot.** -/
theorem fill_empty (x : EngB) (hW : WfB x) (l : Lane) (s : Slot)
    (h : (capTo x l s || loadTo x l s) = true) : x.e.actv l s = false := by
  rcases (Bool.or_eq_true _ _).mp h with hc | hl
  · obtain ⟨hpc, hlp⟩ := capTo_cap x l s hc
    cases hpb : x.pb
    · have hs := capTo_first x l s hc hpb
      rw [hlp, hs]
      exact hW.fe (by rw [hpc]; decide) hpb
    · exact capSlot_some_empty x.e l s (capTo_second x l s hc hpb)
  · exact (loadTo_spec x l s hl).2.2

/-- **A fill into the spare happens behind a valid head.** -/
theorem fill_spare_head (x : EngB) (hW : WfB x) (l : Lane) (s : Slot)
    (h : (capTo x l s || loadTo x l s) = true) (hne : s ≠ x.e.sel l) :
    x.e.headValid l = true := by
  rcases (Bool.or_eq_true _ _).mp h with hc | hl
  · obtain ⟨hpc, hlp⟩ := capTo_cap x l s hc
    cases hpb : x.pb
    · have hs := capTo_first x l s hc hpb
      rw [hlp] at hne ⊢
      rw [hs] at hne
      exact hW.sf (by rw [hpc]; decide) hpb hne
    · exact capSlot_some_spare x.e l s (capTo_second x l s hc hpb) hne
  · exact hW.bh l (loadTo_spec x l s hl).1

theorem actvB_of_true (x : EngB) (l : Lane) (s : Slot)
    (hn : ¬(x.e.st = .wb ∧ l = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true))
    (h : x.e.actv l s = true) : actvB P x l s = true := by
  unfold actvB
  rw [if_neg hn]
  by_cases hf : (capTo x l s || loadTo x l s) = true
  · rw [if_pos hf]
  · rw [if_neg hf, h]

theorem actvB_stay_false (x : EngB) (l : Lane) (s : Slot) (hc : x.e.pst ≠ .cap)
    (hb : x.buf l = false) (h : x.e.actv l s = false) : actvB P x l s = false := by
  unfold actvB
  rw [capTo_off x l s hc, loadTo_off x l s hb]
  by_cases hw : x.e.st = .wb ∧ l = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · rw [if_pos hw]
  · rw [if_neg hw]
    simp [h]

/-- Without a retirement of `l`, a slot is valid next cycle iff it is valid or filled now. -/
theorem actvB_noret (x : EngB) (l : Lane) (s : Slot)
    (hn : ¬(x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true)) :
    actvB P x l s = (capTo x l s || loadTo x l s || x.e.actv l s) := by
  unfold actvB
  rw [if_neg (fun h => hn ⟨h.1, h.2.1, h.2.2.2⟩)]
  by_cases hf : (capTo x l s || loadTo x l s) = true
  · rw [if_pos hf, hf]
    rfl
  · rw [if_neg hf]
    simp only [Bool.not_eq_true] at hf
    rw [hf]
    rfl

/-! #### Preservation, one invariant at a time -/

theorem headFirst_stepB (x : EngB) (hW : WfB x) : HeadFirst (stepB P win usb sreq x).e := by
  intro l hl
  change actvB P x l (selNext P x.e l) = false at hl
  show actvB P x l (!selNext P x.e l) = false
  by_cases hw : x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · have hs : selNext P x.e l = !x.e.sel l := by
      unfold selNext
      rw [if_pos hw]
    rw [hs, Bool.not_not]
    unfold actvB
    rw [if_pos ⟨hw.1, hw.2.1, congrArg x.e.sel hw.2.1, hw.2.2⟩]
  · have hs : selNext P x.e l = x.e.sel l := by
      unfold selNext
      rw [if_neg hw]
    rw [hs, actvB_noret P x l _ hw] at hl
    rw [hs, actvB_noret P x l _ hw]
    simp only [Bool.or_eq_false_iff] at hl
    have hspare : (capTo x l (!x.e.sel l) || loadTo x l (!x.e.sel l)) = false := by
      cases hf : (capTo x l (!x.e.sel l) || loadTo x l (!x.e.sel l))
      · rfl
      · have hv := fill_spare_head x hW l _ hf (by cases x.e.sel l <;> decide)
        have h2 : x.e.actv l (x.e.sel l) = false := hl.2
        have hv' : x.e.actv l (x.e.sel l) = true := hv
        rw [hv'] at h2
        cases h2
    rw [hspare]
    exact hW.hf l hl.2

theorem dispHeadValid_stepB (x : EngB) (hW : WfB x) :
    DispHeadValid (stepB P win usb sreq x).e := by
  have h2 := hW.disp
  unfold DispHeadValid at h2 ⊢
  intro hne
  change (dispNext win x.e).st ≠ .idle at hne
  show actvB P x (dispNext win x.e).cur (selNext P x.e (dispNext win x.e).cur) = true
  have hnr : ∀ l s, x.e.st ≠ .wb →
      ¬(x.e.st = .wb ∧ l = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true) :=
    fun _ _ hw h => hw h.1
  cases hs : x.e.st with
  | wb =>
    have : (dispNext win x.e).st = .idle := by simp [dispNext, hs]
    exact absurd this hne
  | drive =>
    have hd : (dispNext win x.e).cur = x.e.cur := by simp [dispNext, hs]
    have hw : x.e.st ≠ .wb := by rw [hs]; decide
    rw [hd, selNext_of_not_wb P x.e x.e.cur hw]
    exact actvB_of_true P x _ _ (hnr _ _ hw) (h2 (by rw [hs]; decide))
  | idle =>
    have hw : x.e.st ≠ .wb := by rw [hs]; decide
    revert hne
    unfold dispNext
    rw [hs]
    dsimp only
    cases hwin : win x.e with
    | none =>
      dsimp only
      intro h
      exact (h (by simp)).elim
    | some w =>
      dsimp only
      by_cases hv : x.e.headValid w = true
      · rw [if_pos hv]
        intro _hne
        show actvB P x w (selNext P x.e w) = true
        rw [selNext_of_not_wb P x.e w hw]
        exact actvB_of_true P x w (x.e.sel w) (hnr _ _ hw) hv
      · rw [if_neg hv]
        intro h
        exact (h (by simp)).elim

/-- A lane with both words valid keeps a valid head through any cycle. -/
theorem head_of_both (x : EngB) (l : Lane) (hh : x.e.headValid l = true)
    (hs : x.e.spareValid l = true) : actvB P x l (selNext P x.e l) = true := by
  by_cases hw : x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · have hsel : selNext P x.e l = !x.e.sel l := by
      unfold selNext
      rw [if_pos hw]
    rw [hsel]
    apply actvB_of_true P x l _ _ hs
    rintro ⟨_, hlc, hss, _⟩
    rw [← hlc] at hss
    cases hq : x.e.sel l <;> rw [hq] at hss <;> cases hss
  · have hsel : selNext P x.e l = x.e.sel l := by
      unfold selNext
      rw [if_neg hw]
    rw [hsel]
    exact actvB_of_true P x l _ (fun h => hw ⟨h.1, h.2.1, h.2.2.2⟩) hh

theorem bufHead_stepB (x : EngB) (hW : WfB x) (l : Lane)
    (hb : (stepB P win usb sreq x).buf l = true) :
    (stepB P win usb sreq x).e.headValid l = true := by
  change bufB x l = true at hb
  show actvB P x l (selNext P x.e l) = true
  unfold bufB at hb
  by_cases hc : capBuf x l = true
  · have := capSlot_none x.e l (capBuf_spec x l hc).2.2.2
    exact head_of_both P x l this.1 this.2
  · rw [if_neg hc] at hb
    by_cases hl : (x.buf l && !x.e.spareValid l) = true
    · rw [if_pos hl] at hb
      cases hb
    · rw [if_neg hl] at hb
      have hsv : x.e.spareValid l = true := by
        rw [hb] at hl
        simpa using hl
      exact head_of_both P x l (hW.bh l hb) hsv

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-! ### The scan's issues -/

theorem portNextM_br1 (x : EngB) (hp : x.e.pst = .scan) {w : Lane} (hb : br1 P x.e = some w) :
    portNextM P x = ⟨.req, w, x.e.prr, true, x.e.sel w⟩ := by
  unfold portNextM
  rw [hp]
  simp [hb]

theorem portNextM_br2 (x : EngB) (hp : x.e.pst = .scan) (hb : br1 P x.e = none)
    (hc : (P.live x.e.prr && x.wantM x.e.prr) = true) :
    portNextM P x = ⟨.req, x.e.prr, x.e.prr, false, x.e.fetchSlot x.e.prr⟩ := by
  unfold portNextM
  rw [hp]
  simp only [hb]
  rw [if_pos hc]

theorem portNextM_skip (x : EngB) (hp : x.e.pst = .scan) (hb : br1 P x.e = none)
    (hc : ¬(P.live x.e.prr && x.wantM x.e.prr) = true) :
    portNextM P x = ⟨.scan, x.e.pl, nextLane x.e.prr, x.e.pbr1, x.e.pslot⟩ := by
  unfold portNextM
  rw [hp]
  simp only [hb]
  rw [if_neg hc]

theorem portNextB_usb (x : EngB) (hp : x.e.pst = .scan) (hu : usbFirst P usb x.e = true) :
    portNextB P usb sreq x = portNextM P x ∧ pbNext P usb sreq x = false := by
  unfold portNextB pbNext
  rw [hp]
  simp [hu]

theorem portNextB_none (x : EngB) (hp : x.e.pst = .scan) (hu : usbFirst P usb x.e = false)
    (hs : sreq x = none) :
    portNextB P usb sreq x = portNextM P x ∧ pbNext P usb sreq x = false := by
  unfold portNextB pbNext
  rw [hp]
  simp [hu, hs]

theorem portNextB_slot (x : EngB) (hp : x.e.pst = .scan) (hu : usbFirst P usb x.e = false)
    {w : Lane} (hs : sreq x = some w) :
    portNextB P usb sreq x = ⟨.req, w, x.e.prr, true, x.e.fetchSlot w⟩ ∧
      pbNext P usb sreq x = x.e.spareValid w := by
  unfold portNextB pbNext
  rw [hp]
  simp [hu, hs]

/-- What a masked-port issue looks like: an empty slot of a lane with an empty buffer, and a
spare only behind a valid head. -/
theorem issueM (x : EngB) (hW : WfB x) (hp : x.e.pst = .scan)
    (hne : (portNextM P x).pst ≠ .scan) :
    (portNextM P x).pst = .req ∧ x.buf (portNextM P x).pl = false ∧
      x.e.actv (portNextM P x).pl (portNextM P x).pslot = false ∧
      ((portNextM P x).pslot ≠ x.e.sel (portNextM P x).pl →
        x.e.headValid (portNextM P x).pl = true) := by
  cases hb : br1 P x.e with
  | some w =>
    rw [portNextM_br1 P x hp hb]
    have hv := (br1_spec P x.e w hb).2
    refine ⟨rfl, ?_, hv, fun h => absurd rfl h⟩
    cases hbw : x.buf w
    · rfl
    · have := hW.bh w hbw
      rw [hv] at this
      cases this
  | none =>
    by_cases hc : (P.live x.e.prr && x.wantM x.e.prr) = true
    · rw [portNextM_br2 P x hp hb hc]
      simp only [EngB.wantM, Bool.and_eq_true, Bool.not_eq_true'] at hc
      refine ⟨rfl, hc.2.2, fetchSlot_invalid x.e x.e.prr hc.2.1, ?_⟩
      intro hne'
      show x.e.headValid x.e.prr = true
      cases hh : x.e.headValid x.e.prr
      · exfalso
        apply hne'
        show x.e.fetchSlot x.e.prr = x.e.sel x.e.prr
        simp [Engine.fetchSlot, hh]
      · rfl
    · rw [portNextM_skip P x hp hb hc] at hne
      exact absurd rfl hne

/-- **What a scan issues**, with the slot and the buffer: the target lane's buffer is empty;
a first fetch targets an empty slot, a spare only behind a valid head. -/
theorem issueB (hok : SReqB P sreq) (x : EngB) (hW : WfB x) (hp : x.e.pst = .scan)
    (hne : (portNextB P usb sreq x).pst ≠ .scan) :
    x.buf (portNextB P usb sreq x).pl = false ∧
    (pbNext P usb sreq x = false →
      x.e.actv (portNextB P usb sreq x).pl (portNextB P usb sreq x).pslot = false ∧
      ((portNextB P usb sreq x).pslot ≠ x.e.sel (portNextB P usb sreq x).pl →
        x.e.headValid (portNextB P usb sreq x).pl = true)) := by
  cases hu : usbFirst P usb x.e with
  | true =>
    obtain ⟨h1, _⟩ := portNextB_usb P usb sreq x hp hu
    rw [h1] at hne ⊢
    have := issueM P x hW hp hne
    exact ⟨this.2.1, fun _ => this.2.2⟩
  | false =>
    cases hs : sreq x with
    | none =>
      obtain ⟨h1, _⟩ := portNextB_none P usb sreq x hp hu hs
      rw [h1] at hne ⊢
      have := issueM P x hW hp hne
      exact ⟨this.2.1, fun _ => this.2.2⟩
    | some w =>
      obtain ⟨h1, h2⟩ := portNextB_slot P usb sreq x hp hu hs
      rw [h1, h2]
      obtain ⟨_, hv, hbw, _⟩ := hok x w hs
      refine ⟨hbw, fun hsp => ⟨?_, fun _ => hv⟩⟩
      show x.e.actv w (x.e.fetchSlot w) = false
      simp [Engine.fetchSlot, hv]
      exact hsp

/-! ### The remaining invariants -/

theorem stepB_pst (x : EngB) : (stepB P win usb sreq x).e.pst = (portNextB P usb sreq x).pst := rfl
theorem stepB_pl (x : EngB) : (stepB P win usb sreq x).e.pl = (portNextB P usb sreq x).pl := rfl
theorem stepB_pslot (x : EngB) :
    (stepB P win usb sreq x).e.pslot = (portNextB P usb sreq x).pslot := rfl
theorem stepB_pb (x : EngB) : (stepB P win usb sreq x).pb = pbNext P usb sreq x := rfl
theorem stepB_buf (x : EngB) : (stepB P win usb sreq x).buf = bufB x := rfl

/-- Outside a capture, an empty buffer stays empty. -/
theorem bufB_false (x : EngB) (l : Lane) (hc : x.e.pst ≠ .cap) (hb : x.buf l = false) :
    bufB x l = false := by
  unfold bufB
  rw [capBuf_off x l (fun h => hc h.1), hb]
  simp

/-- The port's latched lane and slot outside a scan. -/
theorem portNextB_keeps (x : EngB) (h : x.e.pst ≠ .scan) :
    (portNextB P usb sreq x).pl = x.e.pl ∧ (portNextB P usb sreq x).pslot = x.e.pslot ∧
      pbNext P usb sreq x = x.pb := by
  obtain ⟨h1, h2⟩ := portNextB_of_ne P usb sreq x h
  rw [h1, h2]
  exact ⟨(portNext_keeps P x.e h).1, (portNext_keeps P x.e h).2, rfl⟩

theorem cap_to_scan (x : EngB) (hc : x.e.pst = .cap) : (portNextB P usb sreq x).pst = .scan := by
  rw [(portNextB_of_ne P usb sreq x (by rw [hc]; decide)).1]
  simp [portNext, hc]

theorem fe_stepB (hok : SReqB P sreq) (x : EngB) (hW : WfB x) :
    (stepB P win usb sreq x).e.pst ≠ .scan → (stepB P win usb sreq x).pb = false →
      (stepB P win usb sreq x).e.actv (stepB P win usb sreq x).e.pl
        (stepB P win usb sreq x).e.pslot = false := by
  rw [stepB_pst, stepB_pb, stepB_pl, stepB_pslot, stepB_e_actv]
  intro hne hpb
  cases hp : x.e.pst with
  | scan =>
    have hi := issueB P usb sreq hok x hW hp hne
    exact actvB_stay_false P x _ _ (by rw [hp]; decide) hi.1 (hi.2 hpb).1
  | cap => exact absurd (cap_to_scan P usb sreq x hp) hne
  | req =>
    obtain ⟨hl, hs, hb⟩ := portNextB_keeps P usb sreq x (by rw [hp]; decide)
    rw [hl, hs]
    rw [hb] at hpb
    exact actvB_stay_false P x _ _ (by rw [hp]; decide) (hW.fnb (by rw [hp]; decide))
      (hW.fe (by rw [hp]; decide) hpb)
  | wait =>
    obtain ⟨hl, hs, hb⟩ := portNextB_keeps P usb sreq x (by rw [hp]; decide)
    rw [hl, hs]
    rw [hb] at hpb
    exact actvB_stay_false P x _ _ (by rw [hp]; decide) (hW.fnb (by rw [hp]; decide))
      (hW.fe (by rw [hp]; decide) hpb)

theorem fnb_stepB (hok : SReqB P sreq) (x : EngB) (hW : WfB x) :
    (stepB P win usb sreq x).e.pst ≠ .scan →
      (stepB P win usb sreq x).buf (stepB P win usb sreq x).e.pl = false := by
  rw [stepB_pst, stepB_buf, stepB_pl]
  intro hne
  cases hp : x.e.pst with
  | scan => exact bufB_false x _ (by rw [hp]; decide) (issueB P usb sreq hok x hW hp hne).1
  | cap => exact absurd (cap_to_scan P usb sreq x hp) hne
  | req =>
    rw [(portNextB_keeps P usb sreq x (by rw [hp]; decide)).1]
    exact bufB_false x _ (by rw [hp]; decide) (hW.fnb (by rw [hp]; decide))
  | wait =>
    rw [(portNextB_keeps P usb sreq x (by rw [hp]; decide)).1]
    exact bufB_false x _ (by rw [hp]; decide) (hW.fnb (by rw [hp]; decide))

/-- A first fetch in flight keeps SpareFill: its lane's head stays valid while it fills the spare
(the lane cannot retire an empty head). -/
theorem sf_keep (x : EngB) (hW : WfB x) (l : Lane) (s : Slot) (hempty : x.e.actv l s = false)
    (hspare : s ≠ x.e.sel l → x.e.headValid l = true) (hne : s ≠ selNext P x.e l) :
    actvB P x l (selNext P x.e l) = true := by
  by_cases hw : x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · exfalso
    have hsel : selNext P x.e l = !x.e.sel l := by
      unfold selNext
      rw [if_pos hw]
    rw [hsel] at hne
    have hs : s = x.e.sel l := by
      revert hne
      cases s <;> cases x.e.sel l <;> decide
    have b := hW.disp (by rw [hw.1]; decide)
    unfold Engine.headValid at b
    rw [← hw.2.1, ← hs, hempty] at b
    cases b
  · have hsel : selNext P x.e l = x.e.sel l := by
      unfold selNext
      rw [if_neg hw]
    rw [hsel] at hne ⊢
    exact actvB_of_true P x l _ (fun h => hw ⟨h.1, h.2.1, h.2.2.2⟩) (hspare hne)

theorem sf_stepB (hok : SReqB P sreq) (x : EngB) (hW : WfB x) :
    (stepB P win usb sreq x).e.pst ≠ .scan → (stepB P win usb sreq x).pb = false →
      (stepB P win usb sreq x).e.pslot ≠
        (stepB P win usb sreq x).e.sel (stepB P win usb sreq x).e.pl →
      (stepB P win usb sreq x).e.headValid (stepB P win usb sreq x).e.pl = true := by
  rw [stepB_pst, stepB_pb, stepB_pl, stepB_pslot, stepB_e_sel]
  intro hne hpb hsp
  show actvB P x _ (selNext P x.e _) = true
  cases hp : x.e.pst with
  | scan =>
    have hi := (issueB P usb sreq hok x hW hp hne).2 hpb
    exact sf_keep P x hW _ _ hi.1 hi.2 hsp
  | cap => exact absurd (cap_to_scan P usb sreq x hp) hne
  | req =>
    obtain ⟨hl, hs, hb⟩ := portNextB_keeps P usb sreq x (by rw [hp]; decide)
    rw [hl, hs] at hsp
    rw [hl]
    rw [hb] at hpb
    exact sf_keep P x hW _ _ (hW.fe (by rw [hp]; decide) hpb)
      (hW.sf (by rw [hp]; decide) hpb) hsp
  | wait =>
    obtain ⟨hl, hs, hb⟩ := portNextB_keeps P usb sreq x (by rw [hp]; decide)
    rw [hl, hs] at hsp
    rw [hl]
    rw [hb] at hpb
    exact sf_keep P x hW _ _ (hW.fe (by rw [hp]; decide) hpb)
      (hW.sf (by rw [hp]; decide) hpb) hsp

/-- **Well-formedness survives a cycle** with the slot and the buffer. -/
theorem wfB_step (hok : SReqB P sreq) (x : EngB) (hW : WfB x) :
    WfB (stepB P win usb sreq x) where
  disp := dispHeadValid_stepB P win usb sreq x hW
  hf := headFirst_stepB P win usb sreq x hW
  fe := fe_stepB P win usb sreq hok x hW
  fnb := fnb_stepB P win usb sreq hok x hW
  bh := bufHead_stepB P win usb sreq x hW
  sf := sf_stepB P win usb sreq hok x hW

theorem wfB_run (hok : SReqB P sreq) :
    ∀ (n : Nat) (x : EngB), WfB x → WfB (runB P win usb sreq n x)
  | 0, _, h => h
  | n + 1, x, h => wfB_run hok n (stepB P win usb sreq x) (wfB_step P win usb sreq hok x h)

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-! ### Conservation of words: slots and buffer -/

/-- A capture and a load never write the same lane in one cycle. -/
theorem cap_load_excl (x : EngB) (hW : WfB x) (l : Lane) (s t : Slot)
    (hc : capTo x l s = true) : loadTo x l t = false := by
  obtain ⟨hpc, hlp⟩ := capTo_cap x l s hc
  apply loadTo_off
  rw [hlp]
  exact hW.fnb (by rw [hpc]; decide)

/-- Per slot: valid after + retired = valid before + captured + loaded. -/
theorem slot_balanceB (x : EngB) (hW : WfB x) (y : Lane) (s : Slot) :
    (if actvB P x y s = true then 1 else 0)
        + (if x.e.st = .wb ∧ y = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true
            then 1 else 0)
      = (if x.e.actv y s = true then 1 else 0) + (if capTo x y s = true then 1 else 0)
          + (if loadTo x y s = true then 1 else 0) := by
  by_cases hr : x.e.st = .wb ∧ y = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · have hv : x.e.actv y s = true := by
      have := hW.disp (by rw [hr.1]; decide)
      unfold Engine.headValid at this
      rw [hr.2.1, hr.2.2.1]
      exact this
    have hc : capTo x y s = false := by
      cases h : capTo x y s
      · rfl
      · have := fill_empty x hW y s (by rw [h]; rfl)
        rw [hv] at this
        cases this
    have hl : loadTo x y s = false := by
      cases h : loadTo x y s
      · rfl
      · have := fill_empty x hW y s (by rw [h]; simp)
        rw [hv] at this
        cases this
    have ha : actvB P x y s = false := by
      unfold actvB
      rw [if_pos hr]
    rw [if_pos hr, ha, hv, hc, hl]
    simp
  · rw [if_neg hr]
    have ha : actvB P x y s = (capTo x y s || loadTo x y s || x.e.actv y s) := by
      unfold actvB
      rw [if_neg hr]
      by_cases hf : (capTo x y s || loadTo x y s) = true
      · rw [if_pos hf, hf]
        rfl
      · rw [if_neg hf]
        simp only [Bool.not_eq_true] at hf
        rw [hf]
        rfl
    rw [ha]
    cases hc : capTo x y s
    · cases hl : loadTo x y s
      · simp
      · have he := fill_empty x hW y s (by rw [hc, hl]; rfl)
        rw [he]
        simp
    · have hl := cap_load_excl x hW y s s hc
      have he := fill_empty x hW y s (by rw [hc]; rfl)
      rw [hl, he]
      simp

/-- The two slots' capture indicators and the buffer's add up to one capture. -/
theorem cap_sum (x : EngB) (y : Lane) :
    (if capTo x y false = true then 1 else 0) + (if capTo x y true = true then 1 else 0)
        + (if capBuf x y = true then 1 else 0)
      = if Hit y x.e then 1 else 0 := by
  by_cases hh : x.e.pst = .cap ∧ x.e.pl = y
  · have hH : Hit y x.e := hh
    rw [if_pos hH]
    obtain ⟨hpc, hpl⟩ := hh
    cases hpb : x.pb
    · have hb : capBuf x y = false := by
        unfold capBuf
        simp [hpb]
      rw [hb]
      unfold capTo
      cases x.e.pslot <;> simp [hpc, hpl, hpb]
    · unfold capTo capBuf
      cases hcs : capSlot x.e y with
      | none => simp [hpc, hpl, hpb]
      | some b => cases b <;> simp [hpc, hpl, hpb]
  · have hH : ¬Hit y x.e := hh
    rw [if_neg hH]
    have h1 : ∀ s, capTo x y s = false := fun s => by
      cases h : capTo x y s
      · rfl
      · have := capTo_cap x y s h
        exact absurd ⟨this.1, this.2.symm⟩ hh
    rw [h1, h1, capBuf_off x y (fun h => hh ⟨h.1, h.2.symm⟩)]
    simp

/-- The two slots' load indicators: one load iff the buffer is full and the spare empty. -/
theorem load_sum (x : EngB) (y : Lane) :
    (if loadTo x y false = true then 1 else 0) + (if loadTo x y true = true then 1 else 0)
      = if (x.buf y && !x.e.spareValid y) = true then 1 else 0 := by
  unfold loadTo Engine.spareValid
  cases hb : x.buf y <;> cases hs : x.e.sel y <;> cases h0 : x.e.actv y false <;>
    cases h1 : x.e.actv y true <;> simp [h0, h1]

/-- The buffer: after + loaded = before + captured into it. -/
theorem buf_balance (x : EngB) (hW : WfB x) (y : Lane) :
    bnum (bufB x y) + (if (x.buf y && !x.e.spareValid y) = true then 1 else 0)
      = bnum (x.buf y) + (if capBuf x y = true then 1 else 0) := by
  unfold bufB
  cases hc : capBuf x y
  · simp only [Bool.false_eq_true, if_false]
    cases hl : (x.buf y && !x.e.spareValid y)
    · simp only [Bool.false_eq_true, if_false]
    · simp only [if_true]
      have hb : x.buf y = true := by
        simp only [Bool.and_eq_true] at hl
        exact hl.1
      rw [hb]
      rfl
  · obtain ⟨hpc, hlp, _, _⟩ := capBuf_spec x y hc
    have hb : x.buf y = false := by
      rw [hlp]
      exact hW.fnb (by rw [hpc]; decide)
    rw [hb]
    rfl

/-- The retirement indicator, split over the two slots. -/
theorem ret_split (x : EngB) (y : Lane) :
    (if x.e.st = .wb ∧ y = x.e.cur ∧ false = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true
        then 1 else 0)
      + (if x.e.st = .wb ∧ y = x.e.cur ∧ true = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true
        then 1 else 0)
      = if IsRet P y x.e then 1 else 0 := by
  unfold IsRet
  by_cases h : x.e.st = .wb ∧ y = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · obtain ⟨h1, h2, h3⟩ := h
    have : x.e.st = .wb ∧ x.e.cur = y ∧ P.ret x.e.now y = true := ⟨h1, h2.symm, h2 ▸ h3⟩
    rw [if_pos this]
    cases x.e.sel x.e.cur <;> simp [h1, h2, h3]
  · have : ¬(x.e.st = .wb ∧ x.e.cur = y ∧ P.ret x.e.now y = true) := fun h' =>
      h ⟨h'.1, h'.2.1.symm, h'.2.1 ▸ h'.2.2⟩
    rw [if_neg this]
    rw [if_neg (fun h' => h ⟨h'.1, h'.2.1, h'.2.2.2⟩),
      if_neg (fun h' => h ⟨h'.1, h'.2.1, h'.2.2.2⟩)]

theorem stepB_held (x : EngB) (y : Lane) :
    (stepB P win usb sreq x).held y
      = (if actvB P x y false = true then 1 else 0) + (if actvB P x y true = true then 1 else 0)
          + bnum (bufB x y) := rfl

theorem held_def (x : EngB) (y : Lane) :
    x.held y = (if x.e.actv y false = true then 1 else 0) + (if x.e.actv y true = true then 1 else 0)
      + bnum (x.buf y) := rfl

/-- **Conservation, one cycle.** Words held + a retirement = words held + a capture. -/
theorem held_step (x : EngB) (hW : WfB x) (y : Lane) :
    (stepB P win usb sreq x).held y + (if IsRet P y x.e then 1 else 0)
      = x.held y + (if Hit y x.e then 1 else 0) := by
  have h0 := slot_balanceB P x hW y false
  have h1 := slot_balanceB P x hW y true
  have hc := cap_sum x y
  have hl := load_sum x y
  have hb := buf_balance x hW y
  have hr := ret_split P x y
  rw [stepB_held, held_def]
  omega

/-! ### Counting along the buffered run -/

def cntB (Q : EngB → Prop) [DecidablePred Q] : Nat → EngB → Nat
  | 0, _ => 0
  | n + 1, x => (if Q x then 1 else 0) + cntB Q n (stepB P win usb sreq x)

theorem runB_succ' : ∀ (n : Nat) (x : EngB),
    runB P win usb sreq (n + 1) x = stepB P win usb sreq (runB P win usb sreq n x)
  | 0, _ => rfl
  | n + 1, x => runB_succ' n (stepB P win usb sreq x)

theorem runB_add : ∀ (a k : Nat) (x : EngB),
    runB P win usb sreq (a + k) x = runB P win usb sreq k (runB P win usb sreq a x)
  | 0, k, x => by
    show runB P win usb sreq (0 + k) x = runB P win usb sreq k x
    rw [Nat.zero_add]
  | a + 1, k, x => by
    rw [Nat.add_right_comm]
    exact runB_add a k (stepB P win usb sreq x)

theorem cntB_add (Q : EngB → Prop) [DecidablePred Q] :
    ∀ (a k : Nat) (x : EngB),
      cntB P win usb sreq Q (a + k) x
        = cntB P win usb sreq Q a x + cntB P win usb sreq Q k (runB P win usb sreq a x)
  | 0, k, x => by
    show cntB P win usb sreq Q (0 + k) x = 0 + cntB P win usb sreq Q k x
    rw [Nat.zero_add, Nat.zero_add]
  | a + 1, k, x => by
    rw [Nat.add_right_comm]
    show (if Q x then 1 else 0) + cntB P win usb sreq Q (a + k) (stepB P win usb sreq x)
        = ((if Q x then 1 else 0) + cntB P win usb sreq Q a (stepB P win usb sreq x))
          + cntB P win usb sreq Q k (runB P win usb sreq a (stepB P win usb sreq x))
    rw [cntB_add Q a k (stepB P win usb sreq x)]
    omega

theorem cntB_succ_back (Q : EngB → Prop) [DecidablePred Q] (n : Nat) (x : EngB) :
    cntB P win usb sreq Q (n + 1) x
      = cntB P win usb sreq Q n x + (if Q (runB P win usb sreq n x) then 1 else 0) := by
  have h1 : cntB P win usb sreq Q 1 (runB P win usb sreq n x)
      = (if Q (runB P win usb sreq n x) then 1 else 0) + 0 := rfl
  rw [cntB_add P win usb sreq Q n 1 x, h1, Nat.add_zero]

theorem cntB_mono (Q : EngB → Prop) [DecidablePred Q] (x : EngB) (a : Nat) :
    ∀ (b : Nat), a ≤ b → cntB P win usb sreq Q a x ≤ cntB P win usb sreq Q b x
  | 0, h => by
    have : a = 0 := by omega
    subst this
    exact Nat.le_refl _
  | b + 1, h => by
    by_cases hab : a = b + 1
    · subst hab
      exact Nat.le_refl _
    · have ih := cntB_mono Q x a b (by omega)
      have := cntB_succ_back P win usb sreq Q b x
      omega

theorem no_event_betweenB (Q : EngB → Prop) [DecidablePred Q] (x : EngB) (a b i : Nat)
    (hai : a ≤ i) (hib : i < b)
    (heq : cntB P win usb sreq Q a x = cntB P win usb sreq Q b x) :
    ¬Q (runB P win usb sreq i x) := by
  intro hq
  have h1 := cntB_mono P win usb sreq Q x a i hai
  have h2 := cntB_mono P win usb sreq Q x (i + 1) b hib
  have h3 := cntB_succ_back P win usb sreq Q i x
  rw [if_pos hq] at h3
  omega

theorem cntB_reach (Q : EngB → Prop) [DecidablePred Q] :
    ∀ (n : Nat) (x : EngB) (k : Nat), k < cntB P win usb sreq Q n x →
      ∃ t, t < n ∧ cntB P win usb sreq Q t x = k ∧ Q (runB P win usb sreq t x)
  | 0, x, k, h => by simp [cntB] at h
  | n + 1, x, k, h => by
    have e1 : cntB P win usb sreq Q (n + 1) x
        = (if Q x then 1 else 0) + cntB P win usb sreq Q n (stepB P win usb sreq x) := rfl
    by_cases hq : Q x
    · rw [if_pos hq] at e1
      cases k with
      | zero => exact ⟨0, Nat.succ_pos n, rfl, hq⟩
      | succ k =>
        obtain ⟨t, ht, hc, hq'⟩ := cntB_reach Q n (stepB P win usb sreq x) k (by omega)
        have e2 : cntB P win usb sreq Q (t + 1) x
            = (if Q x then 1 else 0) + cntB P win usb sreq Q t (stepB P win usb sreq x) := rfl
        rw [if_pos hq] at e2
        exact ⟨t + 1, by omega, by omega, hq'⟩
    · rw [if_neg hq] at e1
      obtain ⟨t, ht, hc, hq'⟩ := cntB_reach Q n (stepB P win usb sreq x) k (by omega)
      have e2 : cntB P win usb sreq Q (t + 1) x
          = (if Q x then 1 else 0) + cntB P win usb sreq Q t (stepB P win usb sreq x) := rfl
      rw [if_neg hq] at e2
      exact ⟨t + 1, by omega, by omega, hq'⟩

/-- **Conservation along the buffered run.** -/
theorem held_run (hok : SReqB P sreq) (y : Lane) :
    ∀ (n : Nat) (x : EngB), WfB x →
      (runB P win usb sreq n x).held y + cntB P win usb sreq (fun z => IsRet P y z.e) n x
        = x.held y + cntB P win usb sreq (fun z => Hit y z.e) n x
  | 0, x, _ => by simp [runB, cntB]
  | n + 1, x, hW => by
    have h1 := held_step P win usb sreq x hW y
    have ih := held_run hok y n (stepB P win usb sreq x) (wfB_step P win usb sreq hok x hW)
    have e1 : cntB P win usb sreq (fun z => Hit y z.e) (n + 1) x
        = (if Hit y x.e then 1 else 0)
          + cntB P win usb sreq (fun z => Hit y z.e) n (stepB P win usb sreq x) := rfl
    have e2 : cntB P win usb sreq (fun z => IsRet P y z.e) (n + 1) x
        = (if IsRet P y x.e then 1 else 0)
          + cntB P win usb sreq (fun z => IsRet P y z.e) n (stepB P win usb sreq x) := rfl
    have e3 : runB P win usb sreq (n + 1) x = runB P win usb sreq n (stepB P win usb sreq x) := rfl
    rw [e3]
    omega

/-- **The head bridge with the buffer.** A lane holding a word has a valid head: an empty head
means an empty spare (HeadFirst) and an empty buffer (a buffered word sits behind a valid head). -/
theorem head_of_held (x : EngB) (hW : WfB x) (y : Lane) (h : 1 ≤ x.held y) :
    x.e.headValid y = true := by
  cases hh : x.e.headValid y
  · exfalso
    have hs := hW.hf y hh
    have hb : x.buf y = false := by
      cases hb : x.buf y
      · rfl
      · have := hW.bh y hb
        rw [hh] at this
        cases this
    rw [held_def, hb] at h
    unfold Engine.headValid at hh
    unfold Engine.spareValid at hs
    cases hsel : x.e.sel y
    · rw [hsel] at hh hs
      have hs' : x.e.actv y true = false := by simpa using hs
      rw [hh, hs'] at h
      simp [bnum] at h
    · rw [hsel] at hh hs
      have hs' : x.e.actv y false = false := by simpa using hs
      rw [hh, hs'] at h
      simp [bnum] at h
  · rfl

/-- **The bridge along the buffered run.** From a start with both slots full and the buffer
empty, the head is valid whenever retirements are at most captures + 1. -/
theorem head_valid_of_countsB (hok : SReqB P sreq) (y : Lane) (n : Nat) (x0 : EngB)
    (hW : WfB x0) (h0 : x0.held y = 2)
    (h : cntB P win usb sreq (fun z => IsRet P y z.e) n x0
      ≤ cntB P win usb sreq (fun z => Hit y z.e) n x0 + 1) :
    (runB P win usb sreq n x0).e.headValid y = true := by
  have hr := held_run P win usb sreq hok y n x0 hW
  exact head_of_held _ (wfB_run P win usb sreq hok n x0 hW) y (by omega)

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-! ### The port wait with the mask -/

/-- `L_REFILL` if this cycle's scan issues a fetch for a lane other than `y` (USB receive's
branch 1, a slot fetch -- first or second --, another lane's branch 1). -/
def chargeB (y : Lane) (x : EngB) : Nat :=
  if x.e.pst = .scan ∧ usbFirst P usb x.e = false then
    match sreq x with
    | some w => if w ≠ y then L_REFILL else 0
    | none   => charge P y x.e
  else charge P y x.e

def chargeSumB (y : Lane) : Nat → EngB → Nat
  | 0, _ => 0
  | n + 1, x => chargeB P usb sreq y x + chargeSumB y n (stepB P win usb sreq x)

theorem chargeB_le (y : Lane) (x : EngB) : chargeB P usb sreq y x ≤ L_REFILL := by
  unfold chargeB charge
  split
  · split
    · split <;> simp
    · split
      · split <;> simp
      · simp
  · split
    · split <;> simp
    · simp

theorem usbFirst_br1 (x : EngB) (hu : usbFirst P usb x.e = true) : ∃ u, br1 P x.e = some u := by
  unfold usbFirst at hu
  cases hb : br1 P x.e with
  | none => rw [hb] at hu; simp at hu
  | some u => exact ⟨u, rfl⟩

/-- **One cycle of the port with the mask.** For a live lane that wants a refill and holds no
buffered word, the rank falls by one per cycle, less the charge -- the mask never holds it. -/
theorem phi_stepB (y : Lane) (x : EngB) (hy : P.live y = true) (hw : x.e.wantFetch y = true)
    (hb : x.buf y = false) (hn : ¬Hit y x.e) :
    phi y (portOf (stepB P win usb sreq x).e) + 1 ≤ phi y (portOf x.e) + chargeB P usb sreq y x := by
  rw [stepB_port]
  have hbase := phi_step P win y x.e hy hw hn
  rw [portOf_step] at hbase
  by_cases hp : x.e.pst = .scan
  · by_cases hu : usbFirst P usb x.e = true
    · rw [(portNextB_usb P usb sreq x hp hu).1]
      obtain ⟨u, hbu⟩ := usbFirst_br1 P usb x hu
      rw [portNextM_br1 P x hp hbu]
      rw [portNext_br1 P x.e hp hbu] at hbase
      have hc : chargeB P usb sreq y x = charge P y x.e := by
        unfold chargeB; rw [if_neg (fun h => by simp [h.2] at hu)]
      rw [hc]
      exact hbase
    · have hu' : usbFirst P usb x.e = false := by simpa using hu
      cases hs : sreq x with
      | some w =>
        rw [(portNextB_slot P usb sreq x hp hu' hs).1]
        by_cases hwy : w = y
        · simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy] <;> omega
        · have hc : chargeB P usb sreq y x = L_REFILL := by
            unfold chargeB; simp [hp, hu', hs, hwy]
          simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy, hc] <;> omega
      | none =>
        rw [(portNextB_none P usb sreq x hp hu' hs).1]
        have hc : chargeB P usb sreq y x = charge P y x.e := by
          unfold chargeB; simp [hp, hu', hs]
        rw [hc]
        cases hb1 : br1 P x.e with
        | some u =>
          rw [portNextM_br1 P x hp hb1]
          rw [portNext_br1 P x.e hp hb1] at hbase
          exact hbase
        | none =>
          by_cases hc2 : (P.live x.e.prr && x.wantM x.e.prr) = true
          · rw [portNextM_br2 P x hp hb1 hc2]
            have hc2' : (P.live x.e.prr && x.e.wantFetch x.e.prr) = true := by
              simp only [EngB.wantM, Bool.and_eq_true] at hc2
              simp [hc2.1, hc2.2.1]
            rw [portNext_br2 P x.e hp hb1 hc2'] at hbase
            exact hbase
          · rw [portNextM_skip P x hp hb1 hc2]
            have hpy : x.e.prr ≠ y := fun h => hc2 (by
              rw [h]; simp [EngB.wantM, hy, hw, hb])
            have hd := dist_next x.e.prr y hpy
            have hch : charge P y x.e = 0 := by simp [charge, hb1]
            rw [hch]
            simp [phi, ptr, portOf, rem, L_REFILL, hp] <;> omega
  · rw [(portNextB_of_ne P usb sreq x hp).1]
    have hc : chargeB P usb sreq y x = charge P y x.e := by
      unfold chargeB; rw [if_neg (fun h => hp h.1)]
    rw [hc]
    exact hbase

/-- **The want survives until served** (and the buffer stays empty): nothing but `y`'s own
capture fills `y`, and a retirement of `y` only empties its head. -/
theorem want_stepB (y : Lane) (x : EngB) (hW : WfB x) (hw : x.e.wantFetch y = true)
    (hb : x.buf y = false) (hn : ¬Hit y x.e) :
    (stepB P win usb sreq x).e.wantFetch y = true ∧ (stepB P win usb sreq x).buf y = false := by
  have hn' : ¬(x.e.pst = .cap ∧ y = x.e.pl) := fun h => hn ⟨h.1, h.2.symm⟩
  have hcap : ∀ s, capTo x y s = false := fun s => by
    cases h : capTo x y s
    · rfl
    · exact absurd (capTo_cap x y s h) hn'
  have hld : ∀ s, loadTo x y s = false := fun s => loadTo_off x y s hb
  refine ⟨?_, ?_⟩
  · have hact : ∀ s, actvB P x y s = actvNext P x.e y s := fun s => by
      unfold actvB actvNext
      rw [hcap, hld]
      by_cases hr : x.e.st = .wb ∧ y = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true
      · rw [if_pos hr, if_pos hr]
      · rw [if_neg hr, if_neg hr, if_neg (show ¬((false || false) = true) by decide),
          if_neg (fun h' => hn' ⟨h'.1, h'.2.1⟩)]
    have hnpf : ∀ s, npfB P x y s = x.e.npf y s := fun s => by
      unfold npfB
      rw [hcap, hld]
      simp
    show (!actvB P x y (selNext P x.e y) ||
          (!actvB P x y (!selNext P x.e y) && !npfB P x y (selNext P x.e y))) = true
    by_cases hr : x.e.st = .wb ∧ y = x.e.cur ∧ P.ret x.e.now x.e.cur = true
    · have hv : x.e.headValid y = true := by
        have := hW.disp (by rw [hr.1]; decide)
        rw [← hr.2.1] at this
        exact this
      have hsel : selNext P x.e y = !x.e.sel y := by
        unfold selNext
        rw [if_pos hr]
      have hsp : x.e.actv y (!x.e.sel y) = false := by
        unfold Engine.wantFetch Engine.headValid Engine.spareValid at hw
        unfold Engine.headValid at hv
        rw [hv] at hw
        cases h1 : x.e.actv y (!x.e.sel y)
        · rfl
        · rw [h1] at hw
          simp at hw
      have hnew : actvB P x y (!x.e.sel y) = false := by
        rw [hact]
        unfold actvNext
        rw [if_neg (fun h' => by
          have := h'.2.2.1
          rw [← hr.2.1] at this
          cases hs : x.e.sel y <;> rw [hs] at this <;> cases this),
          if_neg (fun h' => hn' ⟨h'.1, h'.2.1⟩), hsp]
      rw [hsel, hnew]
      rfl
    · have hsel : selNext P x.e y = x.e.sel y := by
        unfold selNext
        rw [if_neg hr]
      have hsame : ∀ s, actvB P x y s = x.e.actv y s := fun s => by
        rw [hact]
        unfold actvNext
        rw [if_neg (fun h' => hr ⟨h'.1, h'.2.1, h'.2.2.2⟩),
          if_neg (fun h' => hn' ⟨h'.1, h'.2.1⟩)]
      rw [hsel, hsame, hsame, hnpf]
      exact hw
  · show bufB x y = false
    unfold bufB
    rw [capBuf_off x y hn', hb]
    simp

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

theorem port_waitB (hok : SReqB P sreq) (y : Lane) (hy : P.live y = true) :
    ∀ (n : Nat) (x : EngB), WfB x → x.e.wantFetch y = true → x.buf y = false →
      (∀ i, i < n → ¬Hit y (runB P win usb sreq i x).e) →
      phi y (portOf (runB P win usb sreq n x).e) + n
        ≤ phi y (portOf x.e) + chargeSumB P win usb sreq y n x
  | 0, x, _, _, _, _ => by simp [runB, chargeSumB]
  | n + 1, x, hW, hw, hb, hnh => by
    have h0 : ¬Hit y x.e := hnh 0 (Nat.succ_pos n)
    have hstep := phi_stepB P win usb sreq y x hy hw hb h0
    have hws := want_stepB P win usb sreq y x hW hw hb h0
    have ih := port_waitB hok y hy n (stepB P win usb sreq x)
      (wfB_step P win usb sreq hok x hW) hws.1 hws.2
      (fun i hi => hnh (i + 1) (Nat.succ_lt_succ hi))
    show phi y (portOf (runB P win usb sreq n (stepB P win usb sreq x)).e) + (n + 1)
      ≤ phi y (portOf x.e) + (chargeB P usb sreq y x
          + chargeSumB P win usb sreq y n (stepB P win usb sreq x))
    omega

/-- **Port wait bound with the slot and the buffer.** A live lane that wants a refill and holds
no buffered word is captured within 22 cycles plus `L_REFILL` per fetch for another lane --
first and second slot fetches included. The mask costs it nothing. -/
theorem port_wait_boundB (hok : SReqB P sreq) (y : Lane) (hy : P.live y = true) (n : Nat)
    (x : EngB) (hW : WfB x) (hw : x.e.wantFetch y = true) (hb : x.buf y = false)
    (hnh : ∀ i, i < n → ¬Hit y (runB P win usb sreq i x).e) :
    n ≤ 22 + chargeSumB P win usb sreq y n x := by
  have h := port_waitB P win usb sreq hok y hy n x hW hw hb hnh
  have h2 := phi_le y (portOf x.e)
  omega

theorem port_wait_bound_19B (hok : SReqB P sreq) (y : Lane) (hy : P.live y = true) (n : Nat)
    (x : EngB) (hW : WfB x) (hw : x.e.wantFetch y = true) (hb : x.buf y = false)
    (hq : x.e.pst = .scan ∨ x.e.pbr1 = false)
    (hnh : ∀ i, i < n → ¬Hit y (runB P win usb sreq i x).e) :
    n ≤ 19 + chargeSumB P win usb sreq y n x := by
  have h := port_waitB P win usb sreq hok y hy n x hW hw hb hnh
  have h2 := phi_le_19 y (portOf x.e) hq
  omega

theorem window_leB (hok : SReqB P sreq) (y : Lane) (hy : P.live y = true) (x : EngB)
    (B n : Nat) (hW : WfB x) (hw : x.e.wantFetch y = true) (hb : x.buf y = false)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSumB P win usb sreq y m x ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (runB P win usb sreq i x).e) : n ≤ 22 + B := by
  by_cases hn : n ≤ 23 + B
  · have h := port_wait_boundB P win usb sreq hok y hy n x hW hw hb hnh
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_wait_boundB P win usb sreq hok y hy (23 + B) x hW hw hb
      (fun i hi => hnh i (by omega))
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

theorem window_le_19B (hok : SReqB P sreq) (y : Lane) (hy : P.live y = true) (x : EngB)
    (B n : Nat) (hW : WfB x) (hw : x.e.wantFetch y = true) (hb : x.buf y = false)
    (hq : x.e.pst = .scan ∨ x.e.pbr1 = false)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSumB P win usb sreq y m x ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (runB P win usb sreq i x).e) : n ≤ 19 + B := by
  by_cases hn : n ≤ 23 + B
  · have h := port_wait_bound_19B P win usb sreq hok y hy n x hW hw hb hq hnh
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_wait_bound_19B P win usb sreq hok y hy (23 + B) x hW hw hb hq
      (fun i hi => hnh i (by omega))
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

/-! ### Clock and timestamps -/

theorem now_runB : ∀ (n : Nat) (x : EngB), (runB P win usb sreq n x).e.now = x.e.now + n
  | 0, _ => rfl
  | n + 1, x => by
    have := now_runB n (stepB P win usb sreq x)
    show (runB P win usb sreq n (stepB P win usb sreq x)).e.now = x.e.now + (n + 1)
    rw [this]
    show x.e.now + 1 + n = x.e.now + (n + 1)
    omega

theorem ts_run_geB (y : Lane) :
    ∀ (n : Nat) (x : EngB),
      x.e.ts y + P.dly y * cntB P win usb sreq (fun z => IsWB y z.e) n x
        ≤ (runB P win usb sreq n x).e.ts y
  | 0, x => by simp [runB, cntB]
  | n + 1, x => by
    have ih := ts_run_geB y n (stepB P win usb sreq x)
    have h1 : (stepB P win usb sreq x).e.ts y
        = x.e.ts y + (if IsWB y x.e then P.dly y + P.ext x.e.now y else 0) := ts_step P win x.e y
    have e1 : cntB P win usb sreq (fun z => IsWB y z.e) (n + 1) x
        = (if IsWB y x.e then 1 else 0)
          + cntB P win usb sreq (fun z => IsWB y z.e) n (stepB P win usb sreq x) := rfl
    have e3 : runB P win usb sreq (n + 1) x = runB P win usb sreq n (stepB P win usb sreq x) := rfl
    rw [e3, e1, Nat.mul_add]
    by_cases h : IsWB y x.e
    · rw [if_pos h] at h1 ⊢
      rw [Nat.mul_one]
      omega
    · rw [if_neg h] at h1 ⊢
      rw [Nat.mul_zero]
      omega

theorem ts_ge_after_wbB (y : Lane) (x : EngB) (a b : Nat) (hab : a < b)
    (hw : IsWB y (runB P win usb sreq a x).e) :
    (runB P win usb sreq a x).e.ts y + P.dly y ≤ (runB P win usb sreq b x).e.ts y := by
  have h1 := ts_run_geB P win usb sreq y (b - a) (runB P win usb sreq a x)
  rw [← runB_add] at h1
  have hba : a + (b - a) = b := by omega
  rw [hba] at h1
  have h2 := cntB_add P win usb sreq (fun z => IsWB y z.e) a (b - a) x
  rw [hba] at h2
  have h3 := cntB_succ_back P win usb sreq (fun z => IsWB y z.e) a x
  rw [if_pos hw] at h3
  have h4 := cntB_mono P win usb sreq (fun z => IsWB y z.e) x (a + 1) b (by omega)
  have hm := dly_le_mul (P.dly y)
    (cntB P win usb sreq (fun z => IsWB y z.e) (b - a) (runB P win usb sreq a x)) (by omega)
  omega

/-! ### The pending bound and the head on the buffered run -/

/-- A lane holding at most one word wants a refill and holds no buffered word. -/
theorem want_of_held (x : EngB) (hW : WfB x) (hnp : x.e.NoNpf) (y : Lane) (h : x.held y ≤ 1) :
    x.e.wantFetch y = true ∧ x.buf y = false := by
  have hb : x.buf y = false := by
    cases hb : x.buf y
    · rfl
    · exfalso
      have hv := hW.bh y hb
      rw [held_def, hb] at h
      unfold Engine.headValid at hv
      cases hs : x.e.sel y <;> rw [hs] at hv <;> rw [hv] at h <;> simp [bnum] at h
  refine ⟨?_, hb⟩
  rw [Engine.wantFetch_iff _ _ (hnp _ _)]
  rw [held_def, hb] at h
  unfold Engine.owed
  cases h0 : x.e.actv y false <;> cases h1 : x.e.actv y true <;> simp [h0, h1, bnum] at h ⊢

theorem hit_then_scanB (y : Lane) (x : EngB) (hh : Hit y x.e) :
    (stepB P win usb sreq x).e.pst = .scan := by
  rw [stepB_pst]
  exact cap_to_scan P usb sreq x hh.1

theorem pb_freshB (hok : SReqB P sreq) (y : Lane) (x0 : EngB)
    (R B T w t k : Nat) (hy : P.live y = true) (hW0 : WfB x0) (h0 : x0.held y = 2)
    (hnp : ∀ t, (runB P win usb sreq t x0).e.NoNpf)
    (hR : ∀ t, t < T → IsWB y (runB P win usb sreq t x0).e →
      (runB P win usb sreq t x0).e.now ≤ (runB P win usb sreq t x0).e.ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumB P win usb sreq y m (runB P win usb sreq a x0) ≤ B)
    (hwt : w < t) (htT : t ≤ T)
    (hwk : cntB P win usb sreq (fun z => IsRet P y z.e) w x0 = k)
    (hwb : IsRet P y (runB P win usb sreq w x0).e)
    (hh : cntB P win usb sreq (fun z => Hit y z.e) t x0 ≤ k)
    (heq : cntB P win usb sreq (fun z => Hit y z.e) (w + 1) x0
      = cntB P win usb sreq (fun z => Hit y z.e) t x0) :
    x0.e.now + t ≤ (runB P win usb sreq w x0).e.ts y + R + PENDING_SLACK + B := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hRw := hR w (by omega) (isWB_of_ret P y _ hwb)
  have hnow := now_runB P win usb sreq w x0
  have hcr := cntB_succ_back P win usb sreq (fun z => IsRet P y z.e) w x0
  rw [if_pos hwb] at hcr
  have hheld := held_run P win usb sreq hok y (w + 1) x0 hW0
  have hwant := want_of_held _ (wfB_run P win usb sreq hok (w + 1) x0 hW0) (hnp (w + 1)) y
    (by omega)
  have hn := window_leB P win usb sreq hok y hy (runB P win usb sreq (w + 1) x0) B (t - (w + 1))
    (wfB_run P win usb sreq hok (w + 1) x0 hW0) hwant.1 hwant.2
    (fun m hm hm' => hB (w + 1) m (by omega) hm')
    (fun i hi => by
      rw [← runB_add]
      exact no_event_betweenB P win usb sreq (fun z => Hit y z.e) x0 (w + 1) t (w + 1 + i)
        (by omega) (by omega) heq)
  omega

/-- **The pending bound on the buffered run.** -/
theorem pending_boundB (hok : SReqB P sreq) (y : Lane) (x0 : EngB)
    (d R B T : Nat) (hW : WfB x0) (h0 : x0.held y = 2)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hnp : ∀ t, (runB P win usb sreq t x0).e.NoNpf)
    (hR : ∀ t, t < T → IsWB y (runB P win usb sreq t x0).e →
      (runB P win usb sreq t x0).e.now ≤ (runB P win usb sreq t x0).e.ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumB P win usb sreq y m (runB P win usb sreq a x0) ≤ B) :
    ∀ (k t w : Nat), t ≤ T → w < t → cntB P win usb sreq (fun z => IsRet P y z.e) w x0 = k →
      IsRet P y (runB P win usb sreq w x0).e →
      cntB P win usb sreq (fun z => Hit y z.e) t x0 ≤ k →
      x0.e.now + t ≤ (runB P win usb sreq w x0).e.ts y + R + PENDING_SLACK + B := by
  intro k
  induction k with
  | zero =>
    intro t w htT hwt hwk hwb hh
    have hm := cntB_mono P win usb sreq (fun z => Hit y z.e) x0 (w + 1) t (by omega)
    exact pb_freshB P win usb sreq hok y x0 R B T w t 0 hy hW h0 hnp hR hB hwt htT hwk hwb hh
      (by omega)
  | succ k ih =>
    intro t w htT hwt hwk hwb hh
    have hm := cntB_mono P win usb sreq (fun z => Hit y z.e) x0 (w + 1) t (by omega)
    by_cases hfresh : k + 1 ≤ cntB P win usb sreq (fun z => Hit y z.e) (w + 1) x0
    · exact pb_freshB P win usb sreq hok y x0 R B T w t (k + 1) hy hW h0 hnp hR hB hwt htT
        hwk hwb hh (by omega)
    · obtain ⟨w', hw'w, hw'k, hw'b⟩ :=
        cntB_reach P win usb sreq (fun z => IsRet P y z.e) w x0 k (by omega)
      have hsp := ts_ge_after_wbB P win usb sreq y x0 w' w hw'w (isWB_of_ret P y _ hw'b)
      by_cases hlate : cntB P win usb sreq (fun z => Hit y z.e) t x0 ≤ k
      · have := ih t w' htT (by omega) hw'k hw'b hlate
        omega
      · obtain ⟨c, hct, hck, hhit⟩ :=
          cntB_reach P win usb sreq (fun z => Hit y z.e) t x0 k (by omega)
        have hc1 : cntB P win usb sreq (fun z => Hit y z.e) (c + 1) x0 = k + 1 := by
          have := cntB_succ_back P win usb sreq (fun z => Hit y z.e) c x0
          rw [if_pos hhit] at this
          omega
        have hwc : w + 1 ≤ c := by
          rcases Nat.lt_or_ge c (w + 1) with hlt | hge
          · have := cntB_mono P win usb sreq (fun z => Hit y z.e) x0 (c + 1) (w + 1) hlt
            omega
          · exact hge
        have hwb1 : cntB P win usb sreq (fun z => IsRet P y z.e) (w + 1) x0 = k + 2 := by
          have := cntB_succ_back P win usb sreq (fun z => IsRet P y z.e) w x0
          rw [if_pos hwb] at this
          omega
        have hwbc1 := cntB_mono P win usb sreq (fun z => IsRet P y z.e) x0 (w + 1) (c + 1)
          (by omega)
        have hic := ih c w' (by omega) (by omega) hw'k hw'b (by omega)
        have hheld := held_run P win usb sreq hok y (c + 1) x0 hW
        have hwant := want_of_held _ (wfB_run P win usb sreq hok (c + 1) x0 hW) (hnp (c + 1)) y
          (by omega)
        have hscan : (runB P win usb sreq (c + 1) x0).e.pst = .scan := by
          rw [runB_succ']
          exact hit_then_scanB P win usb sreq y (runB P win usb sreq c x0) hhit
        have heq : cntB P win usb sreq (fun z => Hit y z.e) (c + 1) x0
            = cntB P win usb sreq (fun z => Hit y z.e) t x0 := by omega
        have hn := window_le_19B P win usb sreq hok y hy (runB P win usb sreq (c + 1) x0) B
          (t - (c + 1)) (wfB_run P win usb sreq hok (c + 1) x0 hW) hwant.1 hwant.2
          (Or.inl hscan)
          (fun m hm hm' => hB (c + 1) m (by omega) hm')
          (fun i hi => by
            rw [← runB_add]
            exact no_event_betweenB P win usb sreq (fun z => Hit y z.e) x0 (c + 1) t (c + 1 + i)
              (by omega) (by omega) heq)
        have hD : DSTAR = 20 := dstar_val
        omega

/-- **The head with the slot and the buffer** (Wilson 11-17, C2). `Run.head_valid_when_ready`
on the cycle-exact buffered engine: with the budget `hB` on the per-victim charge (each slot
fetch, first or second, charged to the other lanes), lane `y`'s head is valid at every cycle
`t ≤ T` where `y` is ready. -/
theorem head_valid_when_readyB (hok : SReqB P sreq) (y : Lane)
    (x0 : EngB) (d R B T : Nat) (hW : WfB x0) (h0 : x0.held y = 2)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hnp : ∀ t, (runB P win usb sreq t x0).e.NoNpf)
    (hlat : R + HEAD_SLACK + B ≤ 2 * d)
    (hR : ∀ t, t < T → IsWB y (runB P win usb sreq t x0).e →
      (runB P win usb sreq t x0).e.now ≤ (runB P win usb sreq t x0).e.ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumB P win usb sreq y m (runB P win usb sreq a x0) ≤ B)
    (t : Nat) (htT : t ≤ T)
    (hrdy : (runB P win usb sreq t x0).e.ts y ≤ (runB P win usb sreq t x0).e.now) :
    (runB P win usb sreq t x0).e.headValid y = true := by
  apply head_valid_of_countsB P win usb sreq hok y t x0 hW h0
  by_cases hc : cntB P win usb sreq (fun z => IsRet P y z.e) t x0
      ≤ cntB P win usb sreq (fun z => Hit y z.e) t x0 + 1
  · exact hc
  · exfalso
    have hHS : HEAD_SLACK = PENDING_SLACK + 1 := rfl
    have hnow := now_runB P win usb sreq t x0
    obtain ⟨w, hwt, hwk, hwb⟩ := cntB_reach P win usb sreq (fun z => IsRet P y z.e) t x0
      (cntB P win usb sreq (fun z => IsRet P y z.e) t x0 - 2) (by omega)
    have hpb := pending_boundB P win usb sreq hok y x0 d R B T hW h0 hy hdly hd hnp hR hB
      (cntB P win usb sreq (fun z => IsRet P y z.e) t x0 - 2) t w htT hwt hwk hwb (by omega)
    obtain ⟨w2, hw2t, hw2k, hw2b⟩ := cntB_reach P win usb sreq (fun z => IsRet P y z.e) t x0
      (cntB P win usb sreq (fun z => IsRet P y z.e) t x0 - 1) (by omega)
    have hww2 : w < w2 := by
      rcases Nat.lt_or_ge w w2 with hlt | hge
      · exact hlt
      · have := cntB_mono P win usb sreq (fun z => IsRet P y z.e) x0 w2 w hge
        omega
    have hs1 := ts_ge_after_wbB P win usb sreq y x0 w w2 hww2 (isWB_of_ret P y _ hwb)
    have hs2 := ts_ge_after_wbB P win usb sreq y x0 w2 t hw2t (isWB_of_ret P y _ hw2b)
    omega

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-! ### Order: words dispatch in fetch order, whichever place they land in (Wilson (3)) -/

/-- The order invariant: the head holds word `nr` (the lane's retirements so far), the spare
word `nr + 1`, the buffer the word after those in the slots, and the word in flight is the
lane's next. -/
structure OrdB (x : EngB) : Prop where
  o1 : ∀ l, x.e.headValid l = true → x.sq l (x.e.sel l) = x.nr l
  o2 : ∀ l, x.e.spareValid l = true → x.sq l (!x.e.sel l) = x.nr l + 1
  o3 : ∀ l, x.buf l = true → x.bsq l = x.nr l + nslots x.e l
  o4 : x.e.pst ≠ .scan → x.psq = x.nr x.e.pl + nslots x.e x.e.pl

theorem nslots_hs (e : Engine) (l : Lane) :
    nslots e l = bnum (e.headValid l) + bnum (e.spareValid l) := by
  unfold nslots Engine.headValid Engine.spareValid
  cases e.sel l <;> simp [bnum] <;> omega

theorem nrB_eq (x : EngB) (l : Lane) :
    nrB P x l = x.nr l + (if IsRet P l x.e then 1 else 0) := by
  unfold nrB
  by_cases h : x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · have hR : IsRet P l x.e := ⟨h.1, h.2.1.symm, h.2.1 ▸ h.2.2⟩
    rw [if_pos h, if_pos hR]
  · have hR : ¬IsRet P l x.e := fun h' => h ⟨h'.1, h'.2.1.symm, h'.2.1 ▸ h'.2.2⟩
    rw [if_neg h, if_neg hR]
    rfl

/-- With nothing filling lane `l` this cycle, retirements and slots trade one for one. -/
theorem nslots_nofill (x : EngB) (hW : WfB x) (l : Lane) (hc : ∀ s, capTo x l s = false)
    (hl : ∀ s, loadTo x l s = false) :
    nrB P x l + nslots (stepB P win usb sreq x).e l = x.nr l + nslots x.e l := by
  have h0 := slot_balanceB P x hW l false
  have h1 := slot_balanceB P x hW l true
  have hr := ret_split P x l
  rw [hc, hl] at h0 h1
  rw [nrB_eq]
  show x.nr l + _ + (bnum (actvB P x l false) + bnum (actvB P x l true))
    = x.nr l + (bnum (x.e.actv l false) + bnum (x.e.actv l true))
  unfold bnum
  simp only [Bool.false_eq_true, if_false, Nat.add_zero] at h0 h1
  omega

theorem stepB_sq (x : EngB) : (stepB P win usb sreq x).sq = sqB x := rfl
theorem stepB_nr (x : EngB) : (stepB P win usb sreq x).nr = nrB P x := rfl
theorem stepB_bsq (x : EngB) : (stepB P win usb sreq x).bsq = bsqB x := rfl
theorem stepB_psq (x : EngB) : (stepB P win usb sreq x).psq = psqB P usb sreq x := rfl

/-- A lane whose head is valid and spare empty holds exactly one slot word. -/
theorem nslots_one (e : Engine) (l : Lane) (hh : e.headValid l = true)
    (hs : e.actv l (!e.sel l) = false) : nslots e l = 1 := by
  rw [nslots_hs]
  have : e.spareValid l = false := hs
  rw [hh, this]
  rfl

theorem nslots_zero (e : Engine) (l : Lane) (hH : HeadFirst e) (hh : e.headValid l = false) :
    nslots e l = 0 := by
  rw [nslots_hs, hh, hH l hh]
  rfl

theorem ordB_o1 (x : EngB) (hW : WfB x) (hO : OrdB x) (l : Lane)
    (hv : actvB P x l (selNext P x.e l) = true) : sqB x l (selNext P x.e l) = nrB P x l := by
  by_cases hr : x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · have hsel : selNext P x.e l = !x.e.sel l := by
      unfold selNext
      rw [if_pos hr]
    have hnr : nrB P x l = x.nr l + 1 := by
      unfold nrB
      rw [if_pos hr]
    have hhv : x.e.headValid l = true := by
      have := hW.disp (by rw [hr.1]; decide)
      rw [← hr.2.1] at this
      exact this
    rw [hsel] at hv ⊢
    rw [hnr]
    unfold sqB
    cases hc : capTo x l (!x.e.sel l)
    · cases hld : loadTo x l (!x.e.sel l)
      · simp only [Bool.false_eq_true, if_false]
        have hsv : x.e.actv l (!x.e.sel l) = true := by
          unfold actvB at hv
          rw [hc, hld] at hv
          rw [if_neg (fun h => by
            have := h.2.2.1
            rw [← h.2.1] at this
            cases hq : x.e.sel l <;> rw [hq] at this <;> cases this)] at hv
          simpa using hv
        exact hO.o2 l hsv
      · simp only [Bool.false_eq_true, if_false, if_true]
        have hsp := loadTo_spec x l _ hld
        rw [hO.o3 l hsp.1, nslots_one x.e l hhv hsp.2.2]
    · simp only [if_true]
      obtain ⟨hpc, hlp⟩ := capTo_cap x l _ hc
      have he := fill_empty x hW l _ (by rw [hc]; rfl)
      rw [hO.o4 (by rw [hpc]; decide), ← hlp, nslots_one x.e l hhv he]
  · have hsel : selNext P x.e l = x.e.sel l := by
      unfold selNext
      rw [if_neg hr]
    have hnr : nrB P x l = x.nr l := by
      unfold nrB
      rw [if_neg hr]
    rw [hsel] at hv ⊢
    rw [hnr]
    have hld : loadTo x l (x.e.sel l) = false := by
      cases h : loadTo x l (x.e.sel l)
      · rfl
      · have := (loadTo_spec x l _ h).2.1
        cases hq : x.e.sel l <;> rw [hq] at this <;> cases this
    unfold sqB
    rw [hld]
    cases hc : capTo x l (x.e.sel l)
    · simp only [Bool.false_eq_true, if_false]
      have hhv : x.e.actv l (x.e.sel l) = true := by
        rw [actvB_noret P x l _ hr, hc, hld] at hv
        simpa using hv
      exact hO.o1 l hhv
    · simp only [if_true]
      obtain ⟨hpc, hlp⟩ := capTo_cap x l _ hc
      have he : x.e.headValid l = false := fill_empty x hW l _ (by rw [hc]; rfl)
      rw [hO.o4 (by rw [hpc]; decide), ← hlp, nslots_zero x.e l hW.hf he]
      rfl

theorem ordB_o2 (x : EngB) (hW : WfB x) (hO : OrdB x) (l : Lane)
    (hv : actvB P x l (!selNext P x.e l) = true) :
    sqB x l (!selNext P x.e l) = nrB P x l + 1 := by
  by_cases hr : x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · exfalso
    have hsel : selNext P x.e l = !x.e.sel l := by
      unfold selNext
      rw [if_pos hr]
    rw [hsel, Bool.not_not] at hv
    unfold actvB at hv
    rw [if_pos ⟨hr.1, hr.2.1, congrArg x.e.sel hr.2.1, hr.2.2⟩] at hv
    cases hv
  · have hsel : selNext P x.e l = x.e.sel l := by
      unfold selNext
      rw [if_neg hr]
    have hnr : nrB P x l = x.nr l := by
      unfold nrB
      rw [if_neg hr]
    rw [hsel] at hv ⊢
    rw [hnr]
    unfold sqB
    cases hc : capTo x l (!x.e.sel l)
    · cases hld : loadTo x l (!x.e.sel l)
      · simp only [Bool.false_eq_true, if_false]
        have hsv : x.e.actv l (!x.e.sel l) = true := by
          rw [actvB_noret P x l _ hr, hc, hld] at hv
          simpa using hv
        exact hO.o2 l hsv
      · simp only [Bool.false_eq_true, if_false, if_true]
        have hsp := loadTo_spec x l _ hld
        rw [hO.o3 l hsp.1, nslots_one x.e l (hW.bh l hsp.1) hsp.2.2]
    · simp only [if_true]
      obtain ⟨hpc, hlp⟩ := capTo_cap x l _ hc
      have he := fill_empty x hW l _ (by rw [hc]; rfl)
      have hh := fill_spare_head x hW l _ (by rw [hc]; rfl) (by cases x.e.sel l <;> decide)
      rw [hO.o4 (by rw [hpc]; decide), ← hlp, nslots_one x.e l hh he]

theorem ordB_o3 (x : EngB) (hW : WfB x) (hO : OrdB x) (l : Lane) (hb : bufB x l = true) :
    bsqB x l = nrB P x l + nslots (stepB P win usb sreq x).e l := by
  unfold bsqB
  cases hcb : capBuf x l
  · simp only [Bool.false_eq_true, if_false]
    unfold bufB at hb
    rw [hcb] at hb
    simp only [Bool.false_eq_true, if_false] at hb
    have hbl : x.buf l = true ∧ x.e.spareValid l = true := by
      cases h1 : x.buf l <;> cases h2 : x.e.spareValid l <;> simp [h1, h2] at hb ⊢
    have hc : ∀ s, capTo x l s = false := fun s => by
      cases h : capTo x l s
      · rfl
      · obtain ⟨hpc, hlp⟩ := capTo_cap x l s h
        have := hW.fnb (by rw [hpc]; decide)
        rw [← hlp, hbl.1] at this
        cases this
    have hl : ∀ s, loadTo x l s = false := fun s => by
      cases h : loadTo x l s
      · rfl
      · have hsp := loadTo_spec x l s h
        have : x.e.actv l (!x.e.sel l) = true := hbl.2
        rw [← hsp.2.1, hsp.2.2] at this
        cases this
    have := nslots_nofill P win usb sreq x hW l hc hl
    rw [hO.o3 l hbl.1]
    omega
  · simp only [if_true]
    obtain ⟨hpc, hlp, hpb, hcs⟩ := capBuf_spec x l hcb
    have hb0 : x.buf l = false := by
      rw [hlp]
      exact hW.fnb (by rw [hpc]; decide)
    have hc : ∀ s, capTo x l s = false := fun s => by
      cases h : capTo x l s
      · rfl
      · have := capTo_second x l s h hpb
        rw [hcs] at this
        cases this
    have hl : ∀ s, loadTo x l s = false := fun s => loadTo_off x l s hb0
    have := nslots_nofill P win usb sreq x hW l hc hl
    rw [hO.o4 (by rw [hpc]; decide), ← hlp]
    omega


end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

theorem portNextM_scan_req (x : EngB) (hp : x.e.pst = .scan) :
    (portNextM P x).pst = .req ∨ (portNextM P x).pst = .scan := by
  cases hb : br1 P x.e with
  | some w =>
    left
    rw [portNextM_br1 P x hp hb]
  | none =>
    by_cases hc : (P.live x.e.prr && x.wantM x.e.prr) = true
    · left
      rw [portNextM_br2 P x hp hb hc]
    · right
      rw [portNextM_skip P x hp hb hc]

theorem scan_next_req (x : EngB) (hp : x.e.pst = .scan)
    (hne : (portNextB P usb sreq x).pst ≠ .scan) : (portNextB P usb sreq x).pst = .req := by
  have h : (portNextB P usb sreq x).pst = .req ∨ (portNextB P usb sreq x).pst = .scan := by
    cases hu : usbFirst P usb x.e with
    | true =>
      rw [(portNextB_usb P usb sreq x hp hu).1]
      exact portNextM_scan_req P x hp
    | false =>
      cases hs : sreq x with
      | none =>
        rw [(portNextB_none P usb sreq x hp hu hs).1]
        exact portNextM_scan_req P x hp
      | some w =>
        left
        rw [(portNextB_slot P usb sreq x hp hu hs).1]
  rcases h with h | h
  · exact h
  · exact absurd h hne

theorem ordB_o4 (hok : SReqB P sreq) (x : EngB) (hW : WfB x) (hO : OrdB x)
    (hne : (portNextB P usb sreq x).pst ≠ .scan) :
    psqB P usb sreq x = nrB P x (portNextB P usb sreq x).pl
      + nslots (stepB P win usb sreq x).e (portNextB P usb sreq x).pl := by
  cases hp : x.e.pst with
  | scan =>
    have hreq := scan_next_req P usb sreq x hp hne
    have hb0 := (issueB P usb sreq hok x hW hp hne).1
    have hc : ∀ s, capTo x (portNextB P usb sreq x).pl s = false :=
      fun s => capTo_off x _ s (by rw [hp]; decide)
    have hl : ∀ s, loadTo x (portNextB P usb sreq x).pl s = false :=
      fun s => loadTo_off x _ s hb0
    have := nslots_nofill P win usb sreq x hW _ hc hl
    unfold psqB
    rw [if_pos ⟨hp, hreq⟩]
    unfold EngB.held
    rw [hb0]
    simp only [bnum, Bool.false_eq_true, if_false, Nat.add_zero]
    omega
  | cap => exact absurd (cap_to_scan P usb sreq x hp) hne
  | req =>
    have hne' : x.e.pst ≠ .scan := by rw [hp]; decide
    have hkeep := (portNextB_keeps P usb sreq x hne').1
    rw [hkeep]
    have hb0 := hW.fnb hne'
    have hc : ∀ s, capTo x x.e.pl s = false := fun s => capTo_off x _ s (by rw [hp]; decide)
    have hl : ∀ s, loadTo x x.e.pl s = false := fun s => loadTo_off x _ s hb0
    have := nslots_nofill P win usb sreq x hW _ hc hl
    unfold psqB
    rw [if_neg (fun h => hne' h.1), hO.o4 hne']
    omega
  | wait =>
    have hne' : x.e.pst ≠ .scan := by rw [hp]; decide
    have hkeep := (portNextB_keeps P usb sreq x hne').1
    rw [hkeep]
    have hb0 := hW.fnb hne'
    have hc : ∀ s, capTo x x.e.pl s = false := fun s => capTo_off x _ s (by rw [hp]; decide)
    have hl : ∀ s, loadTo x x.e.pl s = false := fun s => loadTo_off x _ s hb0
    have := nslots_nofill P win usb sreq x hW _ hc hl
    unfold psqB
    rw [if_neg (fun h => hne' h.1), hO.o4 hne']
    omega

/-- **The order invariant survives a cycle.** -/
theorem ordB_step (hok : SReqB P sreq) (x : EngB) (hW : WfB x) (hO : OrdB x) :
    OrdB (stepB P win usb sreq x) where
  o1 := fun l hv => by
    rw [stepB_sq, stepB_nr]
    exact ordB_o1 P x hW hO l hv
  o2 := fun l hv => by
    rw [stepB_sq, stepB_nr]
    have hv' : actvB P x l (!selNext P x.e l) = true := hv
    exact ordB_o2 P x hW hO l hv'
  o3 := fun l hb => by
    rw [stepB_bsq, stepB_nr]
    exact ordB_o3 P win usb sreq x hW hO l hb
  o4 := fun hne => by
    rw [stepB_psq, stepB_nr]
    exact ordB_o4 P win usb sreq hok x hW hO hne

theorem ordB_run (hok : SReqB P sreq) :
    ∀ (n : Nat) (x : EngB), WfB x → OrdB x → OrdB (runB P win usb sreq n x)
  | 0, _, _, h => h
  | n + 1, x, hW, hO => ordB_run hok n (stepB P win usb sreq x)
      (wfB_step P win usb sreq hok x hW) (ordB_step P win usb sreq hok x hW hO)

theorem nr_run (l : Lane) :
    ∀ (n : Nat) (x : EngB),
      (runB P win usb sreq n x).nr l = x.nr l + cntB P win usb sreq (fun z => IsRet P l z.e) n x
  | 0, x => by simp [runB, cntB]
  | n + 1, x => by
    have ih := nr_run l n (stepB P win usb sreq x)
    have e1 : cntB P win usb sreq (fun z => IsRet P l z.e) (n + 1) x
        = (if IsRet P l x.e then 1 else 0)
          + cntB P win usb sreq (fun z => IsRet P l z.e) n (stepB P win usb sreq x) := rfl
    have e3 : runB P win usb sreq (n + 1) x = runB P win usb sreq n (stepB P win usb sreq x) := rfl
    rw [e3, ih, e1, stepB_nr, nrB_eq]
    omega

/-- **The order is kept (Wilson (3)).** From an ordered start, the lane's `k`-th retirement
(counting from 0) retires the word with fetch index `nr₀ + k`, wherever that word landed --
spare, buffer, or a late second fetch straight into the spare. -/
theorem order_kept (hok : SReqB P sreq) (x0 : EngB) (hW : WfB x0) (hO : OrdB x0) (l : Lane)
    (t : Nat) (hr : IsRet P l (runB P win usb sreq t x0).e) :
    (runB P win usb sreq t x0).sq l ((runB P win usb sreq t x0).e.sel l)
      = x0.nr l + cntB P win usb sreq (fun z => IsRet P l z.e) t x0 := by
  have hOt := ordB_run P win usb sreq hok t x0 hW hO
  have hWt := wfB_run P win usb sreq hok t x0 hW
  have hv : (runB P win usb sreq t x0).e.headValid l = true := by
    have := hWt.disp (by rw [hr.1]; decide)
    rw [hr.2.1] at this
    exact this
  rw [hOt.o1 l hv, nr_run]

/-- Each fetch is issued with the lane's next index: retirements so far plus words held. -/
theorem issue_index (x : EngB) (hp : x.e.pst = .scan)
    (hreq : (portNextB P usb sreq x).pst = .req) :
    (stepB P win usb sreq x).psq
      = x.nr (portNextB P usb sreq x).pl + x.held (portNextB P usb sreq x).pl := by
  rw [stepB_psq]
  unfold psqB
  rw [if_pos ⟨hp, hreq⟩]

/-- Retirements plus words held plus the word in flight count every capture: indices are
handed out in capture order. -/
theorem nr_held_run (hok : SReqB P sreq) (l : Lane) (n : Nat) (x : EngB) (hW : WfB x) :
    (runB P win usb sreq n x).nr l + (runB P win usb sreq n x).held l
      = x.nr l + x.held l + cntB P win usb sreq (fun z => Hit l z.e) n x := by
  have h1 := nr_run P win usb sreq l n x
  have h2 := held_run P win usb sreq hok l n x hW
  omega

/-! ### (1) The empty cycle: the load comes one cycle later, and dispatch never reads the gap -/

/-- **The gap follows a retirement.** A lane with a buffered word and an empty spare retired
on the previous cycle. -/
theorem empty_cycle_after_ret (x : EngB) (hW : WfB x) (l : Lane)
    (hb : (stepB P win usb sreq x).buf l = true)
    (hs : (stepB P win usb sreq x).e.spareValid l = false) : IsRet P l x.e := by
  change bufB x l = true at hb
  change actvB P x l (!selNext P x.e l) = false at hs
  have hboth : x.e.headValid l = true ∧ x.e.spareValid l = true := by
    unfold bufB at hb
    by_cases hc : capBuf x l = true
    · exact capSlot_none x.e l (capBuf_spec x l hc).2.2.2
    · rw [if_neg hc] at hb
      by_cases hl : (x.buf l && !x.e.spareValid l) = true
      · rw [if_pos hl] at hb
        cases hb
      · rw [if_neg hl] at hb
        refine ⟨hW.bh l hb, ?_⟩
        rw [hb] at hl
        simpa using hl
  by_cases hr : x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true
  · exact ⟨hr.1, hr.2.1.symm, hr.2.1 ▸ hr.2.2⟩
  · exfalso
    have hsel : selNext P x.e l = x.e.sel l := by
      unfold selNext
      rw [if_neg hr]
    rw [hsel] at hs
    have := actvB_of_true P x l _ (fun h => hr ⟨h.1, h.2.1, h.2.2.2⟩) hboth.2
    rw [hs] at this
    cases this

/-- **Dispatch never reads the gap.** In the empty cycle the dispatcher is idle (the cycle after
a writeback) and the empty slot is the spare: the head -- the only slot dispatch reads -- is
valid. -/
theorem empty_cycle_disp (x : EngB) (hW : WfB x) (l : Lane)
    (hb : (stepB P win usb sreq x).buf l = true)
    (hs : (stepB P win usb sreq x).e.spareValid l = false) :
    (stepB P win usb sreq x).e.st = .idle ∧ (stepB P win usb sreq x).e.headValid l = true := by
  have hr := empty_cycle_after_ret P win usb sreq x hW l hb hs
  refine ⟨?_, bufHead_stepB P win usb sreq x hW l hb⟩
  rw [stepB_e_st]
  simp [dispNext, hr.1]

/-- **The load, one cycle later.** In the empty cycle the buffered word loads into the spare and
the buffer empties. -/
theorem empty_cycle_load (x : EngB) (hW : WfB x) (l : Lane) (hb : x.buf l = true)
    (hs : x.e.spareValid l = false) :
    actvB P x l (!x.e.sel l) = true ∧ bufB x l = false := by
  have hld : loadTo x l (!x.e.sel l) = true := by
    unfold loadTo
    have : x.e.actv l (!x.e.sel l) = false := hs
    simp [hb, this]
  refine ⟨?_, ?_⟩
  · unfold actvB
    rw [if_neg (fun h => by
      have := h.2.2.1
      rw [← h.2.1] at this
      cases hq : x.e.sel l <;> rw [hq] at this <;> cases this)]
    rw [if_pos (by rw [hld]; simp)]
  · unfold bufB
    have hcb : capBuf x l = false := by
      cases h : capBuf x l
      · rfl
      · obtain ⟨hpc, hlp, _, _⟩ := capBuf_spec x l h
        have := hW.fnb (by rw [hpc]; decide)
        rw [← hlp, hb] at this
        cases this
    rw [hcb]
    simp [hb, hs]

/-! ### (2) The mask starves nothing -/

/-- **A buffered word is the lane's next word.** While the mask is up because the lane holds a
buffered word, that word is the one after the words in its slots. -/
theorem mask_buf_next (x : EngB) (hO : OrdB x) (l : Lane) (hb : x.buf l = true) :
    x.bsq l = x.nr l + nslots x.e l :=
  hO.o3 l hb

/-- **A second fetch in flight is the lane's next word.** -/
theorem mask_flight_next (x : EngB) (hO : OrdB x) (hp : x.e.pst ≠ .scan) :
    x.psq = x.nr x.e.pl + nslots x.e x.e.pl :=
  hO.o4 hp

end

/-! ### The count: slot fetches against retirements, two per ARM -/

/-- A slot issue for lane `u` (first or second fetch). -/
def SlotForB (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane) (u : Lane)
    (x : EngB) : Prop :=
  x.e.pst = .scan ∧ usbFirst P usb x.e = false ∧ sreq x = some u

instance (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane) (u : Lane) (x : EngB) :
    Decidable (SlotForB P usb sreq u x) :=
  inferInstanceAs (Decidable (x.e.pst = .scan ∧ usbFirst P usb x.e = false ∧ sreq x = some u))

/-- Any port issue for lane `u` this cycle. -/
def IssueFor (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane) (u : Lane)
    (x : EngB) : Prop :=
  x.e.pst = .scan ∧ (portNextB P usb sreq x).pst ≠ .scan ∧ (portNextB P usb sreq x).pl = u

instance (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane) (u : Lane) (x : EngB) :
    Decidable (IssueFor P usb sreq u x) :=
  inferInstanceAs (Decidable (x.e.pst = .scan ∧ (portNextB P usb sreq x).pst ≠ .scan ∧
    (portNextB P usb sreq x).pl = u))

/-- 1 if a fetch for `u` is in flight. -/
def inflight (x : EngB) (u : Lane) : Nat := if x.e.pst ≠ .scan ∧ x.e.pl = u then 1 else 0

/-- Words the lane holds or has coming. -/
def EngB.owns (x : EngB) (u : Lane) : Nat := x.held u + inflight x u

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

theorem inflight_step (x : EngB) (u : Lane) :
    inflight (stepB P win usb sreq x) u + (if Hit u x.e then 1 else 0)
      = inflight x u + (if IssueFor P usb sreq u x then 1 else 0) := by
  unfold inflight
  rw [stepB_pst, stepB_pl]
  by_cases hs : x.e.pst = .scan
  · have hH : ¬Hit u x.e := fun h => by
      have := h.1
      rw [hs] at this
      cases this
    rw [if_neg hH, if_neg (show ¬(x.e.pst ≠ .scan ∧ x.e.pl = u) from fun h => h.1 hs)]
    by_cases hI : IssueFor P usb sreq u x
    · rw [if_pos hI, if_pos (show (portNextB P usb sreq x).pst ≠ .scan ∧
        (portNextB P usb sreq x).pl = u from ⟨hI.2.1, hI.2.2⟩)]
    · rw [if_neg hI, if_neg (show ¬((portNextB P usb sreq x).pst ≠ .scan ∧
        (portNextB P usb sreq x).pl = u) from fun h => hI ⟨hs, h.1, h.2⟩)]
  · have hI : ¬IssueFor P usb sreq u x := fun h => hs h.1
    rw [if_neg hI]
    obtain ⟨h1, _⟩ := portNextB_of_ne P usb sreq x hs
    obtain ⟨hl, _⟩ := portNext_keeps P x.e hs
    rw [h1, hl]
    by_cases hc : x.e.pst = .cap
    · have h2 : (portNext P x.e).pst = .scan := by simp [portNext, hc]
      rw [h2, if_neg (show ¬((PState.scan : PState) ≠ .scan ∧ x.e.pl = u) from fun h => h.1 rfl)]
      by_cases hu : x.e.pl = u
      · rw [if_pos (show Hit u x.e from ⟨hc, hu⟩),
          if_pos (show x.e.pst ≠ .scan ∧ x.e.pl = u from ⟨hs, hu⟩)]
      · rw [if_neg (show ¬Hit u x.e from fun h => hu h.2),
          if_neg (show ¬(x.e.pst ≠ .scan ∧ x.e.pl = u) from fun h => hu h.2)]
    · have h2 : (portNext P x.e).pst ≠ .scan := by
        cases hp : x.e.pst with
        | scan => exact absurd hp hs
        | cap => exact absurd hp hc
        | req => simp [portNext, hp]
        | wait => simp [portNext, hp]
      rw [if_neg (show ¬Hit u x.e from fun h => hc h.1)]
      by_cases hu : x.e.pl = u
      · rw [if_pos (show (portNext P x.e).pst ≠ .scan ∧ x.e.pl = u from ⟨h2, hu⟩),
          if_pos (show x.e.pst ≠ .scan ∧ x.e.pl = u from ⟨hs, hu⟩)]
      · rw [if_neg (show ¬((portNext P x.e).pst ≠ .scan ∧ x.e.pl = u) from fun h => hu h.2),
          if_neg (show ¬(x.e.pst ≠ .scan ∧ x.e.pl = u) from fun h => hu h.2)]

theorem owns_step (x : EngB) (hW : WfB x) (u : Lane) :
    (stepB P win usb sreq x).owns u + (if IsRet P u x.e then 1 else 0)
      = x.owns u + (if IssueFor P usb sreq u x then 1 else 0) := by
  have h1 := held_step P win usb sreq x hW u
  have h2 := inflight_step P win usb sreq x u
  unfold EngB.owns
  omega

theorem owns_le (x : EngB) (hW : WfB x) (u : Lane) : x.owns u ≤ 3 := by
  unfold EngB.owns inflight
  rw [held_def]
  by_cases h : x.e.pst ≠ .scan ∧ x.e.pl = u
  · rw [if_pos h]
    have hb := hW.fnb h.1
    rw [h.2] at hb
    rw [hb]
    simp only [bnum, Bool.false_eq_true, if_false]
    split <;> split <;> omega
  · rw [if_neg h]
    unfold bnum
    split <;> split <;> split <;> omega

/-- The potential: words owned, at least one. -/
def potS (x : EngB) (u : Lane) : Nat := if x.owns u = 0 then 1 else x.owns u

/-- **One cycle of the count.** A slot issue for `u` raises the potential by one; only a
retirement of `u` lowers it, by at most one. -/
theorem slot_step (hok : SReqB P sreq) (x : EngB) (hW : WfB x) (u : Lane) :
    (if SlotForB P usb sreq u x then 1 else 0) + potS x u
      ≤ potS (stepB P win usb sreq x) u + (if IsRet P u x.e then 1 else 0) := by
  have ho := owns_step P win usb sreq x hW u
  have hr1 : (if IsRet P u x.e then 1 else 0) ≤ 1 := by split <;> omega
  have hi1 : (if IssueFor P usb sreq u x then 1 else 0) ≤ 1 := by split <;> omega
  unfold potS
  by_cases hs : SlotForB P usb sreq u x
  · rw [if_pos hs]
    obtain ⟨hp, hu, hsr⟩ := hs
    have hI : IssueFor P usb sreq u x := by
      have h1 := (portNextB_slot P usb sreq x hp hu hsr).1
      refine ⟨hp, ?_, ?_⟩ <;> rw [h1] <;> simp
    rw [if_pos hI] at ho
    have hv := (hok x u hsr).2.1
    have hheld : 1 ≤ x.owns u := by
      have : 1 ≤ x.held u := by
        rw [held_def]
        unfold Engine.headValid at hv
        cases hq : x.e.sel u <;> rw [hq] at hv <;> rw [hv] <;> simp only [if_true] <;> omega
      unfold EngB.owns
      omega
    rw [if_neg (show x.owns u ≠ 0 by omega)]
    by_cases h0 : (stepB P win usb sreq x).owns u = 0
    · rw [if_pos h0]
      omega
    · rw [if_neg h0]
      omega
  · rw [if_neg hs]
    by_cases h0 : x.owns u = 0
    · rw [if_pos h0]
      by_cases h1 : (stepB P win usb sreq x).owns u = 0
      · rw [if_pos h1]
        omega
      · rw [if_neg h1]
        omega
    · rw [if_neg h0]
      by_cases h1 : (stepB P win usb sreq x).owns u = 0
      · rw [if_pos h1]
        omega
      · rw [if_neg h1]
        omega

def cntSlot (u : Lane) : Nat → EngB → Nat :=
  cntB P win usb sreq (SlotForB P usb sreq u)

theorem slot_window (hok : SReqB P sreq) (u : Lane) :
    ∀ (m : Nat) (x : EngB), WfB x →
      cntB P win usb sreq (SlotForB P usb sreq u) m x + potS x u
        ≤ potS (runB P win usb sreq m x) u + cntB P win usb sreq (fun z => IsRet P u z.e) m x
  | 0, x, _ => by simp [cntB, runB]
  | m + 1, x, hW => by
    have h1 := slot_step P win usb sreq hok x hW u
    have ih := slot_window hok u m (stepB P win usb sreq x) (wfB_step P win usb sreq hok x hW)
    have e1 : cntB P win usb sreq (SlotForB P usb sreq u) (m + 1) x
        = (if SlotForB P usb sreq u x then 1 else 0)
          + cntB P win usb sreq (SlotForB P usb sreq u) m (stepB P win usb sreq x) := rfl
    have e2 : cntB P win usb sreq (fun z => IsRet P u z.e) (m + 1) x
        = (if IsRet P u x.e then 1 else 0)
          + cntB P win usb sreq (fun z => IsRet P u z.e) m (stepB P win usb sreq x) := rfl
    have e3 : runB P win usb sreq (m + 1) x = runB P win usb sreq m (stepB P win usb sreq x) := rfl
    rw [e1, e2, e3]
    omega

/-- **The per-window count with the buffer.** Over any `m` cycles from any point of a
well-formed run, lane `u`'s slot fetches (first and second) are at most its retirements
plus two. -/
theorem slot_countB (hok : SReqB P sreq) (u : Lane) (x0 : EngB) (hW : WfB x0) (m a : Nat) :
    cntB P win usb sreq (SlotForB P usb sreq u) m (runB P win usb sreq a x0)
      ≤ cntB P win usb sreq (fun z => IsRet P u z.e) m (runB P win usb sreq a x0) + 2 := by
  have hWa := wfB_run P win usb sreq hok a x0 hW
  have h := slot_window P win usb sreq hok u m (runB P win usb sreq a x0) hWa
  have hle := owns_le _ (wfB_run P win usb sreq hok m _ hWa) u
  have hp1 : 1 ≤ potS (runB P win usb sreq a x0) u := by
    unfold potS
    split <;> omega
  have hp3 : potS (runB P win usb sreq m (runB P win usb sreq a x0)) u ≤ 3 := by
    unfold potS
    split <;> omega
  omega

/-- **Two per ARM.** The certificate's charge (`SLOT_FETCHES_PER_ARM` = 2 slot fetches per
retirement-delimited window, plus the open one) covers the slot's fetches. -/
theorem slot_count_two (hok : SReqB P sreq) (u : Lane) (x0 : EngB) (hW : WfB x0) (m a : Nat) :
    cntB P win usb sreq (SlotForB P usb sreq u) m (runB P win usb sreq a x0)
      ≤ SLOT_FETCHES_PER_ARM *
          (cntB P win usb sreq (fun z => IsRet P u z.e) m (runB P win usb sreq a x0) + 1) := by
  have h := slot_countB P win usb sreq hok u x0 hW m a
  have h2 : SLOT_FETCHES_PER_ARM = 2 := slot_fetches_per_arm_val
  rw [h2]
  omega

end

end JLane
