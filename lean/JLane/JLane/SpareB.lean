import JLane.SlotReadyB
/-!
# Spare capture — slot readiness for an ARM captured behind held words (Wilson 11-19 / 11-20)

`READY_RULES["spare_capture"]`: a plain ARM whose predecessor is not no-prefetch may be captured
while `y` still holds words (the base refill prefetched it into the spare), so `ready_*_T`'s
`hempty` fails. `hempty` enters those proofs twice: the ARM writes back no earlier than `c + 3`
(`wb_after_empty_T`), and `y` holds nothing at `c` (`held_zero_of_empty`). Here both are
replaced:

* `wb_after_wb_T` -- **writebacks are three apart**: one dispatcher, so a writeback at `w1`
  was picked from idle at `w1 - 2` and driven at `w1 - 1`; any earlier writeback `w0` is at
  `w1 - 3` or before. The held words retire first (the last at `w0 ≥ c`), so the ARM writes
  back no earlier than `c + 3` -- the timing the margins (`p1b_margin_scan`,
  `p1b2_margin_*_scan`) were proved from;
* the counting: `k` words held at `c` and `k` retirements of `y` in `[c, w1)` (the ARM's at
  `w1`); conservation (`head_of_counts_T`) still leaves a word held at the release.

Issue path (A), wait at capture 1 (Wilson 11-20): the requester's contract from `c + 1` is the
premise, as in `ready_*_T`; the buffer is BufEng's one word per lane.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB)

/-- **Writebacks are three apart.** A writeback of `y` at `w1` and any writeback at `w0 < w1`:
`w0 + 3 ≤ w1` (`w1 - 1` drives, `w1 - 2` picks from idle). -/
theorem wb_after_wb_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (w0 w1 : Nat) (hw : w1 ≤ T)
    (h01 : w0 < w1) (h0 : (τ w0).e.st = .wb) (hwb : IsWB y (τ w1).e) : w0 + 3 ≤ w1 := by
  obtain ⟨m, rfl⟩ : ∃ m, w1 = m + 1 := ⟨w1 - 1, by omega⟩
  obtain ⟨hd, hcur⟩ := disp_wb_T P win usb sreq y τ T hT m (by omega) hwb.1
  have hcy : (τ m).e.cur = y := by rw [← hcur]; exact hwb.2
  rcases Nat.lt_or_ge w0 m with hlt | hge
  · obtain ⟨p, rfl⟩ : ∃ p, m = p + 1 := ⟨m - 1, by omega⟩
    obtain ⟨hidle, -⟩ := disp_pick_T P win usb sreq y τ T hT p (by omega) hd hcy
    rcases Nat.lt_or_ge w0 p with h2 | h2
    · omega
    · have e : w0 = p := by omega
      rw [e] at h0
      rw [h0] at hidle
      cases hidle
  · have e : w0 = m := by omega
    rw [e] at h0
    rw [h0] at hd
    cases hd

/-- The ARM, behind `k` held words that retire first (the last at `w0`, `c ≤ w0`), writes back
no earlier than `c + 3`. -/
theorem arm_wb_spare_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (c w0 w1 : Nat) (hw : w1 ≤ T)
    (hcw0 : c ≤ w0) (hw01 : w0 < w1) (hw0 : IsRet P y (τ w0).e) (hw1 : IsRet P y (τ w1).e) :
    c + 3 ≤ w1 := by
  have := wb_after_wb_T P win usb sreq y τ T hT w0 w1 hw hw01 hw0.1 (isWB_of_ret P y _ hw1)
  omega

