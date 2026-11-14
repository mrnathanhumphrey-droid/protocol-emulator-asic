import JLane.OptA
/-!
# Brick B — the pending bound under option A (branch brick, stage 2b)

`Run.pending_bound` assumed a lane wants a slot whenever it owes one. Under option A
(`want_fetch` l.2798–2801) a lane whose head is a no-prefetch word does not fetch its spare.
Here every place the old proof used "the lane wants" splits in two:

* it wants: the old port-wait bound;
* it does not: the head is a no-prefetch word (`npf_state`), held until it retires
  (`npf_hold`), after which the lane wants (`npf_unlock`) and the wait restarts there.

Refill `#k` (owed from retirement `#k` at `w`, with retirement `#(k+1)` at `w2`) still pending at
`t` then satisfies one of three bounds:

* **D (deferred)**: the word retired at `w2` was no-prefetch; `t ≤ ts(w2) + R + 25 + B`;
* **F (first after a deferral)**: the word retired at `w` was no-prefetch; the refill queued
  behind the head refill: `t ≤ ts(w) + R + 45 + 2B`;
* **N**: `t ≤ ts(w) + R + 25 + B + Y`, where `Y` is any slack with `40 + 2B ≤ Wn + Y`
  (`Wn` = the least delay a no-prefetch retirement adds).

The corollary `head_valid_optA`: a ready lane has a valid head when
`R + 26 + B ≤ Wn` (D), `R + 46 + 2B ≤ Wn + d` (F) and `R + 26 + B + Y ≤ 2d` (N), with
`D* + B ≤ d`. No `NoNpf` hypothesis anywhere: other lanes may hold no-prefetch words too.
-/
namespace JLane

/-- The head of `y` is a no-prefetch word. -/
def NpfAt (y : Lane) (e : Engine) : Prop := e.npf y (e.sel y) = true

theorem ret_form (P : Program) (y : Lane) (e : Engine) (h : IsRet P y e) :
    e.st = .wb ∧ y = e.cur ∧ P.ret e.now e.cur = true :=
  ⟨h.1, h.2.1.symm, by rw [h.2.1]; exact h.2.2⟩

theorem not_ret_form (P : Program) (y : Lane) (e : Engine) (h : ¬IsRet P y e) :
    ¬(e.st = .wb ∧ y = e.cur ∧ P.ret e.now e.cur = true) := by
  rintro ⟨h1, h2, h3⟩
  rw [← h2] at h3
  exact h ⟨h1, h2.symm, h3⟩

/-- A valid head over an empty spare is one owed slot. -/
theorem owed_one (e : Engine) (y : Lane) (hv : e.headValid y = true)
    (hs : e.spareValid y = false) : e.owed y = 1 := by
  unfold Engine.headValid at hv
  unfold Engine.spareValid at hs
  unfold Engine.owed
  cases hsel : e.sel y <;> rw [hsel] at hv hs <;> simp_all

section
variable (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (R B T : Nat)

/-- **The deferred case.** From a cycle `s` where `y` owes but does not want, with no hit
until `t` and no retirement until `w2`: the word retiring at `w2` is no-prefetch, and `t` is
within one port wait of that retirement. -/
theorem pb_defer (s w2 t : Nat) (hy : P.live y = true) (hS0 : Struct e0)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hs : s ≤ w2) (hw2t : w2 < t) (htT : t ≤ T)
    (ho : 1 ≤ (run P win s e0).owed y) (hw : (run P win s e0).wantFetch y = false)
    (hr2 : IsRet P y (run P win w2 e0))
    (hnr : cnt P win (IsRet P y) s e0 = cnt P win (IsRet P y) w2 e0)
    (hnh : cnt P win (Hit y) s e0 = cnt P win (Hit y) t e0) :
    NpfAt y (run P win w2 e0) ∧ e0.now + t ≤ (run P win w2 e0).ts y + R + 25 + B := by
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
  have hRw := hR w2 (by omega) (isWB_of_ret P y _ hr2)
  have hnow := now_run P win w2 e0
  omega

