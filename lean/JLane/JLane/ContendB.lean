import JLane.FlushHeld
/-!
# Brick C3 — the slot under contention: oldest capture first (Wilson 11-17)

Every slot readiness rule so far (`Slot.p1b_*`, `Buf.p1b2_*`, `FlushKeep.ft_edge_*`) assumed the
lane's fetch is issued at its own capture: the port free. Here the port is shared. The
arbitration (agent 1's rule, Wilson's suggestion): **USB receive first, then the slot request
with the oldest capture** (FCFS by capture cycle).

Proved on BufEng's engine:
* `slot_wait_others` -- while lane `u` has a slot request pending and none is issued for it,
  every scan issues USB receive's fetch or another lane's slot fetch, each a refill's port
  time: `n ≤ rem + L_REFILL · (USB issues + slot issues for other lanes)`. It is BufEng's
  `slot_waitS` (Slot.lean, one requester) with the other requesters counted;
* `slot_wait_fcfs` -- under FCFS the other lanes served before `u` are its **older** requesters
  (`old`, the requester's contract stated on the run): their slot issues are summed lane by lane;
* `slot_wait_fcfs_two` -- with each older request at most `SLOT_FETCHES_PER_ARM` = 2 fetches
  (one ARM's two words, the requester's contract), the wait is
  `SLOT_WAIT_BASE + SLOT_CHARGE · (USB issues + 2 · (older lanes))`: **8 cycles per older lane**;
* `slot_wait_fcfs_ret` -- the same with no per-request premise: an older lane's slot issues in
  the window are bounded by BufEng's `slot_countB` (its retirements there + 2).
The margins then fold the wait (`contend_margin_*`): a word whose margin was `m` at a free port
is late by at most `wait - m` (`CONTEND_PER_LANE` = 8 pinned through `proof_constants`).
-/
namespace JLane

/-! ### Sums over the lanes (no Mathlib: a fold over `0 … K-1`) -/

def nsum (f : Nat → Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => f n + nsum f n

theorem nsum_add (f g : Nat → Nat) : ∀ n, nsum (fun i => f i + g i) n = nsum f n + nsum g n
  | 0 => rfl
  | n + 1 => by
    show f n + g n + nsum (fun i => f i + g i) n = (f n + nsum f n) + (g n + nsum g n)
    rw [nsum_add f g n]
    omega

theorem nsum_le (f g : Nat → Nat) (h : ∀ i, f i ≤ g i) : ∀ n, nsum f n ≤ nsum g n
  | 0 => Nat.le_refl 0
  | n + 1 => Nat.add_le_add (h n) (nsum_le f g h n)

theorem nsum_mul (c : Nat) (f : Nat → Nat) : ∀ n, nsum (fun i => c * f i) n = c * nsum f n
  | 0 => by simp [nsum]
  | n + 1 => by
    show c * f n + nsum (fun i => c * f i) n = c * (f n + nsum f n)
    rw [nsum_mul c f n, Nat.mul_add]

theorem nsum_one (w : Nat) : ∀ n, nsum (fun i => if i = w then 1 else 0) n =
    if w < n then 1 else 0
  | 0 => by simp [nsum]
  | n + 1 => by
    show (if n = w then 1 else 0) + nsum (fun i => if i = w then 1 else 0) n = _
    rw [nsum_one w n]
    by_cases h : n = w
    · subst h; simp
    · by_cases h2 : w < n
      · rw [if_neg h, if_pos h2, if_pos (by omega)]
      · rw [if_neg h, if_neg h2, if_neg (by omega)]

/-- A sum over the lanes. -/
def lsum (f : Lane → Nat) : Nat := nsum (fun i => if h : i < K then f ⟨i, h⟩ else 0) K

theorem lsum_add (f g : Lane → Nat) : lsum (fun z => f z + g z) = lsum f + lsum g := by
  unfold lsum
  rw [← nsum_add]
  congr 1
  funext i
  split <;> rfl

theorem lsum_le (f g : Lane → Nat) (h : ∀ z, f z ≤ g z) : lsum f ≤ lsum g := by
  unfold lsum
  apply nsum_le
  intro i
  split
  · exact h _
  · exact Nat.le_refl 0

theorem lsum_mul (c : Nat) (f : Lane → Nat) : lsum (fun z => c * f z) = c * lsum f := by
  unfold lsum
  rw [← nsum_mul]
  congr 1
  funext i
  split <;> simp

/-- A lane-indexed indicator sums to its value at that lane. -/
theorem lsum_single (w : Lane) (c : Nat) :
    lsum (fun z => if z = w then c else 0) = c := by
  unfold lsum
  have h : (fun i => if h : i < K then (if (⟨i, h⟩ : Lane) = w then c else 0) else 0)
      = (fun i => c * (if i = w.val then 1 else 0)) := by
    funext i
    by_cases hi : i < K
    · rw [dif_pos hi]
      by_cases hw : i = w.val
      · have : (⟨i, hi⟩ : Lane) = w := Fin.ext hw
        rw [if_pos this, if_pos hw]
        simp
      · have : (⟨i, hi⟩ : Lane) ≠ w := fun h' => hw (congrArg Fin.val h')
        rw [if_neg this, if_neg hw]
        simp
    · rw [dif_neg hi]
      have : i ≠ w.val := fun h' => hi (h' ▸ w.isLt)
      rw [if_neg this]
      simp
  rw [h, nsum_mul, nsum_one, if_pos w.isLt]
  simp

