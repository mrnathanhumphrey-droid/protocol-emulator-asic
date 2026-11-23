import JLane.FlushKeep
/-!
# Brick K2a — the buffered engine across the keep-flush, with the kill (Wilson 11-17)

The carry-through, part 1: BufEng's well-formedness (`WfB`) survives a FALLTHROUGH edge that keeps
the edge word (K1–K4, `FlushKeep`) **and** kills the lane's in-flight fetch (K5).

**K5 (the kill).** A fetch for the flushed lane that is in flight at the edge (REQ or WAIT) is
killed: its capture files nothing, while the port still runs `REQ → WAIT → CAP` (the RTL's
`pkill`, `FlushStep` l.4424, kept under the buffer). Without it the in-flight timeout word would
land in the spare the flush freed: a wrong-path word held behind the edge word. The edge word is
never the killed fetch: it is captured at or before the edge (`edge_capture_by_edge`).

Model. `EngBK` is `EngB` with the kill register. While a kill is pending the step runs on
`base`, the engine with the fetch marked second (`pb := true`): a killed capture files nothing, so
where it would have landed is never used, and BufEng's first-fetch conditions (`fe`, `sf`) are
not asked of it. `stepBKK` is `BufEng.stepB` on `base` with two overrides: flushed lanes keep only
their edge word and are released the next cycle (`FlushKeep.stepBK`), and a killed capture's slot
or buffer write is dropped.

