import JLane.FlushStep
/-!
# Brick F2 — after a flush: the invariant, and the head refill (FALLTHROUGH, stage F2)

`Head.Wf` (structure, head-first, spare-fill) is what the V4b library starts from. A flush
mid-refill breaks spare-fill for a moment: the refill in flight may still name the spare
while the flushed head is empty — but that refill is killed. `InvF` is `Wf` with spare-fill
weakened to "head valid, **or the refill is killed**", plus the kill facts:

* `invF_step` — preserved by every `stepF` cycle, given no flushed lane is being dispatched
  (an armed lane never is);
* `invF_wf` — with no kill pending it **is** `Wf`: the plain library resumes there;
* `restart_hit` — on a plain run, a live lane whose head is empty gets a capture within
  `23 + B` cycles (one port wait, `window_le`).
-/
namespace JLane

/-- Spare-fill, weakened by a pending kill. -/
def SpareFillF (X : EngineF) : Prop :=
  X.e.pst ≠ .scan → X.e.pslot ≠ X.e.sel X.e.pl → X.e.headValid X.e.pl = true ∨ X.pkill = true

/-- A killed refill's lane has both slots empty. -/
def KillEmpty (X : EngineF) : Prop := X.pkill = true → ∀ s, X.e.actv X.e.pl s = false

/-- The flush-aware invariant. -/
def InvF (X : EngineF) : Prop :=
  Struct X.e ∧ HeadFirst X.e ∧ SpareFillF X ∧ KillInv X ∧ KillEmpty X

theorem invF_wf (X : EngineF) (h : InvF X) (hk : X.pkill = false) : Wf X.e := by
  obtain ⟨hS, hH, hF, -, -⟩ := h
  refine ⟨hS, hH, fun hne hsl => ?_⟩
  rcases hF hne hsl with h' | h'
  · exact h'
  · rw [hk] at h'
    cases h'

/-- Away from a flush and a kill, `stepF`'s slots are the step's. -/
theorem actvF_eq (P : Program) (fl : Lane → Bool) (X : EngineF) (l : Lane) (s : Slot)
    (hf : fl l = false) (hk : ¬(X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true)) :
    actvF P fl X l s = actvNext P X.e l s := by
  unfold actvF
  rw [hf, if_neg (by decide), if_neg hk]

/-- The port keeps its lane through REQ and WAIT. -/
theorem portNext_pl_keep (P : Program) (e : Engine) (h : e.pst = .req ∨ e.pst = .wait) :
    (portNext P e).pl = e.pl ∧ (portNext P e).pslot = e.pslot := by
  rcases h with h | h <;>
    · show (portNextW P e.wantFetch e).pl = e.pl ∧ (portNextW P e.wantFetch e).pslot = e.pslot
      simp [portNextW, h]