theorem lsum_zero : lsum (fun _ => 0) = 0 := by
  have := lsum_single ⟨0, by decide⟩ 0
  simpa using this

/-! ### The wait behind the other requesters -/

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- USB receive's issue this cycle. -/
def UsbIssB (x : EngB) : Prop := x.e.pst = .scan ∧ usbFirst P usb x.e = true

instance (x : EngB) : Decidable (UsbIssB P usb x) :=
  inferInstanceAs (Decidable (x.e.pst = .scan ∧ usbFirst P usb x.e = true))

/-- The issues this cycle charged to `u`'s wait: USB receive's, and older lanes' slot fetches,
summed lane by lane. -/
def oldCost (old : Lane → Bool) (x : EngB) : Nat :=
  (if UsbIssB P usb x then 1 else 0) +
    lsum (fun z => if old z = true then (if SlotForB P usb sreq z x then 1 else 0) else 0)

def oldSum (old : Lane → Bool) : Nat → EngB → Nat
  | 0, _ => 0
  | n + 1, x => oldCost P usb sreq old x + oldSum old n (stepB P win usb sreq x)

theorem stepB_pst_scan_usb (x : EngB) (hp : x.e.pst = .scan) (hu : usbFirst P usb x.e = true) :
    (stepB P win usb sreq x).e.pst = .req := by
  rw [stepB_pst, (portNextB_usb P usb sreq x hp hu).1]
  unfold usbFirst at hu
  unfold portNextM
  rw [hp]
  cases hb : br1 P x.e with
  | none => rw [hb] at hu; simp at hu
  | some w => simp

theorem stepB_pst_scan_slot (x : EngB) (hp : x.e.pst = .scan) (hu : usbFirst P usb x.e = false)
    {w : Lane} (hs : sreq x = some w) : (stepB P win usb sreq x).e.pst = .req := by
  rw [stepB_pst, (portNextB_slot P usb sreq x hp hu hs).1]

theorem stepB_pst_ne (x : EngB) (hp : x.e.pst ≠ .scan) :
    (stepB P win usb sreq x).e.pst = (portNext P x.e).pst := by
  rw [stepB_pst, (portNextB_of_ne P usb sreq x hp).1]

