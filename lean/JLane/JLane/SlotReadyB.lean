import JLane.RestartB
import JLane.ContendB
/-!
# Brick R1 — slot readiness on the buffered engine, along a trajectory
(`slot_on_composition` step 4: the run-level link behind `branch_budget.READY_RULES`)

`READY_RULES`' theorems are the slot's timing margins (`Slot.p1b_margin_scan`,
`Buf.p1b2_margin_*`) and the port's wait behind older requesters (`ContendB.slot_wait_fcfs_two`).
What turns them into "the word's head is valid at its release" on the buffered engine is proved
here, along any trajectory (`TrajB.TrajY`: `runB`, and `runBK` between a lane's flushes):

* `ready_of_capture_T` -- **the counting core.** A capture for `y` at `q` before `t`, with the
  only retirement of `y` in `[q, t)` the one at `w2` (the word before the one released at `t`),
  and `y` already holding a word at `q` when `q` is before `w2`: `y`'s head is valid at `t`.
  Conservation (`held_runT`) leaves a word held at `t`; HeadFirst puts it in the head;
* `slot_issue_cap_T` -- **the port**: a slot issue for `y` at a scan is `y`'s capture three
  cycles later (`REQ → WAIT → CAP`, the lane held).
-/
namespace JLane

/-- A valid head is a held word. -/
theorem held_of_head (x : EngB) (y : Lane) (h : x.e.headValid y = true) : 1 ≤ x.held y := by
  unfold EngB.held nslots
  unfold Engine.headValid at h
  cases hs : x.e.sel y
  · rw [hs] at h; rw [h]; simp only [bnum]
    exact Nat.le_add_right_of_le (Nat.le_add_right _ _)
  · rw [hs] at h; rw [h]; simp only [bnum]
    exact Nat.le_add_right_of_le (Nat.le_add_left _ _)

/-- A retiring lane holds its head (the dispatcher reads only a valid head, `WfB.disp`). -/
theorem held_of_ret (P : Program) (x : EngB) (hW : WfB x) (y : Lane) (h : IsRet P y x.e) :
    1 ≤ x.held y := by
  have hd := hW.disp (by rw [h.1]; decide)
  rw [h.2.1] at hd
  exact held_of_head x y hd

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB)

/-- **The counting core.** `w2`: a retirement of `y`; `t`: a later cycle with no retirement of
`y` in `(w2, t)`; `q < t`: a capture for `y`. If `q ≥ w2`, or `q < w2` with `y` holding a word at
`q` and no retirement of `y` in `[q, w2)`, then `y`'s head is valid at `t`. -/
theorem ready_of_capture_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (w2 q t : Nat) (ht : t ≤ T) (hw2t : w2 < t) (hqt : q < t)
    (hw2 : IsRet P y (τ w2).e)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hq : Hit y (τ q).e)
    (hbefore : q < w2 → 1 ≤ (τ q).held y ∧
      cntT τ (fun z => IsRet P y z.e) q + 1 = cntT τ (fun z => IsRet P y z.e) (w2 + 1)) :
    (τ t).e.headValid y = true := by
  have hrt := held_runT P win usb sreq y τ T hT hWf t ht
  have hrq := held_runT P win usb sreq y τ T hT hWf q (by omega)
  have hH : cntT τ (fun z => Hit y z.e) q + 1 ≤ cntT τ (fun z => Hit y z.e) t := by
    have e : cntT τ (fun z => Hit y z.e) (q + 1) = cntT τ (fun z => Hit y z.e) q + 1 := by
      rw [cntT_succ, if_pos hq]
    have := cntT_mono τ (fun z => Hit y z.e) (q + 1) t (by omega)
    omega
  have hRw : cntT τ (fun z => IsRet P y z.e) (w2 + 1) =
      cntT τ (fun z => IsRet P y z.e) w2 + 1 := by
    rw [cntT_succ, if_pos hw2]
  apply head_of_held _ (hWf t ht) y
  rcases Nat.lt_or_ge q w2 with hlt | hge
  · obtain ⟨h1, hc⟩ := hbefore hlt
    omega
  · rcases Nat.lt_or_ge w2 q with hlt2 | hge2
    · -- after w2: no retirement in [q, t)
      have h1 := cntT_mono τ (fun z => IsRet P y z.e) (w2 + 1) q (by omega)
      have h2 := cntT_mono τ (fun z => IsRet P y z.e) q t (by omega)
      omega
    · -- q = w2: the retiring word was held
      have hqw : q = w2 := by omega
      subst hqw
      have h1 := held_of_ret P (τ q) (hWf q (by omega)) y hw2
      omega