/-- **Fresh case.** Every earlier refill was served by `w + 1`: either the lane wants there
(the old bound, against `ts(w)`) or the refill is deferred to retirement `w2` (bound D). -/
theorem pb_fresh_optA (k t w w2 : Nat) (hy : P.live y = true) (hS0 : Struct e0)
    (h0 : e0.owed y = 0)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (htT : t ≤ T) (hww2 : w < w2) (hw2t : w2 < t)
    (hwk : cnt P win (IsRet P y) w e0 = k) (hwb : IsRet P y (run P win w e0))
    (hw2k : cnt P win (IsRet P y) w2 e0 = k + 1) (hw2b : IsRet P y (run P win w2 e0))
    (hh : cnt P win (Hit y) t e0 ≤ k) (hfresh : k ≤ cnt P win (Hit y) (w + 1) e0) :
    (NpfAt y (run P win w2 e0) ∧ e0.now + t ≤ (run P win w2 e0).ts y + R + 25 + B) ∨
      e0.now + t ≤ (run P win w e0).ts y + R + 25 + B := by
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
    have hRw := hR w (by omega) (isWB_of_ret P y _ hwb)
    have hnow := now_run P win w e0
    omega
  | false =>
    left
    exact pb_defer P win y e0 R B T (w + 1) w2 t hy hS0 hR hB (by omega) hw2t htT
      (by omega) hwant hw2b (by omega) (by omega)