/-- **`u` waits only behind USB receive and the older requesters.** Over `[0, n)`: a slot request
pending at every cycle, none issued for `u`, and every scan's slot pick is `u` or an older lane
(FCFS). Then `n ≤ rem + L_REFILL · (USB issues + older lanes' slot issues)`. -/
theorem slot_wait_fcfs (u : Lane) (old : Lane → Bool) :
    ∀ (n : Nat) (x : EngB),
      (∀ i, i < n → (sreq (runB P win usb sreq i x)).isSome = true) →
      (∀ i, i < n → ¬SlotForB P usb sreq u (runB P win usb sreq i x)) →
      (∀ i, i < n → ∀ w, sreq (runB P win usb sreq i x) = some w → w = u ∨ old w = true) →
      n ≤ rem x.e.pst + L_REFILL * oldSum P win usb sreq old n x
  | 0, x, _, _, _ => by simp [oldSum]
  | n + 1, x, hq, hni, hold => by
    have hq0 : (sreq x).isSome = true := hq 0 (Nat.succ_pos n)
    have hn0 : ¬SlotForB P usb sreq u x := hni 0 (Nat.succ_pos n)
    have ho0 := hold 0 (Nat.succ_pos n)
    have ih := slot_wait_fcfs u old n (stepB P win usb sreq x)
      (fun i hi => hq (i + 1) (Nat.succ_lt_succ hi))
      (fun i hi => hni (i + 1) (Nat.succ_lt_succ hi))
      (fun i hi => hold (i + 1) (Nat.succ_lt_succ hi))
    show n + 1 ≤ rem x.e.pst + L_REFILL * (oldCost P usb sreq old x +
      oldSum P win usb sreq old n (stepB P win usb sreq x))
    have hr := rem_le (stepB P win usb sreq x).e.pst
    have hc0 : 0 ≤ oldCost P usb sreq old x := Nat.zero_le _
    by_cases hp : x.e.pst = .scan
    · by_cases hu : usbFirst P usb x.e = true
      · have hpst := stepB_pst_scan_usb P win usb sreq x hp hu
        have hc : 1 ≤ oldCost P usb sreq old x := by
          unfold oldCost
          rw [if_pos ⟨hp, hu⟩]
          omega
        rw [hpst] at ih
        simp only [rem] at ih
        rw [hp]
        simp only [rem, L_REFILL] at ih ⊢
        rw [Nat.mul_add]
        omega
      · have hu' : usbFirst P usb x.e = false := by simpa using hu
        obtain ⟨w, hw⟩ := Option.isSome_iff_exists.mp hq0
        have hwu : w ≠ u := fun h => hn0 ⟨hp, hu', by rw [hw, h]⟩
        have hwo : old w = true := (ho0 w hw).resolve_left hwu
        have hpst := stepB_pst_scan_slot P win usb sreq x hp hu' hw
        have hc : 1 ≤ oldCost P usb sreq old x := by
          unfold oldCost
          have hl : lsum (fun z => if old z = true then
              (if SlotForB P usb sreq z x then 1 else 0) else 0) = 1 := by
            have : (fun z => if old z = true then (if SlotForB P usb sreq z x then 1 else 0)
                else 0) = (fun z => if z = w then 1 else 0) := by
              funext z
              by_cases hz : z = w
              · subst hz
                rw [if_pos hwo, if_pos ⟨hp, hu', hw⟩, if_pos rfl]
              · rw [if_neg hz]
                have : ¬SlotForB P usb sreq z x := fun h => hz (by
                  have := h.2.2
                  rw [hw] at this
                  exact (Option.some.inj this).symm)
                rw [if_neg this]
                split <;> rfl
            rw [this, lsum_single]
          rw [hl]
          omega
        rw [hpst] at ih
        rw [hp]
        simp only [rem, L_REFILL] at ih ⊢
        rw [Nat.mul_add]
        omega
    · have hpst := stepB_pst_ne P win usb sreq x hp
      rw [hpst] at ih
      cases hpe : x.e.pst with
      | scan => exact absurd hpe hp
      | req => simp only [portNext, hpe, rem] at ih ⊢; rw [Nat.mul_add]; omega
      | wait => simp only [portNext, hpe, rem] at ih ⊢; rw [Nat.mul_add]; omega
      | cap => simp only [portNext, hpe, rem] at ih ⊢; rw [Nat.mul_add]; omega

/-- The charged issues split: USB receive's, plus each older lane's slot issues. -/
theorem oldSum_split (old : Lane → Bool) : ∀ (n : Nat) (x : EngB),
    oldSum P win usb sreq old n x = cntB P win usb sreq (UsbIssB P usb) n x +
      lsum (fun z => if old z = true then cntB P win usb sreq (SlotForB P usb sreq z) n x
        else 0)
  | 0, x => by
    show 0 = 0 + lsum (fun z => if old z = true then 0 else 0)
    have : (fun z => if old z = true then (0 : Nat) else 0) = (fun _ => 0) := by
      funext z; split <;> rfl
    rw [this, lsum_zero]
  | n + 1, x => by
    show oldCost P usb sreq old x + oldSum P win usb sreq old n (stepB P win usb sreq x) =
      ((if UsbIssB P usb x then 1 else 0) + cntB P win usb sreq (UsbIssB P usb) n
        (stepB P win usb sreq x)) +
      lsum (fun z => if old z = true then ((if SlotForB P usb sreq z x then 1 else 0) +
        cntB P win usb sreq (SlotForB P usb sreq z) n (stepB P win usb sreq x)) else 0)
    rw [oldSum_split old n (stepB P win usb sreq x)]
    unfold oldCost
    have : (fun z => if old z = true then ((if SlotForB P usb sreq z x then 1 else 0) +
        cntB P win usb sreq (SlotForB P usb sreq z) n (stepB P win usb sreq x)) else 0) =
        (fun z => (if old z = true then (if SlotForB P usb sreq z x then 1 else 0) else 0) +
          (if old z = true then cntB P win usb sreq (SlotForB P usb sreq z) n
            (stepB P win usb sreq x) else 0)) := by
      funext z; split <;> simp
    rw [this, lsum_add]
    omega

/-- Lanes in a set. -/
def nOld (old : Lane → Bool) : Nat := lsum (fun z => if old z = true then 1 else 0)

/-! ### The bound, with the constants -/

/-- What one older requester costs a waiting lane: its two fetches' port time
(`SLOT_FETCHES_PER_ARM · SLOT_CHARGE`, pinned: `proof_constants.contend_per_lane`). -/
abbrev CONTEND_PER_LANE : Nat := SLOT_FETCHES_PER_ARM * SLOT_CHARGE

theorem contend_per_lane_val : CONTEND_PER_LANE = 8 := rfl

/-- **The contention bound, two fetches per older request** (the requester's contract: an ARM's
request is its two words). `u` waits at most
`SLOT_WAIT_BASE + SLOT_CHARGE · (USB issues) + CONTEND_PER_LANE · (older lanes)`. -/
theorem slot_wait_fcfs_two (u : Lane) (old : Lane → Bool) (n : Nat) (x : EngB)
    (hq : ∀ i, i < n → (sreq (runB P win usb sreq i x)).isSome = true)
    (hni : ∀ i, i < n → ¬SlotForB P usb sreq u (runB P win usb sreq i x))
    (hold : ∀ i, i < n → ∀ w, sreq (runB P win usb sreq i x) = some w → w = u ∨ old w = true)
    (h2 : ∀ z, old z = true → cntB P win usb sreq (SlotForB P usb sreq z) n x ≤
      SLOT_FETCHES_PER_ARM) :
    n ≤ SLOT_WAIT_BASE + SLOT_CHARGE * cntB P win usb sreq (UsbIssB P usb) n x +
      CONTEND_PER_LANE * nOld old := by
  have h := slot_wait_fcfs P win usb sreq u old n x hq hni hold
  rw [oldSum_split] at h
  have hr := rem_le x.e.pst
  have hs : lsum (fun z => if old z = true then cntB P win usb sreq (SlotForB P usb sreq z) n x
      else 0) ≤ SLOT_FETCHES_PER_ARM * nOld old := by
    unfold nOld
    rw [← lsum_mul]
    apply lsum_le
    intro z
    by_cases hz : old z = true
    · rw [if_pos hz, if_pos hz]
      simpa using h2 z hz
    · rw [if_neg hz, if_neg hz]
      simp
  simp only [SLOT_WAIT_BASE, SLOT_CHARGE, CONTEND_PER_LANE, SLOT_FETCHES_PER_ARM,
    L_REFILL] at h hs ⊢
  rw [Nat.mul_add] at h
  have : 4 * (2 * nOld old) = 2 * 4 * nOld old := by rw [← Nat.mul_assoc, Nat.mul_comm 4 2]
  omega

/-- **The contention bound with no per-request premise**: an older lane's slot issues in the
window are at most its retirements there plus two (`BufEng.slot_countB`). -/
theorem slot_wait_fcfs_ret (hok : SReqB P sreq) (u : Lane) (old : Lane → Bool) (x0 : EngB)
    (hW : WfB x0) (a n : Nat)
    (hq : ∀ i, i < n → (sreq (runB P win usb sreq i (runB P win usb sreq a x0))).isSome = true)
    (hni : ∀ i, i < n → ¬SlotForB P usb sreq u (runB P win usb sreq i (runB P win usb sreq a x0)))
    (hold : ∀ i, i < n → ∀ w, sreq (runB P win usb sreq i (runB P win usb sreq a x0)) = some w →
      w = u ∨ old w = true) :
    n ≤ SLOT_WAIT_BASE +
      SLOT_CHARGE * (cntB P win usb sreq (UsbIssB P usb) n (runB P win usb sreq a x0) +
        lsum (fun z => if old z = true then
          cntB P win usb sreq (fun y => IsRet P z y.e) n (runB P win usb sreq a x0) + 2
          else 0)) := by
  have h := slot_wait_fcfs P win usb sreq u old n _ hq hni hold
  rw [oldSum_split] at h
  have hr := rem_le (runB P win usb sreq a x0).e.pst
  have hs : lsum (fun z => if old z = true then
      cntB P win usb sreq (SlotForB P usb sreq z) n (runB P win usb sreq a x0) else 0) ≤
      lsum (fun z => if old z = true then
        cntB P win usb sreq (fun y => IsRet P z y.e) n (runB P win usb sreq a x0) + 2 else 0) := by
    apply lsum_le
    intro z
    by_cases hz : old z = true
    · rw [if_pos hz, if_pos hz]
      exact slot_countB P win usb sreq hok z x0 hW n a
    · rw [if_neg hz, if_neg hz]
      exact Nat.le_refl 0
  simp only [SLOT_WAIT_BASE, SLOT_CHARGE, L_REFILL] at h hs ⊢
  rw [Nat.mul_add] at h ⊢
  omega

end

/-! ### Folding the wait into the margins -/

/-- A word whose margin at a free port is `m` is late by at most `wait - m` once the port's
wait is `wait` (the slot's issue moves by the wait, the word's validity with it). -/
theorem contend_margin (fill m wait rel : Nat) (hfree : fill + m ≤ rel) :
    fill + wait ≤ rel + (wait - m) := by
  omega

/-- With no older requester and no USB issue in the window, the wait is the free port's
(`SLOT_WAIT_BASE`): the margins as proved stand. -/
theorem contend_none (usbN oldN : Nat) (h1 : usbN = 0) (h2 : oldN = 0) :
    SLOT_WAIT_BASE + SLOT_CHARGE * usbN + CONTEND_PER_LANE * oldN = SLOT_WAIT_BASE := by
  subst h1; subst h2; rfl

#print axioms slot_wait_fcfs
#print axioms slot_wait_fcfs_two
#print axioms slot_wait_fcfs_ret
#print axioms oldSum_split
#print axioms lsum_single

end JLane