/-- **The port**: a slot issue for `y` at a scan of the trajectory is `y`'s capture three cycles
later. -/
theorem slot_issue_cap_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (n : Nat) (hn : n + 3 ≤ T)
    (hp : (τ n).e.pst = .scan) (hu : usbFirst P usb (τ n).e = false) (hs : sreq (τ n) = some y) :
    Hit y (τ (n + 3)).e := by
  have hp1 : (τ (n + 1)).e.pst = .req := by
    rw [agree_pst y (hT n (by omega))]
    exact stepB_pst_scan_slot P win usb sreq (τ n) hp hu hs
  have hl1 : (τ (n + 1)).e.pl = y := by
    rw [agree_pl y (hT n (by omega)), stepB_pl, (portNextB_slot P usb sreq (τ n) hp hu hs).1]
  have hp2 : (τ (n + 2)).e.pst = .wait := by
    rw [agree_pst y (hT (n + 1) (by omega))]
    exact stepB_req_wait P win usb sreq (τ (n + 1)) hp1
  have hl2 : (τ (n + 2)).e.pl = y := by
    rw [agree_pl y (hT (n + 1) (by omega)), stepB_pl,
      (portNextB_keeps P usb sreq (τ (n + 1)) (by rw [hp1]; decide)).1, hl1]
  refine ⟨?_, ?_⟩
  · rw [agree_pst y (hT (n + 2) (by omega))]
    exact stepB_wait_cap P win usb sreq (τ (n + 2)) hp2
  · rw [agree_pl y (hT (n + 2) (by omega)), stepB_pl,
      (portNextB_keeps P usb sreq (τ (n + 2)) (by rw [hp2]; decide)).1, hl2]

/-! ### The wait behind USB receive and the older requesters, along the trajectory -/

/-- This scan is charged to `u`'s wait: USB receive's issue, or a slot issue for an older lane. -/
def OldIssB (old : Lane → Bool) (x : EngB) : Prop :=
  x.e.pst = .scan ∧ (usbFirst P usb x.e = true ∨
    (match sreq x with | some w => old w | none => false) = true)

instance (old : Lane → Bool) (x : EngB) : Decidable (OldIssB P usb sreq old x) :=
  inferInstanceAs (Decidable (x.e.pst = .scan ∧ (usbFirst P usb x.e = true ∨
    (match sreq x with | some w => old w | none => false) = true)))

/-- How many of the `n` cycles of `τ` from `a` satisfy `Q`. -/
def cntFromT (Q : EngB → Prop) [DecidablePred Q] : Nat → Nat → Nat
  | _, 0 => 0
  | a, n + 1 => (if Q (τ a) then 1 else 0) + cntFromT Q (a + 1) n

/-- **The wait along the trajectory.** Over `[a, a + n)`: a slot request pending at every cycle,
none issued for `u`, every scan's pick `u` or an older lane (FCFS). Then
`n ≤ rem + L_REFILL · (charged scans)` -- `ContendB.slot_wait_fcfs` on `τ`. -/
theorem slot_wait_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (u : Lane) (old : Lane → Bool) :
    ∀ (n a : Nat), a + n ≤ T →
      (∀ j, a ≤ j → j < a + n → (sreq (τ j)).isSome = true) →
      (∀ j, a ≤ j → j < a + n → ¬SlotForB P usb sreq u (τ j)) →
      (∀ j, a ≤ j → j < a + n → ∀ w, sreq (τ j) = some w → w = u ∨ old w = true) →
      n ≤ rem (τ a).e.pst + L_REFILL * cntFromT τ (OldIssB P usb sreq old) a n
  | 0, _, _, _, _, _ => Nat.zero_le _
  | n + 1, a, hn, hq, hni, hold => by
    have ih := slot_wait_T T hT u old n (a + 1) (by omega)
      (fun j h1 h2 => hq j (by omega) (by omega)) (fun j h1 h2 => hni j (by omega) (by omega))
      (fun j h1 h2 => hold j (by omega) (by omega))
    have hag := hT a (by omega)
    have hpa : (τ (a + 1)).e.pst = (stepB P win usb sreq (τ a)).e.pst := agree_pst y hag
    have e : cntFromT τ (OldIssB P usb sreq old) a (n + 1) =
        (if OldIssB P usb sreq old (τ a) then 1 else 0) +
          cntFromT τ (OldIssB P usb sreq old) (a + 1) n := rfl
    rw [e]
    simp only [L_REFILL] at ih ⊢
    by_cases hp : (τ a).e.pst = .scan
    · have hcharged : OldIssB P usb sreq old (τ a) := by
        refine ⟨hp, ?_⟩
        cases hu : usbFirst P usb (τ a).e
        · right
          obtain ⟨w, hw⟩ := Option.isSome_iff_exists.mp (hq a (by omega) (by omega))
          have hwu : w ≠ u := fun h => hni a (by omega) (by omega) ⟨hp, hu, by rw [hw, h]⟩
          have hwo := (hold a (by omega) (by omega) w hw).resolve_left hwu
          rw [hw]
          exact hwo
        · left; rfl
      have hreq : (τ (a + 1)).e.pst = .req := by
        rw [hpa]
        cases hu : usbFirst P usb (τ a).e
        · obtain ⟨w, hw⟩ := Option.isSome_iff_exists.mp (hq a (by omega) (by omega))
          exact stepB_pst_scan_slot P win usb sreq (τ a) hp hu hw
        · exact stepB_pst_scan_usb P win usb sreq (τ a) hp hu
      rw [hreq] at ih
      rw [if_pos hcharged, hp]
      simp only [rem] at ih ⊢
      omega
    · rw [hpa, stepB_pst_ne P win usb sreq (τ a) hp] at ih
      cases hpe : (τ a).e.pst with
      | scan => exact absurd hpe hp
      | req => simp only [portNext, hpe, rem] at ih ⊢; split <;> omega
      | wait => simp only [portNext, hpe, rem] at ih ⊢; split <;> omega
      | cap => simp only [portNext, hpe, rem] at ih ⊢; split <;> omega

