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

/-! ### F2c — the head refill after a flush -/

theorem runF_succ' (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) :
    ∀ (n : Nat) (X : EngineF),
      runF P win fl (n + 1) X = stepF P win (fl (runF P win fl n X).e.now) (runF P win fl n X)
  | 0, _ => rfl
  | n + 1, X => runF_succ' P win fl n (stepF P win (fl X.e.now) X)

theorem now_runF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) :
    ∀ (n : Nat) (X : EngineF), (runF P win fl n X).e.now = X.e.now + n
  | 0, _ => rfl
  | n + 1, X => by
    rw [runF_succ']
    show (runF P win fl n X).e.now + 1 = X.e.now + (n + 1)
    rw [now_runF P win fl n X]
    omega

theorem runF_add (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) :
    ∀ (a b : Nat) (X : EngineF), runF P win fl (a + b) X = runF P win fl b (runF P win fl a X)
  | a, 0, _ => rfl
  | a, b + 1, X => by
    rw [← Nat.add_assoc, runF_succ', runF_succ', runF_add P win fl a b X]

/-- The port FSM, backwards: CAP comes from WAIT, WAIT from REQ, and the lane is kept. -/
theorem portNext_from_cap (Q : Program) (e : Engine) (h : (portNext Q e).pst = .cap) :
    e.pst = .wait ∧ (portNext Q e).pl = e.pl := by
  revert h
  show (portNextW Q e.wantFetch e).pst = .cap → e.pst = .wait ∧ (portNextW Q e.wantFetch e).pl = e.pl
  cases hp : e.pst with
  | scan =>
    simp only [portNextW, hp]
    cases br1 Q e <;> simp
    split <;> simp
  | req => simp [portNextW, hp]
  | wait => simp [portNextW, hp]
  | cap => simp [portNextW, hp]

theorem portNext_from_wait (Q : Program) (e : Engine) (h : (portNext Q e).pst = .wait) :
    e.pst = .req ∧ (portNext Q e).pl = e.pl := by
  revert h
  show (portNextW Q e.wantFetch e).pst = .wait → e.pst = .req ∧ (portNextW Q e.wantFetch e).pl = e.pl
  cases hp : e.pst with
  | scan =>
    simp only [portNextW, hp]
    cases br1 Q e <;> simp
    split <;> simp
  | req => simp [portNextW, hp]
  | wait => simp [portNextW, hp]
  | cap => simp [portNextW, hp]

theorem portNext_wait_cap (Q : Program) (e : Engine) (h : e.pst = .wait) :
    (portNext Q e).pst = .cap := by
  show (portNextW Q e.wantFetch e).pst = .cap
  simp [portNextW, h]

/-- With no flush this cycle, the kill only clears (at CAP) or carries. -/
theorem stepF_pkill_noflush (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hfl : ∀ l, fl l = false) :
    (stepF P win fl X).pkill = if X.e.pst = .cap then false else X.pkill := by
  show (if X.e.pst = .cap then false
    else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait)))) = _
  rw [hfl X.e.pl]
  simp

