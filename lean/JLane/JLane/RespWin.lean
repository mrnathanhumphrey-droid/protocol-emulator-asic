import JLane.LemmaAS
/-!
# Brick G — the response bound from a window budget (stage 5, step 2)

`Close.wb_bound` closed the response bound with one uniform delay (`d ≥ 29`, so no other
lane is decided twice in 15 cycles) and no stalls. With ARMs (gap as small as 3) and option A
(stalls under the shipped scheduler) neither holds. Here the bound is read off a **window
budget**: if, in every window of `K = 3M + S + 3` cycles, other lanes are decided at most `M`
times and the dispatcher stalls at most `S` cycles, then every writeback of `y` lands within
`K + 1 = 3M + S + 4` of its release (`Rr = 3M + S + 2` in `GapRun`'s form) — provided `y`'s
earlier writebacks came before its current release (`hfree`: automatic after an ARM, whose
release is past its edge, past its writeback; for other words, a gap above the response).
`M` per lane is the decision multiplicity the stage 6 certificate computes from the gap
sequences; `S` is 0 under the ruled scheduler (b′) and the proved stall bound under (c).
-/
namespace JLane

theorem wb_bound_win (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l) (y : Lane) (hy : P.live y = true)
    (M S K : Nat) (hK : K = 3 * M + S + 3)
    (hws : ∀ e, e.st = .idle → Ready P y e → win e ≠ none)
    (t : Nat) (hwb : IsWB y (run P win t e0))
    (hfree : ∀ w, w + 2 < t → IsWB y (run P win w e0) →
      (run P win w e0).now < (run P win t e0).ts y)
    (hM : ∀ c, c + K + 2 ≤ t → cnt P win (fun e => decOther win y e = true) K (run P win c e0) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t → cnt P win (fun e => stallB win e = true) K (run P win c e0) ≤ S) :
    (run P win t e0).now ≤ (run P win t e0).ts y + K + 1 := by
  obtain ⟨D, rfl, hdec⟩ := wb_back P win e0 h0 t y hwb
  obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 D y hdec
  rw [hts2, hnow2]
  rw [hts2] at hfree
  by_cases hfit : (run P win D e0).now + 1 ≤ (run P win D e0).ts y + K
  · omega
  · exfalso
    have hnD := now_run P win D e0
    have hts0 := ts_mono P win y e0 0 D (Nat.zero_le D)
    have h00 : (run P win 0 e0).ts y = e0.ts y := rfl
    have h0y := h0ts y
    obtain ⟨c, rfl⟩ : ∃ c, D = c + K := ⟨D - K, by omega⟩
    have hnc := now_run P win c e0
    -- no writeback of y inside the window: it would precede the release, but the window is past it
    have noWB : ∀ w, c ≤ w → w < c + K → ¬IsWB y (run P win w e0) := by
      intro w hcw hwD hw
      have h1 := hfree w (by omega) hw
      have h2 := now_run P win w e0
      omega
    -- y is ready at the window start
    have hrdy : Ready P y (run P win c e0) := by
      refine ⟨hy, ?_⟩
      have := ts_mono P win y e0 c (c + K) (by omega)
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
    have hnd : ∀ s, s < K → ¬Dec win y (run P win s (run P win c e0)) := by
      intro s hs hds
      rw [← run_add] at hds
      have hw2 := dec_wb P win e0 (c + s) y hds
      rcases Nat.lt_or_ge (c + s + 2) (c + K) with hlt | hge
      · exact noWB (c + s + 2) (by omega) hlt hw2
      · have hidle : (run P win (c + K) e0).st = .idle := by
          obtain ⟨h1, -, -⟩ := hdec
          exact h1
        have hst1 : (run P win (c + s + 1) e0).st = .drive := by
          rw [run_succ']
          exact (step_of_dec P win _ y hds).1
        have hst2 : (run P win (c + s + 2) e0).st = .wb := by
          obtain ⟨h, -⟩ := hw2
          exact h
        have : c + K = c + s + 1 ∨ c + K = c + s + 2 := by omega
        rcases this with h | h
        · rw [h, hst1] at hidle
          cases hidle
        · rw [h, hst2] at hidle
          cases hidle
    have hA := lemmaA_s P win y hws K (run P win c e0) hrdy hmid hnd
    have hm := hM c (by omega)
    have hs := hS c (by omega)
    omega

#print axioms wb_bound_win

end JLane