/-- **The issue comes within the wait.** If over `[a, a + W]` the requester's contract holds up
to `u`'s issue (a request pending, every pick `u` or an older lane), with at most `C` charged
scans and `rem + L_REFILL · C ≤ W` (`rem`: the port's cycles to its next scan at `a`), then `u`'s slot fetch is issued at some `j ≤ a + W`. -/
theorem slot_issue_within_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (u : Lane)
    (old : Lane → Bool) (a W C : Nat) (hn : a + W + 1 ≤ T)
    (hq : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq u (τ i)) →
      (sreq (τ j)).isSome = true)
    (hold : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq u (τ i)) →
      ∀ w, sreq (τ j) = some w → w = u ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) a (W + 1) ≤ C)
    (hW : rem (τ a).e.pst + L_REFILL * C ≤ W) :
    ∃ j, a ≤ j ∧ j ≤ a + W ∧ SlotForB P usb sreq u (τ j) := by
  by_cases hex : ∃ m, m < W + 1 ∧ SlotForB P usb sreq u (τ (a + m))
  · obtain ⟨m, hm, hs⟩ := hex
    exact ⟨a + m, by omega, by omega, hs⟩
  exfalso
  have hni : ∀ j, a ≤ j → j < a + (W + 1) → ¬SlotForB P usb sreq u (τ j) := by
    intro j h1 h2 hs
    apply hex
    refine ⟨j - a, by omega, ?_⟩
    rw [show a + (j - a) = j by omega]
    exact hs
  have h := slot_wait_T P win usb sreq y τ T hT u old (W + 1) a (by omega)
    (fun j h1 h2 => hq j h1 (by omega) (fun i hi1 hi2 => hni i hi1 (by omega)))
    hni
    (fun j h1 h2 => hold j h1 (by omega) (fun i hi1 hi2 => hni i hi1 (by omega)))
  have hr := rem_le (τ a).e.pst
  simp only [L_REFILL] at h hW
  omega

/-- **Slot readiness along the trajectory.** The requester's contract from `a` (the raise) with
the wait `W = rem + L_REFILL · C` (`rem`: the port's cycles to its next scan at the raise); the word's release `t` at least `W + 4` after the raise (the
capture three cycles after the issue, valid the cycle after); `w2` the retirement before `t` with
none of `y`'s in `(w2, t)`; and before `w2`, from the raise on, `y` holding a word and retiring
only at `w2`. Then `y`'s head is valid at `t`. -/
theorem slot_ready_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n))
    (old : Lane → Bool) (a W C w2 t : Nat) (ht : t ≤ T) (hat : a + W + 4 ≤ t) (hw2t : w2 < t)
    (hq : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      (sreq (τ j)).isSome = true)
    (hold : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) a (W + 1) ≤ C)
    (hW : rem (τ a).e.pst + L_REFILL * C ≤ W)
    (hw2 : IsRet P y (τ w2).e)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hheld : ∀ q, a ≤ q → q < w2 → 1 ≤ (τ q).held y ∧
      cntT τ (fun z => IsRet P y z.e) q + 1 = cntT τ (fun z => IsRet P y z.e) (w2 + 1)) :
    (τ t).e.headValid y = true := by
  obtain ⟨j, hj1, hj2, hs⟩ := slot_issue_within_T P win usb sreq y τ T hT y old a W C (by omega)
    hq hold hC hW
  have hhit := slot_issue_cap_T P win usb sreq y τ T hT j (by omega) hs.1 hs.2.1 hs.2.2
  exact ready_of_capture_T P win usb sreq y τ T hT hWf w2 (j + 3) t ht hw2t (by omega) hw2 hnr
    hhit (fun h => hheld (j + 3) (by omega) h)

/-! ### `pc1_plain`: PC+1 of a plain ARM (`READY_RULES`, `Slot.p1b_margin_scan`)

