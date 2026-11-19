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
scans and `3 + L_REFILL · C ≤ W`, then `u`'s slot fetch is issued at some `j ≤ a + W`. -/
theorem slot_issue_within_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (u : Lane)
    (old : Lane → Bool) (a W C : Nat) (hn : a + W + 1 ≤ T)
    (hq : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq u (τ i)) →
      (sreq (τ j)).isSome = true)
    (hold : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq u (τ i)) →
      ∀ w, sreq (τ j) = some w → w = u ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) a (W + 1) ≤ C) (hW : 3 + L_REFILL * C ≤ W) :
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
the wait `W = 3 + L_REFILL · C`; the word's release `t` at least `W + 4` after the raise (the
capture three cycles after the issue, valid the cycle after); `w2` the retirement before `t` with
none of `y`'s in `(w2, t)`; and before `w2`, from the raise on, `y` holding a word and retiring
only at `w2`. Then `y`'s head is valid at `t`. -/
theorem slot_ready_T (T : Nat) (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n))
    (old : Lane → Bool) (a W C w2 t : Nat) (ht : t ≤ T) (hat : a + W + 4 ≤ t) (hw2t : w2 < t)
    (hq : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      (sreq (τ j)).isSome = true)
    (hold : ∀ j, a ≤ j → j ≤ a + W → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) a (W + 1) ≤ C) (hW : 3 + L_REFILL * C ≤ W)
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

end

#print axioms held_of_head
#print axioms held_of_ret
#print axioms ready_of_capture_T
#print axioms slot_issue_cap_T
#print axioms slot_wait_T
#print axioms slot_issue_within_T
#print axioms slot_ready_T

end JLane