/-- **The pending bound under option A.** Refill `#k` of lane `y`, owed from retirement `#k` at
`w`, still pending at `t` after retirement `#(k+1)` at `w2`, meets bound D, F or N. -/
theorem pending_bound_optA (d Wn Y : Nat) (hy : P.live y = true) (hS0 : Struct e0)
    (h0 : e0.owed y = 0) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hY : 40 + 2 * B ≤ Wn + Y)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hWn : ∀ x, x < T → IsRet P y (run P win x e0) → NpfAt y (run P win x e0) →
      (run P win x e0).ts y + Wn ≤ (run P win (x + 1) e0).ts y) :
    ∀ (k t w w2 : Nat), t ≤ T → w < w2 → w2 < t →
      cnt P win (IsRet P y) w e0 = k → IsRet P y (run P win w e0) →
      cnt P win (IsRet P y) w2 e0 = k + 1 → IsRet P y (run P win w2 e0) →
      cnt P win (Hit y) t e0 ≤ k →
      (NpfAt y (run P win w2 e0) ∧ e0.now + t ≤ (run P win w2 e0).ts y + R + 25 + B) ∨
      (NpfAt y (run P win w e0) ∧ e0.now + t ≤ (run P win w e0).ts y + R + 45 + 2 * B) ∨
      e0.now + t ≤ (run P win w e0).ts y + R + 25 + B + Y := by
  have hD : DSTAR = 20 := dstar_val
  intro k
  induction k with
  | zero =>
    intro t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh
    rcases pb_fresh_optA P win y e0 R B T 0 t w w2 hy hS0 h0 hR hB htT hww2 hw2t hwk hwb
      hw2k hw2b hh (Nat.zero_le _) with h | h
    · exact Or.inl h
    · exact Or.inr (Or.inr (by omega))
  | succ k ih =>
    intro t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh
    by_cases hfresh : k + 1 ≤ cnt P win (Hit y) (w + 1) e0
    · rcases pb_fresh_optA P win y e0 R B T (k + 1) t w w2 hy hS0 h0 hR hB htT hww2 hw2t hwk
        hwb hw2k hw2b hh hfresh with h | h
      · exact Or.inl h
      · exact Or.inr (Or.inr (by omega))
    · -- retirement #k at w' < w
      obtain ⟨w', hw'w, hw'k, hw'b⟩ := cnt_reach P win (IsRet P y) w e0 k (by omega)
      have hsp := ts_ge_after_wb P win y e0 w' w hw'w (isWB_of_ret P y _ hw'b)
      have hWw : NpfAt y (run P win w' e0) → (run P win w' e0).ts y + Wn ≤ (run P win w e0).ts y :=
        fun hn => by
          have h1 := hWn w' (by omega) hw'b hn
          have h2 := ts_mono P win y e0 (w' + 1) w (by omega)
          omega
      have hr1 : cnt P win (IsRet P y) (w + 1) e0 = k + 2 := by
        have := cnt_succ_back P win (IsRet P y) w e0
        rw [if_pos hwb] at this
        omega
      by_cases hlate : cnt P win (Hit y) t e0 ≤ k
      · -- refill #k is itself still pending at t
        right; right
        rcases ih t w' w htT hw'w (by omega) hw'k hw'b hwk hwb hlate with ⟨-, h⟩ | ⟨hn, h⟩ | h
        · omega
        · have := hWw hn
          omega
        · omega
      · -- refill #k landed at c, after w; at c + 1 the lane owes refill #(k+1)
        obtain ⟨c, hct, hck, hhit⟩ := cnt_reach P win (Hit y) t e0 k (by omega)
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
          rcases hic with ⟨hn, h⟩ | ⟨hn, h⟩ | h
          · exact Or.inr (Or.inl ⟨hn, by omega⟩)
          · right; right
            have := hWw hn
            omega
          · right; right
            omega
        | false =>
          -- not wanting: the head is valid over an empty spare, so one slot is owed
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
          exact Or.inl (pb_defer P win y e0 R B T (c + 1) w2 t hy hS0 hR hB hcw2 hw2t htT h1
            hwant hw2b (by omega) (by omega))

/-- **Head valid when ready, under option A.** Three conditions, one per bound:
D `R + 26 + B ≤ Wn`, F `R + 46 + 2B ≤ Wn + d`, N `R + 26 + B + Y ≤ 2d`, with `D* + B ≤ d`
and `40 + 2B ≤ Wn + Y`. -/
theorem head_valid_optA (d Wn Y : Nat) (hW : Wf e0)
    (hfull : ∀ s, e0.actv y s = true)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hY : 40 + 2 * B ≤ Wn + Y)
    (hDc : R + 26 + B ≤ Wn) (hFc : R + 46 + 2 * B ≤ Wn + d) (hNc : R + 26 + B + Y ≤ 2 * d)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hWn : ∀ x, x < T → IsRet P y (run P win x e0) → NpfAt y (run P win x e0) →
      (run P win x e0).ts y + Wn ≤ (run P win (x + 1) e0).ts y)
    (t : Nat) (htT : t ≤ T)
    (hrdy : (run P win t e0).ts y ≤ (run P win t e0).now) :
    (run P win t e0).headValid y = true := by
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
    have hs1 := ts_ge_after_wb P win y e0 w w2 hww2 (isWB_of_ret P y _ hwb)
    have hs2 := ts_ge_after_wb P win y e0 w2 t hw2t (isWB_of_ret P y _ hw2b)
    rcases pending_bound_optA P win y e0 R B T d Wn Y hy hS h0 hdly hd hY hR hB hWn
      (cnt P win (IsRet P y) t e0 - 2) t w w2 htT hww2 hw2t hwk hwb (by omega) hw2b
      (by omega) with ⟨hn, h⟩ | ⟨hn, h⟩ | h
    · -- D: the no-prefetch word retired at w2 pushed the release by Wn
      have h1 := hWn w2 (by omega) hw2b hn
      have h2 := ts_mono P win y e0 (w2 + 1) t (by omega)
      omega
    · -- F: the no-prefetch word retired at w, then a normal one at w2
      have h1 := hWn w (by omega) hwb hn
      have h2 := ts_mono P win y e0 (w + 1) w2 (by omega)
      omega
    · omega

end

#print axioms pending_bound_optA
#print axioms head_valid_optA

end JLane