The ARM is captured at `c` into `y`'s empty head; the requester raises at the scan after
(`c + 1`, `RaiseAtCapture`'s cycle); `w2` is `y`'s first retirement after `c` (the ARM's: it is
the only word `y` holds); ArmRetire's gap (`hgap`, what the refinement supplies, as in
`ArmRetire.arm_rd`) releases the successor at least `ARM_RETIRE_GAP` past the ARM's writeback.
The ARM writes back no earlier than `c + 3` (its head is valid for the two dispatch cycles
before), so the successor's release is at least `c + 3 + ARM_RETIRE_GAP`, and
`p1b_margin_scan` puts the slot's fill `P1B_FILL_SCAN` plus the margin under it. Under the
port's wait the word is ready while `L_REFILL · C ≤ P1B_MARGIN_SCAN` (`contend_margin`). -/

theorem disp_wb_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (n : Nat) (hn : n < T)
    (h : (τ (n + 1)).e.st = .wb) :
    (τ n).e.st = .drive ∧ (τ (n + 1)).e.cur = (τ n).e.cur := by
  have hag := hT n hn
  rw [hag.2.2.1, stepB_e_st] at h
  rw [hag.2.2.2.1, stepB_e_cur]
  unfold dispNext at h ⊢
  cases hs : (τ n).e.st with
  | drive => exact ⟨rfl, rfl⟩
  | wb => rw [hs] at h; cases h
  | idle =>
    rw [hs] at h
    dsimp only at h
    cases hw : win (τ n).e with
    | none => rw [hw] at h; cases h
    | some w => rw [hw] at h; dsimp only at h; split at h <;> cases h

theorem disp_drive_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (n : Nat) (hn : n < T)
    (h : (τ (n + 1)).e.st = .drive) (hc : (τ (n + 1)).e.cur = y) :
    (τ n).e.headValid y = true := by
  have hag := hT n hn
  rw [hag.2.2.1, stepB_e_st] at h
  rw [hag.2.2.2.1, stepB_e_cur] at hc
  unfold dispNext at h hc
  cases hs : (τ n).e.st with
  | drive => rw [hs] at h; cases h
  | wb => rw [hs] at h; cases h
  | idle =>
    rw [hs] at h hc
    dsimp only at h hc
    cases hw : win (τ n).e with
    | none => rw [hw] at h; cases h
    | some w =>
      rw [hw] at h hc
      dsimp only at h hc
      by_cases hv : (τ n).e.headValid w = true
      · rw [if_pos hv] at hc
        rw [← hc]
        exact hv
      · rw [if_neg hv] at h; cases h

/-- **A writeback reads a head valid for the two cycles before it**: if `y` writes back at `w`
and its head is empty at `c < w`, then `c + 3 ≤ w`. -/
theorem wb_after_empty_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (c w : Nat) (hw : w ≤ T) (hcw : c < w)
    (hwb : IsWB y (τ w).e) (hc : (τ c).e.headValid y = false) : c + 3 ≤ w := by
  -- the head is valid at w (the dispatcher reads only a valid head)
  have hvw : (τ w).e.headValid y = true := by
    have := (hWf w hw).disp (by rw [hwb.1]; decide)
    rw [hwb.2] at this
    exact this
  obtain ⟨w1, rfl⟩ : ∃ w1, w = w1 + 1 := ⟨w - 1, by omega⟩
  obtain ⟨hd, hcur⟩ := disp_wb_T P win usb sreq y τ T hT w1 (by omega) hwb.1
  have hcy : (τ w1).e.cur = y := by rw [← hcur]; exact hwb.2
  have hv1 : (τ w1).e.headValid y = true := by
    have := (hWf w1 (by omega)).disp (by rw [hd]; decide)
    rw [hcy] at this
    exact this
  rcases Nat.lt_or_ge c w1 with hlt | hge
  · obtain ⟨w0, rfl⟩ : ∃ w0, w1 = w0 + 1 := ⟨w1 - 1, by omega⟩
    have hv0 := disp_drive_T P win usb sreq y τ T hT w0 (by omega) hd hcy
    rcases Nat.lt_or_ge c w0 with hlt2 | hge2
    · omega
    · have : c = w0 := by omega
      subst this
      rw [hc] at hv0; cases hv0
  · have : c = w1 := by omega
    subst this
    rw [hc] at hv1; cases hv1

/-- An empty head holds nothing (HeadFirst; a buffered word sits behind a valid head). -/
theorem held_zero_of_empty (x : EngB) (hW : WfB x) (h : x.e.headValid y = false) :
    x.held y = 0 := by
  have hs := hW.hf y h
  have hb : x.buf y = false := by
    cases hb : x.buf y
    · rfl
    · have := hW.bh y hb
      rw [h] at this; cases this
  unfold EngB.held nslots
  unfold Engine.headValid at h
  unfold Engine.spareValid at hs
  rw [hb]
  cases hsel : x.e.sel y
  · rw [hsel] at h hs; simp at hs; rw [h, hs]; rfl
  · rw [hsel] at h hs; simp at hs; rw [h, hs]; rfl

