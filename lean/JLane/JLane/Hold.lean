import JLane.Refine
/-!
# Brick V2 — the W1 SDA hold (PORT_SPEC §7E)
An open-drain data drive loads a per-lane hold counter; while it is non-zero the lane is
not `ready` (`ready = rel_due & hz_q & cap_ok`, `hz_q = (l_hcnt == 0)`). The engine step is
unchanged; the hold only gates eligibility.

Modelled at the **effective** count `l_hcnt` (TM1: the registered load reads as `SDA_HS`
in exactly the cycle the old register held it, so every reader sees the same value):
* running counter: `l_hcr <= l_hcnt - 1`;
* idle counter and this cycle's DRIVE raises `hold_ld`: next cycle reads `SDA_HS`
  (`hl_v <= hold_ld & hz_q[cur]`: only an idle counter takes a load);
* else 0.

Which DRIVEs raise `hold_ld` (open-drain, SDA_HOLD ≠ 0, data-moving actions) is an input
`hl`, so every theorem holds for every load pattern.
-/
namespace JLane

/-- `SDA_HS = SDA_HOLD + SDA_SETUP = ⌈300/20⌉ + ⌈50/20⌉ = 15 + 3` at 50 MHz. -/
abbrev SDA_HS : Nat := 18

/-- The v2 engine plus the effective hold counters `l_hcnt`. -/
structure EngineH where
  x    : Engine2
  hcnt : Lane → Nat

/-- §7E, per lane, per cycle. -/
def hcntNext (ld : Bool) (y : EngineH) (l : Lane) : Nat :=
  if y.hcnt l ≠ 0 then y.hcnt l - 1
  else if y.x.e.st = .drive ∧ l = y.x.e.cur ∧ ld = true then SDA_HS
  else 0

/-- One cycle: the engine steps as in v2; the counters follow `hcntNext`. -/
def stepH (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool) (w : Option Lane)
    (y : EngineH) : EngineH :=
  { x := step2 P fw w y.x, hcnt := hcntNext (hl y) y }

/-- `n` cycles. -/
def runH (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) : Nat → EngineH → EngineH
  | 0, y => y
  | n + 1, y => runH P fw hl sched n (stepH P fw hl (sched y) y)

/-- The gated `ready`: live, released, and the hold counter idle (`hz_q`). -/
def ReadyH (P : Program2) (i : Lane) (y : EngineH) : Prop :=
  P.live i = true ∧ y.x.e.ts i ≤ y.x.e.now ∧ y.hcnt i = 0

