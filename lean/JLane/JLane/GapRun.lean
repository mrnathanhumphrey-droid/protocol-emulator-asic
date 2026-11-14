import JLane.OptRun
/-!
# Brick D — the pending bound with per-retirement gaps (branch brick, stage 4 step 1)

`OptRun` bounded refills against one minimum delay `d` per lane. An ARM breaks that: its
release is the peer's edge, as soon as `ts(ARM) + 3` (`pe_engine.v` l.4171, l.4239). Here
every quantity is per retirement, read along the run:

* `gp x` — the release gap a retirement at `x` opens: `dly + ext` at that writeback (exact,
  `ts_after_wb`; for an ARM, the edge's distance, supplied by the refinement);
* `Rr x` — the response bound at that retirement (`now ≤ ts + Rr x + 2`);
* `Z x` — a **certificate**: the bound on the refill owed from that retirement is
  `ts(x) + Z x + 25 + B` unless it was deferred past a no-prefetch word;
* `L x` — the lateness allowed to the word released after retirement `x`.

Certificate conditions (any `Z` satisfying them works; stage 6 computes one per program):
`Rr x ≤ Z x`; `Rr x + D* + B ≤ Z x` at a no-prefetch retirement; and for consecutive
retirements `x < x2`, `Z x + D* + B ≤ gp x + Z x2`.
Head-valid conditions: `Rr x + 26 + B ≤ gp x + L x` at a no-prefetch retirement, and
`Z x + 26 + B ≤ gp x + gp x2 + L x2` for consecutive retirements.
With `gp = d`, `Z = R + Y`, these are `OptRun`'s conditions.
-/
namespace JLane

/-- The release gap a writeback of `y` at cycle `x` opens. -/
def gp (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (x : Nat) : Nat :=
  P.dly y + P.ext (run P win x e0).now y

theorem ts_gap (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (x z : Nat)
    (hw : IsWB y (run P win x e0)) (hxz : x < z) :
    (run P win x e0).ts y + gp P win y e0 x ≤ (run P win z e0).ts y := by
  have h1 := ts_after_wb P win y e0 x hw
  have h2 := ts_mono P win y e0 (x + 1) z (by omega)
  unfold gp
  omega

/-- Consecutive retirements of `y`. -/
def Consec (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (x x2 : Nat) :
    Prop :=
  x < x2 ∧ IsRet P y (run P win x e0) ∧ IsRet P y (run P win x2 e0) ∧
    cnt P win (IsRet P y) x2 e0 = cnt P win (IsRet P y) x e0 + 1

section
variable (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (B T : Nat)
  (Rr Z : Nat → Nat)

/-- The deferred case with the response read at `w2`. -/
theorem pb_defer_g (s w2 t : Nat) (hy : P.live y = true) (hS0 : Struct e0)
    (hRw : (run P win w2 e0).now ≤ (run P win w2 e0).ts y + Rr w2 + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hs : s ≤ w2) (hw2t : w2 < t) (htT : t ≤ T)
    (ho : 1 ≤ (run P win s e0).owed y) (hw : (run P win s e0).wantFetch y = false)
    (hr2 : IsRet P y (run P win w2 e0))
    (hnr : cnt P win (IsRet P y) s e0 = cnt P win (IsRet P y) w2 e0)
    (hnh : cnt P win (Hit y) s e0 = cnt P win (Hit y) t e0) :
    NpfAt y (run P win w2 e0) ∧ e0.now + t ≤ (run P win w2 e0).ts y + Rr w2 + PENDING_SLACK + B := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hHS : HEAD_SLACK = 26 := head_slack_val
  have hDS : DSTAR = 20 := dstar_val
  have hold := npf_hold P win y e0 s ho hw (w2 - s) (fun i hi =>
    ⟨no_event_between P win (Hit y) e0 s t (s + i) (by omega) (by omega) hnh,
     not_ret_form P y _
       (no_event_between P win (IsRet P y) e0 s w2 (s + i) (by omega) (by omega) hnr)⟩)
  have hsw : s + (w2 - s) = w2 := by omega
  rw [hsw] at hold
  have hnh2 : ¬Hit y (run P win w2 e0) :=
    no_event_between P win (Hit y) e0 s t w2 hs hw2t hnh
  obtain ⟨hwant, hnpf⟩ := npf_unlock P win y (run P win w2 e0) (struct_run P win w2 e0 hS0)
    hold.1 hold.2 hnh2 (ret_form P y _ hr2)
  refine ⟨hnpf, ?_⟩
  have hwant' : (run P win (w2 + 1) e0).wantFetch y = true := by
    rw [run_succ']
    exact hwant
  have hm1 := cnt_mono P win (Hit y) e0 s (w2 + 1) (by omega)
  have hm2 := cnt_mono P win (Hit y) e0 (w2 + 1) t (by omega)
  have hn := window_le P win y hy (run P win (w2 + 1) e0) B (t - (w2 + 1))
    (struct_run P win (w2 + 1) e0 hS0) hwant'
    (fun m hm hm' => hB (w2 + 1) m (by omega) hm')
    (fun i hi => by
      rw [← run_add]
      exact no_event_between P win (Hit y) e0 (w2 + 1) t (w2 + 1 + i) (by omega) (by omega)
        (by omega))
  have hnow := now_run P win w2 e0
  omega

/-- **The pending bound with per-retirement gaps.** Refill `#k` of lane `y`, owed from
retirement `#k` at `w`, still pending at `t` after retirement `#(k+1)` at `w2`: deferred
(bound against `w2`), or within the certificate `Z w`. -/
theorem pending_bound_gap (hy : P.live y = true) (hS0 : Struct e0) (h0 : e0.owed y = 0)
    (hR : ∀ x, x < T → IsRet P y (run P win x e0) →
      (run P win x e0).now ≤ (run P win x e0).ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hZ0 : ∀ x, x < T → IsRet P y (run P win x e0) → Rr x ≤ Z x)
    (hZF : ∀ x, x < T → IsRet P y (run P win x e0) → NpfAt y (run P win x e0) →
      Rr x + DSTAR + B ≤ Z x)
    (hZC : ∀ x x2, x2 < T → Consec P win y e0 x x2 →
      Z x + DSTAR + B ≤ gp P win y e0 x + Z x2) :
    ∀ (k t w w2 : Nat), t ≤ T → w < w2 → w2 < t →
      cnt P win (IsRet P y) w e0 = k → IsRet P y (run P win w e0) →
      cnt P win (IsRet P y) w2 e0 = k + 1 → IsRet P y (run P win w2 e0) →
      cnt P win (Hit y) t e0 ≤ k →
      (NpfAt y (run P win w2 e0) ∧ e0.now + t ≤ (run P win w2 e0).ts y + Rr w2 + PENDING_SLACK + B) ∨
      e0.now + t ≤ (run P win w e0).ts y + Z w + PENDING_SLACK + B := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hHS : HEAD_SLACK = 26 := head_slack_val
  have hDS : DSTAR = 20 := dstar_val
  have hD : DSTAR = 20 := dstar_val
  -- the fresh case, shared by every k
  have fresh : ∀ (k t w w2 : Nat), t ≤ T → w < w2 → w2 < t →
      cnt P win (IsRet P y) w e0 = k → IsRet P y (run P win w e0) →
      cnt P win (IsRet P y) w2 e0 = k + 1 → IsRet P y (run P win w2 e0) →
      cnt P win (Hit y) t e0 ≤ k → k ≤ cnt P win (Hit y) (w + 1) e0 →
      (NpfAt y (run P win w2 e0) ∧ e0.now + t ≤ (run P win w2 e0).ts y + Rr w2 + PENDING_SLACK + B) ∨
      e0.now + t ≤ (run P win w e0).ts y + Z w + PENDING_SLACK + B := by
    intro k t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh hfresh
    have hm := cnt_mono P win (Hit y) e0 (w + 1) t (by omega)
    have hr1 : cnt P win (IsRet P y) (w + 1) e0 = k + 1 := by
      have := cnt_succ_back P win (IsRet P y) w e0
      rw [if_pos hwb] at this
      omega
    have ho := owed_run P win y (w + 1) e0 hS0
    cases hwant : (run P win (w + 1) e0).wantFetch y with
    | true =>
      right
      have hn := window_le P win y hy (run P win (w + 1) e0) B (t - (w + 1))
        (struct_run P win (w + 1) e0 hS0) hwant
        (fun m hm hm' => hB (w + 1) m (by omega) hm')
        (fun i hi => by
          rw [← run_add]
          exact no_event_between P win (Hit y) e0 (w + 1) t (w + 1 + i)
            (by omega) (by omega) (by omega))
      have hRw := hR w (by omega) hwb
      have hz := hZ0 w (by omega) hwb
      have hnow := now_run P win w e0
      omega
    | false =>
      left
      exact pb_defer_g P win y e0 B T Rr (w + 1) w2 t hy hS0 (hR w2 (by omega) hw2b) hB
        (by omega) hw2t htT (by omega) hwant hw2b (by omega) (by omega)
  intro k
  induction k with
  | zero =>
    intro t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh
    exact fresh 0 t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh (Nat.zero_le _)
  | succ k ih =>
    intro t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh
    by_cases hfresh : k + 1 ≤ cnt P win (Hit y) (w + 1) e0
    · exact fresh (k + 1) t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh hfresh
    · obtain ⟨w', hw'w, hw'k, hw'b⟩ := cnt_reach P win (IsRet P y) w e0 k (by omega)
      have hgap := ts_gap P win y e0 w' w (isWB_of_ret P y _ hw'b) hw'w
      have hzc := hZC w' w (by omega) ⟨hw'w, hw'b, hwb, by omega⟩
      have hz0 := hZ0 w (by omega) hwb
      have hzf : NpfAt y (run P win w e0) → Rr w + DSTAR + B ≤ Z w :=
        hZF w (by omega) hwb
      have hr1 : cnt P win (IsRet P y) (w + 1) e0 = k + 2 := by
        have := cnt_succ_back P win (IsRet P y) w e0
        rw [if_pos hwb] at this
        omega
      by_cases hlate : cnt P win (Hit y) t e0 ≤ k
      · right
        rcases ih t w' w htT hw'w (by omega) hw'k hw'b hwk hwb hlate with ⟨-, h⟩ | h
        · omega
        · omega
      · obtain ⟨c, hct, hck, hhit⟩ := cnt_reach P win (Hit y) t e0 k (by omega)
        have hc1 : cnt P win (Hit y) (c + 1) e0 = k + 1 := by
          have := cnt_succ_back P win (Hit y) c e0
          rw [if_pos hhit] at this
          omega
        have hwc : w + 1 ≤ c := by
          rcases Nat.lt_or_ge c (w + 1) with hlt | hge
          · have := cnt_mono P win (Hit y) e0 (c + 1) (w + 1) hlt
            omega
          · exact hge
        have hct1 := cnt_mono P win (Hit y) e0 (c + 1) t (by omega)
        have hrc := cnt_mono P win (IsRet P y) e0 (w + 1) (c + 1) (by omega)
        have ho := owed_run P win y (c + 1) e0 hS0
        have hic := ih c w' w (by omega) hw'w (by omega) hw'k hw'b hwk hwb (by omega)
        cases hwant : (run P win (c + 1) e0).wantFetch y with
        | true =>
          right
          have hscan : (run P win (c + 1) e0).pst = .scan := by
            rw [run_succ']
            exact hit_then_scan P win y (run P win c e0) hhit
          have hn := window_le_19 P win y hy (run P win (c + 1) e0) B (t - (c + 1))
            (struct_run P win (c + 1) e0 hS0) hwant (Or.inl hscan)
            (fun m hm hm' => hB (c + 1) m (by omega) hm')
            (fun i hi => by
              rw [← run_add]
              exact no_event_between P win (Hit y) e0 (c + 1) t (c + 1 + i)
                (by omega) (by omega) (by omega))
          rcases hic with ⟨hn', h⟩ | h
          · have := hzf hn'
            omega
          · omega
        | false =>
          have h1 : 1 ≤ (run P win (c + 1) e0).owed y := by omega
          obtain ⟨hv, hsp, -⟩ := npf_state _ y h1 hwant
          have hone := owed_one _ y hv hsp
          have hcw2 : c + 1 ≤ w2 := by
            rcases Nat.lt_or_ge w2 (c + 1) with hlt | hge
            · exfalso
              have h2 := cnt_succ_back P win (IsRet P y) w2 e0
              rw [if_pos hw2b] at h2
              have h3 := cnt_mono P win (IsRet P y) e0 (w2 + 1) (c + 1) hlt
              omega
            · exact hge
          have hrw2 := cnt_mono P win (IsRet P y) e0 (c + 1) w2 hcw2
          exact Or.inl (pb_defer_g P win y e0 B T Rr (c + 1) w2 t hy hS0
            (hR w2 (by omega) hw2b) hB hcw2 hw2t htT h1 hwant hw2b (by omega) (by omega))

/-- **Head valid, per-retirement gaps and lateness.** At `t ≤ T`, if the word released after
the latest retirement `x` has waited its allowance `L x` past its release, `y`'s head is
valid. Conditions: `Rr x + 26 + B ≤ gp x + L x` at a no-prefetch retirement;
`Z x + 26 + B ≤ gp x + gp x2 + L x2` for consecutive retirements; plus the certificate. -/
theorem head_late_gap (L : Nat → Nat) (hW : Wf e0) (hfull : ∀ s, e0.actv y s = true)
    (hy : P.live y = true)
    (hR : ∀ x, x < T → IsRet P y (run P win x e0) →
      (run P win x e0).now ≤ (run P win x e0).ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hZ0 : ∀ x, x < T → IsRet P y (run P win x e0) → Rr x ≤ Z x)
    (hZF : ∀ x, x < T → IsRet P y (run P win x e0) → NpfAt y (run P win x e0) →
      Rr x + DSTAR + B ≤ Z x)
    (hZC : ∀ x x2, x2 < T → Consec P win y e0 x x2 →
      Z x + DSTAR + B ≤ gp P win y e0 x + Z x2)
    (hHD : ∀ x, x < T → IsRet P y (run P win x e0) → NpfAt y (run P win x e0) →
      Rr x + HEAD_SLACK + B ≤ gp P win y e0 x + L x)
    (hHN : ∀ x x2, x2 < T → Consec P win y e0 x x2 →
      Z x + HEAD_SLACK + B ≤ gp P win y e0 x + gp P win y e0 x2 + L x2)
    (t : Nat) (htT : t ≤ T)
    (hlate : ∀ x, x < t → IsRet P y (run P win x e0) →
      cnt P win (IsRet P y) (x + 1) e0 = cnt P win (IsRet P y) t e0 →
      (run P win t e0).ts y + L x ≤ (run P win t e0).now) :
    (run P win t e0).headValid y = true := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hHS : HEAD_SLACK = 26 := head_slack_val
  have hDS : DSTAR = 20 := dstar_val
  have hS : Struct e0 := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have h0 := owed_full e0 y hfull
  apply head_valid_of_counts P win y t e0 hW hfull
  by_cases hc : cnt P win (IsRet P y) t e0 ≤ cnt P win (Hit y) t e0 + 1
  · exact hc
  · exfalso
    have hnow := now_run P win t e0
    obtain ⟨w, hwt, hwk, hwb⟩ :=
      cnt_reach P win (IsRet P y) t e0 (cnt P win (IsRet P y) t e0 - 2) (by omega)
    obtain ⟨w2, hw2t, hw2k, hw2b⟩ :=
      cnt_reach P win (IsRet P y) t e0 (cnt P win (IsRet P y) t e0 - 1) (by omega)
    have hww2 : w < w2 := by
      rcases Nat.lt_or_ge w w2 with hlt | hge
      · exact hlt
      · have := cnt_mono P win (IsRet P y) e0 w2 w hge
        omega
    have h3 : cnt P win (IsRet P y) (w2 + 1) e0 = cnt P win (IsRet P y) t e0 := by
      have := cnt_succ_back P win (IsRet P y) w2 e0
      rw [if_pos hw2b] at this
      omega
    have hl := hlate w2 hw2t hw2b h3
    have hs1 := ts_gap P win y e0 w w2 (isWB_of_ret P y _ hwb) hww2
    have hs2 := ts_gap P win y e0 w2 t (isWB_of_ret P y _ hw2b) hw2t
    rcases pending_bound_gap P win y e0 B T Rr Z hy hS h0 hR hB hZ0 hZF hZC
      (cnt P win (IsRet P y) t e0 - 2) t w w2 htT hww2 hw2t hwk hwb (by omega) hw2b
      (by omega) with ⟨hn, h⟩ | h
    · have := hHD w2 (by omega) hw2b hn
      omega
    · have := hHN w w2 (by omega) ⟨hww2, hwb, hw2b, by omega⟩
      omega

end

#print axioms pending_bound_gap
#print axioms head_late_gap

end JLane