/-- **The head refill after a flush.** Lane `y` flushed at cycle `f` (and the invariant holding
there, no flushed lane dispatched next, no flush in the following `3 + 23 + B` cycles): three
cycles later nothing has been filed into `y`, no kill is pending, the invariant is `Wf`, and on
the plain run that follows `y`'s head is captured within `23 + B` cycles. -/
theorem flush_head_refill (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X : EngineF) (y : Lane) (B f : Nat) (hy : P.live y = true)
    (hI : InvF (runF P win fl f X))
    (hmid : ∀ l, fl (runF P win fl f X).e.now l = true →
      ¬((dispNext win (runF P win fl f X).e).st ≠ .idle ∧
        (dispNext win (runF P win fl f X).e).cur = l))
    (hfy : fl (runF P win fl f X).e.now y = true)
    (hnof : ∀ i, 1 ≤ i → i ≤ 3 + (23 + B) → ∀ l, fl ((runF P win fl f X).e.now + i) l = false)
    (hB : ∀ m, m ≤ 23 + B → chargeSum P win y m (runF P win fl (f + 3) X).e ≤ B) :
    Wf (runF P win fl (f + 3) X).e ∧
      (∀ n, n ≤ 23 + B →
        (runF P win fl (f + 3 + n) X).e = run P win n (runF P win fl (f + 3) X).e) ∧
      1 ≤ cnt P win (Hit y) (23 + B) (runF P win fl (f + 3) X).e := by
  -- the three states after the flush
  generalize hXf : runF P win fl f X = Xf at hI hmid hfy hnof
  have hn0 := now_runF P win fl f X
  rw [hXf] at hn0
  have h1 : runF P win fl (f + 1) X = stepF P win (fl Xf.e.now) Xf := by
    rw [runF_succ', hXf]
  have hnow1 : (runF P win fl (f + 1) X).e.now = Xf.e.now + 1 := by
    rw [h1]; rfl
  have h2 : runF P win fl (f + 2) X =
      stepF P win (fl (Xf.e.now + 1)) (runF P win fl (f + 1) X) := by
    rw [show f + 2 = (f + 1) + 1 by omega, runF_succ', hnow1]
  have hnow2 : (runF P win fl (f + 2) X).e.now = Xf.e.now + 2 := by
    rw [h2]; show (runF P win fl (f + 1) X).e.now + 1 = _; rw [hnow1]
  have h3 : runF P win fl (f + 3) X =
      stepF P win (fl (Xf.e.now + 2)) (runF P win fl (f + 2) X) := by
    rw [show f + 3 = (f + 2) + 1 by omega, runF_succ', hnow2]
  generalize hY1 : runF P win fl (f + 1) X = Y1 at h1 h2 hnow1
  generalize hY2 : runF P win fl (f + 2) X = Y2 at h2 h3 hnow2
  have hfl1 : ∀ l, fl (Xf.e.now + 1) l = false := hnof 1 (by omega) (by omega)
  have hfl2 : ∀ l, fl (Xf.e.now + 2) l = false := hnof 2 (by omega) (by omega)
  -- the invariant along the three cycles
  have hI1 : InvF Y1 := by rw [h1]; exact invF_step P win _ Xf hI hmid
  have hI2 : InvF Y2 := by
    rw [h2]; exact invF_step P win _ Y1 hI1 (fun l hl => by rw [hfl1 l] at hl; cases hl)
  have hI3 : InvF (runF P win fl (f + 3) X) := by
    rw [h3]; exact invF_step P win _ Y2 hI2 (fun l hl => by rw [hfl2 l] at hl; cases hl)
  -- no kill pending three cycles on
  have hk2 : Y2.pkill = true → Y2.e.pst = .cap := by
    intro hk
    rw [h2, stepF_pkill_noflush P win _ Y1 hfl1] at hk
    by_cases hc : Y1.e.pst = .cap
    · rw [if_pos hc] at hk; cases hk
    · rw [if_neg hc] at hk
      rcases hI1.2.2.2.1 hk with hw | hw
      · rw [h2]; exact portNext_wait_cap _ _ hw
      · exact absurd hw hc
  have hk3 : (runF P win fl (f + 3) X).pkill = false := by
    rw [h3, stepF_pkill_noflush P win _ Y2 hfl2]
    by_cases hc : Y2.e.pst = .cap
    · rw [if_pos hc]
    · rw [if_neg hc]
      cases hq : Y2.pkill
      · rfl
      · exact absurd (hk2 hq) hc
  -- nothing filed into y
  have he1 : ∀ s, Y1.e.actv y s = false := fun s => by
    rw [h1]; exact stepF_flush_empty P win _ Xf y hfy s
  have he2 : ∀ s, Y2.e.actv y s = false := fun s => by
    cases hv : Y2.e.actv y s
    · rfl
    · exfalso
      rw [h2] at hv
      obtain ⟨hc, hpl, -, hk, -⟩ := stepF_fill P win _ Y1 y s (he1 s) hv
      have hc' : (portNext (liveFl P (fl Xf.e.now)) Xf.e).pst = .cap := by
        rw [h1] at hc; exact hc
      obtain ⟨hw, hplk⟩ := portNext_from_cap _ _ hc'
      have hpl' : Xf.e.pl = y := by
        have : Y1.e.pl = (portNext (liveFl P (fl Xf.e.now)) Xf.e).pl := by rw [h1]; rfl
        rw [this, hplk] at hpl
        exact hpl.symm
      have hks := stepF_kill_set P win (fl Xf.e.now) Xf (Or.inr hw) (by rw [hpl']; exact hfy)
      rw [← h1, hk] at hks
      cases hks
  have he3 : ∀ s, (runF P win fl (f + 3) X).e.actv y s = false := fun s => by
    cases hv : (runF P win fl (f + 3) X).e.actv y s
    · rfl
    · exfalso
      rw [h3] at hv
      obtain ⟨hc, hpl, -, hk, -⟩ := stepF_fill P win _ Y2 y s (he2 s) hv
      -- Y2 at CAP for y: Y1 at WAIT for y, Xf at REQ for y: the flush killed it
      have hc2 : (portNext (liveFl P (fl (Xf.e.now + 1))) Y1.e).pst = .cap := by
        rw [h2] at hc; exact hc
      obtain ⟨hw1, hpl1⟩ := portNext_from_cap _ _ hc2
      have hw1' : (portNext (liveFl P (fl Xf.e.now)) Xf.e).pst = .wait := by
        rw [h1] at hw1; exact hw1
      obtain ⟨hr0, hpl0⟩ := portNext_from_wait _ _ hw1'
      have hY1pl : Y1.e.pl = Xf.e.pl := by
        have : Y1.e.pl = (portNext (liveFl P (fl Xf.e.now)) Xf.e).pl := by rw [h1]; rfl
        rw [this, hpl0]
      have hY2pl : Y2.e.pl = Y1.e.pl := by
        have : Y2.e.pl = (portNext (liveFl P (fl (Xf.e.now + 1))) Y1.e).pl := by rw [h2]; rfl
        rw [this, hpl1]
      have hpx : Xf.e.pl = y := by rw [← hY1pl, ← hY2pl]; exact hpl.symm
      have hks1 := stepF_kill_set P win (fl Xf.e.now) Xf (Or.inl hr0) (by rw [hpx]; exact hfy)
      rw [← h1] at hks1
      have hks2 := stepF_kill_keep P win (fl (Xf.e.now + 1)) Y1 hks1 (by rw [hw1]; decide)
      rw [← h2, hk] at hks2
      cases hks2
  -- the plain run from f + 3
  have hW3 := invF_wf _ hI3 hk3
  have hv3 : (runF P win fl (f + 3) X).e.headValid y = false := he3 _
  refine ⟨hW3, fun n hn => ?_, restart_hit P win y _ B hW3 hy hv3 hB⟩
  have hnow3 : (runF P win fl (f + 3) X).e.now = Xf.e.now + 3 := by
    rw [h3]; show Y2.e.now + 1 = _; rw [hnow2]
  have hseg := runF_seg P win fl n (runF P win fl (f + 3) X) hk3 (fun i hi l => by
    rw [hnow3, Nat.add_assoc]
    exact hnof (3 + i) (by omega) (by omega) l)
  rw [runF_add]
  exact hseg.1

#print axioms killEmpty_step
#print axioms spareFillF_step
#print axioms headFirst_stepF
#print axioms invF_step
#print axioms restart_hit
#print axioms flush_head_refill

end JLane
