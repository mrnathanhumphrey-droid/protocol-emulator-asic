import JLane.ArmClose
/-!
# Brick J — response bounds from the gap sequence (stage 5, step 5)

`wb_close` bounds lane `z`'s decisions in a window by one spacing `σ z`. One number per lane is
too coarse for the USB lane: its ARMs can be decided 4 cycles apart, but only in ARM→ARM pairs;
its other words are ≥ 20 apart. Here the bound comes from the **gap sequence**:

* `hspan` — any `m z` consecutive writebacks of `z` advance its release by at least `G z`
  (the stage 6 checker: the least sum of `m z` consecutive word gaps along any path, an ARM's
  gap from the edge premises), given those writebacks met their response bounds;
* then `z` is decided at most `m z` times in lane `y`'s window `R y + 1`, as long as
  `R y + 1 + R z ≤ G z`: the first and the `(m z)`-th next decision would be at least
  `G z − R z` apart (only the first decision's lateness counts — releases accumulate on the
  timestamp, not on `now`).
-/
namespace JLane

/-- From an idle start, a writeback at `x + 2` is exactly a decision at `x`. -/
theorem wb_iff_dec (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (h0 : e0.st = .idle) (z : Lane) (x : Nat) :
    IsWB z (run P win (x + 2) e0) ↔ Dec win z (run P win x e0) := by
  constructor
  · intro h
    obtain ⟨s, hs, hd⟩ := wb_back P win e0 h0 (x + 2) z h
    have : s = x := by omega
    subst this
    exact hd
  · exact dec_wb P win e0 x z

/-- Writebacks counted from `a + 2` are the decisions counted from `a`. -/
theorem cnt_wb_shift (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (h0 : e0.st = .idle) (z : Lane) :
    ∀ n a, cnt P win (IsWB z) n (run P win (a + 2) e0) = cnt P win (Dec win z) n (run P win a e0)
  | 0, _ => by simp [cnt]
  | n + 1, a => by
    have e1 : cnt P win (IsWB z) (n + 1) (run P win (a + 2) e0)
        = (if IsWB z (run P win (a + 2) e0) then 1 else 0)
          + cnt P win (IsWB z) n (step P win (run P win (a + 2) e0)) := rfl
    have e2 : cnt P win (Dec win z) (n + 1) (run P win a e0)
        = (if Dec win z (run P win a e0) then 1 else 0)
          + cnt P win (Dec win z) n (step P win (run P win a e0)) := rfl
    have s1 : step P win (run P win (a + 2) e0) = run P win ((a + 1) + 2) e0 := by
      rw [← run_succ']
    have s2 : step P win (run P win a e0) = run P win (a + 1) e0 := by
      rw [← run_succ']
    rw [e1, e2, s1, s2, cnt_wb_shift P win e0 h0 z n (a + 1)]
    by_cases h : Dec win z (run P win a e0)
    · rw [if_pos h, if_pos ((wb_iff_dec P win e0 h0 z a).mpr h)]
    · rw [if_neg h, if_neg (fun h' => h ((wb_iff_dec P win e0 h0 z a).mp h'))]

/-- **The per-lane response bounds from the gap sequence.** As `wb_close`, with the spacing
`σ`/`hmul` replaced by the span `hspan` and `R y + 1 + R z ≤ G z`. -/
theorem wb_close_span (P : Program) (win : Engine → Option Lane) (e0 : Engine) (T S : Nat)
    (R m G : Lane → Nat)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hm1 : ∀ z, 1 ≤ m z)
    (hS : ∀ y c, P.live y = true → c + (R y + 1) ≤ T →
      cnt P win (fun e => stallB win e = true) (R y + 1) (run P win c e0) ≤ S)
    (hspan : ∀ z x1 n, cnt P win (IsWB z) n (run P win x1 e0) = m z →
      (∀ x, x1 ≤ x → x < x1 + n → IsWB z (run P win x e0) →
        (run P win x e0).now ≤ (run P win x e0).ts z + R z + 2) →
      (run P win x1 e0).ts z + G z ≤ (run P win (x1 + n) e0).ts z)
    (hrel : ∀ y x, IsWB y (run P win x e0) →
      (run P win x e0).now ≤ (run P win x e0).ts y + R y + 2 →
      (run P win x e0).now < (run P win (x + 1) e0).ts y)
    (hG : ∀ y z, z ≠ y → R y + 1 + R z ≤ G z)
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
              rcases Nat.lt_or_ge (cnt P win (Dec win z) (R y + 1) (run P win c e0)) (m z + 1)
                with hlt | hge
              · omega
              · exfalso
                obtain ⟨i, hi, hci, hdi⟩ :=
                  cnt_reach P win (Dec win z) (R y + 1) (run P win c e0) 0 (by omega)
                obtain ⟨j, hj, hcj, hdj⟩ :=
                  cnt_reach P win (Dec win z) (R y + 1) (run P win c e0) (m z) (by omega)
                rw [← run_add] at hdi hdj
                have hij : i < j := by
                  rcases Nat.lt_or_ge i j with h' | h'
                  · exact h'
                  · have := cnt_mono P win (Dec win z) (run P win c e0) j i h'
                    have := hm1 z
                    omega
                have h3 := dec_sep P win e0 z (c + i) (c + j) (by omega) hdi hdj
                -- the decisions in [c+i, c+j): exactly m z, none in its last two cycles
                have hsplit := cnt_add P win (Dec win z) i (j - i) (run P win c e0)
                rw [show i + (j - i) = j by omega, ← run_add] at hsplit
                have hsplit2 := cnt_add P win (Dec win z) (j - i - 2) 2 (run P win (c + i) e0)
                rw [show j - i - 2 + 2 = j - i by omega, ← run_add] at hsplit2
                have hlast : cnt P win (Dec win z) 2 (run P win (c + i + (j - i - 2)) e0) = 0 :=
                  cnt_zero_of P win (Dec win z) 2 _ (fun s hs hds => by
                    rw [← run_add] at hds
                    have := dec_sep P win e0 z (c + i + (j - i - 2) + s) (c + j) (by omega)
                      hds hdj
                    omega)
                have hshift := cnt_wb_shift P win e0 h0 z (j - i - 2) (c + i)
                have hlz := (hwin _ z hdi.2.1).1
                -- the span over those m z writebacks
                have hsp := hspan z (c + i + 2) (j - i - 2) (by omega) (fun x hx1 hx2 hxw =>
                  IH x (by omega) z hlz hxw)
                rw [show c + i + 2 + (j - i - 2) = c + j by omega] at hsp
                obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 (c + i) z hdi
                have hr := IH (c + i + 2) (by omega) z hlz (dec_wb P win e0 (c + i) z hdi)
                have hrdy := (hwin _ z hdj.2.1).2
                have hni := now_run P win (c + i) e0
                have hnj := now_run P win (c + j) e0
                have hg := hG y z hzy
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

#print axioms cnt_wb_shift
#print axioms wb_close_span

end JLane