/-- **`pc1_plain` on the buffered engine.** The ARM captured at `c` into `y`'s empty head; its
retirement `w2`, `y`'s first after `c`; `t` with `y` released (`ts ≤ now`) and no retirement of
`y` in `(w2, t)`; ArmRetire's gap at `w2`; the requester's contract from `c + 1` with `C`
charged scans and `L_REFILL · C ≤ P1B_MARGIN_SCAN`. Then `y`'s head is valid at `t`. -/
theorem ready_pc1_plain_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (old : Lane → Bool) (c w2 t C : Nat) (ht : t ≤ T)
    (hcap : Hit y (τ c).e) (hempty : (τ c).e.headValid y = false) (hcw : c < w2) (hw2t : w2 < t)
    (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c = cntT τ (fun z => IsRet P y z.e) w2)
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
  have hw3 := wb_after_empty_T P win usb sreq y τ T hT hWf c w2 (by omega) hcw
    (isWB_of_ret P y _ hw2) hempty
  -- the successor's release: t ≥ w2 + ARM_RETIRE_GAP
  have hnow := now_T P win usb sreq y τ T hT
  have hts := ts_monoT P win usb sreq y τ T hT (w2 + 1) (t - (w2 + 1)) (by omega)
  rw [show w2 + 1 + (t - (w2 + 1)) = t by omega] at hts
  have hnt := hnow t ht
  have hnw := hnow w2 (by omega)
  have hrt : w2 + ARM_RETIRE_GAP ≤ t := by omega
  -- the margin (READY_RULES pc1_plain): fill + margin ≤ the ARM's writeback offset + the gap
  have hm := p1b_margin_scan (w2 - c) (by omega)
  have hscan : (τ (c + 1)).e.pst = .scan :=
    hit_then_scanT P win usb sreq y τ T hT c (by omega) hcap
  apply slot_ready_T P win usb sreq y τ T hT hWf old (c + 1) (L_REFILL * C) C w2 t ht
    (by simp only [P1B_FILL_SCAN, P1B_MARGIN_SCAN, ARM_RETIRE_GAP, DISPATCH_CYCLES,
          L_REFILL] at hm hrt hcm ⊢
        omega)
    hw2t hq hold hC (by rw [hscan]; simp [rem]) hw2 hnr
  intro q hq1 hq2
  -- y holds the ARM from c + 1 to its retirement
  have hr0 := held_runT P win usb sreq y τ T hT hWf c (by omega)
  have hrq := held_runT P win usb sreq y τ T hT hWf q (by omega)
  have h0 := held_zero_of_empty y (τ c) (hWf c (by omega)) hempty
  have hH : cntT τ (fun z => Hit y z.e) c + 1 ≤ cntT τ (fun z => Hit y z.e) q := by
    have e : cntT τ (fun z => Hit y z.e) (c + 1) = cntT τ (fun z => Hit y z.e) c + 1 := by
      rw [cntT_succ, if_pos hcap]
    have := cntT_mono τ (fun z => Hit y z.e) (c + 1) q (by omega)
    omega
  have hR1 := cntT_mono τ (fun z => IsRet P y z.e) c q (by omega)
  have hR2 := cntT_mono τ (fun z => IsRet P y z.e) q w2 (by omega)
  have hRw : cntT τ (fun z => IsRet P y z.e) (w2 + 1) =
      cntT τ (fun z => IsRet P y z.e) w2 + 1 := by
    rw [cntT_succ, if_pos hw2]
  exact ⟨by omega, by omega⟩

/-! ### R2b — the second fetch: `pc2_plain`, `pc2_arm` (`READY_RULES`, `Buf.p1b2_margin_*`)

The ARM captured at `c` into `y`'s empty head; the requester raises at the scan after (`c + 1`)
and again at the scan after fetch 1's capture. Fetch 2's word is held at PC+2's release `t`
when `y` has captured three words since `c` (the ARM, PC+1, PC+2) and retired two (the ARM at
`w1`, PC+1 at `w2`): conservation leaves one held, HeadFirst puts it in the head. The release is
far enough out by the margins: `p1b2_margin_plain_scan` (PC+1 plain, spacing `d`) and
`p1b2_margin_arm_scan` (PC+1 a plain edge ARM, retired after its own ArmRetire gap). -/