theorem killEmpty_step (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hKI : KillInv X) (hKE : KillEmpty X) : KillEmpty (stepF P win fl X) := by
  intro hk s
  change (if X.e.pst = .cap then false
    else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait)))) = true
    at hk
  by_cases hc : X.e.pst = .cap
  · rw [if_pos hc] at hk
    cases hk
  · rw [if_neg hc] at hk
    have hrw : X.e.pst = .req ∨ X.e.pst = .wait := by
      cases hp : X.e.pst with
      | scan =>
        rw [hp] at hk
        simp only [reduceCtorEq, decide_false, Bool.or_false, Bool.and_false] at hk
        have := hKI hk
        rw [hp] at this
        rcases this with h' | h' <;> cases h'
      | req => exact Or.inl rfl
      | wait => exact Or.inr rfl
      | cap => exact absurd hp hc
    obtain ⟨hpl, -⟩ := portNext_pl_keep (liveFl P fl) X.e hrw
    show actvF P fl X (portNext (liveFl P fl) X.e).pl s = false
    rw [hpl]
    unfold actvF
    by_cases hf : fl X.e.pl = true
    · rw [if_pos hf]
    · rw [if_neg hf, if_neg (fun h' => hc h'.1)]
      -- not a capture cycle: only a retirement could change the slot, and it only clears;
      -- the slot was empty unless the kill is set now
      by_cases hk0 : X.pkill = true
      · have h0 := hKE hk0 s
        unfold actvNext
        by_cases hr : X.e.st = .wb ∧ X.e.pl = X.e.cur ∧ s = X.e.sel X.e.cur ∧
            P.ret X.e.now X.e.cur = true
        · rw [if_pos hr]
        · rw [if_neg hr, if_neg (fun h'' => hc h''.1)]
          exact h0
      · -- the kill is set now: the lane is flushed this cycle, contradiction with hf
        exfalso
        have hk0' : X.pkill = false := by cases hq : X.pkill <;> simp_all
        rw [hk0'] at hk
        simp only [Bool.false_or, Bool.and_eq_true] at hk
        exact hf hk.1

/-- A branch-1 grant goes to a live lane. -/
theorem br1_live (Q : Program) (e : Engine) (w : Lane) (h : br1 Q e = some w) :
    Q.live w = true := by
  unfold br1 at h
  cases hq : e.winq with
  | none => rw [hq] at h; cases h
  | some v =>
    rw [hq] at h
    simp only at h
    split at h
    · rename_i hc
      cases h
      simp only [Bool.and_eq_true] at hc
      exact hc.1
    · cases h

/-- A lane the scan selects is live in the program the port reads. -/
theorem portNext_scan_live (Q : Program) (e : Engine) (hp : e.pst = .scan)
    (h : (portNext Q e).pst ≠ .scan) : Q.live (portNext Q e).pl = true := by
  revert h
  show (portNextW Q e.wantFetch e).pst ≠ .scan → Q.live (portNextW Q e.wantFetch e).pl = true
  cases hb : br1 Q e with
  | some w =>
    simp only [portNextW, hp, hb]
    intro _
    exact br1_live Q e w hb
  | none =>
    by_cases hc : (Q.live e.prr && e.wantFetch e.prr) = true
    · simp only [portNextW, hp, hb, hc, ↓reduceIte]
      intro _
      simp only [Bool.and_eq_true] at hc
      exact hc.1
    · have hc' : (Q.live e.prr && e.wantFetch e.prr) = false := by
        cases h' : (Q.live e.prr && e.wantFetch e.prr) <;> simp_all
      simp only [portNextW, hp, hb, hc', Bool.false_eq_true, ↓reduceIte]
      intro h0
      exact absurd rfl h0

theorem spareFillF_step (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hS : Struct X.e) (hF : SpareFillF X) (hKI : KillInv X) :
    SpareFillF (stepF P win fl X) := by
  intro hne hsl
  by_cases hk' : (stepF P win fl X).pkill = true
  · exact Or.inr hk'
  · left
    -- no kill after the step: none before at a non-CAP cycle, and the lane isn't flushed
    have hk0 : X.pkill = false ∨ X.e.pst = .cap := by
      cases hq : X.pkill
      · exact Or.inl rfl
      · by_cases hc : X.e.pst = .cap
        · exact Or.inr hc
        · exact absurd (stepF_kill_keep P win fl X hq hc) hk'
    -- the step's spare-fill applies (spare-fill holds now whenever the step's port is busy)
    have hSF : SpareFill X.e := by
      intro hne0 hsl0
      rcases hF hne0 hsl0 with h | h
      · exact h
      · rcases hk0 with h0 | h0
        · rw [h0] at h
          cases h
        · -- a CAP cycle: the port is free next, so the step's spare-fill is vacuous there;
          -- not needed (the goal below is about the stepped engine)
          exfalso
          have : (stepF P win fl X).e.pst = .scan := by
            show (portNext (liveFl P fl) X.e).pst = .scan
            show (portNextW (liveFl P fl) X.e.wantFetch X.e).pst = .scan
            simp [portNextW, h0]
          exact hne this
    have hst := spareFill_step (liveFl P fl) win X.e hS hSF
    have h := hst hne hsl
    -- the stepped lane's head: not flushed (the port never selects or keeps a flushed lane
    -- without a kill) and not killed
    show actvF P fl X (portNext (liveFl P fl) X.e).pl
      (selNext (liveFl P fl) X.e (portNext (liveFl P fl) X.e).pl) = true
    have h' : actvNext (liveFl P fl) X.e (portNext (liveFl P fl) X.e).pl
        (selNext (liveFl P fl) X.e (portNext (liveFl P fl) X.e).pl) = true := h
    unfold actvF
    by_cases hf : fl (portNext (liveFl P fl) X.e).pl = true
    · exfalso
      -- a flushed lane on the port after the step: selected now (masked: impossible) or kept
      -- from REQ / WAIT (then the kill is set): either way contradiction
      cases hp : X.e.pst with
      | scan =>
        have this := portNext_scan_live (liveFl P fl) X.e hp hne
        change (P.live _ && !fl _) = true at this
        rw [hf] at this
        simp at this
      | req =>
        have hpl := (portNext_pl_keep (liveFl P fl) X.e (Or.inl hp)).1
        rw [hpl] at hf
        exact hk' (stepF_kill_set P win fl X (Or.inl hp) hf)
      | wait =>
        have hpl := (portNext_pl_keep (liveFl P fl) X.e (Or.inr hp)).1
        rw [hpl] at hf
        exact hk' (stepF_kill_set P win fl X (Or.inr hp) hf)
      | cap =>
        have : (portNext (liveFl P fl) X.e).pst = .scan := by
          show (portNextW (liveFl P fl) X.e.wantFetch X.e).pst = .scan
          simp [portNextW, hp]
        exact hne this
    · rw [if_neg hf]
      by_cases hkc : X.e.pst = .cap ∧ (portNext (liveFl P fl) X.e).pl = X.e.pl ∧
          selNext (liveFl P fl) X.e (portNext (liveFl P fl) X.e).pl = X.e.pslot ∧ X.pkill = true
      · exfalso
        have : (portNext (liveFl P fl) X.e).pst = .scan := by
          show (portNextW (liveFl P fl) X.e.wantFetch X.e).pst = .scan
          simp [portNextW, hkc.1]
        exact hne this
      · rw [if_neg hkc]
        exact h'

