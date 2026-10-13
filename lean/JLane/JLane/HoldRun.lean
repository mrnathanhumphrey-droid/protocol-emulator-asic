import JLane.Hold
/-!
# Brick V3b-1 — the hold run is a v1 run, while the gate is open at decisions
The hold scheduler `sched` picks gated-ready lanes (`ready = rel_due & hz_q`). From it we
build a v1 scheduler `win1H`: along the hold run it returns exactly `sched`'s answer
(also "nobody" at DRIVE/WB cycles); its first-ready fallback fires only at idle cycles, so
it meets the (V3a, idle-only) v1 contract everywhere.

`runH_coinc`: if `GateOpen` (every released lane has an idle hold counter at a decision
cycle) held at every cycle before `n`, the hold run's engine at `n` equals the v1 run
under `win1H` at `n`. Bite 2 proves `GateOpen` always holds for `d ≥ 39`.
-/
namespace JLane

theorem runH_succ' (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) :
    ∀ (n : Nat) (y : EngineH),
      runH P fw hl sched (n + 1) y =
        stepH P fw hl (sched (runH P fw hl sched n y)) (runH P fw hl sched n y)
  | 0, _ => rfl
  | n + 1, y => runH_succ' P fw hl sched n (stepH P fw hl (sched y) y)

theorem now_runH (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) :
    ∀ (n : Nat) (y : EngineH), (runH P fw hl sched n y).x.e.now = y.x.e.now + n
  | 0, _ => rfl
  | n + 1, y => by
    rw [runH_succ' P fw hl sched n y]
    show (runH P fw hl sched n y).x.e.now + 1 = y.x.e.now + (n + 1)
    rw [now_runH P fw hl sched n y]
    omega

theorem plain_runH (P : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane)
    (hf : ∀ y, PlainW dly y.e.pl (fw y)) :
    ∀ (n : Nat) (y : EngineH), Plain dly y.x → Plain dly (runH P fw hl sched n y).x
  | 0, _, h => h
  | n + 1, y, h => plain_runH P dly fw hl sched hf n _ (plain_step P dly fw _ y.x h hf)

/-- At a decision cycle, every released lane's hold counter is idle. -/
def GateOpen (P : Program) (y : EngineH) : Prop :=
  y.x.e.st = .idle → ∀ l, Ready P l y.x.e → y.hcnt l = 0

/-- The v1 scheduler induced by the hold scheduler along the hold run from `y0`.
Fallback to first-ready only at idle cycles; otherwise `sched`'s answer passes through. -/
def win1H (P : Program) (P2 : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (y0 : EngineH) (e : Engine) : Option Lane :=
  match sched (runH P2 fw hl sched (e.now - y0.x.e.now) y0) with
  | some w => if P.live w && decide (e.ts w ≤ e.now) then some w
              else if e.st = .idle then firstReady P e else none
  | none   => if e.st = .idle then firstReady P e else none

theorem win1H_ready (P : Program) (P2 : Program2) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH) :
    ∀ e w, win1H P P2 fw hl sched y0 e = some w → P.live w = true ∧ e.ts w ≤ e.now := by
  intro e w h
  unfold win1H at h
  split at h
  · split at h
    · rename_i hc
      cases h
      simp only [Bool.and_eq_true, decide_eq_true_eq] at hc
      exact hc
    · split at h
      · exact firstReady_some P e w h
      · cases h
  · split at h
    · exact firstReady_some P e w h
    · cases h

theorem win1H_wc (P : Program) (P2 : Program2) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH) :
    ∀ y e, e.st = .idle → Ready P y e → win1H P P2 fw hl sched y0 e ≠ none := by
  intro y e hi hy h
  unfold win1H at h
  split at h
  · split at h
    · cases h
    · exact firstReady_none P e (by simpa [hi] using h) y hy
  · exact firstReady_none P e (by simpa [hi] using h) y hy

/-- Along the hold run, where the gate is open at decisions, `win1H` is `sched`. -/
theorem win1H_on (P : Program) (P2 : Program2) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH)
    (hsw : ∀ y w, sched y = some w →
      P.live w = true ∧ y.x.e.ts w ≤ y.x.e.now ∧ y.hcnt w = 0)
    (hss : ∀ y l, y.x.e.st = .idle →
      P.live l = true ∧ y.x.e.ts l ≤ y.x.e.now ∧ y.hcnt l = 0 → sched y ≠ none)
    (n : Nat) (hI : GateOpen P (runH P2 fw hl sched n y0)) :
    win1H P P2 fw hl sched y0 (runH P2 fw hl sched n y0).x.e =
      sched (runH P2 fw hl sched n y0) := by
  have hk : (runH P2 fw hl sched n y0).x.e.now - y0.x.e.now = n := by
    rw [now_runH]
    omega
  unfold win1H
  rw [hk]
  cases hs : sched (runH P2 fw hl sched n y0) with
  | some w =>
    have := hsw _ w hs
    have hc : (P.live w && decide ((runH P2 fw hl sched n y0).x.e.ts w ≤
        (runH P2 fw hl sched n y0).x.e.now)) = true := by
      simp [this.1, this.2.1]
    dsimp only
    rw [if_pos hc]
  | none =>
    dsimp only
    by_cases hi : (runH P2 fw hl sched n y0).x.e.st = .idle
    · rw [if_pos hi]
      cases hf : firstReady P (runH P2 fw hl sched n y0).x.e with
      | none => rfl
      | some v =>
        have hv := firstReady_some P _ v hf
        have h0 := hI hi v ⟨hv.1, hv.2⟩
        exact absurd hs (hss _ v hi ⟨hv.1, hv.2, h0⟩)
    · rw [if_neg hi]

/-- **Coincidence.** While the gate has been open at every decision so far, the hold run's
engine is exactly the v1 run under `win1H`. -/
theorem runH_coinc (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH)
    (hx0 : Plain dly y0.x) (hf : ∀ y, PlainW dly y.e.pl (fw y))
    (hsw : ∀ y w, sched y = some w →
      (P2.toP dly).live w = true ∧ y.x.e.ts w ≤ y.x.e.now ∧ y.hcnt w = 0)
    (hss : ∀ y l, y.x.e.st = .idle →
      (P2.toP dly).live l = true ∧ y.x.e.ts l ≤ y.x.e.now ∧ y.hcnt l = 0 → sched y ≠ none) :
    ∀ n, (∀ m, m < n → GateOpen (P2.toP dly) (runH P2 fw hl sched m y0)) →
      (runH P2 fw hl sched n y0).x.e =
        run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) n y0.x.e
  | 0, _ => rfl
  | n + 1, hI => by
    rw [runH_succ', run_succ',
      ← runH_coinc P2 dly fw hl sched y0 hx0 hf hsw hss n (fun m hm => hI m (by omega))]
    rw [step_win_congr (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0),
      win1H_on (P2.toP dly) P2 fw hl sched y0 hsw hss n (hI n (by omega))]
    exact step2_proj P2 dly fw _ _ (plain_runH P2 dly fw hl sched hf n y0 hx0)

#print axioms runH_coinc

end JLane
