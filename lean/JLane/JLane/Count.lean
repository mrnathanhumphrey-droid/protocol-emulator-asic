import JLane.Lateness
/-!
# Brick 6 — counting a lane's events
Owed slots are conserved: each writeback of `y` frees one, each hit for `y` fills
one, and nothing else touches `y`'s slots. Along a run:
`owed(now) + hits = owed(start) + writebacks`.
-/
namespace JLane

/-- Lane `y` is in its writeback this cycle. -/
def IsWB (y : Lane) (e : Engine) : Prop := e.st = .wb ∧ e.cur = y

instance (y : Lane) (e : Engine) : Decidable (IsWB y e) :=
  inferInstanceAs (Decidable (e.st = .wb ∧ e.cur = y))

instance (y : Lane) (e : Engine) : Decidable (Hit y e) :=
  inferInstanceAs (Decidable (e.pst = .cap ∧ e.pl = y))

/-- Lane `y` **retires** an action this cycle: a writeback the program says
invalidates the head. Every retirement is a writeback; not every writeback retires. -/
def IsRet (P : Program) (y : Lane) (e : Engine) : Prop :=
  e.st = .wb ∧ e.cur = y ∧ P.ret e.now y = true

instance (P : Program) (y : Lane) (e : Engine) : Decidable (IsRet P y e) :=
  inferInstanceAs (Decidable (e.st = .wb ∧ e.cur = y ∧ P.ret e.now y = true))

theorem isWB_of_ret (P : Program) (y : Lane) (e : Engine) (h : IsRet P y e) : IsWB y e :=
  ⟨h.1, h.2.1⟩

/-! ### One slot, one cycle -/

/-- Per slot: emptiness after + (a hit fills it) = emptiness before + (a retirement frees it). -/
theorem slot_balance (P : Program) (y : Lane) (e : Engine) (hS : Struct e) (s : Slot) :
    (if actvNext P e y s then 0 else 1) + (if Hit y e ∧ s = e.pslot then 1 else 0)
      = (if e.actv y s then 0 else 1) + (if IsRet P y e ∧ s = e.sel y then 1 else 0) := by
  obtain ⟨h1, h2⟩ := hS
  unfold actvNext
  by_cases hw : e.st = .wb ∧ y = e.cur ∧ s = e.sel e.cur ∧ P.ret e.now e.cur = true
  · rw [if_pos hw]
    obtain ⟨hst, hy, hs, hr⟩ := hw
    have hv : e.actv y s = true := by
      have := h2 (by rw [hst]; decide)
      unfold Engine.headValid at this
      rw [hy, hs]
      exact this
    have hnh : ¬(Hit y e ∧ s = e.pslot) := by
      rintro ⟨⟨hc, hl⟩, hp⟩
      exact no_collision P e h1 h2 hst hc ⟨hst, hl.trans hy, hp.symm.trans hs, hr⟩
    have hwb : IsRet P y e ∧ s = e.sel y :=
      ⟨⟨hst, hy.symm, by rw [hy]; exact hr⟩, hs.trans (congrArg e.sel hy.symm)⟩
    rw [if_neg hnh, hv, if_pos hwb] <;> simp
  · rw [if_neg hw]
    have hnw : ¬(IsRet P y e ∧ s = e.sel y) := by
      rintro ⟨⟨hst, hcy, hr⟩, hss⟩
      exact hw ⟨hst, hcy.symm, hss.trans (congrArg e.sel hcy.symm), by rw [hcy]; exact hr⟩
    by_cases hc : e.pst = .cap ∧ y = e.pl ∧ s = e.pslot
    · rw [if_pos hc]
      obtain ⟨hpc, hyl, hsp⟩ := hc
      have hv : e.actv y s = false := by
        have := h1 (by rw [hpc]; decide)
        rw [hyl, hsp]
        exact this
      have hhit : Hit y e ∧ s = e.pslot := ⟨⟨hpc, hyl.symm⟩, hsp⟩
      rw [if_pos hhit, hv, if_neg hnw] <;> simp
    · rw [if_neg hc]
      have hnh : ¬(Hit y e ∧ s = e.pslot) := by
        rintro ⟨⟨hpc, hl⟩, hp⟩
        exact hc ⟨hpc, hl.symm, hp⟩
      rw [if_neg hnh, if_neg hnw] <;> simp

/-- Two slots, one indicator: exactly one of them is the named slot. -/
theorem split_ind (p : Prop) [Decidable p] (b : Bool) :
    (if p ∧ false = b then 1 else 0) + (if p ∧ true = b then 1 else 0)
      = if p then 1 else 0 := by
  cases b <;> by_cases hp : p <;> simp [hp]