/-- A killed lane's slots stay empty through the cycle. -/
theorem actvF_killed_empty (P : Program) (fl : Lane → Bool) (X : EngineF) (hKE : KillEmpty X)
    (hk : X.pkill = true) (s : Slot) : actvF P fl X X.e.pl s = false := by
  have h0 := hKE hk s
  unfold actvF
  by_cases hf : fl X.e.pl = true
  · rw [if_pos hf]
  · rw [if_neg hf]
    by_cases hc : X.e.pst = .cap ∧ X.e.pl = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true
    · rw [if_pos hc]
      exact h0
    · rw [if_neg hc]
      unfold actvNext
      by_cases hr : X.e.st = .wb ∧ X.e.pl = X.e.cur ∧ s = X.e.sel X.e.cur ∧
          P.ret X.e.now X.e.cur = true
      · rw [if_pos hr]
      · rw [if_neg hr, if_neg (fun h' => hc ⟨h'.1, rfl, h'.2.2, hk⟩)]
        exact h0

/-- **Head-first survives a flush step.** -/
theorem headFirst_stepF (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hH : HeadFirst X.e) (hF : SpareFillF X) (hKE : KillEmpty X) :
    HeadFirst (stepF P win fl X).e := by
  intro l hl
  change actvF P fl X l (selNext (liveFl P fl) X.e l) = false at hl
  show actvF P fl X l (!selNext (liveFl P fl) X.e l) = false
  by_cases hf : fl l = true
  · unfold actvF
    rw [if_pos hf]
  by_cases hkl : X.pkill = true ∧ l = X.e.pl
  · rw [hkl.2]
    exact actvF_killed_empty P fl X hKE hkl.1 _
  -- away from the flush and the kill: the step's slots
  have hf' : fl l = false := by cases hc : fl l <;> simp_all
  have heq : ∀ s, actvF P fl X l s = actvNext P X.e l s := fun s =>
    actvF_eq P fl X l s hf' (fun h' => hkl ⟨h'.2.2.2, h'.2.1⟩)
  rw [heq] at hl ⊢
  by_cases hk : X.pkill = true
  · -- a kill on another lane: run the step on the engine whose in-flight slot is renamed to
    -- that lane's head (spare-fill trivially), which changes nothing for lane l
    have hl_ne : l ≠ X.e.pl := fun h' => hkl ⟨hk, h'⟩
    let eb : Engine := { X.e with pslot := X.e.sel X.e.pl }
    have hFb : SpareFill eb := fun _ h' => absurd rfl h'
    have hHb : HeadFirst eb := hH
    have hst := headFirst_step (liveFl P fl) win eb hHb hFb l
    have hsame : ∀ s, (step (liveFl P fl) win eb).actv l s = actvNext P X.e l s := fun s => by
      show (if X.e.st = .wb ∧ l = X.e.cur ∧ s = X.e.sel X.e.cur ∧ P.ret X.e.now X.e.cur = true
          then false
          else if X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.sel X.e.pl then true else X.e.actv l s) =
        (if X.e.st = .wb ∧ l = X.e.cur ∧ s = X.e.sel X.e.cur ∧ P.ret X.e.now X.e.cur = true
          then false
          else if X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot then true else X.e.actv l s)
      by_cases hr : X.e.st = .wb ∧ l = X.e.cur ∧ s = X.e.sel X.e.cur ∧
          P.ret X.e.now X.e.cur = true
      · rw [if_pos hr, if_pos hr]
      · rw [if_neg hr, if_neg hr, if_neg (fun h' => hl_ne h'.2.1), if_neg (fun h' => hl_ne h'.2.1)]
    have hselb : (step (liveFl P fl) win eb).sel l = selNext (liveFl P fl) X.e l := rfl
    unfold Engine.headValid Engine.spareValid at hst
    rw [hselb, hsame, hsame] at hst
    exact hst hl
  · -- no kill: spare-fill holds, the step's head-first applies
    have hk0 : X.pkill = false := by cases hq : X.pkill <;> simp_all
    have hSF : SpareFill X.e := fun hne hsl => by
      rcases hF hne hsl with h' | h'
      · exact h'
      · rw [hk0] at h'
        cases h'
    have hst := headFirst_step (liveFl P fl) win X.e hH hSF l
    unfold Engine.headValid Engine.spareValid at hst
    exact hst hl

/-- **The flush-aware invariant is preserved**, given no flushed lane is being dispatched next. -/
theorem invF_step (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool) (X : EngineF)
    (hI : InvF X)
    (hmid : ∀ l, fl l = true →
      ¬((dispNext win X.e).st ≠ .idle ∧ (dispNext win X.e).cur = l)) :
    InvF (stepF P win fl X) := by
  obtain ⟨hS, hH, hF, hKI, hKE⟩ := hI
  exact ⟨struct_stepF P win fl X hS hmid, headFirst_stepF P win fl X hH hF hKE,
    spareFillF_step P win fl X hS hF hKI, killInv_step P win fl X hKI,
    killEmpty_step P win fl X hKI hKE⟩

/-- **The head refill after a restart.** On a plain run, a live lane whose head is empty gets a
capture within `23 + B` cycles (one port wait). -/
theorem restart_hit (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine) (B : Nat)
    (hW : Wf e) (hy : P.live y = true) (hv : e.headValid y = false)
    (hB : ∀ m, m ≤ 23 + B → chargeSum P win y m e ≤ B) :
    1 ≤ cnt P win (Hit y) (23 + B) e := by
  have hS : Struct e := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  rcases Nat.lt_or_ge (cnt P win (Hit y) (23 + B) e) 1 with h | h
  · exfalso
    have hz : cnt P win (Hit y) (23 + B) e = 0 := by omega
    have hwant : e.wantFetch y = true := by
      unfold Engine.wantFetch
      rw [hv]
      rfl
    have hn := window_le P win y hy e B (23 + B) hS hwant
      (fun m hm hm' => hB m hm')
      (fun i hi => no_event_between P win (Hit y) e 0 (23 + B) i (Nat.zero_le _) hi
        (by rw [hz]; rfl))
    omega
  · exact h

#print axioms killEmpty_step
#print axioms spareFillF_step
#print axioms headFirst_stepF
#print axioms invF_step
#print axioms restart_hit

end JLane
