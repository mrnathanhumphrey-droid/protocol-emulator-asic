import JLane.RespWin
/-!
# Brick H — closing the response bounds per lane (stage 5, step 3)

`Close.wb_bound` closed one uniform bound (14 + 2) by strong induction on time, from one
uniform delay `d ≥ 29`. Here every lane `y` has its own bound `R y`, closed the same way from
`wb_bound_win`, with the program facts entering as **conditional** hypotheses — each holds
given the response bound of the earlier writeback, which the induction supplies:

* `hsep` — two decisions of lane `z` are at least `σ z` apart, given the first one's writeback
  met its bound (a word with gap `g`: `σ = g − R`; after an ARM `σ ≥ 4` outright, its release
  being past its edge, past its writeback);
* `hrel` — a writeback that met its bound comes before the lane's next release (an ARM:
  outright; other words: gap `≥ R + 3`);
* `hmul` — `σ z · m z` covers lane `y`'s window `R y + 1`, so `z` is decided at most `m z`
  times in it (`cnt_sparse_g`);
* `hK` — `3·Σ_{z≠y} m z + S + 3 ≤ R y + 1`, with `S` the stall budget per window (`hS`;
  0 under the ruled scheduler (b′), the proved bound under (c)).
-/
namespace JLane

/-- Events at least `σ` apart: at most one in `σ` cycles. -/
theorem cnt_le_one_sep (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] (e : Engine) (σ n : Nat) (hn : n ≤ σ)
    (hsep : ∀ i j, i < j → j < n → Q (run P win i e) → Q (run P win j e) → i + σ ≤ j) :
    cnt P win Q n e ≤ 1 := by
  rcases Nat.lt_or_ge (cnt P win Q n e) 2 with h | h
  · omega
  · exfalso
    obtain ⟨t0, ht0, hc0, hq0⟩ := cnt_reach P win Q n e 0 (by omega)
    obtain ⟨t1, ht1, hc1, hq1⟩ := cnt_reach P win Q n e 1 (by omega)
    have hlt : t0 < t1 := by
      rcases Nat.lt_or_ge t0 t1 with h' | h'
      · exact h'
      · have := cnt_mono P win Q e t1 t0 h'
        omega
    have := hsep t0 t1 hlt ht1 hq0 hq1
    omega

/-- **Sparse events.** Events at least `σ ≥ 1` apart number at most `k` in `n ≤ σ·k` cycles. -/
theorem cnt_sparse_g (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] (e : Engine) (σ : Nat) (hσ : 1 ≤ σ) :
    ∀ k n, n ≤ σ * k →
      (∀ i j, i < j → j < n → Q (run P win i e) → Q (run P win j e) → i + σ ≤ j) →
      cnt P win Q n e ≤ k
  | 0, n, hn, _ => by
    have : n = 0 := by rw [Nat.mul_zero] at hn; omega
    subst this
    simp [cnt]
  | k + 1, n, hn, hsep => by
    rw [Nat.mul_succ] at hn
    rcases Nat.lt_or_ge σ n with hbig | hsmall
    · have hsplit := cnt_add P win Q (n - σ) σ e
      have hn' : n - σ + σ = n := by omega
      rw [hn'] at hsplit
      have h1 := cnt_sparse_g P win Q e σ hσ k (n - σ) (by omega)
        (fun i j hij hj => hsep i j hij (by omega))
      have h2 := cnt_le_one_sep P win Q (run P win (n - σ) e) σ σ (Nat.le_refl σ)
        (fun i j hij hj hqi hqj => by
          rw [← run_add] at hqi hqj
          have := hsep (n - σ + i) (n - σ + j) (by omega) (by omega) hqi hqj
          omega)
      omega
    · have := cnt_le_one_sep P win Q e σ n hsmall hsep
      omega

/-- **The per-lane response bounds, closed.** Under the conditional program facts above, every
writeback of every live lane `y` before `T` lands within `R y + 2` of its release. -/
theorem wb_close (P : Program) (win : Engine → Option Lane) (e0 : Engine) (T S : Nat)
    (R m σ : Lane → Nat)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hσ : ∀ z, 1 ≤ σ z)
    (hS : ∀ y c, P.live y = true → c + (R y + 1) ≤ T →
      cnt P win (fun e => stallB win e = true) (R y + 1) (run P win c e0) ≤ S)
    (hsep : ∀ z a b, a < b → Dec win z (run P win a e0) → Dec win z (run P win b e0) →
      (run P win (a + 2) e0).now ≤ (run P win (a + 2) e0).ts z + R z + 2 → a + σ z ≤ b)
    (hrel : ∀ y x, IsWB y (run P win x e0) →
      (run P win x e0).now ≤ (run P win x e0).ts y + R y + 2 →
      (run P win x e0).now < (run P win (x + 1) e0).ts y)
    (hmul : ∀ y z, z ≠ y → R y + 1 ≤ σ z * m z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + S + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P.live y = true → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R y + 2 := by
  have key : ∀ n, ∀ t, t < n → t < T → ∀ y, P.live y = true → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R y + 2 := by
    intro n
    induction n with
    | zero => intro t ht; exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht htT y hy hwb
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn htT y hy hwb
      · have IH : ∀ t', t' < t → ∀ z, P.live z = true → IsWB z (run P win t' e0) →
            (run P win t' e0).now ≤ (run P win t' e0).ts z + R z + 2 :=
          fun t' h' => ih t' (by omega) (by omega)
        have hw := wb_bound_win P win e0 h0 h0ts y hy
          (m L0 + m L1 + m L2 + m L3 + m L4 - m y) S (R y + 1) (hK y) (hws y) t hwb
          (fun w hw hwbw => by
            have hr := IH w (by omega) y hy hwbw
            have h1 := hrel y w hwbw hr
            have h2 := ts_mono P win y e0 (w + 1) t (by omega)
            omega)
          (fun c hc => by
            have hz : ∀ z, z ≠ y → cnt P win (Dec win z) (R y + 1) (run P win c e0) ≤ m z := by
              intro z hzy
              apply cnt_sparse_g P win (Dec win z) (run P win c e0) (σ z) (hσ z) (m z) (R y + 1)
                (hmul y z hzy)
              intro i j hij hj hqi hqj
              rw [← run_add] at hqi hqj
              have hlz := (hwin _ z hqi.2.1).1
              have hr := IH (c + i + 2) (by omega) z hlz (dec_wb P win e0 (c + i) z hqi)
              have := hsep z (c + i) (c + j) (by omega) hqi hqj hr
              omega
            have hs := cnt_decOther_split P win y (R y + 1) (run P win c e0)
            have ha := cnt_decAny_split P win (R y + 1) (run P win c e0)
            rcases lane_cases y with rfl | rfl | rfl | rfl | rfl
            · have a := hz L1 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L3 (by decide); omega)
          (fun c hc => hS y c hy (by omega))
        omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

#print axioms cnt_sparse_g
#print axioms wb_close

end JLane
