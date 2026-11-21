import JLane.RespWinB
import JLane.Pigeon
/-!
# Brick C3c — the counting lemmas along `runBK` (`slot_on_composition`, closure step 2)

`RespClose.wb_close` closes the per-lane bounds with `cnt_add`, `cnt_mono`, `cnt_reach`,
`cnt_sparse_g` and `cnt_decOther_split`, all stated for `cnt` along `run`. The closure on the
buffered engine with flushes (`wb_closeBK`) counts along `runBK` with `cntBK`; these are the same
lemmas there, proved the same way from `runBK_succ'` and `runBK_add`.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- The counter seen from the back. -/
theorem cntBK_succ_back (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop)
    [DecidablePred Q] :
    ∀ (n : Nat) (X : EngBK),
      cntBK P win usb sreq fl k Q (n + 1) X
        = cntBK P win usb sreq fl k Q n X
          + (if Q (runBK P win usb sreq fl k n X).x.e then 1 else 0)
  | 0, X => by simp [cntBK, runBK]
  | n + 1, X => by
    have ih := cntBK_succ_back fl k Q n (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)
    have e1 : cntBK P win usb sreq fl k Q (n + 1 + 1) X
        = (if Q X.x.e then 1 else 0) + cntBK P win usb sreq fl k Q (n + 1)
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e2 : cntBK P win usb sreq fl k Q (n + 1) X
        = (if Q X.x.e then 1 else 0) + cntBK P win usb sreq fl k Q n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e3 : runBK P win usb sreq fl k (n + 1) X
        = runBK P win usb sreq fl k n (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    rw [e3]
    omega

/-- **Counters add along `runBK`.** -/
theorem cntBK_add (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop)
    [DecidablePred Q] :
    ∀ (a b : Nat) (X : EngBK),
      cntBK P win usb sreq fl k Q (a + b) X
        = cntBK P win usb sreq fl k Q a X
          + cntBK P win usb sreq fl k Q b (runBK P win usb sreq fl k a X)
  | 0, b, X => by
    show cntBK P win usb sreq fl k Q (0 + b) X = 0 + cntBK P win usb sreq fl k Q b X
    rw [Nat.zero_add, Nat.zero_add]
  | a + 1, b, X => by
    rw [Nat.add_right_comm]
    show (if Q X.x.e then 1 else 0)
          + cntBK P win usb sreq fl k Q (a + b)
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)
        = ((if Q X.x.e then 1 else 0)
            + cntBK P win usb sreq fl k Q a
              (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X))
          + cntBK P win usb sreq fl k Q b
            (runBK P win usb sreq fl k a (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X))
    rw [cntBK_add fl k Q a b (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)]
    omega

/-- **Counters are monotone in the horizon.** -/
theorem cntBK_mono (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop)
    [DecidablePred Q] (X : EngBK) (a : Nat) :
    ∀ (b : Nat), a ≤ b → cntBK P win usb sreq fl k Q a X ≤ cntBK P win usb sreq fl k Q b X
  | 0, h => by
    have : a = 0 := by omega
    subst this
    exact Nat.le_refl _
  | b + 1, h => by
    by_cases hab : a = b + 1
    · subst hab
      exact Nat.le_refl _
    · have ih := cntBK_mono fl k Q X a b (by omega)
      have := cntBK_succ_back P win usb sreq fl k Q b X
      omega

