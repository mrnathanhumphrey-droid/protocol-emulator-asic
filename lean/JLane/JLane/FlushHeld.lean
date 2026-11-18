import JLane.FlushKill
/-!
# Brick K2b — the edge word is still held at the edge: the buffered armed view (Wilson 11-17)

The carry-through, part 2. `FlushKill` proves BufEng's invariant across the keep-flush given
`FlushOk`, and `FlushKeep.edge_survives_flush` keeps the edge word **if it is held or arriving at
the edge** (`hasEdge`). Here both premises are discharged on the buffered engine itself:

* **persistence** (`heldB_step`, `heldB_run`): on a lane that is not flushed, a word held in a
  slot or the buffer -- or arriving by an unkilled capture -- is still held after the cycle
  (a buffered word may load into the spare, keeping its fetch index), unless it is the head a
  retirement consumes;
* **the armed view** (`EngBA`, `stepBA`): BufEng's engine with the ARM registers of
  `Armed.lean` -- an ARM's retiring writeback arms its lane with the edge cycle `edge now l`
  (`≥ now + 1`); the edge (`hit`) is the keep-flush; the dispatcher never picks an armed lane
  (`winA`, the RTL's `rdy_rel = … & ~armed`). `armInvB_step`: an armed lane is not being
  dispatched and its edge is not past. `flushOk_hit`: **the flushed lane is not dispatched next**
  -- `FlushOk`'s first condition, discharged;
* **held at the edge** (`edge_held_at_edge`): from the ARM's writeback to its edge the lane is
  armed, so nothing retires on it and no edge flushes it; a word held or arriving (unkilled) at
  the writeback, other than the ARM itself (the head that writeback consumes), is held at the
  edge -- and then `edge_survives_flushK` makes it the head at the edge path's release.

`FlushOk`'s second condition (the scan does not issue for a lane flushed in its own cycle) stays
a premise: it is agent 1's 11-14 port fix (`FlushStep.liveFl`), an RTL contract.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (fl : Lane → Bool) (k : Lane → Nat)

theorem sqK (X : EngBK) (l : Lane) (s : Slot) :
    (stepBKK P win usb sreq fl k X).x.sq l s =
      (if fl l = true ∧ s = keepSlot X.base l (k l) then k l
       else sqB X.base l s) := rfl

theorem bsqK (X : EngBK) (l : Lane) :
    (stepBKK P win usb sreq fl k X).x.bsq l = bsqB X.base l := rfl

/-- The lane holds the word with fetch index `kk` (slot or buffer). -/
def EngB.holds (x : EngB) (l : Lane) (kk : Nat) : Bool :=
  x.inSlot l kk true || x.inSlot l kk false || x.inBuf l kk

theorem holds_hasEdge (x : EngB) (l : Lane) (kk : Nat) (h : x.holds l kk = true) :
    x.hasEdge l kk = true := by
  unfold EngB.holds at h
  unfold EngB.hasEdge
  rw [h]
  rfl

theorem holds_of_slot (x : EngB) (l : Lane) (kk : Nat) (s : Slot) (h : x.inSlot l kk s = true) :
    x.holds l kk = true := by
  unfold EngB.holds
  cases s <;> simp [h]

/-- **Persistence, one cycle.** On a lane not flushed this cycle, a word held now -- or captured
now by a fetch that is not killed -- is held after the cycle, unless it is the head a retirement
consumes this cycle. -/
theorem heldB_step (X : EngBK) (hW : WfB X.base) (l : Lane) (kk : Nat) (hf : fl l = false)
    (hh : X.base.holds l kk = true ∨ (X.base.inCap l kk = true ∧ X.pkill = false))
    (hnr : X.base.e.st = .wb → l = X.base.e.cur → P.ret X.base.e.now X.base.e.cur = true →
      X.base.inSlot l kk (X.base.e.sel l) = false) :
    (stepBKK P win usb sreq fl k X).x.holds l kk = true := by
  -- a fetch in flight for `l` means `l`'s buffer is empty
  have hcapnb : ∀ s, capTo X.base l s = true → X.base.buf l = false := by
    intro s hc
    obtain ⟨hpc, hlp⟩ := capTo_cap X.base l s hc
    rw [hlp]
    exact hW.fnb (by rw [hpc]; decide)
  rcases hh with hh | ⟨hc, hk⟩
  · unfold EngB.holds at hh
    -- a word in a slot
    have slot_case : ∀ s, X.base.inSlot l kk s = true →
        (stepBKK P win usb sreq fl k X).x.holds l kk = true := by
      intro s hs
      unfold EngB.inSlot at hs
      simp only [Bool.and_eq_true, decide_eq_true_eq] at hs
      obtain ⟨ha, hq⟩ := hs
      have hnc : capTo X.base l s = false := by
        cases h : capTo X.base l s
        · rfl
        · have := fill_empty X.base hW l s (by rw [h]; rfl)
          rw [ha] at this
          cases this
      have hnl : loadTo X.base l s = false := by
        cases h : loadTo X.base l s
        · rfl
        · have := (loadTo_spec X.base l s h).2.2
          rw [ha] at this
          cases this
      have hnret : ¬(X.base.e.st = .wb ∧ l = X.base.e.cur ∧ s = X.base.e.sel X.base.e.cur ∧
          P.ret X.base.e.now X.base.e.cur = true) := by
        rintro ⟨hw, hlc, hss, hr⟩
        have := hnr hw hlc hr
        rw [← hlc] at hss
        rw [← hss] at this
        unfold EngB.inSlot at this
        rw [ha, hq] at this
        simp at this
      apply holds_of_slot _ l kk s
      unfold EngB.inSlot
      rw [actvK, sqK, hf]
      simp only [Bool.false_eq_true, false_and, ↓reduceIte, hnc, Bool.and_false]
      have h1 : (stepB P win usb sreq X.base).e.actv l s = true :=
        actvB_of_true P X.base l s hnret ha
      have h2 : sqB X.base l s = kk := by
        unfold sqB
        rw [hnc, hnl]
        simpa using hq
      rw [h1, h2]
      simp
    rcases (Bool.or_eq_true _ _).mp hh with h12 | hb
    · rcases (Bool.or_eq_true _ _).mp h12 with h1 | h2
      · exact slot_case true h1
      · exact slot_case false h2
    · -- a word in the buffer
      unfold EngB.inBuf at hb
      simp only [Bool.and_eq_true, decide_eq_true_eq] at hb
      obtain ⟨hbuf, hbq⟩ := hb
      have hncap : ∀ s, capTo X.base l s = false := by
        intro s
        cases h : capTo X.base l s
        · rfl
        · have := hcapnb s h
          rw [hbuf] at this
          cases this
      have hncb : capBuf X.base l = false := by
        cases h : capBuf X.base l
        · rfl
        · obtain ⟨hpc, hlp, -, -⟩ := capBuf_spec X.base l h
          have := hW.fnb (by rw [hpc]; decide)
          rw [← hlp, hbuf] at this
          cases this
      have hkl : (X.kc && decide (l = X.base.e.pl)) = false := by
        cases h : X.kc
        · rfl
        · have hpc := (kc_spec X h).1
          rw [← base_e] at hpc
          have hnb := hW.fnb (by rw [hpc]; decide)
          cases hl : decide (l = X.base.e.pl)
          · rfl
          · simp only [decide_eq_true_eq] at hl
            rw [← hl, hbuf] at hnb
            cases hnb
      by_cases hsp : X.base.e.spareValid l = true
      · -- stays in the buffer
        unfold EngB.holds EngB.inBuf
        rw [bufK, bsqK, hf]
        simp only [Bool.false_eq_true, ↓reduceIte, hkl]
        have hb' : (stepB P win usb sreq X.base).buf l = true := by
          show bufB X.base l = true
          unfold bufB
          rw [hncb, hbuf, hsp]
          simp
        have hq' : bsqB X.base l = kk := by
          unfold bsqB
          rw [hncb]
          simpa using hbq
        rw [hb', hq']
        simp
      · -- loads into the spare
        have hse : X.base.e.actv l (!X.base.e.sel l) = false := by
          simpa [Engine.spareValid] using hsp
        have hld : loadTo X.base l (!X.base.e.sel l) = true := by
          unfold loadTo
          rw [hbuf, hse]
          simp
        have hnret : ¬(X.base.e.st = .wb ∧ l = X.base.e.cur ∧
            (!X.base.e.sel l) = X.base.e.sel X.base.e.cur ∧
            P.ret X.base.e.now X.base.e.cur = true) := by
          rintro ⟨-, hlc, hss, -⟩
          rw [← hlc] at hss
          cases hq : X.base.e.sel l <;> rw [hq] at hss <;> cases hss
        apply holds_of_slot _ l kk (!X.base.e.sel l)
        unfold EngB.inSlot
        rw [actvK, sqK, hf]
        simp only [Bool.false_eq_true, false_and, ↓reduceIte, hncap, Bool.and_false]
        have h1 : (stepB P win usb sreq X.base).e.actv l (!X.base.e.sel l) = true := by
          show actvB P X.base l (!X.base.e.sel l) = true
          unfold actvB
          rw [if_neg hnret, hld]
          simp
        have h2 : sqB X.base l (!X.base.e.sel l) = kk := by
          unfold sqB
          rw [hncap, hld]
          simpa using hbq
        rw [h1, h2]
        simp
  · -- arriving by an unkilled capture
    unfold EngB.inCap at hc
    simp only [Bool.and_eq_true, decide_eq_true_eq] at hc
    obtain ⟨⟨hpc, hlp⟩, hpq⟩ := hc
    have hkc : X.kc = false := by
      unfold EngBK.kc
      rw [hk]
      simp
    -- the captured slot is empty, so it is not the head a retirement consumes
    have nret : ∀ s, X.base.e.actv l s = false → ¬(X.base.e.st = .wb ∧ l = X.base.e.cur ∧
        s = X.base.e.sel X.base.e.cur ∧ P.ret X.base.e.now X.base.e.cur = true) := by
      rintro s hs ⟨hw, hlc, hss, -⟩
      have := hW.disp (by rw [hw]; decide)
      unfold Engine.headValid at this
      rw [← hss, ← hlc, hs] at this
      cases this
    have slot_fill : ∀ s, capTo X.base l s = true →
        (stepBKK P win usb sreq fl k X).x.holds l kk = true := by
      intro s hct
      have he := fill_empty X.base hW l s (by rw [hct]; rfl)
      apply holds_of_slot _ l kk s
      unfold EngB.inSlot
      rw [actvK, sqK, hf]
      simp only [Bool.false_eq_true, false_and, ↓reduceIte, hkc, Bool.false_and]
      have h1 : (stepB P win usb sreq X.base).e.actv l s = true := by
        show actvB P X.base l s = true
        unfold actvB
        rw [if_neg (nret s he), hct]
        simp
      have h2 : sqB X.base l s = kk := by
        unfold sqB
        rw [hct]
        simpa using hpq
      rw [h1, h2]
      simp
    cases hpb : X.base.pb
    · apply slot_fill X.base.e.pslot
      unfold capTo
      simp [hpc, hlp, hpb]
    · cases hcs : capSlot X.base.e l with
      | some s =>
        apply slot_fill s
        unfold capTo
        simp [hpc, ← hlp, hpb, hcs]
      | none =>
        have hcb : capBuf X.base l = true := by
          unfold capBuf
          simp [hpc, ← hlp, hpb, hcs]
        unfold EngB.holds EngB.inBuf
        rw [bufK, bsqK, hf]
        simp only [Bool.false_eq_true, ↓reduceIte, hkc, Bool.false_and]
        have hb' : (stepB P win usb sreq X.base).buf l = true := by
          show bufB X.base l = true
          unfold bufB
          rw [hcb]
          rfl
        have hq' : bsqB X.base l = kk := by
          unfold bsqB
          rw [hcb]
          simpa using hpq
        rw [hb', hq']
        simp

end

theorem holds_base (X : EngBK) (l : Lane) (kk : Nat) : X.base.holds l kk = X.x.holds l kk := by
  unfold EngBK.base; split <;> rfl

/-! ### The armed view on the buffered engine -/

/-- The buffered engine (with the kill) and the ARM registers (`Armed.Engine3`'s). -/
structure EngBA where
  X     : EngBK
  armed : Lane → Bool
  armE  : Lane → Nat

/-- `arm_hit`: the lane is armed and its edge is this cycle. -/
def EngBA.hit (A : EngBA) (l : Lane) : Bool := A.armed l && decide (A.X.x.e.now = A.armE l)

/-- This cycle arms `l`: a retiring writeback of `l` whose head is an ARM (`isArm`, the word's
opcode, abstract as in `Slot.RaiseAtCapture`). -/
def EngBA.arms (P : Program) (isArm : EngB → Bool) (A : EngBA) (l : Lane) : Bool :=
  decide (A.X.x.e.st = .wb) && decide (l = A.X.x.e.cur) && P.ret A.X.x.e.now A.X.x.e.cur &&
    isArm A.X.base

/-- The dispatcher never picks an armed lane (`rdy_rel = … & ~armed`, `Armed.winq3`). -/
def winA (win : Engine → Option Lane) (armed : Lane → Bool) : Engine → Option Lane :=
  fun e => match win e with
    | some v => if armed v = true then none else some v
    | none => none

/-- One cycle: the buffered step with the edges as keep-flushes (`stepBKK`, `fl := hit`), the
dispatcher masked by `armed`, arming at an ARM's retiring writeback with the edge cycle
`edge now l`, disarming at the edge. -/
def stepBA (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
    (k : Lane → Nat) (A : EngBA) : EngBA :=
  { X := stepBKK P (winA win A.armed) usb sreq A.hit k A.X
    armed := fun l => if A.hit l = true then false
      else if A.arms P isArm l = true then true else A.armed l
    armE := fun l => if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l }

/-- The armed invariant: an armed lane is not being dispatched, and its edge is not past. -/
def ArmInvB (A : EngBA) : Prop :=
  (∀ l, A.armed l = true → ¬(A.X.x.e.st ≠ .idle ∧ A.X.x.e.cur = l)) ∧
  (∀ l, A.armed l = true → A.X.x.e.now ≤ A.armE l)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)

theorem stepBA_now (k : Lane → Nat) (A : EngBA) :
    (stepBA P win usb sreq isArm edge k A).X.x.e.now = A.X.x.e.now + 1 := by
  show (stepB P (winA win A.armed) usb sreq A.X.base).e.now = _
  rw [stepB_e_now, base_e]

/-- **An armed lane is not the lane dispatched next.** -/
theorem next_disp_ne (A : EngBA) (hA : ArmInvB A) (l : Lane) (ha : A.armed l = true)
    (hne : (stepB P (winA win A.armed) usb sreq A.X.base).e.st ≠ .idle) :
    (stepB P (winA win A.armed) usb sreq A.X.base).e.cur ≠ l := by
  have hbe := base_e A.X
  change (dispNext (winA win A.armed) A.X.base.e).st ≠ .idle at hne
  show (dispNext (winA win A.armed) A.X.base.e).cur ≠ l
  rw [hbe] at hne ⊢
  have hcur := hA.1 l ha
  cases hs : A.X.x.e.st with
  | wb =>
    have : (dispNext (winA win A.armed) A.X.x.e).st = .idle := by simp [dispNext, hs]
    exact absurd this hne
  | drive =>
    have hd : (dispNext (winA win A.armed) A.X.x.e).cur = A.X.x.e.cur := by simp [dispNext, hs]
    rw [hd]
    intro h
    exact hcur ⟨by rw [hs]; decide, h⟩
  | idle =>
    revert hne
    unfold dispNext
    rw [hs]
    dsimp only
    unfold winA
    cases hw : win A.X.x.e with
    | none =>
      dsimp only
      intro h
      exact (h rfl).elim
    | some v =>
      dsimp only
      by_cases hav : A.armed v = true
      · rw [if_pos hav]
        dsimp only
        intro h
        exact (h rfl).elim
      · rw [if_neg hav]
        dsimp only
        by_cases hv : A.X.x.e.headValid v = true
        · rw [if_pos hv]
          intro _ hvl
          have hvl' : v = l := hvl
          rw [hvl'] at hav
          exact hav ha
        · rw [if_neg hv]
          intro h
          exact (h rfl).elim

/-- **The armed invariant survives a cycle** (edges at least one cycle after the writeback). -/
theorem armInvB_step (k : Lane → Nat) (hedge : ∀ t l, t + 1 ≤ edge t l) (A : EngBA)
    (hA : ArmInvB A) : ArmInvB (stepBA P win usb sreq isArm edge k A) := by
  have hn := stepBA_now P win usb sreq isArm edge k A
  constructor
  · intro l ha
    show ¬((stepB P (winA win A.armed) usb sreq A.X.base).e.st ≠ .idle ∧
      (stepB P (winA win A.armed) usb sreq A.X.base).e.cur = l)
    change (if A.hit l = true then false
      else if A.arms P isArm l = true then true else A.armed l) = true at ha
    by_cases hh : A.hit l = true
    · rw [if_pos hh] at ha
      cases ha
    · rw [if_neg hh] at ha
      by_cases har : A.arms P isArm l = true
      · -- armed at its own writeback: the dispatcher goes idle
        unfold EngBA.arms at har
        simp only [Bool.and_eq_true, decide_eq_true_eq] at har
        have hwb := har.1.1.1
        rintro ⟨hne, -⟩
        apply hne
        show (dispNext (winA win A.armed) A.X.base.e).st = .idle
        rw [base_e]
        simp [dispNext, hwb]
      · rw [if_neg har] at ha
        exact fun ⟨hne, hc⟩ => next_disp_ne P win usb sreq A hA l ha hne hc
  · intro l ha
    rw [hn]
    change (if A.hit l = true then false
      else if A.arms P isArm l = true then true else A.armed l) = true at ha
    show A.X.x.e.now + 1 ≤ (if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l)
    by_cases hh : A.hit l = true
    · rw [if_pos hh] at ha
      cases ha
    · rw [if_neg hh] at ha
      by_cases har : A.arms P isArm l = true
      · rw [if_pos har]
        exact hedge _ _
      · rw [if_neg har] at ha ⊢
        have h1 := hA.2 l ha
        have h2 : A.X.x.e.now ≠ A.armE l := by
          intro h
          apply hh
          unfold EngBA.hit
          rw [ha, h]
          simp
        omega

/-- **`FlushOk` from the armed view**: an edge's lane is armed, so it is not dispatched next;
the scan condition is agent 1's port fix, a premise. -/
theorem flushOk_hit (A : EngBA) (hA : ArmInvB A)
    (hscan : ∀ l, A.hit l = true → A.X.x.e.pst = .scan →
      (stepB P (winA win A.armed) usb sreq A.X.base).e.pst ≠ .scan →
      (stepB P (winA win A.armed) usb sreq A.X.base).e.pl ≠ l) :
    FlushOk P (winA win A.armed) usb sreq A.hit A.X := by
  refine ⟨fun l hh hne => ?_, hscan⟩
  have ha : A.armed l = true := by
    unfold EngBA.hit at hh
    simp only [Bool.and_eq_true] at hh
    exact hh.1
  exact next_disp_ne P win usb sreq A hA l ha hne

/-! ### Runs and the edge -/

/-- `n` cycles, the edge words' indices read by time. -/
def runBA (kt : Nat → Lane → Nat) : Nat → EngBA → EngBA
  | 0, A => A
  | n + 1, A => stepBA P win usb sreq isArm edge (kt (runBA kt n A).X.x.e.now) (runBA kt n A)

/-- The scan condition along a run (agent 1's port fix). -/
def ScanOk (A : EngBA) : Prop :=
  ∀ l, A.hit l = true → A.X.x.e.pst = .scan →
    (stepB P (winA win A.armed) usb sreq A.X.base).e.pst ≠ .scan →
    (stepB P (winA win A.armed) usb sreq A.X.base).e.pl ≠ l

/-- **One armed cycle before the edge**: the lane stays armed with the same edge, and a word
held (or arriving unkilled) is held after the cycle. -/
theorem armed_step (k : Lane → Nat) (A : EngBA) (l : Lane) (kk : Nat) (hW : WfBK A.X)
    (hA : ArmInvB A) (ha : A.armed l = true) (hlt : A.X.x.e.now < A.armE l)
    (hh : A.X.base.holds l kk = true ∨ (A.X.base.inCap l kk = true ∧ A.X.pkill = false)) :
    (stepBA P win usb sreq isArm edge k A).armed l = true ∧
    (stepBA P win usb sreq isArm edge k A).armE l = A.armE l ∧
    (stepBA P win usb sreq isArm edge k A).X.base.holds l kk = true := by
  have hnhit : A.hit l = false := by
    unfold EngBA.hit
    rw [ha]
    simp only [Bool.true_and, decide_eq_false_iff_not]
    omega
  have hna : A.arms P isArm l = false := by
    unfold EngBA.arms
    cases hw : decide (A.X.x.e.st = .wb)
    · rfl
    · simp only [decide_eq_true_eq] at hw
      cases hc : decide (l = A.X.x.e.cur)
      · simp
      · simp only [decide_eq_true_eq] at hc
        exact absurd ⟨by rw [hw]; decide, hc.symm⟩ (hA.1 l ha)
  refine ⟨?_, ?_, ?_⟩
  · show (if A.hit l = true then false
      else if A.arms P isArm l = true then true else A.armed l) = true
    rw [hnhit, hna, ha]
    rfl
  · show (if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l) = A.armE l
    rw [hna]
    rfl
  · rw [holds_base]
    apply heldB_step P (winA win A.armed) usb sreq A.hit k A.X hW.wf l kk hnhit hh
    intro hw hlc _
    exfalso
    rw [base_e] at hw hlc
    exact hA.1 l ha ⟨by rw [hw]; decide, hlc.symm⟩

/-- **Held at the edge, from any armed cycle.** A word held -- or arriving by an unkilled
capture -- on an armed lane before its edge is held at the edge cycle `armE l`: it covers the
edge word captured after the ARM's writeback (through the scan, the writeback can be at `c + 3`
and the capture at `c + 4`). -/
theorem edge_held_armed (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (kt : Nat → Lane → Nat) (A0 : EngBA) (l : Lane) (kk : Nat)
    (hI : WfBK A0.X) (hA : ArmInvB A0) (ha0 : A0.armed l = true)
    (hlt : A0.X.x.e.now < A0.armE l)
    (hh : A0.X.base.holds l kk = true ∨ (A0.X.base.inCap l kk = true ∧ A0.X.pkill = false))
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0)) :
    ∀ i, 1 ≤ i → i ≤ A0.armE l - A0.X.x.e.now →
      (runBA P win usb sreq isArm edge kt i A0).armed l = true ∧
      (runBA P win usb sreq isArm edge kt i A0).armE l = A0.armE l ∧
      (runBA P win usb sreq isArm edge kt i A0).X.base.holds l kk = true ∧
      WfBK (runBA P win usb sreq isArm edge kt i A0).X ∧
      ArmInvB (runBA P win usb sreq isArm edge kt i A0) ∧
      (runBA P win usb sreq isArm edge kt i A0).X.x.e.now = A0.X.x.e.now + i := by
  have inv : ∀ n, WfBK (runBA P win usb sreq isArm edge kt n A0).X ∧
      ArmInvB (runBA P win usb sreq isArm edge kt n A0) ∧
      (runBA P win usb sreq isArm edge kt n A0).X.x.e.now = A0.X.x.e.now + n := by
    intro n
    induction n with
    | zero => exact ⟨hI, hA, rfl⟩
    | succ n ih =>
      obtain ⟨h1, h2, h3⟩ := ih
      refine ⟨?_, armInvB_step P win usb sreq isArm edge _ hedge _ h2, ?_⟩
      · exact wfBK_step P (winA win _) usb sreq _ _ hok _ h1
          (flushOk_hit P win usb sreq _ h2 (hscan n))
      · show (stepBA P win usb sreq isArm edge _ _).X.x.e.now = _
        rw [stepBA_now, h3]
        rfl
  intro i hi1 hij
  induction i with
  | zero => exact absurd hi1 (by decide)
  | succ i ih =>
    obtain ⟨hWi, hAi, hni⟩ := inv (i + 1)
    obtain ⟨hW0, hA0', hn0⟩ := inv i
    have pre : (runBA P win usb sreq isArm edge kt i A0).armed l = true ∧
        (runBA P win usb sreq isArm edge kt i A0).armE l = A0.armE l ∧
        ((runBA P win usb sreq isArm edge kt i A0).X.base.holds l kk = true ∨
          ((runBA P win usb sreq isArm edge kt i A0).X.base.inCap l kk = true ∧
            (runBA P win usb sreq isArm edge kt i A0).X.pkill = false)) := by
      cases i with
      | zero => exact ⟨ha0, rfl, hh⟩
      | succ i =>
        obtain ⟨a, b, c, -⟩ := ih (Nat.succ_pos i) (by omega)
        exact ⟨a, b, Or.inl c⟩
    obtain ⟨ha, hae, hho⟩ := pre
    have hlt' : (runBA P win usb sreq isArm edge kt i A0).X.x.e.now <
        (runBA P win usb sreq isArm edge kt i A0).armE l := by
      rw [hn0, hae]
      omega
    obtain ⟨r1, r2, r3⟩ := armed_step P win usb sreq isArm edge
      (kt (runBA P win usb sreq isArm edge kt i A0).X.x.e.now) _ l kk hW0 hA0' ha hlt' hho
    exact ⟨r1, r2.trans hae, r3, hWi, hAi, hni⟩

/-- **`ft_edge`, from any armed cycle**: a word held or arriving unkilled on an armed lane before
its edge is, the cycle after the edge, the lane's valid head, released that cycle. -/
theorem ft_edge_at_release_armed (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (kt : Nat → Lane → Nat) (A0 : EngBA) (l : Lane) (kk : Nat)
    (hI : WfBK A0.X) (hA : ArmInvB A0) (ha0 : A0.armed l = true)
    (hlt : A0.X.x.e.now < A0.armE l)
    (hh : A0.X.base.holds l kk = true ∨ (A0.X.base.inCap l kk = true ∧ A0.X.pkill = false))
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0))
    (hk : kt (A0.armE l) l = kk) :
    let j := A0.armE l - A0.X.x.e.now
    (runBA P win usb sreq isArm edge kt j A0).hit l = true ∧
    (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.headValid l = true ∧
    (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.sq l
      ((runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.sel l) = kk ∧
    (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.ts l =
      (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.now := by
  intro j
  obtain ⟨ha, hae, hho, -, -, hn⟩ :=
    edge_held_armed P win usb sreq isArm edge hok hedge kt A0 l kk hI hA ha0 hlt hh hscan j
      (by omega) (Nat.le_refl _)
  have hhit : (runBA P win usb sreq isArm edge kt j A0).hit l = true := by
    unfold EngBA.hit
    rw [ha, hae, hn]
    simp only [Bool.true_and, decide_eq_true_eq]
    omega
  refine ⟨hhit, ?_⟩
  have hkj : kt (runBA P win usb sreq isArm edge kt j A0).X.x.e.now l = kk := by
    rw [hn]
    have : A0.X.x.e.now + j = A0.armE l := by omega
    rw [this, hk]
  have := edge_survives_flushK P (winA win (runBA P win usb sreq isArm edge kt j A0).armed) usb
    sreq (runBA P win usb sreq isArm edge kt j A0).hit
    (kt (runBA P win usb sreq isArm edge kt j A0).X.x.e.now)
    (runBA P win usb sreq isArm edge kt j A0).X l hhit
    (by rw [hkj]; exact holds_hasEdge _ l kk hho)
  rw [hkj] at this
  exact this

/-- **The edge word is held at the edge.** At an ARM's retiring writeback on `l` (cycle `t₀`),
a word with fetch index `kk` that is held or arriving unkilled, and is not the head that
writeback consumes (the ARM itself), is still held at the edge cycle `edge t₀ l`; the lane is
armed until then, and the invariants hold. -/
theorem edge_held_at_edge (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (kt : Nat → Lane → Nat) (A0 : EngBA) (l : Lane) (kk : Nat)
    (hI : WfBK A0.X) (hA : ArmInvB A0) (harm : A0.arms P isArm l = true)
    (hh : A0.X.base.holds l kk = true ∨ (A0.X.base.inCap l kk = true ∧ A0.X.pkill = false))
    (hnh : A0.X.base.inSlot l kk (A0.X.base.e.sel l) = false)
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0)) :
    ∀ i, 1 ≤ i → i ≤ edge A0.X.x.e.now l - A0.X.x.e.now →
      (runBA P win usb sreq isArm edge kt i A0).armed l = true ∧
      (runBA P win usb sreq isArm edge kt i A0).armE l = edge A0.X.x.e.now l ∧
      (runBA P win usb sreq isArm edge kt i A0).X.base.holds l kk = true ∧
      WfBK (runBA P win usb sreq isArm edge kt i A0).X ∧
      ArmInvB (runBA P win usb sreq isArm edge kt i A0) ∧
      (runBA P win usb sreq isArm edge kt i A0).X.x.e.now = A0.X.x.e.now + i := by
  -- the run's invariants and clock, from 0
  have inv : ∀ n, WfBK (runBA P win usb sreq isArm edge kt n A0).X ∧
      ArmInvB (runBA P win usb sreq isArm edge kt n A0) ∧
      (runBA P win usb sreq isArm edge kt n A0).X.x.e.now = A0.X.x.e.now + n := by
    intro n
    induction n with
    | zero => exact ⟨hI, hA, rfl⟩
    | succ n ih =>
      obtain ⟨h1, h2, h3⟩ := ih
      refine ⟨?_, armInvB_step P win usb sreq isArm edge _ hedge _ h2, ?_⟩
      · exact wfBK_step P (winA win _) usb sreq _ _ hok _ h1
          (flushOk_hit P win usb sreq _ h2 (hscan n))
      · show (stepBA P win usb sreq isArm edge _ _).X.x.e.now = _
        rw [stepBA_now, h3]
        rfl
  have hE := hedge A0.X.x.e.now l
  intro i hi1 hij
  induction i with
  | zero => exact absurd hi1 (by decide)
  | succ i ih =>
    obtain ⟨hWi, hAi, hni⟩ := inv (i + 1)
    have hstep : runBA P win usb sreq isArm edge kt (i + 1) A0 =
        stepBA P win usb sreq isArm edge (kt (runBA P win usb sreq isArm edge kt i A0).X.x.e.now)
          (runBA P win usb sreq isArm edge kt i A0) := rfl
    obtain ⟨hW0, hA0, hn0⟩ := inv i
    -- the state before this cycle: either the writeback (i = 0) or armed, before the edge
    have pre : (i = 0 ∧ runBA P win usb sreq isArm edge kt i A0 = A0) ∨
        (1 ≤ i ∧ (runBA P win usb sreq isArm edge kt i A0).armed l = true ∧
          (runBA P win usb sreq isArm edge kt i A0).armE l = edge A0.X.x.e.now l ∧
          (runBA P win usb sreq isArm edge kt i A0).X.base.holds l kk = true) := by
      cases i with
      | zero => exact Or.inl ⟨rfl, rfl⟩
      | succ i =>
        obtain ⟨a, b, c, -⟩ := ih (Nat.succ_pos i) (by omega)
        exact Or.inr ⟨Nat.succ_pos i, a, b, c⟩
    -- this cycle has no edge on `l`, and no arming of `l` after the first
    rw [hstep]
    refine ⟨?_, ?_, ?_, hstep ▸ hWi, hstep ▸ hAi, hstep ▸ hni⟩
    · show (if (runBA P win usb sreq isArm edge kt i A0).hit l = true then false
        else if (runBA P win usb sreq isArm edge kt i A0).arms P isArm l = true then true
        else (runBA P win usb sreq isArm edge kt i A0).armed l) = true
      rcases pre with ⟨-, h0⟩ | ⟨-, ha, hae, -⟩
      · rw [h0]
        have hnh : A0.hit l = false := by
          unfold EngBA.arms at harm
          simp only [Bool.and_eq_true, decide_eq_true_eq] at harm
          cases hal : A0.armed l
          · unfold EngBA.hit; rw [hal]; rfl
          · exact absurd ⟨by rw [harm.1.1.1]; decide, harm.1.1.2.symm⟩ (hA.1 l hal)
        rw [hnh, harm]
        rfl
      · have hnh : (runBA P win usb sreq isArm edge kt i A0).hit l = false := by
          unfold EngBA.hit
          rw [ha, hae, hn0]
          simp only [Bool.true_and, decide_eq_false_iff_not]
          omega
        rw [hnh, ha]
        simp
    · show (if (runBA P win usb sreq isArm edge kt i A0).arms P isArm l = true
        then edge (runBA P win usb sreq isArm edge kt i A0).X.x.e.now l
        else (runBA P win usb sreq isArm edge kt i A0).armE l) = edge A0.X.x.e.now l
      rcases pre with ⟨-, h0⟩ | ⟨-, ha, hae, -⟩
      · rw [h0, harm]
        rfl
      · have hna : (runBA P win usb sreq isArm edge kt i A0).arms P isArm l = false := by
          unfold EngBA.arms
          cases hw : decide ((runBA P win usb sreq isArm edge kt i A0).X.x.e.st = .wb)
          · rfl
          · simp only [decide_eq_true_eq] at hw
            cases hc : decide (l = (runBA P win usb sreq isArm edge kt i A0).X.x.e.cur)
            · simp
            · simp only [decide_eq_true_eq] at hc
              exact absurd ⟨by rw [hw]; decide, hc.symm⟩ (hA0.1 l ha)
        rw [hna, hae]
        rfl
    · rw [holds_base]
      rcases pre with ⟨-, h0⟩ | ⟨-, ha, hae, hho⟩
      · -- the writeback cycle: the ARM retires; the edge word is not that head
        rw [h0]
        have hnhit : A0.hit l = false := by
          unfold EngBA.arms at harm
          simp only [Bool.and_eq_true, decide_eq_true_eq] at harm
          cases hal : A0.armed l
          · unfold EngBA.hit; rw [hal]; rfl
          · exact absurd ⟨by rw [harm.1.1.1]; decide, harm.1.1.2.symm⟩ (hA.1 l hal)
        exact heldB_step P (winA win A0.armed) usb sreq A0.hit _ A0.X hI.wf l kk hnhit hh
          (fun _ _ _ => hnh)
      · -- armed, before the edge: nothing retires on `l`, no edge flushes it
        have hnhit : (runBA P win usb sreq isArm edge kt i A0).hit l = false := by
          unfold EngBA.hit
          rw [ha, hae, hn0]
          simp only [Bool.true_and, decide_eq_false_iff_not]
          omega
        apply heldB_step P (winA win _) usb sreq _ _ _ hW0.wf l kk hnhit (Or.inl hho)
        intro hw hlc _
        exfalso
        rw [base_e] at hw hlc
        exact hA0.1 l ha ⟨by rw [hw]; decide, hlc.symm⟩

/-- **At the edge, the edge word is the head at the edge path's release** (`ft_edge`). From an
ARM's retiring writeback on `l` with its edge word (fetch index `kk`, not the ARM) held or
arriving unkilled: at the edge cycle `edge t₀ l` the keep-flush fires and, the cycle after, the
lane's head is valid, it is the word `kk`, and the lane is released that cycle. -/
theorem ft_edge_at_release (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (kt : Nat → Lane → Nat) (A0 : EngBA) (l : Lane) (kk : Nat)
    (hI : WfBK A0.X) (hA : ArmInvB A0) (harm : A0.arms P isArm l = true)
    (hh : A0.X.base.holds l kk = true ∨ (A0.X.base.inCap l kk = true ∧ A0.X.pkill = false))
    (hnh : A0.X.base.inSlot l kk (A0.X.base.e.sel l) = false)
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0))
    (hk : kt (edge A0.X.x.e.now l) l = kk) :
    let j := edge A0.X.x.e.now l - A0.X.x.e.now
    let Aj := runBA P win usb sreq isArm edge kt j A0
    Aj.hit l = true ∧
    (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.headValid l = true ∧
    (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.sq l
      ((runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.sel l) = kk ∧
    (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.ts l =
      (runBA P win usb sreq isArm edge kt (j + 1) A0).X.x.e.now := by
  intro j Aj
  have hE := hedge A0.X.x.e.now l
  obtain ⟨ha, hae, hho, -, -, hn⟩ :=
    edge_held_at_edge P win usb sreq isArm edge hok hedge kt A0 l kk hI hA harm hh hnh hscan j
      (by omega) (Nat.le_refl _)
  have hhit : Aj.hit l = true := by
    show (runBA P win usb sreq isArm edge kt j A0).hit l = true
    unfold EngBA.hit
    rw [ha, hae, hn]
    simp only [Bool.true_and, decide_eq_true_eq]
    omega
  refine ⟨hhit, ?_⟩
  have hkj : kt (runBA P win usb sreq isArm edge kt j A0).X.x.e.now l = kk := by
    rw [hn]
    have : A0.X.x.e.now + j = edge A0.X.x.e.now l := by omega
    rw [this, hk]
  have := edge_survives_flushK P (winA win Aj.armed) usb sreq Aj.hit
    (kt (runBA P win usb sreq isArm edge kt j A0).X.x.e.now) Aj.X l hhit
    (by rw [hkj]; exact holds_hasEdge _ l kk hho)
  rw [hkj] at this
  exact this

end

#print axioms heldB_step
#print axioms armInvB_step
#print axioms flushOk_hit
#print axioms edge_held_at_edge
#print axioms ft_edge_at_release
#print axioms edge_held_armed
#print axioms ft_edge_at_release_armed

end JLane