/-- **Conservation, one cycle.** -/
theorem owed_step (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hS : Struct e) :
    (step P win e).owed y + (if Hit y e then 1 else 0)
      = e.owed y + (if IsRet P y e then 1 else 0) := by
  have hf := slot_balance P y e hS false
  have ht := slot_balance P y e hS true
  have hh := split_ind (Hit y e) e.pslot
  have hw := split_ind (IsRet P y e) (e.sel y)
  show (if actvNext P e y false then 0 else 1) + (if actvNext P e y true then 0 else 1)
      + (if Hit y e then 1 else 0)
      = (if e.actv y false then 0 else 1) + (if e.actv y true then 0 else 1)
      + (if IsRet P y e then 1 else 0)
  omega

/-! ### Counters along a run -/

/-- Number of cycles among the first `n` at which `Q` holds. -/
def cnt (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop) [DecidablePred Q] :
    Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => (if Q e then 1 else 0) + cnt P win Q n (step P win e)

/-- **Conservation along a run.** Slots are freed by retirements, not by every writeback. -/
theorem owed_run (P : Program) (win : Engine → Option Lane) (y : Lane) :
    ∀ (n : Nat) (e : Engine), Struct e →
      (run P win n e).owed y + cnt P win (Hit y) n e
        = e.owed y + cnt P win (IsRet P y) n e
  | 0, e, _ => by simp [run, cnt]
  | n + 1, e, hS => by
    have h1 := owed_step P win y e hS
    have ih := owed_run P win y n (step P win e) (struct_step P win e hS)
    have e1 : cnt P win (Hit y) (n + 1) e
        = (if Hit y e then 1 else 0) + cnt P win (Hit y) n (step P win e) := rfl
    have e2 : cnt P win (IsRet P y) (n + 1) e
        = (if IsRet P y e then 1 else 0) + cnt P win (IsRet P y) n (step P win e) := rfl
    have e3 : run P win (n + 1) e = run P win n (step P win e) := rfl
    rw [e3]
    omega

/-- From a primed start, a lane is never served ahead of its retirements... -/
theorem hits_le_wbs (P : Program) (win : Engine → Option Lane) (y : Lane) (n : Nat)
    (e : Engine) (hS : Struct e) (h0 : e.owed y = 0) :
    cnt P win (Hit y) n e ≤ cnt P win (IsRet P y) n e := by
  have := owed_run P win y n e hS
  omega

/-- ...and never more than two retirements behind. -/
theorem wbs_le_hits_two (P : Program) (win : Engine → Option Lane) (y : Lane) (n : Nat)
    (e : Engine) (hS : Struct e) (h0 : e.owed y = 0) :
    cnt P win (IsRet P y) n e ≤ cnt P win (Hit y) n e + 2 := by
  have := owed_run P win y n e hS
  have := Engine.owed_le_two (run P win n e) y
  omega

/-- The counter seen from the back: the last cycle adds its own indicator. -/
theorem cnt_succ_back (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] :
    ∀ (n : Nat) (e : Engine),
      cnt P win Q (n + 1) e = cnt P win Q n e + (if Q (run P win n e) then 1 else 0)
  | 0, e => by simp [cnt, run]
  | n + 1, e => by
    have ih := cnt_succ_back P win Q n (step P win e)
    have e1 : cnt P win Q (n + 1 + 1) e
        = (if Q e then 1 else 0) + cnt P win Q (n + 1) (step P win e) := rfl
    have e2 : cnt P win Q (n + 1) e
        = (if Q e then 1 else 0) + cnt P win Q n (step P win e) := rfl
    have e3 : run P win (n + 1) e = run P win n (step P win e) := rfl
    rw [e3]
    omega

/-- **Event extraction.** If the counter has passed `k`, the `k`-th event happened at
some cycle `t`, with exactly `k` events before it. -/
theorem cnt_reach (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] :
    ∀ (n : Nat) (e : Engine) (k : Nat), k < cnt P win Q n e →
      ∃ t, t < n ∧ cnt P win Q t e = k ∧ Q (run P win t e)
  | 0, e, k, h => by simp [cnt] at h
  | n + 1, e, k, h => by
    have e1 : cnt P win Q (n + 1) e
        = (if Q e then 1 else 0) + cnt P win Q n (step P win e) := rfl
    by_cases hq : Q e
    · rw [if_pos hq] at e1
      cases k with
      | zero => exact ⟨0, Nat.succ_pos n, rfl, hq⟩
      | succ k =>
        have h' : k < cnt P win Q n (step P win e) := by omega
        obtain ⟨t, ht, hc, hq'⟩ := cnt_reach P win Q n (step P win e) k h'
        have e2 : cnt P win Q (t + 1) e
            = (if Q e then 1 else 0) + cnt P win Q t (step P win e) := rfl
        rw [if_pos hq] at e2
        exact ⟨t + 1, by omega, by omega, hq'⟩
    · rw [if_neg hq] at e1
      have h' : k < cnt P win Q n (step P win e) := by omega
      obtain ⟨t, ht, hc, hq'⟩ := cnt_reach P win Q n (step P win e) k h'
      have e2 : cnt P win Q (t + 1) e
          = (if Q e then 1 else 0) + cnt P win Q t (step P win e) := rfl
      rw [if_neg hq] at e2
      exact ⟨t + 1, by omega, by omega, hq'⟩

end JLane