theorem runH_succ_front (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (n : Nat) (y : EngineH) :
    runH P fw hl sched (n + 1) y = runH P fw hl sched n (stepH P fw hl (sched y) y) := rfl

theorem run2_succ_front (P : Program2) (fw : Engine2 → Word) (sched : Engine2 → Option Lane)
    (n : Nat) (x : Engine2) :
    run2 P fw sched (n + 1) x = run2 P fw sched n (step2 P fw (sched x) x) := rfl

/-! ### The counter -/

/-- A running counter drops by exactly one, whatever else happens. -/
theorem hcnt_dec (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (w : Option Lane) (y : EngineH) (l : Lane) (k : Nat) (h : y.hcnt l = k + 1) :
    (stepH P fw hl w y).hcnt l = k := by
  show hcntNext (hl y) y l = k
  unfold hcntNext
  rw [if_pos (by omega : y.hcnt l ≠ 0)]
  omega

/-- A counter at `j + k` reads `k` after `j` cycles. -/
theorem hcnt_run (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (l : Lane) :
    ∀ (j k : Nat) (y : EngineH), y.hcnt l = j + k → (runH P fw hl sched j y).hcnt l = k
  | 0, k, y, h => by
    show y.hcnt l = k
    omega
  | j + 1, k, y, h => by
    rw [runH_succ_front]
    apply hcnt_run P fw hl sched l j k
    exact hcnt_dec P fw hl (sched y) y l (j + k) (by omega)

/-- A DRIVE that raises `hold_ld` on an idle counter loads `SDA_HS`. -/
theorem hcnt_load (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (w : Option Lane) (y : EngineH) (hd : y.x.e.st = .drive)
    (h0 : y.hcnt y.x.e.cur = 0) (hld : hl y = true) :
    (stepH P fw hl w y).hcnt y.x.e.cur = SDA_HS := by
  show hcntNext (hl y) y y.x.e.cur = SDA_HS
  unfold hcntNext
  have hne : ¬(y.hcnt y.x.e.cur ≠ 0) := fun h => h h0
  have hc : y.x.e.st = .drive ∧ y.x.e.cur = y.x.e.cur ∧ hl y = true := ⟨hd, rfl, hld⟩
  rw [if_neg hne, if_pos hc]

/-- An idle counter stays idle unless this lane is DRIVEn with a load. -/
theorem hcnt_zero_stay (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (w : Option Lane) (y : EngineH) (l : Lane) (h0 : y.hcnt l = 0)
    (hn : ¬(y.x.e.st = .drive ∧ l = y.x.e.cur ∧ hl y = true)) :
    (stepH P fw hl w y).hcnt l = 0 := by
  show hcntNext (hl y) y l = 0
  unfold hcntNext
  have hne : ¬(y.hcnt l ≠ 0) := fun h => h h0
  rw [if_neg hne, if_neg hn]

/-- Nothing loads during IDLE: a lane picked with an idle counter still has it at DRIVE,
so the RTL's "load only on an idle counter" never drops a load. -/
theorem hcnt_idle_stay (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (w : Option Lane) (y : EngineH) (l : Lane) (hi : y.x.e.st = .idle) (h0 : y.hcnt l = 0) :
    (stepH P fw hl w y).hcnt l = 0 :=
  hcnt_zero_stay P fw hl w y l h0 (fun hc => by
    rw [hi] at hc
    exact absurd hc.1 (by decide))

/-- **The hold window.** A hold loaded at a DRIVE keeps the lane's gate closed for the next
`SDA_HS` cycles and re-opens it exactly `SDA_HS + 1 = 19` cycles after the DRIVE. -/
theorem hold_window (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (y : EngineH) (hd : y.x.e.st = .drive)
    (h0 : y.hcnt y.x.e.cur = 0) (hld : hl y = true) :
    (runH P fw hl sched (SDA_HS + 1) y).hcnt y.x.e.cur = 0 ∧
    ∀ j, 1 ≤ j → j ≤ SDA_HS → (runH P fw hl sched j y).hcnt y.x.e.cur ≠ 0 := by
  have hs := hcnt_load P fw hl (sched y) y hd h0 hld
  constructor
  · rw [runH_succ_front]
    exact hcnt_run P fw hl sched y.x.e.cur SDA_HS 0 _ (hs.trans (Nat.add_zero SDA_HS).symm)
  · intro j hj1 hj2
    obtain ⟨i, rfl⟩ : ∃ i, j = i + 1 := ⟨j - 1, by omega⟩
    rw [runH_succ_front,
      hcnt_run P fw hl sched y.x.e.cur i (SDA_HS - i) _ (by rw [hs]; omega)]
    omega

/-! ### No holds: the hold layer is invisible -/

/-- If no DRIVE ever raises `hold_ld`, every counter stays 0 (the gate is always open). -/
theorem hcnt_nohold (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (hn : ∀ y, hl y = false) :
    ∀ (n : Nat) (y : EngineH), (∀ l, y.hcnt l = 0) →
      ∀ l, (runH P fw hl sched n y).hcnt l = 0
  | 0, _, h => h
  | n + 1, y, h => hcnt_nohold P fw hl sched hn n _ (fun l =>
      hcnt_zero_stay P fw hl (sched y) y l (h l) (fun hc => by
        rw [hn y] at hc
        exact Bool.noConfusion hc.2.2))

/-- With no holds, a hold-model run is exactly a v2 run (under the scheduler that sees
zero counters), so V0/V1 — and `dstar39_v2` — apply unchanged. -/
theorem runH_nohold (P : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (hn : ∀ y, hl y = false) :
    ∀ (n : Nat) (x : Engine2),
      runH P fw hl sched n ⟨x, fun _ => 0⟩ =
        ⟨run2 P fw (fun x' => sched ⟨x', fun _ => 0⟩) n x, fun _ => 0⟩
  | 0, _ => rfl
  | n + 1, x => by
    have hz : stepH P fw hl (sched ⟨x, fun _ => 0⟩) ⟨x, fun _ => 0⟩ =
        ⟨step2 P fw (sched ⟨x, fun _ => 0⟩) x, fun _ => 0⟩ := by
      unfold stepH
      congr 1
      funext l
      simp [hcntNext, hn]
    rw [runH_succ_front, hz, runH_nohold P fw hl sched hn n, run2_succ_front]

#print axioms hold_window
#print axioms runH_nohold

end JLane