/-- **Head from counts.** If at `t` the retirements of `y` since `c` are fewer than `y`'s holding
at `c` plus its captures since `c`, `y`'s head is valid at `t`. -/
theorem head_of_counts_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (c t : Nat) (hct : c ≤ t) (ht : t ≤ T)
    (h : cntT τ (fun z => IsRet P y z.e) t + 1 + cntT τ (fun z => Hit y z.e) c ≤
      cntT τ (fun z => IsRet P y z.e) c + (τ c).held y + cntT τ (fun z => Hit y z.e) t) :
    (τ t).e.headValid y = true := by
  have hrt := held_runT P win usb sreq y τ T hT hWf t ht
  have hrc := held_runT P win usb sreq y τ T hT hWf c (by omega)
  apply head_of_held _ (hWf t ht) y
  omega

/-- Three captures for `y` at `c < q1 < q2 < t`. -/
theorem cnt_three_hits (c q1 q2 t : Nat) (h1 : c < q1) (h2 : q1 < q2) (h3 : q2 < t)
    (hc : Hit y (τ c).e) (hq1 : Hit y (τ q1).e) (hq2 : Hit y (τ q2).e) :
    cntT τ (fun z => Hit y z.e) c + 3 ≤ cntT τ (fun z => Hit y z.e) t := by
  have e0 : cntT τ (fun z => Hit y z.e) (c + 1) = cntT τ (fun z => Hit y z.e) c + 1 := by
    rw [cntT_succ, if_pos hc]
  have e1 : cntT τ (fun z => Hit y z.e) (q1 + 1) = cntT τ (fun z => Hit y z.e) q1 + 1 := by
    rw [cntT_succ, if_pos hq1]
  have e2 : cntT τ (fun z => Hit y z.e) (q2 + 1) = cntT τ (fun z => Hit y z.e) q2 + 1 := by
    rw [cntT_succ, if_pos hq2]
  have m0 := cntT_mono τ (fun z => Hit y z.e) (c + 1) q1 (by omega)
  have m1 := cntT_mono τ (fun z => Hit y z.e) (q1 + 1) q2 (by omega)
  have m2 := cntT_mono τ (fun z => Hit y z.e) (q2 + 1) t (by omega)
  omega

/-- **Two fetches along the trajectory.** From `y`'s capture at `c`: the requester's contract
from the raise at `c + 1` over the wait `W1` (`L_REFILL · C1 ≤ W1`, `C1` charged scans), and
from the raise after fetch 1's capture (any `a2` in `[c + 5, c + 5 + W1]`) over `W2`. Then
fetch 1 is captured at `q1 ≥ c + 4`, fetch 2 at `q2 ≥ q1 + 4`, and `q2 ≤ c + 8 + W1 + W2`
(free port: `c + 8`, `Buf.two_fetch_scan`). -/
theorem slot_two_fetch_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (old : Lane → Bool)
    (c W1 W2 C1 C2 : Nat) (hn : c + 9 + W1 + W2 ≤ T) (hcap : Hit y (τ c).e)
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
    (hW2 : L_REFILL * C2 ≤ W2) :
    ∃ q1 q2, c + 4 ≤ q1 ∧ q1 + 4 ≤ q2 ∧ q2 ≤ c + 8 + W1 + W2 ∧
      Hit y (τ q1).e ∧ Hit y (τ q2).e := by
  have hs1 : (τ (c + 1)).e.pst = .scan := hit_then_scanT P win usb sreq y τ T hT c (by omega) hcap
  obtain ⟨j1, hj1a, hj1b, hs⟩ := slot_issue_within_T P win usb sreq y τ T hT y old (c + 1) W1 C1
    (by omega) hq1 hold1 hC1 (by rw [hs1]; simp only [rem]; omega)
  have hh1 := slot_issue_cap_T P win usb sreq y τ T hT j1 (by omega) hs.1 hs.2.1 hs.2.2
  have hs2 : (τ (j1 + 4)).e.pst = .scan :=
    hit_then_scanT P win usb sreq y τ T hT (j1 + 3) (by omega) hh1
  obtain ⟨j2, hj2a, hj2b, hs'⟩ := slot_issue_within_T P win usb sreq y τ T hT y old (j1 + 4) W2 C2
    (by omega) (hq2 (j1 + 4) (by omega) (by omega)) (hold2 (j1 + 4) (by omega) (by omega))
    (hC2 (j1 + 4) (by omega) (by omega)) (by rw [hs2]; simp only [rem]; omega)
  have hh2 := slot_issue_cap_T P win usb sreq y τ T hT j2 (by omega) hs'.1 hs'.2.1 hs'.2.2
  exact ⟨j1 + 3, j2 + 3, by omega, by omega, by omega, hh1, hh2⟩

