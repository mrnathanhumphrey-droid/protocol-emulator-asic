import JLane.SelfTimed
/-!
# Brick U — the USB lane under re-anchor (Wilson 11-12, option (i))

The re-anchor (`l_timestamp[USB_LANE] <= rean_ts`, `rean_ts = now + d/2`) can bring the USB
lane's next release as close as `reanFloor d = 3 + ⌊d/2⌋` after the last one (23 at d = 40),
not `d`. So inside one Lemma-A window the USB lane may be decided **twice**, and the response
bound becomes `R_USB = 3k + 2 = 17` instead of 14.

**The named hardware hypothesis.** The V4b model has no re-anchor. The USB lane is modelled by
its floor: a lane whose every writeback advances its release by at least `P.dly u`, with
`reanFloor dbit ≤ P.dly u` (`ReanFloorModel`). That the RTL's USB lane obeys this floor is
**measured, not proved**: `test/run_rean_floor.py` (exact on the RTL at d = 40 and d = 48, the
guard seen dropping early edges; Wilson 11-12, floor ruling).

What the theorem then needs, and which gate checks it:
* USB lane, per dispatch: `NOWB_MIN = 20 ≤ dly u` (clock row 1: 23 ≥ 20 at d = 40);
* USB lane, per retirement: releases of consecutive retirements `DSTAR_RETIRE_USB = 42` apart
  (`RetSpaced`). Byte to byte this is 8 · 23 ≥ 42, but **not** for every pair: a byte
  followed by a LEVEL is spaced by its last bit alone (23–40 at d = 40), REARM → ARM by the
  REARM's delay. Wilson 11-13: the condition is **per pair**, derived in `StRetire.lean`
  (`retSpaced_of_pairs`, `dstar_usb_pairs`) and checked on the image by
  `proof_constants.retire_pairs`;
* every other live lane: `dly ≥ DSTAR_RETIRE_USB = 42` (the compiler and the image gate:
  `proof_constants.usb_coresident_problems`).
-/
namespace JLane

/-! ### Two decisions of a lane are a dispatch apart -/

theorem dec_sep (P : Program) (win : Engine → Option Lane) (e : Engine) (z : Lane)
    (a b : Nat) (hab : a < b) (ha : Dec win z (run P win a e))
    (hb : Dec win z (run P win b e)) : a + 3 ≤ b := by
  obtain ⟨hbi, -, -⟩ := hb
  have hst1 : (run P win (a + 1) e).st = .drive := by
    rw [run_succ']
    exact (step_of_dec P win _ z ha).1
  have hst2 : (run P win (a + 2) e).st = .wb := by
    obtain ⟨h, -⟩ := dec_wb P win e a z ha
    exact h
  rcases Nat.lt_or_ge b (a + 3) with hlt | hge
  · exfalso
    have : b = a + 1 ∨ b = a + 2 := by omega
    rcases this with rfl | rfl
    · rw [hst1] at hbi
      cases hbi
    · rw [hst2] at hbi
      cases hbi
  · exact hge

/-! ### Lemma A, one lane decided up to twice -/

/-- Per-lane decision budget in a window: none for the waiting lane `i`, two for the USB lane
`u`, one for every other lane. -/
def bnd (i u z : Lane) : Nat := if z = i then 0 else if z = u then 2 else 1

theorem bnd_sum (i u : Lane) :
    bnd i u L0 + bnd i u L1 + bnd i u L2 + bnd i u L3 + bnd i u L4 ≤ K := by
  rcases lane_cases i with rfl | rfl | rfl | rfl | rfl <;>
    rcases lane_cases u with rfl | rfl | rfl | rfl | rfl <;> decide

theorem pigeon_usb (P : Program) (win : Engine → Option Lane) (i u : Lane) (n : Nat)
    (e : Engine) (h : ∀ z, cnt P win (Dec win z) n e ≤ bnd i u z) :
    cnt P win (fun e => decOther win i e = true) n e ≤ K := by
  have hs := cnt_decAny_split P win n e
  have ho := cnt_decOther_split P win i n e
  have a0 := h L0
  have a1 := h L1
  have a2 := h L2
  have a3 := h L3
  have a4 := h L4
  have hb := bnd_sum i u
  omega

/-- **Lemma A, USB form.** If the USB lane is decided at most twice and every other lane at
most once while lane `i` waits, the wait is at most `3k + 2 = R_USB = 17` cycles. -/
theorem lemmaA_usb (P : Program) (win : Engine → Option Lane) (i u : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) (t : Nat) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e))
    (hns : ∀ s, s < t → NoStall win (run P win s e))
    (hu : cnt P win (Dec win u) t e ≤ 2)
    (h1 : ∀ z, z ≠ i → z ≠ u → cnt P win (Dec win z) t e ≤ 1) :
    t ≤ R_USB := by
  have h0 := cnt_zero_of P win (Dec win i) t e hnd
  have hp := pigeon_usb P win i u t e (fun z => by
    unfold bnd
    by_cases hzi : z = i
    · rw [if_pos hzi, hzi]
      omega
    · rw [if_neg hzi]
      by_cases hzu : z = u
      · rw [if_pos hzu, hzu]
        exact hu
      · rw [if_neg hzu]
        exact h1 z hzi hzu)
  have hA := lemmaA P win i hws t e hr hm hnd hns
  have hK : K = 5 := rfl
  have hR : R_USB = 17 := rfl
  omega