/-- Two captures for `y` at `c < q < t`. -/
theorem cnt_two_hits (c q t : Nat) (h1 : c < q) (h2 : q < t)
    (hc : Hit y (τ c).e) (hq : Hit y (τ q).e) :
    cntT τ (fun z => Hit y z.e) c + 2 ≤ cntT τ (fun z => Hit y z.e) t := by
  have e0 : cntT τ (fun z => Hit y z.e) (c + 1) = cntT τ (fun z => Hit y z.e) c + 1 := by
    rw [cntT_succ, if_pos hc]
  have e1 : cntT τ (fun z => Hit y z.e) (q + 1) = cntT τ (fun z => Hit y z.e) q + 1 := by
    rw [cntT_succ, if_pos hq]
  have m0 := cntT_mono τ (fun z => Hit y z.e) (c + 1) q (by omega)
  have m1 := cntT_mono τ (fun z => Hit y z.e) (q + 1) t (by omega)
  omega

/-- **`pc1_plain`, spare capture.** As `ready_pc1_plain_T` with `hempty` replaced: `y` holds
`k ≤ held` words at the ARM's capture `c`, and they are the `k` retirements of `y` in `[c, w2)`
(the last at `w0 ≥ c`); `w2` is the ARM's. Then `y`'s head is valid at `t`. -/
theorem ready_pc1_spare_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (old : Lane → Bool) (c w0 w2 t C k : Nat) (ht : t ≤ T)
    (hcap : Hit y (τ c).e) (hk : k ≤ (τ c).held y)
    (hcw0 : c ≤ w0) (hw02 : w0 < w2) (hw2t : w2 < t)
    (hw0 : IsRet P y (τ w0).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c + k = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap : (τ w2).e.now + ARM_RETIRE_GAP ≤ (τ (w2 + 1)).e.ts y)
    (hq : ∀ j, c + 1 ≤ j → j ≤ c + 1 + L_REFILL * C →
      (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold : ∀ j, c + 1 ≤ j → j ≤ c + 1 + L_REFILL * C →
      (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) (c + 1) (L_REFILL * C + 1) ≤ C)
    (hcm : L_REFILL * C ≤ P1B_MARGIN_SCAN) :
    (τ t).e.headValid y = true := by
  have hw3 := arm_wb_spare_T P win usb sreq y τ T hT c w0 w2 (by omega) hcw0 hw02 hw0 hw2
  have hnow := now_T P win usb sreq y τ T hT
  have hts := ts_monoT P win usb sreq y τ T hT (w2 + 1) (t - (w2 + 1)) (by omega)
  rw [show w2 + 1 + (t - (w2 + 1)) = t by omega] at hts
  have hnt := hnow t ht
  have hnw := hnow w2 (by omega)
  have hrt : w2 + ARM_RETIRE_GAP ≤ t := by omega
  have hm := p1b_margin_scan (w2 - c) (by omega)
  have hscan : (τ (c + 1)).e.pst = .scan :=
    hit_then_scanT P win usb sreq y τ T hT c (by omega) hcap
  simp only [P1B_FILL_SCAN, P1B_MARGIN_SCAN, ARM_RETIRE_GAP, DISPATCH_CYCLES, L_REFILL]
    at hm hrt hcm
  obtain ⟨j, hj1, hj2, hs⟩ := slot_issue_within_T P win usb sreq y τ T hT y old (c + 1)
    (L_REFILL * C) C (by simp only [L_REFILL]; omega) hq hold hC
    (by rw [hscan]; simp only [rem, L_REFILL]; omega)
  simp only [L_REFILL] at hj2
  have hh := slot_issue_cap_T P win usb sreq y τ T hT j (by omega) hs.1 hs.2.1 hs.2.2
  have h2 := cnt_two_hits y τ c (j + 3) t (by omega) (by omega) hcap hh
  have hR : cntT τ (fun z => IsRet P y z.e) (w2 + 1) =
      cntT τ (fun z => IsRet P y z.e) w2 + 1 := by rw [cntT_succ, if_pos hw2]
  exact head_of_counts_T P win usb sreq y τ T hT hWf c t (by omega) ht (by omega)

/-- **`pc2_plain`, spare capture.** As `ready_pc2_plain_T` with `hempty` replaced by the `k`
held words retiring first (the last at `w0 ≥ c`). -/
theorem ready_pc2_plain_spare_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (old : Lane → Bool) (c w0 w1 w2 t d W1 W2 C1 C2 k : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hk : k ≤ (τ c).held y)
    (hcw0 : c ≤ w0) (hw01 : w0 < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw0 : IsRet P y (τ w0).e) (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c + k = cntT τ (fun z => IsRet P y z.e) w1)
    (hmid : cntT τ (fun z => IsRet P y z.e) (w1 + 1) = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap : (τ w1).e.now + ARM_RETIRE_GAP ≤ (τ (w1 + 1)).e.ts y)
    (hd : (τ (w1 + 1)).e.ts y + d ≤ (τ (w2 + 1)).e.ts y) (hd4 : 4 ≤ d)
    (hq1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
      (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
      (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) (c + 1) (W1 + 1) ≤ C1)
    (hW1 : L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 →
      cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2) (hcm : W1 + W2 ≤ d - 4) :
    (τ t).e.headValid y = true := by
  have hw3 := arm_wb_spare_T P win usb sreq y τ T hT c w0 w1 (by omega) hcw0 hw01 hw0 hw1
  have hnow := now_T P win usb sreq y τ T hT
  have hts := ts_monoT P win usb sreq y τ T hT (w2 + 1) (t - (w2 + 1)) (by omega)
  rw [show w2 + 1 + (t - (w2 + 1)) = t by omega] at hts
  have hnt := hnow t ht
  have hnw := hnow w1 (by omega)
  have hrt : w1 + ARM_RETIRE_GAP + d ≤ t := by omega
  have hm := p1b2_margin_plain_scan d hd4
  simp only [P1B2_FILL_SCAN, DISPATCH_CYCLES, ARM_RETIRE_GAP, L_REFILL] at hm hrt
  obtain ⟨q1, q2, hq1a, hq12, hq2b, hh1, hh2⟩ := slot_two_fetch_T P win usb sreq y τ T hT old
    c W1 W2 C1 C2 (by omega) hcap hq1 hold1 hC1 hW1 hq2 hold2 hC2 hW2
  have h3 := cnt_three_hits y τ c q1 q2 t (by omega) (by omega) (by omega) hcap hh1 hh2
  have hR1 : cntT τ (fun z => IsRet P y z.e) (w1 + 1) =
      cntT τ (fun z => IsRet P y z.e) w1 + 1 := by rw [cntT_succ, if_pos hw1]
  have hR2 : cntT τ (fun z => IsRet P y z.e) (w2 + 1) =
      cntT τ (fun z => IsRet P y z.e) w2 + 1 := by rw [cntT_succ, if_pos hw2]
  exact head_of_counts_T P win usb sreq y τ T hT hWf c t (by omega) ht (by omega)

/-- **`pc2_arm`, spare capture.** As `ready_pc2_arm_T` with `hempty` replaced by the `k` held
words retiring first (the last at `w0 ≥ c`). -/
theorem ready_pc2_arm_spare_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n))
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (old : Lane → Bool) (c w0 w1 w2 t W1 W2 C1 C2 k : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hk : k ≤ (τ c).held y)
    (hcw0 : c ≤ w0) (hw01 : w0 < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw0 : IsRet P y (τ w0).e) (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c + k = cntT τ (fun z => IsRet P y z.e) w1)
    (hmid : cntT τ (fun z => IsRet P y z.e) (w1 + 1) = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap1 : (τ w1).e.now + ARM_RETIRE_GAP ≤ (τ (w1 + 1)).e.ts y)
    (hgap2 : (τ w2).e.now + ARM_RETIRE_GAP ≤ (τ (w2 + 1)).e.ts y)
    (hq1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
      (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
      (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) (c + 1) (W1 + 1) ≤ C1)
    (hW1 : L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 →
      cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2) (hcm : W1 + W2 ≤ P1B2_MARGIN_ARM_SCAN) :
    (τ t).e.headValid y = true := by
  have hw3 := arm_wb_spare_T P win usb sreq y τ T hT c w0 w1 (by omega) hcw0 hw01 hw0 hw1
  have hwb2 := isWB_of_ret P y _ hw2
  obtain ⟨m, hm⟩ : ∃ m, w2 = m + 1 := ⟨w2 - 1, by omega⟩
  rw [hm] at hwb2
  obtain ⟨hdr, hcur⟩ := disp_wb_T P win usb sreq y τ T hT m (by omega) hwb2.1
  have hcy : (τ m).e.cur = y := by rw [← hcur]; exact hwb2.2
  obtain ⟨p, hp⟩ : ∃ p, m = p + 1 := ⟨m - 1, by omega⟩
  rw [hp] at hdr hcy
  obtain ⟨hidle, hwp⟩ := disp_pick_T P win usb sreq y τ T hT p (by omega) hdr hcy
  have hrp := (hwin _ _ hwp).2
  have hpw : w1 + 1 ≤ p := by
    rcases Nat.lt_or_ge p (w1 + 1) with hlt | hge
    · exfalso
      rcases Nat.lt_or_ge p w1 with hlt2 | hge2
      · have e : p + 1 = w1 := by omega
        rw [e, hw1.1] at hdr; cases hdr
      · have e : p = w1 := by omega
        rw [e, hw1.1] at hidle; cases hidle
    · exact hge
  have hnow := now_T P win usb sreq y τ T hT
  have hts1 := ts_monoT P win usb sreq y τ T hT (w1 + 1) (p - (w1 + 1)) (by omega)
  rw [show w1 + 1 + (p - (w1 + 1)) = p by omega] at hts1
  have hts2 := ts_monoT P win usb sreq y τ T hT (w2 + 1) (t - (w2 + 1)) (by omega)
  rw [show w2 + 1 + (t - (w2 + 1)) = t by omega] at hts2
  have hnt := hnow t ht
  have hnw1 := hnow w1 (by omega)
  have hnw2 := hnow w2 (by omega)
  have hnp := hnow p (by omega)
  have hrt : c + P1B2_REL_ARM ≤ t := by
    simp only [P1B2_REL_ARM, DISPATCH_CYCLES, ARM_RETIRE_GAP] at hgap1 hgap2 ⊢
    omega
  have hm2 := p1b2_margin_arm_scan
  simp only [P1B2_FILL_SCAN, P1B2_MARGIN_ARM_SCAN, P1B2_REL_ARM, DISPATCH_CYCLES, ARM_RETIRE_GAP,
    L_REFILL] at hm2 hrt hcm
  obtain ⟨q1, q2, hq1a, hq12, hq2b, hh1, hh2⟩ := slot_two_fetch_T P win usb sreq y τ T hT old
    c W1 W2 C1 C2 (by omega) hcap hq1 hold1 hC1 hW1 hq2 hold2 hC2 hW2
  have h3 := cnt_three_hits y τ c q1 q2 t (by omega) (by omega) (by omega) hcap hh1 hh2
  have hR1 : cntT τ (fun z => IsRet P y z.e) (w1 + 1) =
      cntT τ (fun z => IsRet P y z.e) w1 + 1 := by rw [cntT_succ, if_pos hw1]
  have hR2 : cntT τ (fun z => IsRet P y z.e) (w2 + 1) =
      cntT τ (fun z => IsRet P y z.e) w2 + 1 := by rw [cntT_succ, if_pos hw2]
  exact head_of_counts_T P win usb sreq y τ T hT hWf c t (by omega) ht (by omega)

end

#print axioms wb_after_wb_T
#print axioms arm_wb_spare_T
#print axioms cnt_two_hits
#print axioms ready_pc1_spare_T
#print axioms ready_pc2_plain_spare_T
#print axioms ready_pc2_arm_spare_T

end JLane