/-- **`pc2_plain` on the buffered engine.** The ARM captured at `c` into `y`'s empty head,
retired at `w1` (ArmRetire's gap there, `hgap`); PC+1 (any word) retired at `w2`, the only
retirements of `y` in `[c, t)`; PC+2 released at `t` (`ts ≤ now`), `d` past PC+1's release
(`hd`: the certificate's spacing, `d ≥ p1b2_plain_min_d` = 4); the two waits inside the margin
`d - 4`. Then `y`'s head is valid at `t`. -/
theorem ready_pc2_plain_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (old : Lane → Bool) (c w1 w2 t d W1 W2 C1 C2 : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hempty : (τ c).e.headValid y = false)
    (hcw : c < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c = cntT τ (fun z => IsRet P y z.e) w1)
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
  have hw3 := wb_after_empty_T P win usb sreq y τ T hT hWf c w1 (by omega) hcw
    (isWB_of_ret P y _ hw1) hempty
  have hnow := now_T P win usb sreq y τ T hT
  have hts := ts_monoT P win usb sreq y τ T hT (w2 + 1) (t - (w2 + 1)) (by omega)
  rw [show w2 + 1 + (t - (w2 + 1)) = t by omega] at hts
  have hnt := hnow t ht
  have hnw := hnow w1 (by omega)
  -- PC+2's release: t ≥ w1 + ARM_RETIRE_GAP + d
  have hrt : w1 + ARM_RETIRE_GAP + d ≤ t := by omega
  -- the margin (READY_RULES pc2_plain): fill 9 + (d - 4) ≤ (DISPATCH_CYCLES + gap) + d
  have hm := p1b2_margin_plain_scan d hd4
  simp only [P1B2_FILL_SCAN, DISPATCH_CYCLES, ARM_RETIRE_GAP, L_REFILL] at hm hrt
  obtain ⟨q1, q2, hq1a, hq12, hq2b, hh1, hh2⟩ := slot_two_fetch_T P win usb sreq y τ T hT old
    c W1 W2 C1 C2 (by omega) hcap hq1 hold1 hC1 hW1 hq2 hold2 hC2 hW2
  have h3 := cnt_three_hits y τ c q1 q2 t (by omega) (by omega) (by omega) hcap hh1 hh2
  have h0 := held_zero_of_empty y (τ c) (hWf c (by omega)) hempty
  have hR1 : cntT τ (fun z => IsRet P y z.e) (w1 + 1) =
      cntT τ (fun z => IsRet P y z.e) w1 + 1 := by rw [cntT_succ, if_pos hw1]
  have hR2 : cntT τ (fun z => IsRet P y z.e) (w2 + 1) =
      cntT τ (fun z => IsRet P y z.e) w2 + 1 := by rw [cntT_succ, if_pos hw2]
  exact head_of_counts_T P win usb sreq y τ T hT hWf c t (by omega) ht (by omega)

/-- The dispatcher's pick: `y` driving at `n + 1` was picked by `win` from idle at `n`. -/
theorem disp_pick_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (n : Nat) (hn : n < T)
    (h : (τ (n + 1)).e.st = .drive) (hc : (τ (n + 1)).e.cur = y) :
    (τ n).e.st = .idle ∧ win (τ n).e = some y := by
  have hag := hT n hn
  rw [hag.2.2.1, stepB_e_st] at h
  rw [hag.2.2.2.1, stepB_e_cur] at hc
  unfold dispNext at h hc
  cases hs : (τ n).e.st with
  | drive => rw [hs] at h; cases h
  | wb => rw [hs] at h; cases h
  | idle =>
    rw [hs] at h hc
    dsimp only at h hc
    cases hw : win (τ n).e with
    | none => rw [hw] at h; cases h
    | some w =>
      rw [hw] at h hc
      dsimp only at h hc
      by_cases hv : (τ n).e.headValid w = true
      · rw [if_pos hv] at hc
        exact ⟨rfl, congrArg some hc⟩
      · rw [if_neg hv] at h; cases h

/-- **`pc2_arm` on the buffered engine.** As `pc2_plain`, with PC+1 a plain edge ARM: it is
picked only once released (`hwin`, the shipped dispatcher's rule), so it writes back at least
`ARM_RETIRE_GAP + (DISPATCH_CYCLES - 1)` past the first ARM's writeback, and PC+2 is released
ArmRetire's gap after that (`hgap2`): `P1B2_REL_ARM` = 9 past `c`. The two waits inside the
margin `P1B2_MARGIN_ARM_SCAN` (= 0). Then `y`'s head is valid at `t`. -/
theorem ready_pc2_arm_T (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n))
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (old : Lane → Bool) (c w1 w2 t W1 W2 C1 C2 : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hempty : (τ c).e.headValid y = false)
    (hcw : c < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c = cntT τ (fun z => IsRet P y z.e) w1)
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
  have hw3 := wb_after_empty_T P win usb sreq y τ T hT hWf c w1 (by omega) hcw
    (isWB_of_ret P y _ hw1) hempty
  -- PC+1 (the second ARM) was picked at p = w2 - 2, from idle, once released
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
  -- PC+2's release: t ≥ c + P1B2_REL_ARM
  have hrt : c + P1B2_REL_ARM ≤ t := by
    simp only [P1B2_REL_ARM, DISPATCH_CYCLES, ARM_RETIRE_GAP] at hgap1 hgap2 ⊢
    omega
  -- the margin (READY_RULES pc2_arm): fill 9 + 0 ≤ P1B2_REL_ARM
  have hm2 := p1b2_margin_arm_scan
  simp only [P1B2_FILL_SCAN, P1B2_MARGIN_ARM_SCAN, P1B2_REL_ARM, DISPATCH_CYCLES, ARM_RETIRE_GAP,
    L_REFILL] at hm2 hrt hcm
  obtain ⟨q1, q2, hq1a, hq12, hq2b, hh1, hh2⟩ := slot_two_fetch_T P win usb sreq y τ T hT old
    c W1 W2 C1 C2 (by omega) hcap hq1 hold1 hC1 hW1 hq2 hold2 hC2 hW2
  have h3 := cnt_three_hits y τ c q1 q2 t (by omega) (by omega) (by omega) hcap hh1 hh2
  have h0 := held_zero_of_empty y (τ c) (hWf c (by omega)) hempty
  have hR1 : cntT τ (fun z => IsRet P y z.e) (w1 + 1) =
      cntT τ (fun z => IsRet P y z.e) w1 + 1 := by rw [cntT_succ, if_pos hw1]
  have hR2 : cntT τ (fun z => IsRet P y z.e) (w2 + 1) =
      cntT τ (fun z => IsRet P y z.e) w2 + 1 := by rw [cntT_succ, if_pos hw2]
  exact head_of_counts_T P win usb sreq y τ T hT hWf c t (by omega) ht (by omega)

/-- **The no-prefetch bridge, pointwise (Wilson 11-19).** Under the requester's contract
`SReqB`, a lane holding a no-prefetch word -- in its head, or in a valid spare -- is never
named by the requester, so the slot does not serve it this cycle. -/
theorem npf_no_slot (hok : SReqB P sreq) (x : EngB)
    (h : x.e.npf y (x.e.sel y) = true ∨
      (x.e.spareValid y = true ∧ x.e.npf y (!x.e.sel y) = true)) :
    ¬SlotForB P usb sreq y x := by
  rintro ⟨-, -, hs⟩
  obtain ⟨-, -, -, h1, h2⟩ := hok x y hs
  rcases h with h | ⟨hv, h⟩
  · rw [h1] at h; cases h
  · rw [h2 hv] at h; cases h

/-- **The no-prefetch bridge (Wilson 11-19): READY_RULES `pc1_not_npf`.** Under `SReqB`, if `y`
holds a no-prefetch word (head, or valid spare) on every cycle of a wait window `[a, a + W]`,
the requester premises of that wait -- `hq`, `hold`, `hC` with `hW` (the form `hq2 / hold2 /
hC2 / hW2` take in `ready_pc2_plain_T` / `ready_pc2_arm_T` for each start `a2`) -- cannot all
hold: they would give a slot for `y` inside the window (`slot_issue_within_T`). So behind a held
branch PC+1 the second fetch's premises are never met, and the certificate's exclusion of
`pc2_plain` there rests on this theorem. -/
theorem npf_no_issue_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (hok : SReqB P sreq)
    (old : Lane → Bool) (a W C : Nat) (hn : a + W + 1 ≤ T)
    (hnpf : ∀ j, a ≤ j → j ≤ a + W →
      (τ j).e.npf y ((τ j).e.sel y) = true ∨
        ((τ j).e.spareValid y = true ∧ (τ j).e.npf y (!(τ j).e.sel y) = true))
    (hq : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      (sreq (τ j)).isSome = true)
    (hold : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) a (W + 1) ≤ C)
    (hW : rem (τ a).e.pst + L_REFILL * C ≤ W) : False := by
  obtain ⟨j, h1, h2, hs⟩ :=
    slot_issue_within_T P win usb sreq y τ T hT y old a W C hn hq hold hC hW
  exact npf_no_slot P usb sreq y hok (τ j) (hnpf j h1 h2) hs

end

#print axioms npf_no_slot
#print axioms npf_no_issue_T
#print axioms head_of_counts_T
#print axioms cnt_three_hits
#print axioms slot_two_fetch_T
#print axioms ready_pc2_plain_T
#print axioms disp_pick_T
#print axioms ready_pc2_arm_T
#print axioms held_of_head
#print axioms held_of_ret
#print axioms ready_of_capture_T
#print axioms slot_issue_cap_T
#print axioms slot_wait_T
#print axioms slot_issue_within_T
#print axioms slot_ready_T
#print axioms wb_after_empty_T
#print axioms ready_pc1_plain_T

end JLane