/-! ### The response bound, R = 17 -/

/-- **The response bound with a re-anchoring lane.** On a stall-free prefix where the USB lane
`u` has per-dispatch spacing `≥ NOWB_MIN` and every other live lane `≥ DSTAR_RETIRE_USB`,
every writeback is within `R_USB + 2` of its release. -/
theorem wb_bound_usb (P : Program) (win : Engine → Option Lane) (e0 : Engine) (T : Nat)
    (u : Lane)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hdu : NOWB_MIN ≤ P.dly u)
    (hd : ∀ l, P.live l = true → l ≠ u → DSTAR_RETIRE_USB ≤ P.dly l)
    (hNS : ∀ t, t < T → NoStall win (run P win t e0)) :
    ∀ t, t < T → ∀ y, P.live y = true → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R_USB + 2 := by
  have hRv : R_USB = 17 := rfl
  have hNv : NOWB_MIN = 20 := rfl
  have hXv : DSTAR_RETIRE_USB = 42 := rfl
  have hd20 : ∀ l, P.live l = true → 20 ≤ P.dly l := fun l hl => by
    by_cases h : l = u
    · rw [h]
      omega
    · have := hd l hl h
      omega
  have key : ∀ n, ∀ t, t < n → t < T → ∀ y, P.live y = true →
      IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + 17 + 2 := by
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
        by_cases hK : (run P win D e0).now ≤ (run P win D e0).ts y + 17
        · omega
        · exfalso
          have hrel := ts_mono P win y e0 0 D (Nat.zero_le D)
          have h00 : (run P win 0 e0).ts y = e0.ts y := rfl
          have h0y := h0ts y
          have hnD := now_run P win D e0
          obtain ⟨c, rfl⟩ : ∃ c, D = c + 18 := ⟨D - 18, by omega⟩
          have hnow_c := now_run P win c e0
          -- y has no writeback in the window: an earlier one would need `d < NOWB_MIN`
          have noWB : ∀ w, c ≤ w → w < c + 18 → ¬IsWB y (run P win w e0) := by
            intro w hcw hwD hw
            have hIH := ih w (by omega) (by omega) y hy hw
            have hA := ts_after_wb P win y e0 w hw
            have hM := ts_mono P win y e0 (w + 1) (c + 18) (by omega)
            have hnw := now_run P win w e0
            have hdy := hd20 y hy
            omega
          -- y is ready at the window start
          have hrdy : Ready P y (run P win c e0) := by
            refine ⟨hy, ?_⟩
            have := ts_mono P win y e0 c (c + 18) (by omega)
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
          have hnd : ∀ s, s < 18 → ¬Dec win y (run P win s (run P win c e0)) := by
            intro s hs hds
            rw [← run_add] at hds
            have hw2 := dec_wb P win e0 (c + s) y hds
            rcases Nat.lt_or_ge (c + s + 2) (c + 18) with hlt | hge
            · exact noWB (c + s + 2) (by omega) hlt hw2
            · have hidle : (run P win (c + 18) e0).st = .idle := by
                obtain ⟨h1, -, -⟩ := hdec
                exact h1
              have hst1 : (run P win (c + s + 1) e0).st = .drive := by
                rw [run_succ']
                exact (step_of_dec P win _ y hds).1
              have hst2 : (run P win (c + s + 2) e0).st = .wb := by
                obtain ⟨h, -⟩ := hw2
                exact h
              have : c + 18 = c + s + 1 ∨ c + 18 = c + s + 2 := by omega
              rcases this with h | h
              · rw [h, hst1] at hidle
                cases hidle
              · rw [h, hst2] at hidle
                cases hidle
          -- no stalls inside the window
          have hns : ∀ s, s < 18 → NoStall win (run P win s (run P win c e0)) := by
            intro s hs
            rw [← run_add]
            exact hNS (c + s) (by omega)
          -- a decision of z at c + a inside the window was within 17 of its release
          have hlate : ∀ z a, a < 18 → Dec win z (run P win (c + a) e0) →
              P.live z = true ∧
              (run P win (c + a) e0).now ≤ (run P win (c + a) e0).ts z + 17 := by
            intro z a ha hda
            have hw0 := dec_wb P win e0 (c + a) z hda
            have hlz : P.live z = true := by
              obtain ⟨-, h, -⟩ := hda
              exact (hwin _ z h).1
            have hIH := ih (c + a + 2) (by omega) (by omega) z hlz hw0
            obtain ⟨hts0, hnow0⟩ := dec_ts P win e0 (c + a) z hda
            exact ⟨hlz, by omega⟩
          -- the k-th decision of z inside the window, as a cycle of the run
          have hreach : ∀ z k, k < cnt P win (Dec win z) 18 (run P win c e0) →
              ∃ a, a < 18 ∧ cnt P win (Dec win z) a (run P win c e0) = k ∧
                Dec win z (run P win (c + a) e0) := by
            intro z k hk
            obtain ⟨a, ha, hc, hda⟩ := cnt_reach P win (Dec win z) 18 (run P win c e0) k hk
            rw [← run_add] at hda
            exact ⟨a, ha, hc, hda⟩
          have hord : ∀ z a b k, cnt P win (Dec win z) a (run P win c e0) = k →
              cnt P win (Dec win z) b (run P win c e0) = k + 1 → a < b := by
            intro z a b k ha hb
            rcases Nat.lt_or_ge a b with h | h
            · exact h
            · have := cnt_mono P win (Dec win z) (run P win c e0) b a h
              omega
          -- every lane other than u is decided at most once inside the window
          have h1 : ∀ z, z ≠ y → z ≠ u → cnt P win (Dec win z) 18 (run P win c e0) ≤ 1 := by
            intro z _ hzu
            rcases Nat.lt_or_ge (cnt P win (Dec win z) 18 (run P win c e0)) 2 with hlt | hge
            · omega
            · exfalso
              obtain ⟨t0, ht0, hc0, hd0⟩ := hreach z 0 (by omega)
              obtain ⟨t1, ht1, hc1, hd1⟩ := hreach z 1 (by omega)
              have h01 := hord z t0 t1 0 hc0 hc1
              obtain ⟨hlz, hl0⟩ := hlate z t0 ht0 hd0
              have hgap := dec_gap_time P win e0 z hwin (c + t0) (c + t1) 17 (by omega)
                hd0 hd1 hl0
              have hdz := hd z hlz hzu
              omega
          -- the USB lane is decided at most twice: a third decision is two releases later
          have hu : cnt P win (Dec win u) 18 (run P win c e0) ≤ 2 := by
            rcases Nat.lt_or_ge (cnt P win (Dec win u) 18 (run P win c e0)) 3 with hlt | hge
            · omega
            · exfalso
              obtain ⟨t0, ht0, hc0, hd0⟩ := hreach u 0 (by omega)
              obtain ⟨t1, ht1, hc1, hd1⟩ := hreach u 1 (by omega)
              obtain ⟨t2, ht2, hc2, hd2⟩ := hreach u 2 (by omega)
              have h01 := hord u t0 t1 0 hc0 hc1
              have h12 := hord u t1 t2 1 hc1 hc2
              obtain ⟨hlu, hl0⟩ := hlate u t0 ht0 hd0
              have hsep := dec_sep P win e0 u (c + t0) (c + t1) (by omega) hd0 hd1
              have hw0 := dec_wb P win e0 (c + t0) u hd0
              obtain ⟨hts0, -⟩ := dec_ts P win e0 (c + t0) u hd0
              have hs1 := ts_ge_after_wb P win u e0 (c + t0 + 2) (c + t1) (by omega) hw0
              have hs2 := dec_gap P win e0 u hwin (c + t1) (c + t2) (by omega) hd1 hd2
              have hn0 := now_run P win (c + t0) e0
              have hn2 := now_run P win (c + t2) e0
              have hdu' := hd20 u hlu
              omega
          -- Lemma A: an 18-cycle wait is impossible
          have hA := lemmaA_usb P win y u (hws y) 18 (run P win c e0) hrdy hmid hnd hns hu h1
          omega
  intro t ht y hy hwb
  have := key (t + 1) t (Nat.lt_succ_self t) ht y hy hwb
  omega

/-! ### Retirement spacing -/

/-- Lane `y`'s retirements release at least `D` apart. -/
def RetSpaced (P : Program) (win : Engine → Option Lane) (e0 : Engine) (y : Lane) (D : Nat) :
    Prop :=
  ∀ a b, a < b → IsRet P y (run P win a e0) → IsRet P y (run P win b e0) →
    (run P win a e0).ts y + D ≤ (run P win b e0).ts y

/-- A lane whose every writeback advances it by `≥ D` has its retirements `D` apart. -/
theorem retSpaced_of_dly (P : Program) (win : Engine → Option Lane) (e0 : Engine) (y : Lane)
    (D : Nat) (h : D ≤ P.dly y) : RetSpaced P win e0 y D := by
  intro a b hab ha _
  have := ts_ge_after_wb P win y e0 a b hab (isWB_of_ret P y _ ha)
  omega

/-- **The byte form** (clock row 2). If at least `k` writebacks of `y` separate consecutive
retirements, from the earlier one on, and `D ≤ k · dly`, retirements are `D` apart. For the USB
receive a byte is 8 bit writebacks: `8 · reanFloor 40 = 184 ≥ 42`. -/
theorem retSpaced_of_wbs (P : Program) (win : Engine → Option Lane) (e0 : Engine) (y : Lane)
    (D k : Nat) (hk : D ≤ P.dly y * k)
    (hw : ∀ a b, a < b → IsRet P y (run P win a e0) → IsRet P y (run P win b e0) →
      k ≤ cnt P win (IsWB y) b e0 - cnt P win (IsWB y) a e0) :
    RetSpaced P win e0 y D := by
  intro a b hab ha hb
  have hsp := ts_spacing P win y e0 a (b - a)
  have hba : a + (b - a) = b := by omega
  rw [hba] at hsp
  have hm := Nat.mul_le_mul_left (P.dly y) (hw a b hab ha hb)
  omega

/-- `head_valid_when_ready` with the latency condition carried by the retirement spacing
instead of `2d`: with retirements `Dr` apart and `R + 25 + B < Dr + d`, the head is valid
whenever the lane is ready. -/
theorem head_valid_ret (P : Program) (win : Engine → Option Lane) (y : Lane)
    (e0 : Engine) (d R B T Dr : Nat) (hW : Wf e0)
    (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hnp : ∀ t, (run P win t e0).NoNpf)
    (hret : RetSpaced P win e0 y Dr) (hlat : R + 25 + B < Dr + d)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (t : Nat) (htT : t ≤ T)
    (hrdy : (run P win t e0).ts y ≤ (run P win t e0).now) :
    (run P win t e0).headValid y = true := by
  apply head_valid_of_counts P win y t e0 hW (fun s => hfull y s hy)
  by_cases hc : cnt P win (IsRet P y) t e0 ≤ cnt P win (Hit y) t e0 + 1
  · exact hc
  · exfalso
    have hnow := now_run P win t e0
    obtain ⟨w, hwt, hwk, hwb⟩ :=
      cnt_reach P win (IsRet P y) t e0 (cnt P win (IsRet P y) t e0 - 2) (by omega)
    have hpb := pending_bound P win y e0 d R B T hW hfull hy hdly hd hnp hR hB
      (cnt P win (IsRet P y) t e0 - 2) t w htT hwt hwk hwb (by omega)
    obtain ⟨w2, hw2t, hw2k, hw2b⟩ :=
      cnt_reach P win (IsRet P y) t e0 (cnt P win (IsRet P y) t e0 - 1) (by omega)
    have hww2 : w < w2 := by
      rcases Nat.lt_or_ge w w2 with hlt | hge
      · exact hlt
      · have := cnt_mono P win (IsRet P y) e0 w2 w hge
        omega
    have hs1 := hret w w2 hww2 hwb hw2b
    have hs2 := ts_ge_after_wb P win y e0 w2 t hw2t (isWB_of_ret P y _ hw2b)
    omega

/-! ### No stall, no branch-1, with the USB lane re-anchoring -/

/-- **D\* with a re-anchoring USB lane (Wilson 11-12, option (i)), no external hypotheses on
the scheduler.** From a primed start, any work-conserving scheduler that picks a ready lane
never stalls and never issues a branch-1 refill, when
* the USB lane `u` has per-dispatch spacing `≥ NOWB_MIN` (20) and its retirements release
  `≥ DSTAR_RETIRE_USB` (42) apart, and
* every other live lane has `dly ≥ DSTAR_RETIRE_USB` (42). -/
theorem dstar_usb (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane)
    (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hfn : ∀ e, P.fnpf e = false) (hn0 : e0.NoNpf)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hdu : NOWB_MIN ≤ P.dly u)
    (hretu : RetSpaced P win e0 u DSTAR_RETIRE_USB)
    (hd : ∀ l, P.live l = true → l ≠ u → DSTAR_RETIRE_USB ≤ P.dly l) :
    ∀ T, NoStall win (run P win T e0) ∧ NoBr1 P (run P win T e0) := by
  have hS : Struct e0 := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have hRv : R_USB = 17 := rfl
  have hNv : NOWB_MIN = 20 := rfl
  have hXv : DSTAR_RETIRE_USB = 42 := rfl
  have hD : DSTAR = 20 := dstar_val
  have hd20 : ∀ l, P.live l = true → 20 ≤ P.dly l := fun l hl => by
    by_cases h : l = u
    · rw [h]
      omega
    · have := hd l hl h
      omega
  have hret : ∀ l, P.live l = true → RetSpaced P win e0 l DSTAR_RETIRE_USB := fun l hl => by
    by_cases h : l = u
    · rw [h]
      exact hretu
    · exact retSpaced_of_dly P win e0 l _ (hd l hl h)
  -- the response bound, R = 17, from a stall-free prefix
  have hRof : ∀ n, (∀ t, t < n → NoStall win (run P win t e0)) →
      ∀ y, P.live y = true → ∀ t, t < n → IsWB y (run P win t e0) →
        (run P win t e0).now ≤ (run P win t e0).ts y + R_USB + 2 :=
    fun n hn y hy t ht hwb => wb_bound_usb P win e0 n u h0 h0ts hwin hws hdu hd hn t ht y hy hwb
  -- the zero budget, from a branch-1-free prefix
  have hBof : ∀ n, (∀ t, t < n → NoBr1 P (run P win t e0)) →
      ∀ y a m, a + m ≤ n → m ≤ 23 + 0 → chargeSum P win y m (run P win a e0) ≤ 0 := by
    intro n hn y a m ham _
    have := chargeSum_zero P win y m (run P win a e0) (fun i hi => by
      rw [← run_add]
      exact hn (a + i) (by omega))
    omega
  -- valid heads whenever ready, up to a clean horizon
  have hHV : ∀ n, (∀ t, t < n → NoStall win (run P win t e0) ∧ NoBr1 P (run P win t e0)) →
      ∀ y, P.live y = true → (run P win n e0).ts y ≤ (run P win n e0).now →
        (run P win n e0).headValid y = true := by
    intro n hn y hy hrdy
    have hdy := hd20 y hy
    exact head_valid_ret P win y e0 (P.dly y) R_USB 0 n DSTAR_RETIRE_USB hW hfull hy rfl
      (by omega) (fun t => nonpf_run P win hfn t e0 hn0) (hret y hy) (by omega)
      (fun t ht hwb => hRof n (fun t ht => (hn t ht).1) y hy t ht hwb)
      (fun a m ham hm => hBof n (fun t ht => (hn t ht).2) y a m ham hm)
      n (Nat.le_refl n) hrdy
  have key : ∀ n, ∀ t, t < n →
      NoStall win (run P win t e0) ∧ NoBr1 P (run P win t e0) := by
    intro n
    induction n with
    | zero =>
      intro t ht
      exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn
      · have hteq : t = n := by omega
        rw [hteq]
        constructor
        · -- no stall at n
          unfold NoStall
          intro _hidle w hw
          obtain ⟨hlive, hrdy⟩ := hwin _ w hw
          exact hHV n ih w hlive hrdy
        · -- no branch-1 issue at n
          unfold NoBr1
          intro _hscan
          cases hb : br1 P (run P win n e0) with
          | none => rfl
          | some w =>
            exfalso
            obtain ⟨hlive, hinv⟩ := br1_spec P _ w hb
            cases n with
            | zero =>
              have hv : (run P win 0 e0).headValid w = true := hfull w _ hlive
              rw [hv] at hinv
              cases hinv
            | succ m =>
              have hwq : win (run P win m e0) = some w := by
                have := br1_winq P _ w hb
                rw [run_succ'] at this
                exact this
              have hrdy := (hwin _ w hwq).2
              have hvalid := hHV m (fun t ht => ih t (by omega)) w hlive hrdy
              have hinv' : (step P win (run P win m e0)).headValid w = false := by
                rw [← run_succ']
                exact hinv
              -- w retired at m, and now owes both slots
              have hwb := head_drop_wb P win (run P win m e0) w hvalid hinv'
              have hH : HeadFirst (run P win (m + 1) e0) := by
                have hw := wf_run P win (m + 1) e0 hW
                unfold Wf at hw
                exact hw.2.1
              have h2 := owed_two_of_head _ w hH hinv
              have hown := owed_run P win w (m + 1) e0 hS
              have h0w := owed_full e0 w (fun s => hfull w s hlive)
              have hcb := cnt_succ_back P win (IsRet P w) m e0
              rw [if_pos hwb] at hcb
              have hJ : 1 ≤ cnt P win (IsRet P w) m e0 := by omega
              have hdw := hd20 w hlive
              -- the previous retirement, at w' < m: its refill is still pending at m + 1
              obtain ⟨w', hw'm, hw'k, hw'b⟩ :=
                cnt_reach P win (IsRet P w) m e0 (cnt P win (IsRet P w) m e0 - 1) (by omega)
              have hpb := pending_bound P win w e0 (P.dly w) R_USB 0 (m + 1) hW hfull hlive rfl
                (by omega) (fun t => nonpf_run P win hfn t e0 hn0)
                (fun t ht hwb' => hRof (m + 1) (fun t ht => (ih t ht).1) w hlive t ht hwb')
                (fun a k hak hk => hBof (m + 1) (fun t ht => (ih t ht).2) w a k hak hk)
                (cnt P win (IsRet P w) m e0 - 1) (m + 1) w' (Nat.le_refl _) (by omega) hw'k hw'b
                (by omega)
              -- ... yet w was ready at m, a retirement DSTAR_RETIRE_USB after w'
              have hsp := hret w hlive w' m hw'm hw'b hwb
              have hnow := now_run P win m e0
              omega
  intro T
  exact key (T + 1) T (Nat.lt_succ_self T)

/-! ### The named hardware hypothesis -/

/-- **The re-anchor floor, as the model sees it (named hardware hypothesis).** The USB lane's
every writeback advances its release by at least the floor `reanFloor dbit` at bit period
`dbit`. The V4b model has no re-anchor: this hypothesis is what stands in for it. Evidence:
`test/run_rean_floor.py` (measured on the RTL, exact at d = 40 and d = 48; the floor derived
from `rean_cap`'s guard `tf_diff(now_n, l_timestamp)` and the target `now + d/2`). -/
def ReanFloorModel (P : Program) (u : Lane) (dbit : Nat) : Prop := reanFloor dbit ≤ P.dly u

/-- Clock row 1 at the USB low-speed bit (d = 40): the floor clears `NOWB_MIN`. -/
theorem rean_row1_40 : NOWB_MIN ≤ reanFloor 40 := by decide

/-- **D\* under the re-anchor floor.** `dstar_usb` with the USB lane's per-dispatch condition
taken from the named hypothesis and clock row 1. -/
theorem dstar_usb_rean (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane)
    (dbit : Nat)
    (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hfn : ∀ e, P.fnpf e = false) (hn0 : e0.NoNpf)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hfl : ReanFloorModel P u dbit) (hrow1 : NOWB_MIN ≤ reanFloor dbit)
    (hretu : RetSpaced P win e0 u DSTAR_RETIRE_USB)
    (hd : ∀ l, P.live l = true → l ≠ u → DSTAR_RETIRE_USB ≤ P.dly l) :
    ∀ T, NoStall win (run P win T e0) ∧ NoBr1 P (run P win T e0) :=
  dstar_usb P win e0 u hW hfull hfn hn0 h0 h0ts hwin hws (Nat.le_trans hrow1 hfl) hretu hd

/-! ### The v2 engine with self-timed bytes -/

/-- **D\* for the v2 engine with self-timed bytes and a re-anchoring USB lane.** As
`dstar39_st` (every fragment program stream, every last-bit and stuff-slot pattern, every
work-conserving scheduler that picks a ready lane), with the USB lane `u` modelled by its
re-anchor floor (`ReanFloorModel`, measured by `run_rean_floor`), clock row 1, the USB lane's
retirements `DSTAR_RETIRE_USB` apart along the run (clock row 2), and every other live lane at
`dly ≥ DSTAR_RETIRE_USB` (the image check). -/
theorem dstar_usb_st (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) (u : Lane) (dbit : Nat)
    (hx0 : StFrag dly x0) (hf : ∀ y, StFragW dly y.e.pl (fw y))
    (hW : Wf x0.e) (hfull : ∀ l s, P2.live l = true → x0.e.actv l s = true)
    (h0 : x0.e.st = .idle) (h0ts : ∀ l, x0.e.now ≤ x0.e.ts l)
    (hsw : ∀ x w, sched x = some w → P2.live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (P2.toP dly) y x.e → sched x ≠ none)
    (hfl : reanFloor dbit ≤ dly u) (hrow1 : NOWB_MIN ≤ reanFloor dbit)
    (hretu : RetSpaced (stP P2 dly fw sched x0) (win1 (stP P2 dly fw sched x0) P2 fw sched x0)
      x0.e u DSTAR_RETIRE_USB)
    (hd : ∀ l, P2.live l = true → l ≠ u → DSTAR_RETIRE_USB ≤ dly l) :
    ∀ T, ((run2 P2 fw sched T x0).e.st = .idle →
            ∀ w, sched (run2 P2 fw sched T x0) = some w →
              (run2 P2 fw sched T x0).e.headValid w = true) ∧
         NoBr1 (stP P2 dly fw sched x0) (run2 P2 fw sched T x0).e := by
  intro T
  have hsw' : ∀ x w, sched x = some w →
      (stP P2 dly fw sched x0).live w = true ∧ x.e.ts w ≤ x.e.now := hsw
  have hss' : ∀ y x, Ready (stP P2 dly fw sched x0) y x.e → sched x ≠ none :=
    fun y x h => hss y x h
  have key := dstar_usb_rean (stP P2 dly fw sched x0)
    (win1 (stP P2 dly fw sched x0) P2 fw sched x0) x0.e u dbit hW hfull (fun _ => rfl) hx0.2 h0 h0ts
    (win1_ready _ P2 fw sched x0) (fun y e _ hy => win1_wc _ P2 fw sched x0 y e hy)
    hfl hrow1 hretu hd T
  have hr := run2_proj_st P2 dly fw sched x0 hx0 hf hsw' hss' T
  rw [← hr] at key
  refine ⟨fun hi w hw => key.1 hi w ?_, key.2⟩
  rw [win1_on (stP P2 dly fw sched x0) P2 fw sched x0 hsw' hss' T]
  exact hw

#print axioms wb_bound_usb
#print axioms dstar_usb
#print axioms dstar_usb_rean
#print axioms dstar_usb_st

end JLane