/-- **Event extraction.** If the counter has passed `j`, the `j`-th event happened at some cycle
`t`, with exactly `j` events before it. -/
theorem cntBK_reach (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop)
    [DecidablePred Q] :
    ∀ (n : Nat) (X : EngBK) (j : Nat), j < cntBK P win usb sreq fl k Q n X →
      ∃ t, t < n ∧ cntBK P win usb sreq fl k Q t X = j
        ∧ Q (runBK P win usb sreq fl k t X).x.e
  | 0, X, j, h => by simp [cntBK] at h
  | n + 1, X, j, h => by
    have e1 : cntBK P win usb sreq fl k Q (n + 1) X
        = (if Q X.x.e then 1 else 0) + cntBK P win usb sreq fl k Q n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    by_cases hq : Q X.x.e
    · rw [if_pos hq] at e1
      cases j with
      | zero => exact ⟨0, Nat.succ_pos n, rfl, hq⟩
      | succ j =>
        have h' : j < cntBK P win usb sreq fl k Q n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := by omega
        obtain ⟨t, ht, hc, hq'⟩ := cntBK_reach fl k Q n
          (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) j h'
        have e2 : cntBK P win usb sreq fl k Q (t + 1) X
            = (if Q X.x.e then 1 else 0) + cntBK P win usb sreq fl k Q t
                (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
        rw [if_pos hq] at e2
        exact ⟨t + 1, by omega, by omega, hq'⟩
    · rw [if_neg hq] at e1
      have h' : j < cntBK P win usb sreq fl k Q n
          (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := by omega
      obtain ⟨t, ht, hc, hq'⟩ := cntBK_reach fl k Q n
        (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) j h'
      have e2 : cntBK P win usb sreq fl k Q (t + 1) X
          = (if Q X.x.e then 1 else 0) + cntBK P win usb sreq fl k Q t
              (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
      rw [if_neg hq] at e2
      exact ⟨t + 1, by omega, by omega, hq'⟩

/-- Events at least `σ` apart: at most one in `σ` cycles. -/
theorem cntBK_le_one_sep (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop)
    [DecidablePred Q] (X : EngBK) (σ n : Nat) (hn : n ≤ σ)
    (hsep : ∀ i j, i < j → j < n → Q (runBK P win usb sreq fl k i X).x.e →
      Q (runBK P win usb sreq fl k j X).x.e → i + σ ≤ j) :
    cntBK P win usb sreq fl k Q n X ≤ 1 := by
  rcases Nat.lt_or_ge (cntBK P win usb sreq fl k Q n X) 2 with h | h
  · omega
  · exfalso
    obtain ⟨t0, ht0, hc0, hq0⟩ := cntBK_reach P win usb sreq fl k Q n X 0 (by omega)
    obtain ⟨t1, ht1, hc1, hq1⟩ := cntBK_reach P win usb sreq fl k Q n X 1 (by omega)
    have hlt : t0 < t1 := by
      rcases Nat.lt_or_ge t0 t1 with h' | h'
      · exact h'
      · have := cntBK_mono P win usb sreq fl k Q X t1 t0 h'
        omega
    have := hsep t0 t1 hlt ht1 hq0 hq1
    omega

/-- **Sparse events.** Events at least `σ ≥ 1` apart number at most `m` in `n ≤ σ·m` cycles. -/
theorem cntBK_sparse_g (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop)
    [DecidablePred Q] (X : EngBK) (σ : Nat) (hσ : 1 ≤ σ) :
    ∀ m n, n ≤ σ * m →
      (∀ i j, i < j → j < n → Q (runBK P win usb sreq fl k i X).x.e →
        Q (runBK P win usb sreq fl k j X).x.e → i + σ ≤ j) →
      cntBK P win usb sreq fl k Q n X ≤ m
  | 0, n, hn, _ => by
    have : n = 0 := by rw [Nat.mul_zero] at hn; omega
    subst this
    simp [cntBK]
  | m + 1, n, hn, hsep => by
    rw [Nat.mul_succ] at hn
    rcases Nat.lt_or_ge σ n with hbig | hsmall
    · have hsplit := cntBK_add P win usb sreq fl k Q (n - σ) σ X
      have hn' : n - σ + σ = n := by omega
      rw [hn'] at hsplit
      have h1 := cntBK_sparse_g fl k Q X σ hσ m (n - σ) (by omega)
        (fun i j hij hj => hsep i j hij (by omega))
      have h2 := cntBK_le_one_sep P win usb sreq fl k Q
        (runBK P win usb sreq fl k (n - σ) X) σ σ (Nat.le_refl σ)
        (fun i j hij hj hqi hqj => by
          rw [← runBK_add] at hqi hqj
          have := hsep (n - σ + i) (n - σ + j) (by omega) (by omega) hqi hqj
          omega)
      omega
    · have := cntBK_le_one_sep P win usb sreq fl k Q X σ n hsmall hsep
      omega

/-- Other-lane decisions plus lane `i`'s are all the decisions, along `runBK`. -/
theorem cntBK_decOther_split (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (i : Lane) :
    ∀ (n : Nat) (X : EngBK),
      cntBK P win usb sreq fl k (fun e => decOther win i e = true) n X
          + cntBK P win usb sreq fl k (Dec win i) n X
        = cntBK P win usb sreq fl k (fun e => decAny win e = true) n X
  | 0, X => by simp [cntBK]
  | n + 1, X => by
    have ih := cntBK_decOther_split fl k i n
      (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)
    have h := decOther_split win i X.x.e
    have e0 : cntBK P win usb sreq fl k (fun e => decOther win i e = true) (n + 1) X
        = (if decOther win i X.x.e = true then 1 else 0)
          + cntBK P win usb sreq fl k (fun e => decOther win i e = true) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e1 : cntBK P win usb sreq fl k (Dec win i) (n + 1) X
        = (if Dec win i X.x.e then 1 else 0)
          + cntBK P win usb sreq fl k (Dec win i) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e2 : cntBK P win usb sreq fl k (fun e => decAny win e = true) (n + 1) X
        = (if decAny win X.x.e = true then 1 else 0)
          + cntBK P win usb sreq fl k (fun e => decAny win e = true) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    omega

end

end JLane
