import JLane.Gap
/-!
# Brick 13 — closing the response bound
For `d_min ≥ 29`, every writeback lands within `14 + 2` of its release, by strong
induction on time. Plugged into `dstar`, this removes `hEDF`: stall-freedom holds for
any work-conserving scheduler that picks a ready lane.
-/
namespace JLane

theorem ts_flat (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine) (t : Nat)
    (h : ¬IsWB y (run P win t e)) : (run P win (t + 1) e).ts y = (run P win t e).ts y := by
  rw [run_succ', ts_step, if_neg h, Nat.add_zero]

theorem not_wb_of_st (y : Lane) (e : Engine) (h : e.st ≠ .wb) : ¬IsWB y e := by
  rintro ⟨h1, _⟩
  exact h h1

/-- A decision at `D` is written back at `D + 2`, with the same timestamp. -/
theorem dec_ts (P : Program) (win : Engine → Option Lane) (e0 : Engine) (D : Nat) (y : Lane)
    (h : Dec win y (run P win D e0)) :
    (run P win (D + 2) e0).ts y = (run P win D e0).ts y ∧
    (run P win (D + 2) e0).now = (run P win D e0).now + 2 := by
  have hidle : (run P win D e0).st = .idle := by
    obtain ⟨h1, -, -⟩ := h
    exact h1
  have hdrive : (run P win (D + 1) e0).st = .drive := by
    rw [run_succ']
    exact (step_of_dec P win _ y h).1
  have t1 := ts_flat P win y e0 D (not_wb_of_st y _ (by rw [hidle]; decide))
  have t2 := ts_flat P win y e0 (D + 1) (not_wb_of_st y _ (by rw [hdrive]; decide))
  have n1 := now_run P win D e0
  have n2 := now_run P win (D + 1 + 1) e0
  constructor
  · show (run P win (D + 1 + 1) e0).ts y = (run P win D e0).ts y
    rw [t2, t1]
  · show (run P win (D + 1 + 1) e0).now = (run P win D e0).now + 2
    omega

/-- **The response bound.** On a stall-free prefix with `d_min ≥ 29`, every writeback is
within `14 + 2` of its release. -/
theorem wb_bound (P : Program) (win : Engine → Option Lane) (e0 : Engine) (T : Nat)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, Ready P y e → win e ≠ none)
    (hd : ∀ l, P.live l = true → 29 ≤ P.dly l)
    (hNS : ∀ t, t < T → NoStall win (run P win t e0)) :
    ∀ t, t < T → ∀ y, P.live y = true → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + 14 + 2 := by
  have key : ∀ n, ∀ t, t < n → t < T → ∀ y, P.live y = true →
      IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + 14 + 2 := by
    intro n
    induction n with
    | zero =>
      intro t ht
      exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht htT y hy hwb
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn htT y hy hwb
      · obtain ⟨D, rfl, hdec⟩ := wb_back P win e0 h0 t y hwb
        obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 D y hdec
        rw [hts2, hnow2]
        by_cases hK : (run P win D e0).now ≤ (run P win D e0).ts y + 14
        · omega
        · exfalso
          have hrel := ts_mono P win y e0 0 D (Nat.zero_le D)
          have h00 : (run P win 0 e0).ts y = e0.ts y := rfl
          have h0y := h0ts y
          have hnD := now_run P win D e0
          obtain ⟨c, rfl⟩ : ∃ c, D = c + 15 := ⟨D - 15, by omega⟩
          have hnow_c := now_run P win c e0
          -- y has no writeback in the window: an earlier one would need `d ≤ 16`
          have noWB : ∀ w, c ≤ w → w < c + 15 → ¬IsWB y (run P win w e0) := by
            intro w hcw hwD hw
            have hIH := ih w (by omega) (by omega) y hy hw
            have hA := ts_after_wb P win y e0 w hw
            have hM := ts_mono P win y e0 (w + 1) (c + 15) (by omega)
            have hnw := now_run P win w e0
            have hdy := hd y hy
            omega
          -- y is ready at the window start
          have hrdy : Ready P y (run P win c e0) := by
            refine ⟨hy, ?_⟩
            have := ts_mono P win y e0 c (c + 15) (by omega)
            omega
          -- ... and not in the middle of its own dispatch
          have hmid : NotMid y (run P win c e0) := by
            unfold NotMid
            rintro ⟨hne, hcur⟩
            cases hs : (run P win c e0).st with
            | idle => exact hne hs
            | wb => exact noWB c (Nat.le_refl c) (by omega) ⟨hs, hcur⟩
            | drive =>
              have h1 := step_drive P win (run P win c e0) hs
              apply noWB (c + 1) (by omega) (by omega)
              rw [run_succ']
              exact ⟨h1.1, h1.2.trans hcur⟩
          -- y is not decided inside the window
          have hnd : ∀ s, s < 15 → ¬Dec win y (run P win s (run P win c e0)) := by
            intro s hs hds
            rw [← run_add] at hds
            have hw2 := dec_wb P win e0 (c + s) y hds
            rcases Nat.lt_or_ge (c + s + 2) (c + 15) with hlt | hge
            · exact noWB (c + s + 2) (by omega) hlt hw2
            · have hidle : (run P win (c + 15) e0).st = .idle := by
                obtain ⟨h1, -, -⟩ := hdec
                exact h1
              have hst1 : (run P win (c + s + 1) e0).st = .drive := by
                rw [run_succ']
                exact (step_of_dec P win _ y hds).1
              have hst2 : (run P win (c + s + 2) e0).st = .wb := by
                obtain ⟨h, -⟩ := hw2
                exact h
              have : c + 15 = c + s + 1 ∨ c + 15 = c + s + 2 := by omega
              rcases this with h | h
              · rw [h, hst1] at hidle
                cases hidle
              · rw [h, hst2] at hidle
                cases hidle
          -- no stalls inside the window
          have hns : ∀ s, s < 15 → NoStall win (run P win s (run P win c e0)) := by
            intro s hs
            rw [← run_add]
            exact hNS (c + s) (by omega)
          -- no other lane is decided twice inside the window
          have honce : ∀ z, z ≠ y → cnt P win (Dec win z) 15 (run P win c e0) ≤ 1 := by
            intro z _
            rcases Nat.lt_or_ge (cnt P win (Dec win z) 15 (run P win c e0)) 2 with hlt | hge
            · omega
            · exfalso
              obtain ⟨t0, ht0, hc0, hd0⟩ :=
                cnt_reach P win (Dec win z) 15 (run P win c e0) 0 (by omega)
              obtain ⟨t1, ht1, hc1, hd1⟩ :=
                cnt_reach P win (Dec win z) 15 (run P win c e0) 1 (by omega)
              have hlt01 : t0 < t1 := by
                rcases Nat.lt_or_ge t0 t1 with h | h
                · exact h
                · have := cnt_mono P win (Dec win z) (run P win c e0) t1 t0 h
                  omega
              rw [← run_add] at hd0 hd1
              have hw0 := dec_wb P win e0 (c + t0) z hd0
              have hlz : P.live z = true := by
                obtain ⟨-, h, -⟩ := hd0
                exact (hwin _ z h).1
              have hIH := ih (c + t0 + 2) (by omega) (by omega) z hlz hw0
              obtain ⟨hts0, hnow0⟩ := dec_ts P win e0 (c + t0) z hd0
              have hgap := dec_gap_time P win e0 z hwin (c + t0) (c + t1) 14 (by omega)
                hd0 hd1 (by omega)
              have hdz := hd z hlz
              omega
          -- Lemma A: a 15-cycle wait is impossible
          have hA := lemmaA_once P win y (hws y) 15 (run P win c e0) hrdy hmid hnd hns honce
          have hK1 : K - 1 = 4 := rfl
          omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

/-- **D* without EDF.** From a primed start with no lane overdue, any work-conserving
scheduler that picks a ready lane never stalls when every live lane has `d ≥ 29` and
`d ≥ D* + B`, given the branch-1 budget `B` on stall-free prefixes. -/
theorem dstar29 (P : Program) (win : Engine → Option Lane) (e0 : Engine) (B : Nat)
    (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, Ready P y e → win e ≠ none)
    (hd : ∀ l, P.live l = true → 29 ≤ P.dly l)
    (hBd : ∀ l, P.live l = true → DSTAR + B ≤ P.dly l)
    (hB : ∀ T, (∀ t, t < T → NoStall win (run P win t e0)) →
      ∀ y a m, P.live y = true → a + m ≤ T → m ≤ 23 + B →
        chargeSum P win y m (run P win a e0) ≤ B) :
    ∀ T, NoStall win (run P win T e0) :=
  dstar P win e0 (fun _ => 14) B hW hfull hwin hBd
    (fun l hl => by
      show 14 + 26 + B ≤ 2 * P.dly l
      have h1 := hd l hl
      have h2 := hBd l hl
      have h3 : DSTAR = 20 := dstar_val
      omega)
    (fun T hT y t hy ht hwb => wb_bound P win e0 T h0 h0ts hwin hws hd hT t ht y hy hwb)
    hB

#print axioms dstar29

end JLane