Proved:
* `wfBK_step`, `wfBK_run` -- **the invariant**: `WfB` of `base`, and a kill pending only in WAIT or
  CAP (so it clears within two cycles), survive every cycle, under two conditions on the
  flush (`FlushOk`): a flushed lane is not the lane dispatched next (an armed lane is never
  dispatched, `Armed.ArmInv`; the buffered armed view is K2b), and the scan does not issue for a
  lane flushed in its own cycle (agent 1's 11-14 fix, `FlushStep.liveFl`);
* `stepBKK_noflush` -- with no flush and no kill pending, the cycle **is** `stepB`;
* `edge_survives_flushK`, `flushK_keeps_only_edge`, `flushK_buf_empty` -- K1 / K2 on this engine;
* `kill_files_nothing` -- K5: the killed capture's slot is empty after the cycle and the buffer is
  not written.
-/
namespace JLane

/-- The buffered engine with the kill register. -/
structure EngBK where
  x     : EngB
  pkill : Bool
  /-- ghost (K4, agent 1 11-22): the lane's `ts` is an edge's rebase (`ts` = the edge cycle), so
  its release is `ts + 1` (`EngBK.rel`) -- set at a flush, cleared at the lane's next writeback
  that moves `ts` (one with `dly + ext > 0`; a zero-delay writeback leaves the release at
  `ts + 1`), as `ArmFT.EngineT.reb` on the slot-off path -/
  reb   : Lane → Bool := fun _ => false

/-- The engine the cycle runs on: while a kill is pending, the in-flight fetch is a second fetch
(its capture is dropped, so where it would land is never used). -/
def EngBK.base (X : EngBK) : EngB := if X.pkill = true then { X.x with pb := true } else X.x

/-- This cycle is a killed capture. -/
def EngBK.kc (X : EngBK) : Bool := decide (X.x.e.pst = .cap) && X.pkill

theorem base_e (X : EngBK) : X.base.e = X.x.e := by
  unfold EngBK.base; split <;> rfl

theorem base_buf (X : EngBK) : X.base.buf = X.x.buf := by
  unfold EngBK.base; split <;> rfl

theorem base_pb_kill (X : EngBK) (h : X.pkill = true) : X.base.pb = true := by
  unfold EngBK.base; rw [if_pos h]

theorem base_nokill (X : EngBK) (h : X.pkill = false) : X.base = X.x := by
  unfold EngBK.base; rw [if_neg (by rw [h]; decide)]

theorem kc_spec (X : EngBK) (h : X.kc = true) : X.x.e.pst = .cap ∧ X.pkill = true := by
  unfold EngBK.kc at h
  simpa using h

/-- One cycle: `stepB` on `base`, flushed lanes keep only their edge word (K1–K4), a killed
capture is dropped (K5), and the kill register as the RTL's `pkill`. -/
def stepBKK (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) : EngBK :=
  let b := X.base
  let y := stepB P win usb sreq b
  { x := { y with
      e := { y.e with
        actv := fun l s => if fl l = true then b.hasEdge l (k l) && decide (s = keepSlot b l (k l))
          else if (X.kc && decide (l = b.e.pl) && capTo b l s) = true then false
          else y.e.actv l s
        sel := fun l => if fl l = true then keepSlot b l (k l) else y.e.sel l
        ts := fun l => if fl l = true then b.e.now else y.e.ts l }
      buf := fun l => if fl l = true then false
        else if (X.kc && decide (l = b.e.pl)) = true then false else y.buf l
      sq := fun l s => if fl l = true ∧ s = keepSlot b l (k l) then y.nr l else y.sq l s }
    pkill := if X.x.e.pst = .cap then false
      else X.pkill || (fl X.x.e.pl && (decide (X.x.e.pst = .req) || decide (X.x.e.pst = .wait)))
    reb := fun l => if fl l = true then true
      else if X.x.e.st = .wb ∧ l = X.x.e.cur ∧ 0 < P.dly l + P.ext X.x.e.now l then false
      else X.reb l }

/-- The release: one past a rebased `ts` (the RTL's registered release after its rebase), else
`ts`. The window bounds are anchored here; the EDF key reads `ts`. -/
def EngBK.rel (X : EngBK) (l : Lane) : Nat := X.x.e.ts l + (if X.reb l = true then 1 else 0)

/-- The invariant: BufEng's on the engine the cycle runs on, and a kill pending only in WAIT or
CAP. -/
structure WfBK (X : EngBK) : Prop where
  wf : WfB X.base
  ki : X.pkill = true → X.x.e.pst = .wait ∨ X.x.e.pst = .cap

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (fl : Lane → Bool) (k : Lane → Nat)

/-- The two conditions on a flush: a flushed lane is not dispatched next, and the scan does not
issue for a lane flushed in its own cycle. -/
def FlushOk (X : EngBK) : Prop :=
  (∀ l, fl l = true → (stepB P win usb sreq X.base).e.st ≠ .idle →
    (stepB P win usb sreq X.base).e.cur ≠ l) ∧
  (∀ l, fl l = true → X.x.e.pst = .scan → (stepB P win usb sreq X.base).e.pst ≠ .scan →
    (stepB P win usb sreq X.base).e.pl ≠ l)

/-! ### The step, field by field -/

theorem actvK (X : EngBK) (l : Lane) (s : Slot) :
    (stepBKK P win usb sreq fl k X).x.e.actv l s =
      (if fl l = true then X.base.hasEdge l (k l) && decide (s = keepSlot X.base l (k l))
       else if (X.kc && decide (l = X.base.e.pl) && capTo X.base l s) = true then false
       else (stepB P win usb sreq X.base).e.actv l s) := rfl

theorem selK (X : EngBK) (l : Lane) :
    (stepBKK P win usb sreq fl k X).x.e.sel l =
      (if fl l = true then keepSlot X.base l (k l) else (stepB P win usb sreq X.base).e.sel l) :=
  rfl

theorem bufK (X : EngBK) (l : Lane) :
    (stepBKK P win usb sreq fl k X).x.buf l =
      (if fl l = true then false
       else if (X.kc && decide (l = X.base.e.pl)) = true then false
       else (stepB P win usb sreq X.base).buf l) := rfl

theorem stK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.st = (stepB P win usb sreq X.base).e.st := rfl
theorem curK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.cur = (stepB P win usb sreq X.base).e.cur := rfl
theorem pstK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.pst = (stepB P win usb sreq X.base).e.pst := rfl
theorem plK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.pl = (stepB P win usb sreq X.base).e.pl := rfl
theorem pslotK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.pslot = (stepB P win usb sreq X.base).e.pslot := rfl
theorem pbK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.pb = (stepB P win usb sreq X.base).pb := rfl
theorem pkillK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).pkill =
      (if X.x.e.pst = .cap then false
       else X.pkill || (fl X.x.e.pl && (decide (X.x.e.pst = .req) || decide (X.x.e.pst = .wait))))
    := rfl

/-! ### Facts about `stepB` the proof needs -/

/-- The lane dispatched next reads a head that is already valid now (BufEng's
`dispHeadValid_stepB`, with its source kept). -/
theorem disp_src (x : EngB) (hW : WfB x) (hne : (stepB P win usb sreq x).e.st ≠ .idle) :
    x.e.actv (stepB P win usb sreq x).e.cur
      ((stepB P win usb sreq x).e.sel (stepB P win usb sreq x).e.cur) = true := by
  change (dispNext win x.e).st ≠ .idle at hne
  show x.e.actv (dispNext win x.e).cur (selNext P x.e (dispNext win x.e).cur) = true
  cases hs : x.e.st with
  | wb =>
    have : (dispNext win x.e).st = .idle := by simp [dispNext, hs]
    exact absurd this hne
  | drive =>
    have hd : (dispNext win x.e).cur = x.e.cur := by simp [dispNext, hs]
    rw [hd, selNext_of_not_wb P x.e x.e.cur (by rw [hs]; decide)]
    exact hW.disp (by rw [hs]; decide)
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
        show x.e.actv w (selNext P x.e w) = true
        rw [selNext_of_not_wb P x.e w hw]
        exact hv
      · rw [if_neg hv]
        intro h
        exact (h (by simp)).elim

theorem capSlot_sel (e : Engine) (l : Lane) (h : capSlot e l = some (e.sel l)) :
    e.headValid l = false := by
  unfold capSlot at h
  cases hh : e.headValid l
  · rfl
  · rw [if_neg (by rw [hh]; decide)] at h
    cases hs : e.spareValid l
    · exfalso
      rw [if_pos (by simp [hs])] at h
      revert h
      cases e.sel l <;> decide
    · rw [if_neg (by rw [hs]; decide)] at h
      cases h

/-- A second fetch captured into what becomes the lane's head leaves the spare empty after the
cycle (the killed word was the only fill). -/
theorem kill_head_spare (x : EngB) (hW : WfB x) (hpb : x.pb = true) (l : Lane)
    (hc : capTo x l (selNext P x.e l) = true) : actvB P x l (!selNext P x.e l) = false := by
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
    rw [hs] at hc ⊢
    have hcs := capTo_second x l _ hc hpb
    have hh : x.e.headValid l = false := capSlot_sel x.e l hcs
    rw [actvB_noret P x l _ hw]
    have h1 : capTo x l (!x.e.sel l) = false := by
      cases h : capTo x l (!x.e.sel l)
      · rfl
      · have := capTo_second x l _ h hpb
        rw [hcs] at this
        cases hq : x.e.sel l <;> rw [hq] at this <;> simp at this
    have h2 : loadTo x l (!x.e.sel l) = false := by
      cases h : loadTo x l (!x.e.sel l)
      · rfl
      · have := hW.bh l (loadTo_spec x l _ h).1
        rw [hh] at this
        cases this
    have h3 : x.e.actv l (!x.e.sel l) = false := hW.hf l hh
    rw [h1, h2, h3]
    rfl

theorem stepB_req_wait (x : EngB) (h : x.e.pst = .req) :
    (stepB P win usb sreq x).e.pst = .wait := by
  rw [stepB_pst, (portNextB_of_ne P usb sreq x (by rw [h]; decide)).1]
  simp [portNext, h]

theorem stepB_wait_cap (x : EngB) (h : x.e.pst = .wait) :
    (stepB P win usb sreq x).e.pst = .cap := by
  rw [stepB_pst, (portNextB_of_ne P usb sreq x (by rw [h]; decide)).1]
  simp [portNext, h]

/-! ### The invariant, one field at a time -/

section
variable (hok : SReqB P sreq) (X : EngBK) (hI : WfBK X) (hF : FlushOk P win usb sreq fl X)
include hok hI hF

theorem dispK : DispHeadValid (stepBKK P win usb sreq fl k X).x.e := by
  intro hne
  have hne' : (stepB P win usb sreq X.base).e.st ≠ .idle := hne
  have hY := wfB_step P win usb sreq hok X.base hI.wf
  have hfl : fl (stepB P win usb sreq X.base).e.cur = false := by
    cases h : fl (stepB P win usb sreq X.base).e.cur
    · rfl
    · exact absurd rfl (hF.1 _ h hne')
  have hsrc := disp_src P win usb sreq X.base hI.wf hne'
  have hK : capTo X.base (stepB P win usb sreq X.base).e.cur
      ((stepB P win usb sreq X.base).e.sel (stepB P win usb sreq X.base).e.cur) = false := by
    cases h : capTo X.base _ _
    · rfl
    · have := fill_empty X.base hI.wf _ _ (by rw [h]; rfl)
      rw [hsrc] at this
      cases this
  show (stepBKK P win usb sreq fl k X).x.e.actv (stepBKK P win usb sreq fl k X).x.e.cur
    ((stepBKK P win usb sreq fl k X).x.e.sel (stepBKK P win usb sreq fl k X).x.e.cur) = true
  rw [curK, selK, actvK, hfl]
  simp only [Bool.false_eq_true, ↓reduceIte, hK, Bool.and_false]
  exact hY.disp hne'

theorem hfK : HeadFirst (stepBKK P win usb sreq fl k X).x.e := by
  intro l hl
  have hY := wfB_step P win usb sreq hok X.base hI.wf
  unfold Engine.headValid at hl
  unfold Engine.spareValid
  rw [selK] at hl ⊢
  rw [actvK] at hl ⊢
  cases hf : fl l
  · simp only [hf, Bool.false_eq_true, ↓reduceIte] at hl ⊢
    by_cases hK2 : (X.kc && decide (l = X.base.e.pl) &&
        capTo X.base l (!(stepB P win usb sreq X.base).e.sel l)) = true
    · rw [if_pos hK2]
    · rw [if_neg hK2]
      by_cases hK1 : (X.kc && decide (l = X.base.e.pl) &&
          capTo X.base l ((stepB P win usb sreq X.base).e.sel l)) = true
      · simp only [Bool.and_eq_true, decide_eq_true_eq] at hK1
        obtain ⟨⟨hkc, -⟩, hc⟩ := hK1
        have hpb := base_pb_kill X (kc_spec X hkc).2
        exact kill_head_spare P X.base hI.wf hpb l hc
      · rw [if_neg hK1] at hl
        exact hY.hf l hl
  · simp only [hf, ↓reduceIte]
    cases keepSlot X.base l (k l) <;> simp

theorem bhK (l : Lane) (hb : (stepBKK P win usb sreq fl k X).x.buf l = true) :
    (stepBKK P win usb sreq fl k X).x.e.headValid l = true := by
  have hY := wfB_step P win usb sreq hok X.base hI.wf
  rw [bufK] at hb
  cases hf : fl l
  · simp only [hf, Bool.false_eq_true, ↓reduceIte] at hb
    by_cases hkl : (X.kc && decide (l = X.base.e.pl)) = true
    · rw [if_pos hkl] at hb
      cases hb
    · rw [if_neg hkl] at hb
      unfold Engine.headValid
      rw [selK, actvK, hf]
      simp only [Bool.false_eq_true, ↓reduceIte]
      have hK : (X.kc && decide (l = X.base.e.pl) &&
          capTo X.base l ((stepB P win usb sreq X.base).e.sel l)) = false := by
        simp only [Bool.not_eq_true] at hkl
        rw [hkl]
        rfl
      rw [hK]
      simp only [Bool.false_eq_true, ↓reduceIte]
      exact hY.bh l hb
  · simp only [hf, ↓reduceIte] at hb
    cases hb

theorem fnbK (hne : (stepBKK P win usb sreq fl k X).x.e.pst ≠ .scan) :
    (stepBKK P win usb sreq fl k X).x.buf (stepBKK P win usb sreq fl k X).x.e.pl = false := by
  have hY := wfB_step P win usb sreq hok X.base hI.wf
  rw [plK, bufK]
  split
  · rfl
  · split
    · rfl
    · exact hY.fnb hne

/-- Outside a scan, the lane in flight was not flushed this cycle unless a kill was set for it,
and no killed capture happened. -/
theorem flight_clean (hk0 : (stepBKK P win usb sreq fl k X).pkill = false)
    (hne : (stepB P win usb sreq X.base).e.pst ≠ .scan) :
    fl (stepB P win usb sreq X.base).e.pl = false ∧ X.kc = false := by
  have hbe := base_e X
  have hkc : X.kc = false := by
    cases h : X.kc
    · rfl
    · exfalso
      have hc := (kc_spec X h).1
      exact hne (cap_to_scan P usb sreq X.base (by rw [hbe]; exact hc))
  refine ⟨?_, hkc⟩
  cases h : fl (stepB P win usb sreq X.base).e.pl
  · rfl
  · exfalso
    cases hp : X.x.e.pst with
    | scan => exact hF.2 _ h hp hne rfl
    | cap => exact hne (cap_to_scan P usb sreq X.base (by rw [hbe]; exact hp))
    | req =>
      have hpl := (portNextB_keeps P usb sreq X.base (by rw [hbe, hp]; decide)).1
      rw [← stepB_pl, hbe] at hpl
      rw [hpl] at h
      rw [pkillK, hp] at hk0
      simp [h] at hk0
    | wait =>
      have hpl := (portNextB_keeps P usb sreq X.base (by rw [hbe, hp]; decide)).1
      rw [← stepB_pl, hbe] at hpl
      rw [hpl] at h
      rw [pkillK, hp] at hk0
      simp [h] at hk0

theorem feK (hk0 : (stepBKK P win usb sreq fl k X).pkill = false)
    (hne : (stepBKK P win usb sreq fl k X).x.e.pst ≠ .scan)
    (hpb : (stepBKK P win usb sreq fl k X).x.pb = false) :
    (stepBKK P win usb sreq fl k X).x.e.actv (stepBKK P win usb sreq fl k X).x.e.pl
      (stepBKK P win usb sreq fl k X).x.e.pslot = false := by
  have hY := wfB_step P win usb sreq hok X.base hI.wf
  obtain ⟨hfl, hkc⟩ := flight_clean P win usb sreq fl k hok X hI hF hk0 hne
  rw [plK, pslotK, actvK, hfl, hkc]
  simp only [Bool.false_eq_true, ↓reduceIte, Bool.false_and]
  exact hY.fe hne hpb

theorem sfK (hk0 : (stepBKK P win usb sreq fl k X).pkill = false)
    (hne : (stepBKK P win usb sreq fl k X).x.e.pst ≠ .scan)
    (hpb : (stepBKK P win usb sreq fl k X).x.pb = false)
    (hsp : (stepBKK P win usb sreq fl k X).x.e.pslot ≠
      (stepBKK P win usb sreq fl k X).x.e.sel (stepBKK P win usb sreq fl k X).x.e.pl) :
    (stepBKK P win usb sreq fl k X).x.e.headValid (stepBKK P win usb sreq fl k X).x.e.pl
      = true := by
  have hY := wfB_step P win usb sreq hok X.base hI.wf
  obtain ⟨hfl, hkc⟩ := flight_clean P win usb sreq fl k hok X hI hF hk0 hne
  rw [plK, selK, hfl] at hsp
  simp only [Bool.false_eq_true, ↓reduceIte] at hsp
  unfold Engine.headValid
  rw [plK, selK, actvK, hfl, hkc]
  simp only [Bool.false_eq_true, ↓reduceIte, Bool.false_and]
  exact hY.sf hne hpb hsp

theorem kiK : (stepBKK P win usb sreq fl k X).pkill = true →
    (stepBKK P win usb sreq fl k X).x.e.pst = .wait ∨
      (stepBKK P win usb sreq fl k X).x.e.pst = .cap := by
  intro hk
  have hbe := base_e X
  rw [pkillK] at hk
  rw [pstK]
  split at hk
  · cases hk
  · rename_i hnc
    rcases (Bool.or_eq_true _ _).mp hk with hp | hr
    · rcases hI.ki hp with hw | hc
      · exact Or.inr (stepB_wait_cap P win usb sreq X.base (by rw [hbe]; exact hw))
      · exact absurd hc hnc
    · simp only [Bool.and_eq_true, Bool.or_eq_true, decide_eq_true_eq] at hr
      rcases hr.2 with hq | hw
      · exact Or.inl (stepB_req_wait P win usb sreq X.base (by rw [hbe]; exact hq))
      · exact Or.inr (stepB_wait_cap P win usb sreq X.base (by rw [hbe]; exact hw))

/-- **The invariant survives a cycle** with keep-flushes and the kill. -/
theorem wfBK_step : WfBK (stepBKK P win usb sreq fl k X) := by
  refine ⟨?_, kiK P win usb sreq fl k hok X hI hF⟩
  unfold EngBK.base
  split
  · exact { disp := dispK P win usb sreq fl k hok X hI hF
            hf := hfK P win usb sreq fl k hok X hI hF
            fe := fun _ h => by cases h
            fnb := fnbK P win usb sreq fl k hok X hI hF
            bh := bhK P win usb sreq fl k hok X hI hF
            sf := fun _ h => by cases h }
  · rename_i hk
    have hk0 : (stepBKK P win usb sreq fl k X).pkill = false := by simpa using hk
    exact { disp := dispK P win usb sreq fl k hok X hI hF
            hf := hfK P win usb sreq fl k hok X hI hF
            fe := feK P win usb sreq fl k hok X hI hF hk0
            fnb := fnbK P win usb sreq fl k hok X hI hF
            bh := bhK P win usb sreq fl k hok X hI hF
            sf := sfK P win usb sreq fl k hok X hI hF hk0 }

end

/-! ### K1, K2, K5 on this engine -/

theorem edge_survives_flushK (X : EngBK) (l : Lane) (hf : fl l = true)
    (hk : X.base.hasEdge l (k l) = true) :
    (stepBKK P win usb sreq fl k X).x.e.headValid l = true ∧
    (stepBKK P win usb sreq fl k X).x.sq l ((stepBKK P win usb sreq fl k X).x.e.sel l)
      = (stepBKK P win usb sreq fl k X).x.nr l ∧
    (stepBKK P win usb sreq fl k X).x.e.ts l + 1 = (stepBKK P win usb sreq fl k X).x.e.now := by
  have hn : (stepBKK P win usb sreq fl k X).x.e.now = X.base.e.now + 1 :=
    stepB_e_now P win usb sreq X.base
  refine ⟨?_, ?_, ?_⟩
  · unfold Engine.headValid
    rw [selK, actvK]
    simp [hf, hk]
  · show (if fl l = true ∧ _ = keepSlot X.base l (k l)
        then (stepB P win usb sreq X.base).nr l else _) = (stepB P win usb sreq X.base).nr l
    rw [selK]
    simp [hf]
  · rw [hn]
    show (if fl l = true then X.base.e.now else _) + 1 = _
    simp [hf]

theorem flushK_keeps_only_edge (X : EngBK) (l : Lane) (hf : fl l = true) (s : Slot)
    (h : (stepBKK P win usb sreq fl k X).x.e.actv l s = true) :
    s = (stepBKK P win usb sreq fl k X).x.e.sel l ∧
      (stepBKK P win usb sreq fl k X).x.sq l s = (stepBKK P win usb sreq fl k X).x.nr l := by
  rw [actvK] at h
  simp only [hf, ↓reduceIte, Bool.and_eq_true, decide_eq_true_eq] at h
  refine ⟨?_, ?_⟩
  · rw [selK]
    simp [hf, h.2]
  · show (if fl l = true ∧ s = keepSlot X.base l (k l)
        then (stepB P win usb sreq X.base).nr l else _) = (stepB P win usb sreq X.base).nr l
    simp [hf, h.2]

theorem flushK_buf_empty (X : EngBK) (l : Lane) (hf : fl l = true) :
    (stepBKK P win usb sreq fl k X).x.buf l = false := by
  rw [bufK]
  simp [hf]

/-- **K5: a killed capture files nothing.** The slot it would have written is empty after the
cycle (it was empty, `fill_empty`, and nothing else fills it), and the buffer is not written. -/
theorem kill_files_nothing (X : EngBK) (hkc : X.kc = true)
    (hf : fl X.x.e.pl = false) (s : Slot) (hc : capTo X.base X.x.e.pl s = true) :
    (stepBKK P win usb sreq fl k X).x.e.actv X.x.e.pl s = false ∧
      (stepBKK P win usb sreq fl k X).x.buf X.x.e.pl = false := by
  have hbe := base_e X
  constructor
  · rw [actvK, hf]
    simp only [Bool.false_eq_true, ↓reduceIte]
    rw [if_pos]
    rw [hkc, hbe, hc]
    simp
  · rw [bufK, hf]
    simp only [Bool.false_eq_true, ↓reduceIte]
    rw [if_pos]
    rw [hkc, hbe]
    simp

/-- **No flush, no kill: the buffered step.** -/
theorem stepBKK_noflush (X : EngBK) (hfl : ∀ l, fl l = false) (hk : X.pkill = false) :
    (stepBKK P win usb sreq fl k X).x = stepB P win usb sreq X.x ∧
      (stepBKK P win usb sreq fl k X).pkill = false := by
  have hb := base_nokill X hk
  have hkc : X.kc = false := by
    unfold EngBK.kc
    rw [hk]
    simp
  constructor
  · show ({ (stepB P win usb sreq X.base) with
        e := { (stepB P win usb sreq X.base).e with
          actv := fun l s => if fl l = true then X.base.hasEdge l (k l) &&
              decide (s = keepSlot X.base l (k l))
            else if (X.kc && decide (l = X.base.e.pl) && capTo X.base l s) = true then false
            else (stepB P win usb sreq X.base).e.actv l s
          sel := fun l => if fl l = true then keepSlot X.base l (k l)
            else (stepB P win usb sreq X.base).e.sel l
          ts := fun l => if fl l = true then X.base.e.now
            else (stepB P win usb sreq X.base).e.ts l }
        buf := fun l => if fl l = true then false
          else if (X.kc && decide (l = X.base.e.pl)) = true then false
          else (stepB P win usb sreq X.base).buf l
        sq := fun l s => if fl l = true ∧ s = keepSlot X.base l (k l)
          then (stepB P win usb sreq X.base).nr l
          else (stepB P win usb sreq X.base).sq l s } : EngB) = stepB P win usb sreq X.x
    simp only [hfl, hkc, Bool.false_eq_true, ↓reduceIte, Bool.false_and, false_and]
    rw [hb]
  · rw [pkillK, hk]
    split
    · rfl
    · simp [hfl]

/-! ### Runs -/

/-- `n` cycles with the edges `fl` and the edge words' indices `k` read by time. -/
def runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) : Nat → EngBK → EngBK
  | 0, X => X
  | n + 1, X => runBK fl k n (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)

/-- **The invariant along a run**, given the flush conditions at every cycle of it. -/
theorem wfBK_run (hok : SReqB P sreq) (flt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) :
    ∀ (n : Nat) (X : EngBK), WfBK X →
      (∀ j, j < n → FlushOk P win usb sreq (flt (runBK P win usb sreq flt kt j X).x.e.now)
        (runBK P win usb sreq flt kt j X)) →
      WfBK (runBK P win usb sreq flt kt n X)
  | 0, _, h, _ => h
  | n + 1, X, h, hF => by
    have h1 := wfBK_step P win usb sreq (flt X.x.e.now) (kt X.x.e.now) hok X h
      (hF 0 (Nat.succ_pos n))
    exact wfBK_run hok flt kt n _ h1 (fun j hj => hF (j + 1) (Nat.succ_lt_succ hj))

/-- A run starts from BufEng's invariant with no kill pending. -/
theorem wfBK_init (x : EngB) (hW : WfB x) : WfBK { x := x, pkill := false } :=
  ⟨by rw [base_nokill _ rfl]; exact hW, fun h => by cases h⟩

end

#print axioms wfBK_step
#print axioms wfBK_run
#print axioms stepBKK_noflush
#print axioms edge_survives_flushK
#print axioms flushK_keeps_only_edge
#print axioms kill_files_nothing

end JLane
